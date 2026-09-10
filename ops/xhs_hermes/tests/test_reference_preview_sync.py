import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))
from sync_reference_previews import make_snapshot


def test_snapshot_preserves_text_converts_origin_and_strips_credentials_and_user_metadata():
    original = '原文🚗\n#话题#'
    snapshot = make_snapshot([{'id': 1, 'title': '标题', 'content': original, 'token': 'must not export'}], [
        {'id': 2, 'name': '原始母图', 'chinese': original, 'image_url': '/uploads/example.png', 'is_public': True, 'created_by_name': 'private metadata'},
        {'id': 3, 'chinese': original, 'image_url': 'javascript:alert(1)'},
        {'id': 4, 'chinese': original, 'image_url': 'https://secret:password@example.test/x.png'},
    ], 'https://library.example.test')
    assert snapshot['copies'] == [{'id': 1, 'title': '标题', 'content': original}]
    first, second, third = snapshot['images']
    assert first['chinese'] == original
    assert first['image_url'] == 'https://library.example.test/uploads/example.png'
    assert first['is_public'] is True
    assert 'created_by_name' not in first
    assert second['is_public'] is False
    assert second['image_url'] == third['image_url'] == ''
