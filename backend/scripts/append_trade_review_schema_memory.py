"""
Append trade review candidate schema lessons to strategy memory.
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


CANDIDATE_PATH = BACKEND / "data" / "ai" / "youzi_trade_notes" / "trade_review_candidates.json"
CSV_PATH = BACKEND / "data" / "ai" / "youzi_trade_notes" / "trade_review_candidates.csv"


def main() -> None:
    payload = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))
    note = {
        "type": "trade_review_candidate_schema_v1",
        "title": "交割单复盘候选表与AI学习边界 v1",
        "candidate_json": str(CANDIDATE_PATH),
        "candidate_csv": str(CSV_PATH),
        "coverage": {
            "row_count": payload.get("row_count"),
            "status_counts": payload.get("status_counts"),
            "category_counts": payload.get("category_counts"),
        },
        "takeaways": [
            "OCR/PDF交割单已转成候选复盘表，但候选字段不是事实；AI只能把它们作为复盘线索，不能直接当成买卖流水。",
            "正式学习胜率和权重前，必须经过人工或高置信结构化确认，至少确认日期、标的、买卖方向、仓位变化、盈亏和卖出原因。",
            "复盘表的核心价值是训练AI问对问题：买点类别、是否符合计划、次日是否验证、亏损属于选股/买点/卖点/风控/数据哪一类。",
            "低质量OCR、扫描PDF和异常PDF进入增强队列，不参与量化权重调整，只能提醒后续补数。",
        ],
        "review_schema": {
            "required_before_training": [
                "trade_date",
                "code",
                "name",
                "side",
                "setup_type",
                "entry_reason",
                "exit_reason",
                "pnl_pct_or_amount",
                "plan_followed",
                "next_day_validation",
                "loss_reason",
                "source_confidence",
            ],
            "allowed_setup_types": [
                "low_suck",
                "halfway",
                "limit_board",
                "reseal",
                "leader_follow",
                "watch_only",
            ],
            "allowed_loss_reasons": [
                "stock_selection",
                "entry_timing",
                "exit_timing",
                "risk_control",
                "market_emotion",
                "data_missing",
                "unknown",
            ],
        },
        "factor_adjustments": [
            "AI质量打分可以引用 trade_review_candidates 的模式标签，但不得用未校验的OCR盈亏数据调整权重。",
            "当后续 paper_trade_log.csv 形成已验证交易样本后，才允许按至少30笔样本提出因子权重微调建议。",
            "如果连续亏损样本被标记为 entry_timing 或 market_emotion，youzi_experience 中的盘口承接和情绪周期权重应优先复核。",
        ],
        "implementation_hooks": [
            "前端后续增加交割单校验页，读取 trade_review_candidates.csv，人工确认后再写入 verified_trade_reviews.csv。",
            "verified_trade_reviews.csv 再与 paper_trade_log.csv 合并，用于日报、周报和AI复盘。",
            "AI对话中回答交割单问题时，要主动区分 OCR候选、PDF原则、已验证模拟交易 三类证据。",
        ],
    }
    appended = strategy_memory_service.append_learning_note(note)
    print(json.dumps({"appended_title": appended.get("title"), "created_at": appended.get("created_at")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
