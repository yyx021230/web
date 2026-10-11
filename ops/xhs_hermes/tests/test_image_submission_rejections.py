"""Offline regressions for the local C11 stale-reference/retry incident."""
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import run_daily_8x5 as runner
import web_worker


def production(tmp_path, monkeypatch):
    run = runner.ProductionRun.__new__(runner.ProductionRun)
    run.online = SimpleNamespace(backend='https://backend.test/api/v1', auth={})
    run.config = {'image_attempts': 2}
    run.args = SimpleNamespace(batch_date='2026-10-10')
    run.cases = {'c11': {}}
    run.lock = threading.RLock()
    run.state = {}
    run.checkpoint_path = tmp_path / 'checkpoint.json'
    monkeypatch.setattr(runner, 'make_generation_prompt', lambda *args: 'safe prompt')
    monkeypatch.setattr(runner, 'emit', lambda *args, **kwargs: None)
    row = {'key': '42-01', 'case_id': 'c11',
           'copy': {'title': '标题', 'content': '正文'},
           'image_plan': {'selected_prompt_id': 1, 'vehicle_image': {'url': '/uploads/car.webp'}}}
    return run, row


@pytest.mark.parametrize('status', [400, 401, 403, 404, 413, 415, 422])
def test_permanent_rejection_is_one_request_without_inner_or_outer_retry(tmp_path, monkeypatch, status):
    run, row = production(tmp_path, monkeypatch)
    requests = []

    def reject(url, **kwargs):
        requests.append(kwargs['body']['client_request_id'])
        raise runner.HttpFailure(status, 'Authorization: secret-example' + (' 最多同时提交' if status == 422 else ''), url)

    monkeypatch.setattr(runner, 'request_json', reject)
    monkeypatch.setattr(runner.time, 'sleep', lambda *args: pytest.fail('permanent errors must not sleep/retry'))
    key, image = run.image_job(row, tmp_path / 'ocr')
    assert len(requests) == 1 and key == row['key']
    assert image['status'] == 'rejected' and image['http_status'] == status
    assert 'secret-example' not in json.dumps(image)
    assert runner.ProductionRun.image_failure_code(image) == 'submission_rejected'
    row['image'] = image
    assert run.image_job(row, tmp_path / 'ocr')[1] == image
    assert len(requests) == 1
    assert web_worker.retryable_image_keys({'posts': [{
        **row['copy'], 'key': key, 'copy_ok': True, 'image_plan_ok': True,
        'image_status': image['status'], 'image_failure_code': 'submission_rejected',
    }]}) == []


@pytest.mark.parametrize('error', [
    runner.HttpFailure(400, '最多同时提交 6 个任务', 'https://backend.test'),
    runner.HttpFailure(429, 'busy', 'https://backend.test'),
    TimeoutError('response lost'),
])
def test_capacity_and_uncertain_network_keep_same_idempotency_key(tmp_path, monkeypatch, error):
    run, row = production(tmp_path, monkeypatch)
    requests = []
    sleeps = []

    def request(url, **kwargs):
        requests.append(kwargs['body']['client_request_id'])
        if len(requests) == 1:
            raise error
        return {'data': {'task_id': 'accepted'}}

    monkeypatch.setattr(runner, 'request_json', request)
    monkeypatch.setattr(runner.time, 'sleep', sleeps.append)
    task, _ = run.submit_image(row, 1, '')
    assert task == 'accepted' and len(requests) == 2 and len(set(requests)) == 1
    assert len(sleeps) == 1
    assert row['image']['task_id'] == 'accepted'


def online():
    value = runner.OnlineData.__new__(runner.OnlineData)
    value.public_root = 'http://127.0.0.1:8000'
    value.backend = value.public_root + '/api/v1'
    value.auth = {}
    return value


@pytest.mark.parametrize('url, expected', [
    ('/uploads/car.webp', '/uploads/car.webp'),
    ('http://127.0.0.1:8000/uploads/car.webp', '/uploads/car.webp'),
    ('http://127.0.0.1:8000/uploads/car.webp?v=1', '/uploads/car.webp?v=1'),
    ('https://oss.test/car.webp', 'https://oss.test/car.webp'),
])
def test_internal_upload_references_are_not_converted_to_rejected_loopback_urls(url, expected):
    assert online().reference_url(url) == expected


