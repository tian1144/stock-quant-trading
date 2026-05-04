"""
Build review candidates from OCR/PDF extraction results.

This does not create official paper_trade_log rows. It creates a cautious,
human-verifiable table for learning and later correction.
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "backend" / "data" / "ai" / "youzi_trade_notes"
OCR_REPORT = DATA_DIR / "image_ocr" / "windows_ocr_report.json"
PDF_IMAGE_REPORT = DATA_DIR / "pdf_image_extraction_report.json"
OUT_JSON = DATA_DIR / "trade_review_candidates.json"
OUT_CSV = DATA_DIR / "trade_review_candidates.csv"

DATE_RE = re.compile(r"20[0-9]{2}[\s._-]*[0-9]{1,2}[\s._-]*[0-9]{1,2}")
CODE_RE = re.compile(r"(?<!\d)([0368][0-9]{5})(?!\d)")
AMOUNT_RE = re.compile(r"(?<!\d)([0-9]{1,3}(?:[,，][0-9]{3})+(?:\.[0-9]+)?|[0-9]{4,}(?:\.[0-9]+)?)(?!\d)")


def normalize_ocr_digits(text: str) -> str:
    return (
        (text or "")
        .replace("g", "9")
        .replace("O", "0")
        .replace("S", "5")
        .replace("，", ",")
    )


def category(path: str) -> str:
    for key in ["退学炒股", "BJ炒家", "轮回666", "善行天助", "陈小群", "赵老哥", "华东大导弹", "凡倍无名"]:
        if key in path:
            return key
    return "其他"


def setup_tags(text: str, path: str) -> list[str]:
    raw = f"{text} {path}"
    tags = []
    mapping = {
        "low_suck": ["低吸", "支撑", "回调", "恐慌", "反包"],
        "limit_board": ["打板", "涨停", "封板", "回封", "炸板"],
        "halfway": ["半路", "突破", "拉升", "追涨"],
        "leader": ["龙头", "主线", "前排", "辨识度"],
        "risk_control": ["止损", "回撤", "仓位", "空仓", "纪律"],
        "lhb_review": ["龙虎榜", "席位", "营业部"],
    }
    for tag, words in mapping.items():
        if any(w in raw for w in words):
            tags.append(tag)
    return tags


def build_from_ocr() -> list[dict]:
    report = json.loads(OCR_REPORT.read_text(encoding="utf-8"))
    rows = []
    for item in report.get("rows", []):
        q = int(item.get("quality_score") or 0)
        text = item.get("preview") or ""
        norm = normalize_ocr_digits(text)
        dates = DATE_RE.findall(norm)
        codes = CODE_RE.findall(norm)
        amounts = AMOUNT_RE.findall(norm)
        source_path = item.get("relative_path", "")
        candidate_type = "ocr_trade_sheet" if ("交割单" in source_path or "实盘" in source_path) else "ocr_lesson_image"
        rows.append({
            "candidate_id": f"ocr-{len(rows)+1:04d}",
            "source_type": candidate_type,
            "source_path": source_path,
            "trader_or_folder": category(source_path),
            "ocr_quality_score": q,
            "confidence": "high" if q >= 900 else "medium" if q >= 300 else "low",
            "extracted_dates": " | ".join(dates[:12]),
            "extracted_codes": " | ".join(codes[:12]),
            "extracted_amounts": " | ".join(amounts[:12]),
            "setup_tags": " | ".join(setup_tags(text, source_path)),
            "review_status": "needs_human_check" if q >= 120 else "low_quality_reprocess",
            "learning_use": "candidate_only_not_fact",
            "ocr_preview": text[:500],
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    return rows


def build_from_pdf_summary() -> list[dict]:
    report = json.loads(PDF_IMAGE_REPORT.read_text(encoding="utf-8"))
    rows = []
    for item in report.get("top_pdf_documents", [])[:80]:
        if item.get("data_status") != "text_extracted":
            continue
        path = item.get("relative_path", "")
        text = item.get("preview") or ""
        rows.append({
            "candidate_id": f"pdf-{len(rows)+1:04d}",
            "source_type": "pdf_lesson_or_trade_summary",
            "source_path": path,
            "trader_or_folder": category(path),
            "ocr_quality_score": item.get("char_count") or 0,
            "confidence": "text_pdf",
            "extracted_dates": "",
            "extracted_codes": "",
            "extracted_amounts": "",
            "setup_tags": " | ".join(setup_tags(text, path)),
            "review_status": "lesson_summary_available",
            "learning_use": "principle_and_review_schema",
            "ocr_preview": text[:500],
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    return rows


def main() -> None:
    rows = build_from_ocr() + build_from_pdf_summary()
    status_counts = Counter(row["review_status"] for row in rows)
    category_counts = Counter(row["trader_or_folder"] for row in rows)
    payload = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "description": "Candidate-only trade review table. Do not treat OCR fields as verified facts.",
        "row_count": len(rows),
        "status_counts": dict(status_counts),
        "category_counts": dict(category_counts),
        "rows": rows,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = [
        "candidate_id", "source_type", "source_path", "trader_or_folder", "ocr_quality_score",
        "confidence", "extracted_dates", "extracted_codes", "extracted_amounts", "setup_tags",
        "review_status", "learning_use", "ocr_preview", "created_at",
    ]
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})
    print(json.dumps({"json": str(OUT_JSON), "csv": str(OUT_CSV), "row_count": len(rows), "status_counts": dict(status_counts)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
