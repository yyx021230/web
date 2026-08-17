from app.services.ai_task_payload import compact_terminal_task_params


def test_compact_terminal_task_params_removes_reference_payloads() -> None:
    compacted = compact_terminal_task_params(
        {
            "width": 768,
            "height": 1024,
            "image_data": "data:image/png;base64,large",
            "image_url": "https://example.com/reference.png",
            "images_data": ["data:image/png;base64,one", "https://example.com/two.png"],
            "_processing_started_at": "2026-08-17T00:00:00",
            "provider": {"id": 5, "name": "provider"},
        }
    )

    assert compacted == {
        "width": 768,
        "height": 1024,
        "provider": {"id": 5, "name": "provider"},
        "_input_reference_payload_removed": True,
        "_input_reference_count": 4,
    }


def test_compact_terminal_task_params_keeps_small_metadata_unchanged() -> None:
    params = {
        "width": 1024,
        "height": 1024,
        "style": "写实",
        "_upstream_attempts": [
            {
                "upstream_task_id": "batch-123",
                "provider_id": 5,
                "query_capability": "batch_status",
            }
        ],
    }
    assert compact_terminal_task_params(params) == params
