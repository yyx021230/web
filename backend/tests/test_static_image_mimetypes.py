import mimetypes

from app import main as _main  # noqa: F401


def test_uploaded_image_mimetypes_are_registered() -> None:
    assert mimetypes.guess_type("cover.webp")[0] == "image/webp"
    assert mimetypes.guess_type("cover.avif")[0] == "image/avif"
    assert mimetypes.guess_type("vector.svg")[0] == "image/svg+xml"
