"""Read local cover headers, not pixels or remote images, for stable feed layout."""

from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlsplit

from PIL import Image


@lru_cache(maxsize=8192)
def _dimensions(path: str, mtime_ns: int, size: int) -> tuple[int, int]:
    with Image.open(path) as image:
        width, height = image.size
        if image.getexif().get(274) in (5, 6, 7, 8):
            width, height = height, width
        return width, height


def add_prompt_image_dimensions(items: list[dict], storage_path: str) -> None:
    root = Path(storage_path).resolve()
    for item in items:
        try:
            url = urlsplit(str(item.get("image_url") or ""))
            if url.netloc or url.scheme or not url.path.startswith("/uploads/"):
                continue
            path = (root / unquote(url.path[len("/uploads/"):])).resolve()
            if not path.is_relative_to(root):
                continue
            stat = path.stat()
            width, height = _dimensions(str(path), stat.st_mtime_ns, stat.st_size)
            item.update(image_width=width, image_height=height)
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
            # Missing/corrupt covers must never prevent the feed from loading.
            continue
