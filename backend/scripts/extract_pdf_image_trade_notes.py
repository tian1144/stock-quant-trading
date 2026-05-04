"""
Read-only PDF/image extractor for Youzi trade-sheet materials.

This script uses the bundled Codex Python runtime when available because it has
pypdf/Pillow in this desktop environment. It never modifies the source folder.
OCR is optional: if tesseract is unavailable, images are indexed and queued.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path


SOURCE_ROOT = Path(r"E:\迅雷\下载目录\游资交割单")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "backend" / "data" / "ai" / "youzi_trade_notes"
PDF_TEXT_DIR = OUTPUT_DIR / "pdf_text"
IMAGE_INDEX_DIR = OUTPUT_DIR / "image_index"

KEYWORDS = [
    "交割单",
    "心法",
    "情绪",
    "龙头",
    "板块",
    "复盘",
    "龙虎榜",
    "买卖点",
    "仓位",
    "风险",
    "公告",
    "题材",
    "看盘",
    "短线",
    "退学",
    "炒股养家",
    "涅盘",
    "涅槃",
    "92科比",
    "乔帮主",
    "赵老哥",
    "BJ炒家",
    "轮回666",
]

THEME_PATTERNS = {
    "emotion_cycle": ["情绪", "周期", "退潮", "高潮", "冰点", "修复", "分歧", "一致"],
    "leader_sector": ["龙头", "板块", "主线", "题材", "强弱", "辨识度", "带动"],
    "entry_timing": ["买点", "低吸", "半路", "打板", "回封", "分时", "承接", "突破"],
    "exit_timing": ["卖点", "止损", "止盈", "不及预期", "炸板", "破位", "减仓"],
    "position_risk": ["仓位", "回撤", "风险", "控制", "纪律", "空仓"],
    "disclosure_news": ["公告", "信息", "利好", "利空", "公开信息", "新闻"],
    "lhb_review": ["龙虎榜", "席位", "营业部", "交割单", "复盘"],
    "market_tape": ["看盘", "盘口", "量能", "换手", "封单", "炸板", "大单"],
}


def _import_pdf_reader():
    try:
        from pypdf import PdfReader
        return PdfReader
    except Exception:
        return None


def _import_pil_image():
    try:
        from PIL import Image
        return Image
    except Exception:
        return None


def clean_text(text: str, limit: int = 30000) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit]


def priority_score(path: Path) -> int:
    name = str(path)
    score = sum(10 for kw in KEYWORDS if kw in name)
    if path.suffix.lower() == ".pdf":
        score += 20
    if "悟道心法" in name:
        score += 25
    if "交割单" in name:
        score += 20
    if "实盘" in name:
        score += 12
    return score


def theme_hits(text: str) -> dict:
    return {theme: sum(text.count(word) for word in words) for theme, words in THEME_PATTERNS.items()}


def safe_name(path: Path) -> str:
    rel = str(path.relative_to(SOURCE_ROOT))
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", rel)[-180:]


def extract_pdf_text(path: Path, PdfReader) -> dict:
    result = {
        "relative_path": str(path.relative_to(SOURCE_ROOT)),
        "extension": ".pdf",
        "size": path.stat().st_size,
        "priority": priority_score(path),
        "page_count": 0,
        "char_count": 0,
        "theme_hits": {},
        "preview": "",
        "text_file": None,
        "data_status": "unread",
        "error": "",
    }
    try:
        reader = PdfReader(str(path))
        result["page_count"] = len(reader.pages)
        parts = []
        for page in reader.pages[:80]:
            try:
                parts.append(page.extract_text() or "")
            except Exception:
                continue
        text = clean_text("\n".join(parts))
        result["char_count"] = len(text)
        result["theme_hits"] = theme_hits(text)
        result["preview"] = text[:900]
        if text:
            PDF_TEXT_DIR.mkdir(parents=True, exist_ok=True)
            out = PDF_TEXT_DIR / f"{safe_name(path)}.txt"
            out.write_text(text, encoding="utf-8")
            result["text_file"] = str(out)
            result["data_status"] = "text_extracted"
        else:
            result["data_status"] = "needs_ocr_or_scanned_pdf"
    except Exception as exc:
        result["data_status"] = "pdf_error"
        result["error"] = str(exc)[:300]
    return result


def image_info(path: Path, Image) -> dict:
    result = {
        "relative_path": str(path.relative_to(SOURCE_ROOT)),
        "extension": path.suffix.lower(),
        "size": path.stat().st_size,
        "priority": priority_score(path),
        "width": None,
        "height": None,
        "mode": None,
        "data_status": "indexed",
        "ocr_status": "queued",
    }
    try:
        with Image.open(path) as img:
            result["width"], result["height"] = img.size
            result["mode"] = img.mode
            pixels = (result["width"] or 0) * (result["height"] or 0)
            if pixels < 250000:
                result["ocr_status"] = "low_resolution_review_first"
    except Exception as exc:
        result["data_status"] = "image_error"
        result["ocr_status"] = "failed_open"
        result["error"] = str(exc)[:300]
    return result


def main() -> None:
    if not SOURCE_ROOT.exists():
        raise SystemExit(f"source root not found: {SOURCE_ROOT}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    Image = _import_pil_image()
    PdfReader = _import_pdf_reader()
    tesseract = shutil.which("tesseract")

    files = [p for p in SOURCE_ROOT.rglob("*") if p.is_file()]
    pdfs = sorted([p for p in files if p.suffix.lower() == ".pdf"], key=lambda p: (priority_score(p), -p.stat().st_size), reverse=True)
    images = sorted([p for p in files if p.suffix.lower() in {".png", ".jpg", ".jpeg"}], key=lambda p: (priority_score(p), -p.stat().st_size), reverse=True)

    pdf_results = []
    if PdfReader:
        for path in pdfs:
            pdf_results.append(extract_pdf_text(path, PdfReader))
    else:
        pdf_results = [{
            "relative_path": str(path.relative_to(SOURCE_ROOT)),
            "extension": ".pdf",
            "size": path.stat().st_size,
            "priority": priority_score(path),
            "data_status": "missing_pypdf",
        } for path in pdfs]

    image_results = []
    if Image:
        for path in images:
            image_results.append(image_info(path, Image))
    else:
        image_results = [{
            "relative_path": str(path.relative_to(SOURCE_ROOT)),
            "extension": path.suffix.lower(),
            "size": path.stat().st_size,
            "priority": priority_score(path),
            "data_status": "missing_pillow",
            "ocr_status": "blocked",
        } for path in images]

    pdf_theme_totals = Counter()
    for item in pdf_results:
        pdf_theme_totals.update(item.get("theme_hits") or {})

    report = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_root": str(SOURCE_ROOT),
        "pdf_count": len(pdfs),
        "image_count": len(images),
        "dependencies": {
            "pypdf": bool(PdfReader),
            "pillow": bool(Image),
            "tesseract_cmd": tesseract,
        },
        "pdf_status_counts": dict(Counter(item.get("data_status") for item in pdf_results)),
        "image_status_counts": dict(Counter(item.get("data_status") for item in image_results)),
        "image_ocr_status_counts": dict(Counter(item.get("ocr_status") for item in image_results)),
        "pdf_theme_hit_totals": dict(pdf_theme_totals),
        "top_pdf_documents": sorted(pdf_results, key=lambda x: (x.get("char_count") or 0, x.get("priority") or 0), reverse=True)[:80],
        "pdf_documents": pdf_results,
        "image_documents": image_results,
        "notes": [
            "PDF文本抽取优先使用 pypdf；无文本的扫描PDF标记为 needs_ocr_or_scanned_pdf。",
            "图片本轮先完成索引和OCR队列；若本机安装 tesseract，可在下一轮启用图片OCR。",
            "视频、音频仍按用户要求放到最后处理。",
        ],
    }
    out_path = OUTPUT_DIR / "pdf_image_extraction_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(out_path),
        "pdf_count": len(pdfs),
        "image_count": len(images),
        "pdf_status_counts": report["pdf_status_counts"],
        "image_ocr_status_counts": report["image_ocr_status_counts"],
        "tesseract_cmd": tesseract,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
