"""
Append a distilled Youzi trade-sheet learning note to strategy memory.
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


REPORT_PATH = BACKEND / "data" / "ai" / "youzi_trade_notes" / "youzi_extraction_report.json"


def main() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    docs = report.get("parsed_documents", [])
    source_samples = [
        d["relative_path"]
        for d in docs
        if any(key in d["relative_path"] for key in ["仓位", "看盘", "公告", "龙头", "龙虎榜", "题材", "Asking"])
    ][:18]

    note = {
        "type": "youzi_trade_sheet_digest_v1",
        "title": "游资交割单与短线课程抽取精华 v1",
        "source_root": report.get("source_root"),
        "extraction_report": str(REPORT_PATH),
        "coverage": {
            "total_files_scanned": report.get("file_count"),
            "parsed_structured_documents": report.get("parsed_count"),
            "file_count_by_type": report.get("file_count_by_type"),
            "deferred": "PDF、图片、视频、音频、旧版 xls/doc/ppt 本轮未做 OCR/转写；后续可单独建解析任务。",
        },
        "documents_sampled": source_samples,
        "theme_hit_totals": report.get("theme_hit_totals"),
        "takeaways": [
            "短线核心不是预测，而是围绕情绪周期、主线板块、龙头辨识度和承接强弱做概率选择；市场否认预判时必须立刻降级。",
            "仓位应跟随赢面变化：赢面不足时空仓或小仓观察，只有情绪、板块、个股、风控同时确认时才允许提高模拟仓位。",
            "公告和公开信息能制造短线机会，但公告战法必须先看市场氛围、板块联动、前排强度和次日承接，不能只因利好买入。",
            "龙虎榜和交割单复盘重点不是崇拜席位，而是拆解买入位置、买入时点、题材级别、卖出纪律和亏损处理。",
            "看盘要优先识别全市场情绪、涨跌家数、昨日涨停红盘率、板块攻击数量、连板高度、封板/炸板质量，而不是只盯单股分时。",
            "亏损交易的处理决定短线水平：跌破计划、低于预期、情绪退潮或主力转弱时，先承认错误，禁止用补仓掩盖判断失败。",
        ],
        "factor_adjustments": [
            "AI质量打分中提高 emotion_cycle、sector_momentum、leader_status、market_tape_confirmation 的解释权重，但必须受 disclosure_risk 和 risk_review 约束。",
            "对公告/消息驱动票增加 market_breadth、yesterday_limit_up_red_rate、sector_limit_up_count、consecutive_limit_up_count 等短线氛围校验。",
            "对疑似龙头票增加 leader_identification、sector_follow_strength、first_divergence_repair、next_day_acceptance 字段；没有板块跟随的单股脉冲降权。",
            "对低吸支撑池继续保留 support_pullback，但若市场情绪退潮、板块无主线或大单承接不足，应只进观察池不进推荐池。",
            "仓位建议由 AI 分数和赢面共同决定：低于60%只观察，60%-70%小仓，70%-80%中低仓，80%以上也只允许模拟盘逐步验证。",
        ],
        "avoid_rules": [
            "连续加速高位再用利好解释的票，默认视为兑现风险，除非次日承接和板块强度同时确认。",
            "一字板、秒板、缩量高位板不直接追；缺少换手和可执行买点时只记录观察。",
            "龙虎榜单日豪华席位不等于买点；若位置高、筹码松、次日承接弱，应降权。",
            "亏损后不得让 AI 自动扩大仓位或提高激进因子；必须先归因到选股、买点、卖点、风控或数据缺失。",
        ],
        "implementation_hooks": [
            "后续接入涨停池/跌停池/炸板率后，把市场情绪周期作为 AI 选股质量分的一项。",
            "后续接入龙虎榜席位后，用席位连续性、买卖净额、板块联动验证游资参与质量。",
            "paper_trade_log.csv 完成后，每笔模拟交易都按本笔是否符合情绪、主线、买点、仓位、退出纪律打标签，作为策略记忆新增证据。",
            "AI输出推荐时必须写明：当前属于情绪周期哪一段、板块是否有攻击、个股是否前排、买点是低吸/半路/打板/回封中的哪类。",
        ],
    }

    appended = strategy_memory_service.append_learning_note(note)
    print(json.dumps({"appended_title": appended.get("title"), "created_at": appended.get("created_at")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
