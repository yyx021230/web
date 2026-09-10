"""Local OCR adapters. Windows-hosted Linux workers use pinned CPU ONNX models.

Both backends return the existing text/confidence contract. They never rewrite
recognized text or call an image-generation / remote OCR service.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import subprocess
import threading
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
RAPIDOCR_VERSION = "3.9.2"
ONNX_VERSION = "1.29.0"
# Models bundled in rapidocr 3.9.2; also checked against its default_models.yaml.
MODELS = {
    "Det": ("PP-OCRv6_det_small.onnx", "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f"),
    "Rec": ("PP-OCRv6_rec_small.onnx", "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884"),
    "Cls": ("ch_ppocr_mobile_v2.0_cls_mobile.onnx", "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c"),
}


def backend_name() -> str:
    value = os.environ.get("HERMES_OCR_BACKEND", "auto").strip().lower()
    if value == "auto":
        value = "apple-vision" if platform.system() == "Darwin" else "rapidocr"
    if value not in ("apple-vision", "rapidocr"):
        raise ValueError(f"Unsupported HERMES_OCR_BACKEND: {value}")
    if value == "apple-vision" and platform.system() != "Darwin":
        raise RuntimeError("Apple Vision requires macOS; configure HERMES_OCR_BACKEND=rapidocr")
    return value


def normalize_lines(texts: Any, scores: Any, boxes: Any = None) -> list[dict[str, Any]]:
    if texts is None or scores is None or len(texts) != len(scores):
        raise RuntimeError("OCR returned missing or mismatched text/confidence")
    lines = []
    for index, (text, confidence) in enumerate(zip(texts, scores)):
        value = float(confidence)
        if not isinstance(text, str) or not math.isfinite(value) or not 0 <= value <= 1:
            raise RuntimeError("OCR returned invalid text/confidence")
        if not text.strip():
            continue
        row: dict[str, Any] = {"text": text.strip(), "confidence": value}
        if boxes is not None and len(boxes) == len(texts):
            box = boxes[index]
            row["box"] = box.tolist() if hasattr(box, "tolist") else box
        lines.append(row)
    if not lines:
        raise RuntimeError("OCR recognized no text; image has not passed the text audit")
    return lines


class AppleVisionOCR:
    def __init__(self, run_dir: Path):
        source = ROOT / "ocr_image.swift"
        run_dir.mkdir(parents=True, exist_ok=True)
        self.binary = run_dir / "ocr_image"
        if not self.binary.exists() or self.binary.stat().st_mtime < source.stat().st_mtime:
            env = dict(os.environ, CLANG_MODULE_CACHE_PATH=str(run_dir / ".clang-module-cache"),
                       SWIFT_MODULE_CACHE_PATH=str(run_dir / ".swift-module-cache"))
            result = subprocess.run(["/usr/bin/swiftc", str(source), "-o", str(self.binary)],
                                    env=env, capture_output=True, text=True, timeout=180)
            if result.returncode:
                raise RuntimeError("Apple Vision compiler failed: " + result.stderr[-1200:])
        self.metadata = {"backend": "apple-vision"}

    def recognize(self, path: Path) -> list[dict[str, Any]]:
        result = subprocess.run([str(self.binary), str(path)], capture_output=True,
                                text=True, timeout=120)
        if result.returncode:
            raise RuntimeError("Apple Vision OCR failed: " + result.stderr[-1000:])
        payload = json.loads(result.stdout)
        if not payload or payload[0].get("error"):
            raise RuntimeError("Apple Vision returned no usable result")
        rows = payload[0].get("lines") or []
        return normalize_lines([row["text"] for row in rows], [row["confidence"] for row in rows])


class RapidOCRCPU:
    def __init__(self):
        for name, wanted in (("rapidocr", RAPIDOCR_VERSION), ("onnxruntime", ONNX_VERSION)):
            actual = importlib.metadata.version(name)
            if actual != wanted:
                raise RuntimeError(f"Expected {name}=={wanted}, found {actual}; use the tested worker image")
        import rapidocr
        from rapidocr import RapidOCR

        threads = int(os.environ.get("HERMES_OCR_THREADS", "2"))
        if not 1 <= threads <= 8:
            raise ValueError("HERMES_OCR_THREADS must be between 1 and 8")
        root = Path(os.environ.get("HERMES_OCR_MODEL_DIR") or Path(rapidocr.__file__).parent / "models")
        params: dict[str, Any] = {
            "Global.log_level": "warning", "Global.text_score": 0.25,
            "Global.max_side_len": 2048, "Det.limit_type": "max", "Det.limit_side_len": 1536,
            "EngineConfig.onnxruntime.intra_op_num_threads": threads,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            "EngineConfig.onnxruntime.use_cuda": False,
            "EngineConfig.onnxruntime.use_dml": False,
            "EngineConfig.onnxruntime.use_coreml": False,
        }
        for kind, (filename, expected) in MODELS.items():
            path = root / filename
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise RuntimeError(f"OCR model missing or checksum mismatch: {filename}")
            # Explicit paths prevent first-run model downloads / mutable remote defaults.
            params[f"{kind}.model_path"] = str(path)
        self.engine = RapidOCR(params=params)
        self.lock = threading.Lock()
        self.metadata = {"backend": "rapidocr", "rapidocr": RAPIDOCR_VERSION, "onnxruntime": ONNX_VERSION,
                         "models": {k: {"file": v[0], "sha256": v[1]} for k, v in MODELS.items()},
                         "cpu_threads": threads, "det_max_side": 1536}

    def recognize(self, path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            raise FileNotFoundError(path)
        # One model instance per batch; serialize CPU OCR, not network image jobs.
        with self.lock:
            result = self.engine(str(path))
        return normalize_lines(result.txts, result.scores, result.boxes)


def prepare_ocr(run_dir: Path) -> AppleVisionOCR | RapidOCRCPU:
    return AppleVisionOCR(run_dir) if backend_name() == "apple-vision" else RapidOCRCPU()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("images", type=Path, nargs="*")
    parser.add_argument("--run-dir", type=Path, default=Path(".ocr-probe"))
    args = parser.parse_args()
    engine = prepare_ocr(args.run_dir)
    result = {"runtime": engine.metadata, "images": [
        {"path": str(path), "lines": engine.recognize(path)} for path in args.images]}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
