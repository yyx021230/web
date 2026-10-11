"""Offline failure-report regressions; no model, API or device calls."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import web_worker


SHORTAGE = 'RuntimeError: 文案类型「product_features」可用母文不足：0条；未调用生成接口，请调整类型或补充文案库'


def test_known_shortage_uses_ui_label(tmp_path):
    log = tmp_path / 'worker.log'
    log.write_text('Traceback (most recent call last):\n' + SHORTAGE + '\n', encoding='utf-8')
    assert web_worker.missing_delivery_error(log, 1) == SHORTAGE.removeprefix('RuntimeError: ').replace('product_features', '配置亮点')


@pytest.mark.parametrize('text', [
    'RuntimeError: provider failed: secret-token-example',
    'RuntimeError: 文案类型「secret_token_example」可用母文不足：0条；未调用生成接口，请调整类型或补充文案库',
    SHORTAGE + ' Authorization: secret-token-example',
    '{"error": "secret-token-example"}',
])
def test_unknown_errors_never_forward_raw_logs(tmp_path, text):
    log = tmp_path / 'worker.log'
    log.write_text(text, encoding='utf-8')
    assert web_worker.missing_delivery_error(log, 1) == 'Hermes exited 1 without a delivery manifest'


def test_missing_log_is_non_fatal(tmp_path):
    assert web_worker.missing_delivery_error(tmp_path / 'missing.log', 9) == 'Hermes exited 9 without a delivery manifest'


def test_large_log_and_auto_selection(tmp_path):
    log = tmp_path / 'worker.log'
    log.write_text('旧日志' * 20_000 + '\n' + SHORTAGE.replace('product_features', 'None'), encoding='utf-8')
    assert '自动选择' in web_worker.missing_delivery_error(log, 1)


def test_prior_shortage_does_not_hide_current_error(tmp_path):
    log = tmp_path / 'worker.log'
    log.write_text(SHORTAGE + '\nRuntimeError: a different stage failed\n', encoding='utf-8')
    assert web_worker.missing_delivery_error(log, 1) == 'Hermes exited 1 without a delivery manifest'


def test_successful_exit_does_not_reuse_a_prior_failure(tmp_path):
    log = tmp_path / 'worker.log'
    log.write_text(SHORTAGE, encoding='utf-8')
    assert web_worker.missing_delivery_error(log, 0) == 'Hermes exited 0 without a delivery manifest'


def test_worker_reports_shortage_without_retrying_or_completing(monkeypatch, tmp_path):
    calls = []
    processes = []
    monkeypatch.setenv('HERMES_IMAGE_RECOVERY_ROUNDS', '2')
    monkeypatch.setattr(web_worker, 'build_run_config', lambda *args: ({}, '2026-10-09'))
    monkeypatch.setattr(web_worker, 'capabilities', lambda: {})
    monkeypatch.setattr(web_worker, 'send_progress', lambda *args: None)

    def request(base, path, token, body, **kwargs):
        calls.append((path, body))
        return {'id': 11} if path.endswith('/claim') else {}

    class Process:
        returncode = 1

        def __init__(self, command, **kwargs):
            processes.append(command)
            kwargs['stdout'].write(SHORTAGE + '\n')
            kwargs['stdout'].flush()

        def poll(self):
            return self.returncode

    monkeypatch.setattr(web_worker, 'request_json', request)
    monkeypatch.setattr(web_worker.subprocess, 'Popen', Process)
    assert web_worker.run_once('https://example.test', 'offline', 'worker', tmp_path)
    assert len(processes) == 1
    assert [path.rsplit('/', 1)[-1] for path, _ in calls] == ['claim', 'fail']
    assert '配置亮点' in calls[-1][1]['error']
    assert '0条' in calls[-1][1]['error']
    assert not (tmp_path / 'run-11' / web_worker.REPORT_FILE).exists()
