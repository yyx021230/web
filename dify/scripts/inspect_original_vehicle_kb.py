import json
import re

from extensions.ext_storage import storage


KEYS = {
    "original": "upload_files/e26eb051-74fd-4a24-aa59-5b2f448e5d1b/7e0fcd25-29f5-4615-912a-8ca0ffc3feee.md",
}


for label, key in KEYS.items():
    raw = storage.load(key)
    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    separator_chunks = re.split(r"(?m)^---\s*$", text)
    version_records = re.split(r"(?m)^====\s*$", text)
    headers = re.findall(
        r"(?m)^品牌:\s*([^|\n]+)\s*\|\s*车型:\s*([^|\n]+)\s*\|\s*版本:\s*(.+)$",
        text,
    )
    chunk_summary = []
    for index, chunk in enumerate(separator_chunks[:12], start=1):
        chunk_headers = re.findall(r"(?m)^品牌:.*$", chunk)
        chunk_summary.append({
            "chunk": index,
            "chars": len(chunk),
            "version_count": len(chunk_headers),
            "first_header": chunk_headers[0] if chunk_headers else "",
            "last_header": chunk_headers[-1] if chunk_headers else "",
        })
    print(json.dumps({
        "label": label,
        "chars": len(text),
        "line_count": len(text.splitlines()),
        "separator_count": len(separator_chunks) - 1,
        "version_delimiter_count": len(version_records) - 1,
        "version_header_count": len(headers),
        "models": sorted(set(model.strip() for _, model, _ in headers)),
        "first_20_lines": text.splitlines()[:20],
        "first_12_separator_chunks": chunk_summary,
    }, ensure_ascii=False, indent=2))
