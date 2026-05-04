"""
Append distilled image OCR lessons to strategy memory.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import strategy_memory_service  # noqa: E402


PDF_IMAGE_REPORT = BACKEND / "data" / "ai" / "youzi_trade_notes" / "pdf_image_extraction_report.json"
OCR_REPORT = BACKEND / "data" / "ai" / "youzi_trade_notes" / "image_ocr" / "windows_ocr_report.json"


def _category(path: str) -> str:
    for key in ["退学炒股", "BJ炒家", "轮回666", "善行天助", "陈小群", "赵老哥", "凡倍无名"]:
        if key in path:
            return key
    return "其他"


def main() -> None:
    pdf_report = json.loads(PDF_IMAGE_REPORT.read_text(encoding="utf-8"))
    ocr_report = json.loads(OCR_REPORT.read_text(encoding="utf-8"))
    rows = ocr_report.get("rows") or []
    usable = [r for r in rows if int(r.get("quality_score") or 0) >= 120]
    low_quality = [r for r in rows if int(r.get("quality_score") or 0) < 120]
    categories = {}
    for row in usable:
        categories[_category(row.get("relative_path", ""))] = categories.get(_category(row.get("relative_path", "")), 0) + 1

    date_hits = 0
    table_like = 0
    for row in usable:
        text = re.sub(r"\s+", "", row.get("preview") or "")
        date_hits += len(re.findall(r"20[0-9四g]{2}[0-9OS口]{4}", text))
        if "明细" in text or "交易日期" in text or "查询日期" in text:
            table_like += 1

    note = {
        "type": "youzi_image_ocr_digest_v1",
        "title": "游资图片交割单OCR精华 v1",
        "source_root": pdf_report.get("source_root"),
        "pdf_image_report": str(PDF_IMAGE_REPORT),
        "ocr_report": str(OCR_REPORT),
        "coverage": {
            "image_count": pdf_report.get("image_count"),
            "ocr_attempted": ocr_report.get("attempted"),
            "usable_ocr_count": len(usable),
            "low_quality_count": len(low_quality),
            "category_counts": categories,
            "pdf_text_extracted": (pdf_report.get("pdf_status_counts") or {}).get("text_extracted", 0),
            "scanned_pdf_needs_ocr": (pdf_report.get("pdf_status_counts") or {}).get("needs_ocr_or_scanned_pdf", 0),
        },
        "ocr_quality_note": "Windows OCR 可识别表格日期和部分文字，但小字号证券代码/买卖方向/金额仍有误识别，暂不把图片OCR直接转为精确逐笔交易流水。",
        "observations": [
            f"可用OCR图片 {len(usable)} 张，多数来自退学炒股、BJ炒家、轮回666、善行天助、陈小群等实盘/交割单截图。",
            f"可识别的表格型图片约 {table_like} 张，日期字段命中约 {date_hits} 次，但存在 2019 被识别为 20四/201g 的问题。",
            "图片交割单更适合先沉淀为复盘数据结构：交易日期、标的、买卖方向、仓位变化、盈亏、次日处理、是否符合预案。",
            "当前 OCR 不适合直接生成 paper_trade_log.csv 的精确金额流水；需要更强表格 OCR 或人工校正后再写入正式模拟训练集。",
        ],
        "takeaways": [
            "实盘交割单的价值不只在单笔盈亏，而在连续交易中的仓位变化和错误修正：连续亏损应自动降低 AI 的激进评分。",
            "图片交割单强化了“交易后验标签”的重要性：买点类别、是否按计划卖出、次日承接是否验证、是否因为情绪退潮亏损。",
            "AI 学习交割单时必须区分可验证交易数据和 OCR 噪声；低置信度字段只能进入备注，不能参与权重训练。",
            "后续正式训练应先建立人工可校验的 trade_review schema，再从 OCR 中抽取候选字段供人工确认。",
        ],
        "factor_adjustments": [
            "youzi_experience 继续保留仓位纪律权重；当模拟盘出现连续亏损或 OCR/交割单复盘标记为买点错误时，自动降低 position_advice。",
            "新增后续字段建议：trade_setup_type、plan_followed、next_day_validation、loss_reason、ocr_confidence。",
            "AI 质量打分不得把 OCR 低置信度文本当作事实；只有人工确认或结构化解析置信度足够时才允许影响分数。",
        ],
        "implementation_hooks": [
            "建立 paper_trade_log.csv 后，将 OCR 图片作为候选证据来源而不是最终真值。",
            "为图片OCR增加人工校验页：原图、OCR文本、可编辑交易字段、保存到训练日志。",
            "扫描PDF 87 份和低质量图片 14 张进入增强OCR队列，可后续尝试 Tesseract/PaddleOCR 或版面表格识别。",
        ],
    }
    appended = strategy_memory_service.append_learning_note(note)
    print(json.dumps({"appended_title": appended.get("title"), "created_at": appended.get("created_at")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
