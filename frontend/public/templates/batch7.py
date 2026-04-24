#!/usr/bin/env python3
"""Batch 7: Expand template collection - fixed for new API format."""

import json
import re
import gzip
import time
import requests
from pathlib import Path

BASE_DIR = Path("/Users/yyx/ztqc/web/frontend/public/templates")
INDEX_FILE = BASE_DIR / "index.json"

with open(INDEX_FILE) as f:
    existing_templates = json.load(f)
existing_ids = set(t["id"] for t in existing_templates)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "X-Channel-Id": "32",
}

def api_get(url, params=None):
    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    data = resp.content
    if data[:2] == b'\x1f\x8b':
        data = gzip.decompress(data)
    return json.loads(data.decode("utf-8"))

def get_similar_templates(template_id, pages=4):
    results = []
    for page in range(1, pages + 1):
        try:
            url = "https://www.gaoding.com/api/v3/cp/recommend-contents/templates/similar"
            data = api_get(url, params={"id": template_id, "page": page, "page_size": 40})
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                if isinstance(data.get("data"), list):
                    items = data["data"]
                elif isinstance(data.get("data"), dict):
                    items = data.get("data", {}).get("items", [])
                else:
                    items = []
            else:
                items = []
            if not items:
                break
            results.extend(items)
            time.sleep(0.3)
        except Exception as e:
            print(f"  Error page {page}: {e}")
            break
    return results

def get_template_meta(template_id):
    url = f"https://www.gaoding.com/api/v3/cp/contents/{template_id}/distribution-infos"
    data = api_get(url)
    # New format: data is returned directly at top level
    if isinstance(data, dict) and "id" in data:
        return data
    return data.get("data", {})

def download_file(url, path):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code == 200:
            with open(path, "wb") as f:
                f.write(resp.content)
            return True
    except Exception:
        pass
    return False

def extract_image_urls(design_data):
    text = json.dumps(design_data)
    urls = re.findall(r'https?://[^\s"\'}\)]+\.(?:jpg|jpeg|png|gif|svg|webp)[^\s"\'}\)]*', text)
    return list(set(urls))

def download_template(meta, folder_name):
    folder = BASE_DIR / folder_name
    folder.mkdir(exist_ok=True)
    img_folder = folder / "images"
    img_folder.mkdir(exist_ok=True)

    # Design JSON: prefer content_url, fallback to parsing content field
    content_url = meta.get("content_url")
    content_str = meta.get("content")
    design_json = None

    if content_url:
        try:
            resp = requests.get(content_url, headers=HEADERS, timeout=30)
            cdata = resp.content
            if cdata[:2] == b'\x1f\x8b':
                cdata = gzip.decompress(cdata)
            design_json = json.loads(cdata.decode("utf-8"))
        except Exception as e:
            print(f"    content_url error: {e}")

    if not design_json and content_str:
        try:
            design_json = json.loads(content_str)
        except Exception:
            pass

    if design_json:
        with open(folder / "design.json", "w") as f:
            json.dump(design_json, f)

        img_urls = extract_image_urls(design_json)
        downloaded = 0
        for i, url in enumerate(img_urls):
            ext = url.split("?")[0].split(".")[-1].lower()
            if ext not in ("jpg", "jpeg", "png", "gif", "svg", "webp"):
                ext = "png"
            fname = f"img_{i:03d}.{ext}"
            if download_file(url, img_folder / fname):
                downloaded += 1
        print(f"    design.json + {downloaded}/{len(img_urls)} images")
    else:
        print(f"    No design data available")

    # Preview: from preview.url or composite_preview.url
    preview = meta.get("preview", {})
    preview_url = preview.get("url") or preview.get("url_watermark") or meta.get("composite_preview", {}).get("url", "")
    if preview_url:
        ext = "png" if ".png" in preview_url.split("?")[0].lower() else "jpg"
        download_file(preview_url, folder / f"preview.{ext}")

def sanitize_title(title):
    safe = re.sub(r'[\\/:*?"<>|\s]+', '', title)[:50]
    return safe if safe else "untitled"

def main():
    seeds = [
        "194446051",  # 考研英语
        "194541671",  # CPA考试
        "194982671",  # K12数理思维
        "33960314",   # 种草购物
        "33968252",   # 母婴亲子
        "48230617",   # 准大一
        "48210964",   # 简约光影
        "48245044",   # 母婴糖果
    ]

    all_new = []
    scanned = 0

    print("=== Phase 1: Discover ===")
    for seed in seeds:
        print(f"\nSeed: {seed}")
        similar = get_similar_templates(seed, pages=4)
        scanned += len(similar)
        for item in similar:
            tid = str(item.get("id", ""))
            if tid and tid not in existing_ids and tid not in [t["id"] for t in all_new]:
                title = item.get("title", "untitled")
                all_new.append({"id": tid, "title": title})
                print(f"  NEW: {tid} - {title[:40]}")

    print(f"\nScanned: {scanned}, Found new: {len(all_new)}")
    if not all_new:
        print("Pool may be exhausted.")
        return

    print("\n=== Phase 2: Download ===")
    for i, new_t in enumerate(all_new):
        tid = new_t["id"]
        print(f"\n[{i+1}/{len(all_new)}] {tid}: {new_t['title'][:50]}")
        try:
            meta = get_template_meta(tid)
            if not meta or "id" not in meta:
                print(f"    No metadata")
                continue

            folder_name = f"gaoding_{tid}_{sanitize_title(new_t['title'])}"
            download_template(meta, folder_name)

            # Get dimensions from content
            width, height = 1242, 1656
            content_str = meta.get("content")
            if content_str:
                try:
                    content = json.loads(content_str)
                    layouts = content.get("layouts", [])
                    if layouts:
                        w = layouts[0].get("width")
                        h = layouts[0].get("height")
                        if w and h:
                            width, height = w, h
                except Exception:
                    pass

            entry = {
                "id": tid,
                "title": new_t["title"],
                "type": "poster",
                "width": width,
                "height": height,
                "payment": meta.get("price", 0),
                "image_count": 0,
                "preview": f"{folder_name}/preview.jpg",
                "design_json": f"{folder_name}/design.json",
                "meta_json": f"{folder_name}/meta.json",
                "folder": folder_name,
            }
            img_folder = BASE_DIR / folder_name / "images"
            if img_folder.exists():
                entry["image_count"] = len(list(img_folder.glob("*")))

            meta_out = {
                "id": tid, "title": new_t["title"], "type": "poster",
                "width": width, "height": height,
                "backgroundImage": meta.get("preview", {}).get("url", ""),
                "content_url": meta.get("content_url", ""),
                "preview_url": meta.get("preview", {}).get("url", ""),
            }
            with open(BASE_DIR / folder_name / "meta.json", "w") as f:
                json.dump(meta_out, f, ensure_ascii=False, indent=2)

            existing_templates.append(entry)
            existing_ids.add(tid)
            print(f"    OK")
        except Exception as e:
            print(f"    Error: {e}")
        time.sleep(0.5)

    print("\n=== Phase 3: Update index ===")
    with open(INDEX_FILE, "w") as f:
        json.dump(existing_templates, f, ensure_ascii=False, indent=2)

    total_images = sum(e.get("image_count", 0) for e in existing_templates)
    print(f"Templates: {len(existing_templates)}, Images: {total_images}")

if __name__ == "__main__":
    main()