@pytest.mark.parametrize('url', ['/car-models/零跑C11/斜前.webp', 'car.webp',
                                 '/uploads/../private.png', '/uploads/%2e%2e/private.png',
                                 'http://127.0.0.1:8000/uploads/../private.png',
                                 'file:///tmp/car.png', 'https://user:secret@oss.test/car.png'])
def test_invalid_reference_shape_fails_before_model_calls(url):
    with pytest.raises(runner.ImageReferenceUnavailable):
        online().reference_url(url)


@pytest.mark.parametrize('header, valid', [
    (b'RIFF1234WEBP' + b'x' * 100, True),
    (b'\x89PNG\r\n\x1a\n' + b'x' * 100, True),
    (b'\xff\xd8\xff' + b'x' * 100, True),
    (b'<html>404</html>', False),
    (b'', False),
])
def test_reference_probe_checks_bytes_and_bounds_read(monkeypatch, header, valid):
    probes = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            assert limit == 32
            return header[:limit]

    def open_request(request, timeout):
        probes.append(request)
        assert timeout == 15
        return Response()

    monkeypatch.setattr(runner.urllib.request, 'build_opener', lambda *args: SimpleNamespace(open=open_request))
    if valid:
        online().check_reference_image('/uploads/car.webp')
    else:
        with pytest.raises(runner.ImageReferenceUnavailable):
            online().check_reference_image('/uploads/car.webp')
    assert len(probes) == 1


@pytest.mark.parametrize('address', ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1'])
def test_remote_reference_probe_refuses_private_addresses(monkeypatch, address):
    monkeypatch.setattr(runner.socket, 'getaddrinfo', lambda *args: [(None, None, None, None, (address, 80))])
    monkeypatch.setattr(runner.urllib.request, 'build_opener', lambda *args: pytest.fail('private source must not be read'))
    with pytest.raises(runner.ImageReferenceUnavailable):
        online().check_reference_image('http://untrusted.test/car.webp')


def test_probe_does_not_follow_redirects_to_private_hosts():
    with pytest.raises(runner.ImageReferenceUnavailable):
        runner.NoImageRedirect().redirect_request(None, None, 302, '', {}, 'http://127.0.0.1/private')


def test_catalog_rows_are_not_proof_of_readable_images(monkeypatch):
    monkeypatch.setattr(runner, 'request_json', lambda *args, **kwargs: {'data': {'images': [
        {'label': '斜前方', 'url': '/car-models/零跑C11/斜前.webp'},
    ]}})
    with pytest.raises(runner.ImageReferenceUnavailable):
        online().car_images('零跑汽车', '零跑C11')


def test_worker_reports_reference_failure_without_exposing_raw_log(tmp_path):
    log = tmp_path / 'worker.log'
    log.write_text('ImageReferenceUnavailable: ' + str(runner.ImageReferenceUnavailable()) + '\n')
    assert web_worker.missing_delivery_error(log, 1) == str(runner.ImageReferenceUnavailable())


def test_outer_worker_completes_rejected_delivery_without_recovery(monkeypatch, tmp_path):
    commands = []
    reports = []
    candidate = tmp_path / 'run-11' / '2026-10-10' / 'delivery_candidate.json'
    monkeypatch.setenv('HERMES_IMAGE_RECOVERY_ROUNDS', '2')
    monkeypatch.setattr(web_worker, 'build_run_config', lambda *args: ({}, '2026-10-10'))
    monkeypatch.setattr(web_worker, 'capabilities', lambda: {})
    monkeypatch.setattr(web_worker, 'send_progress', lambda *args: None)
    monkeypatch.setattr(web_worker, 'request_json', lambda *args, **kwargs: {'id': 11})
    monkeypatch.setattr(web_worker, 'send_report', lambda base, token, path: reports.append(json.loads(path.read_text())))

    class Process:
        returncode = 1

        def __init__(self, command, **kwargs):
            commands.append(command)
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_text(json.dumps({'production_ready': False, 'posts': [{
                'key': '42-01', 'title': '已生成标题', 'content': '已生成正文',
                'copy_ok': True, 'image_plan_ok': True, 'image_status': 'rejected',
                'image_failure_code': 'submission_rejected',
            }]}))

        def poll(self):
            return self.returncode

    monkeypatch.setattr(web_worker.subprocess, 'Popen', Process)
    assert web_worker.run_once('https://backend.test', 'offline', 'worker', tmp_path)
    assert len(commands) == 1 and len(reports) == 1
    assert reports[0]['path'].endswith('/complete')
