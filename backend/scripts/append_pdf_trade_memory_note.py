"""
Append distilled PDF text extraction lessons to strategy memory.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import strategy_memory_service  # noqa: E402


REPORT_PATH = BACKEND / "data" / "ai" / "youzi_trade_notes" / "pdf_image_extraction_report.json"


def main() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    top_docs = report.get("top_pdf_documents", [])
    sampled = [
        d["relative_path"]
        for d in top_docs
        if d.get("data_status") == "text_extracted"
    ][:20]

    note = {
        "type": "youzi_pdf_text_digest_v1",
        "title": "游资PDF文字资料精华 v1",
        "source_root": report.get("source_root"),
        "extraction_report": str(REPORT_PATH),
        "coverage": {
            "pdf_count": report.get("pdf_count"),
            "text_extracted": (report.get("pdf_status_counts") or {}).get("text_extracted", 0),
            "needs_ocr_or_scanned_pdf": (report.get("pdf_status_counts") or {}).get("needs_ocr_or_scanned_pdf", 0),
            "pdf_error": (report.get("pdf_status_counts") or {}).get("pdf_error", 0),
            "image_count": report.get("image_count"),
            "image_ocr_queued": (report.get("image_ocr_status_counts") or {}).get("queued", 0),
        },
        "documents_sampled": sampled,
        "theme_hit_totals": report.get("pdf_theme_hit_totals"),
        "takeaways": [
            "PDF资料进一步强化了“赚钱效应优先”的短线框架：先判断昨日涨停、连板高度、主线延续和亏钱效应，再决定是否出手。",
            "龙头/前排不是标签，而是由板块带动性、辨识度、承接强度和次日溢价共同确认；无跟风、无成交、无持续性的单股异动要降权。",
            "低吸资料强调模式边界：低吸必须发生在主线仍未证伪、回落到关键支撑、恐慌释放后承接出现的位置，不能把下跌趋势硬解释成低吸。",
            "打板/半路资料强调确定性来自情绪和盘口，不来自冲动；缩量一字、高位秒板、烂板弱回封都要区分处理。",
            "仓位资料强调回撤控制优先级高于收益追逐：亏损期减频减仓，连续判断错误时暂停交易并复盘，不允许 AI 自动加码。",
            "实盘记录和问答资料强化复盘纪律：每天记录买入理由、预期、次日验证、失败条件和卖出执行，而不是只记录盈亏。",
        ],
        "factor_adjustments": [
            "youzi_experience 中增加对赚钱效应/亏钱效应的解释权重：市场退潮或昨日涨停无溢价时，即使个股支撑形态好也应降级。",
            "leader_status 不能只看所属板块涨幅，应结合前排排名、板块跟随数量、连板高度、次日承接和成交额。",
            "entry_timing 应区分低吸、半路、打板、回封四类买点；AI 质量分必须说明当前候选属于哪类买点，若无法归类则只观察。",
            "position_advice 应受情绪周期和连续交易表现约束，模拟盘亏损期自动降到观察/小仓，不让单只高分票绕过仓位纪律。",
            "AI 复核理由中必须说明预期和证伪条件：买入后哪种盘口/板块/情绪表现说明判断失败。",
        ],
        "avoid_rules": [
            "把所有强势股都叫龙头。",
            "把所有回调都叫低吸。",
            "只因名人席位、PDF心法或历史战绩出现就提高买入评级。",
            "只看买点不看卖点和次日验证。",
            "在亏钱效应扩散时扩大候选池或提高仓位。",
        ],
        "implementation_hooks": [
            "后续 OCR 图片交割单后，优先抽取日期、股票、买卖方向、金额、盈亏和次日处理，用于 paper_trade_log.csv 复盘标签。",
            "AI 选股输出中加入买点类别字段：low吸/halfway/limit_board/reseal/watch_only。",
            "短线日报增加赚钱效应字段：涨停数、炸板率、昨日涨停红盘率、连板高度和跌停数。",
            "模拟交易日志完成后，把每笔交易与 youzi_experience 的情绪/主线/盘口/仓位判断做命中率统计。",
        ],
    }
    appended = strategy_memory_service.append_learning_note(note)
    print(json.dumps({"appended_title": appended.get("title"), "created_at": appended.get("created_at")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
