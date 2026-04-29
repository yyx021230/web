"""Import template images from local folders into the database"""

import os
import uuid
import asyncio
import sqlite3
import shutil
from pathlib import Path

DB_PATH = Path("dev.db")
UPLOADS_DIR = Path("uploads")
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

FOLDERS = {
    "/Users/yyx/Downloads/大字报": "大字报",
    "/Users/yyx/Downloads/汽车报价单图": "汽车报价单图",
    "/Users/yyx/Downloads/汽车产品主图": "汽车产品主图",
}

def import_images():
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    total = 0
    for folder, tag in FOLDERS.items():
        folder_path = Path(folder)
        if not folder_path.exists():
            print(f"Skip {folder}: not found")
            continue
        for f in folder_path.iterdir():
            if not f.is_file():
                continue
            ext = f.suffix.lower()
            if ext not in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
                continue
            # Copy file to uploads
            new_name = f"{uuid.uuid4().hex}{ext}"
            dest = UPLOADS_DIR / new_name
            shutil.copy2(f, dest)
            url = f"/uploads/{new_name}"
            # Insert into materials
            cursor.execute(
                """INSERT INTO materials (name, type, url, category, tags, created_by)
                   VALUES (?, 'image', ?, 'ai-template', ?, 5)""",
                (f.name, url, tag),
            )
            total += 1
            print(f"  [{tag}] {f.name}")
    conn.commit()
    print(f"\nTotal imported: {total}")
    conn.close()

import_images()
