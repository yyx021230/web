import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import ocr_backend
import worker_runtime
import container_entrypoint
import web_worker


@pytest.mark.parametrize('system,expected', [('Darwin', 'apple-vision'), ('Linux', 'rapidocr'), ('Windows', 'rapidocr')])
def test_platform_default(monkeypatch, system, expected):
    monkeypatch.delenv('HERMES_OCR_BACKEND', raising=False)
    monkeypatch.setattr(ocr_backend.platform, 'system', lambda: system)
    assert ocr_backend.backend_name() == expected


def test_apple_cannot_silently_run_on_linux(monkeypatch):
    monkeypatch.setenv('HERMES_OCR_BACKEND', 'apple-vision')
    monkeypatch.setattr(ocr_backend.platform, 'system', lambda: 'Linux')
    with pytest.raises(RuntimeError, match='requires macOS'):
        ocr_backend.backend_name()


def test_ocr_preserves_text_numbers_and_confidence():
    assert ocr_backend.normalize_lines(['￥56,232起', '510智享版', '9月31日'], [.99, .28, .9]) == [
        {'text': '￥56,232起', 'confidence': .99}, {'text': '510智享版', 'confidence': .28},
        {'text': '9月31日', 'confidence': .9}]


@pytest.mark.parametrize('texts,scores', [(None, None), ([], []), (['x'], []), (['x'], [float('nan')]), (['x'], [1.2])])
def test_unusable_ocr_is_not_a_success(texts, scores):
    with pytest.raises(RuntimeError):
        ocr_backend.normalize_lines(texts, scores)


def test_bad_package_version_stops_before_import(monkeypatch):
    monkeypatch.setattr(ocr_backend.importlib.metadata, 'version', lambda name: '0.0.0')
    with pytest.raises(RuntimeError, match='Expected rapidocr'):
        ocr_backend.RapidOCRCPU()


def test_limits_only_cap_concurrency(monkeypatch):
    monkeypatch.setenv('HERMES_MAX_TEXT_WORKERS', '2')
    monkeypatch.setenv('HERMES_MAX_IMAGE_WORKERS', '5')
    original = {'copy_workers': 5, 'image_plan_workers': 1, 'text_workers': 8, 'image_workers': 3, 'selection': 'random'}
    result = worker_runtime.apply_worker_limits(original)
    assert result == {**original, 'copy_workers': 2, 'text_workers': 2}
    assert original['copy_workers'] == 5


def test_no_ceilings_preserves_local_settings(monkeypatch):
    monkeypatch.delenv('HERMES_MAX_TEXT_WORKERS', raising=False)
    monkeypatch.delenv('HERMES_MAX_IMAGE_WORKERS', raising=False)
    original = {'copy_workers': 5, 'image_workers': 5}
    assert worker_runtime.apply_worker_limits(original) == original


def test_runner_uses_current_python_without_shell():
    assert worker_runtime.runner_command() == [sys.executable, str(worker_runtime.ROOT / 'run_daily_8x5.py')]


def test_hermes_paths_can_be_overridden(monkeypatch):
    monkeypatch.setenv('HERMES_REPO', '/opt/hermes-agent')
    monkeypatch.setenv('HERMES_PYTHON', '/opt/venv/bin/python')
    assert worker_runtime.hermes_repo() == Path('/opt/hermes-agent')
    assert worker_runtime.hermes_python() == Path('/opt/venv/bin/python')


def test_missing_or_changed_models_never_start_engine(monkeypatch, tmp_path):
    from types import SimpleNamespace
    versions = {'rapidocr': ocr_backend.RAPIDOCR_VERSION, 'onnxruntime': ocr_backend.ONNX_VERSION}
    monkeypatch.setattr(ocr_backend.importlib.metadata, 'version', versions.__getitem__)
    monkeypatch.setenv('HERMES_OCR_MODEL_DIR', str(tmp_path))
    monkeypatch.setitem(sys.modules, 'rapidocr', SimpleNamespace(RapidOCR=lambda **kw: pytest.fail('must not start')))
    with pytest.raises(RuntimeError, match='checksum mismatch'):
        ocr_backend.RapidOCRCPU()


def test_seeding_preserves_user_policy_and_existing_progress(tmp_path):
    seed, target = tmp_path / 'seed', tmp_path / 'target'
    for folder in (seed, target):
        (folder / 'config').mkdir(parents=True)
    (seed / 'config/cases.json').write_text('old policy')
    (seed / 'config/new.json').write_text('seed')
    (target / 'config/cases.json').write_text('updated by user')
    container_entrypoint.seed_missing(seed, target)
    assert (target / 'config/cases.json').read_text() == 'updated by user'
    assert (target / 'config/new.json').read_text() == 'seed'


def test_managed_home_updates_release_code_not_memory(tmp_path):
    seed, target = tmp_path / 'seed', tmp_path / 'target'
    seed.mkdir()
    target.mkdir()
    (seed / 'config.yaml').write_text('new plugin configuration')
    (target / 'config.yaml').write_text('old plugin configuration')
    (target / 'state.db').write_text('existing state')
    container_entrypoint.refresh_managed_home(seed, target)
    assert (target / 'config.yaml').read_text() == 'new plugin configuration'
    assert (target / 'state.db').read_text() == 'existing state'


def test_health_uses_successful_api_timestamp(monkeypatch, tmp_path):
    path = tmp_path / 'health.json'
    monkeypatch.setattr(container_entrypoint, 'HEALTH', path)
    monkeypatch.setenv('HERMES_CONTAINER_HEALTH_PATH', str(path))
    assert container_entrypoint.health() == 1
    web_worker.record_api_health()
    assert container_entrypoint.health() == 0
    path.write_text('{"last_api_success": 0}')
    assert container_entrypoint.health() == 1


def test_shutdown_requests_drain_not_process_termination(monkeypatch):
    monkeypatch.setattr(web_worker, 'STOP_REQUESTED', False)
    web_worker.request_stop()
    assert web_worker.STOP_REQUESTED is True
