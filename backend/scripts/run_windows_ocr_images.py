"""
Batch OCR image trade sheets with Windows built-in OCR.

Uses Pillow for preprocessing and calls backend/scripts/ocr_image_winrt.ps1.
Only writes derived OCR text under backend/data/ai/youzi_trade_notes/image_ocr.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = Path(r"E:\迅雷\下载目录\游资交割单")
REPORT_PATH = ROOT / "backend" / "data" / "ai" / "youzi_trade_notes" / "pdf_image_extraction_report.json"
OUTPUT_DIR = ROOT / "backend" / "data" / "ai" / "youzi_trade_notes" / "image_ocr"
PREP_DIR = OUTPUT_DIR / "prepared"
PS_SCRIPT = ROOT / "backend" / "scripts" / "ocr_image_winrt.ps1"


def safe_name(rel: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", rel)[-180:]


def prepare_image(src: Path, out: Path) -> None:
    with Image.open(src) as img:
        img = img.convert("L")
        w, h = img.size
        scale = 2 if max(w, h) < 1800 else 1.5 if max(w, h) < 2600 else 1
        if scale != 1:
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        img = ImageEnhance.Contrast(img).enhance(1.8)
        img = ImageEnhance.Sharpness(img).enhance(1.4)
        img = img.filter(ImageFilter.MedianFilter(size=3))
        img.save(out)


def run_ocr(src: Path, prepared: Path) -> dict:
    cmd = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(PS_SCRIPT),
        "-ImagePath",
        str(src),
        "-PreparedPath",
        str(prepared),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    if proc.returncode != 0:
        return {"ok": False, "error": (proc.stderr or proc.stdout)[-500:]}
    try:
        payload = json.loads(proc.stdout)
    except Exception:
        return {"ok": False, "error": proc.stdout[-500:]}
    return {"ok": True, **payload}


def quality_score(text: str, line_count: int) -> int:
    text = text or ""
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
    digits = len(re.findall(r"\d", text))
    boxes = text.count("囗") + text.count("□")
    keywords = sum(text.count(k) for k in ["证券", "股票", "成交", "买入", "卖出", "盈亏", "市值", "资金", "余额", "成本", "代码"])
    return chinese + min(120, digits) + keywords * 20 + line_count * 3 - boxes * 8


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 80
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    images = report.get("image_documents", [])
    queue = [
        item for item in images
        if item.get("ocr_status") == "queued" and item.get("data_status") == "indexed"
    ]
    queue = sorted(queue, key=lambda x: (x.get("priority") or 0, x.get("size") or 0), reverse=True)[:limit]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PREP_DIR.mkdir(parents=True, exist_ok=True)

    rows = []
    for idx, item in enumerate(queue, 1):
        src = SOURCE_ROOT / item["relative_path"]
        name = safe_name(item["relative_path"])
        prepared = PREP_DIR / f"{name}.png"
        text_path = OUTPUT_DIR / f"{name}.txt"
        try:
            prepare_image(src, prepared)
            ocr = run_ocr(src, prepared)
        except Exception as exc:
            ocr = {"ok": False, "error": str(exc)[:500]}
        text = ocr.get("text") if ocr.get("ok") else ""
        q = quality_score(text, int(ocr.get("line_count") or 0))
        if text:
            text_path.write_text(text, encoding="utf-8")
        rows.append({
            "relative_path": item["relative_path"],
            "text_file": str(text_path) if text else None,
            "prepared_file": str(prepared),
            "ok": bool(ocr.get("ok")),
            "line_count": ocr.get("line_count", 0),
            "char_count": len(text or ""),
            "quality_score": q,
            "preview": (text or "")[:700],
            "error": ocr.get("error", ""),
        })
        print(json.dumps({"done": idx, "total": len(queue), "ok": bool(ocr.get("ok")), "quality": q, "file": item["relative_path"]}, ensure_ascii=False))

    out = OUTPUT_DIR / "windows_ocr_report.json"
    payload = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_root": str(SOURCE_ROOT),
        "attempted": len(rows),
        "usable_count": len([r for r in rows if r.get("quality_score", 0) >= 120]),
        "rows": rows,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(out), "attempted": payload["attempted"], "usable_count": payload["usable_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
