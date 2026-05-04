"""
Append high-priority video OCR lessons to strategy memory.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services import strategy_memory_service  # noqa: E402


OCR_REPORT = BACKEND / "data" / "ai" / "youzi_trade_notes" / "video" / "video_frame_ocr_report.json"


KEYWORDS = {
    "盘中异动": ["异动", "盘中", "自下而上", "挖掘"],
    "热点龙头": ["龙头", "热点", "板块", "主线", "前排"],
    "低吸买点": ["低吸", "共振", "5天线", "10天线", "针尖"],
    "纪律止损": ["止损", "纪律", "仓位", "风险", "回撤"],
    "情绪周期": ["情绪", "周期", "买卖时机", "承接"],
    "建仓出货": ["建仓", "拉升", "出货", "卖出"],
}


def main() -> None:
    report = json.loads(OCR_REPORT.read_text(encoding="utf-8"))
    rows = report.get("rows") or []
    theme_counts = Counter()
    video_summaries = []
    for row in rows:
        text = f"{row.get('relative_path', '')}\n{row.get('combined_preview', '')}"
        hits = []
        for label, words in KEYWORDS.items():
            if any(word in text for word in words):
                hits.append(label)
                theme_counts[label] += 1
        video_summaries.append({
            "video_id": row.get("video_id"),
            "relative_path": row.get("relative_path"),
            "themes": hits or [row.get("themes") or "general"],
            "ocr_char_count": row.get("ocr_char_count", 0),
        })

    note = {
        "type": "youzi_video_frame_ocr_lessons_v1",
        "title": "游资视频关键帧OCR精华 v1",
        "source_report": str(OCR_REPORT),
        "coverage": {
            "sampled_videos": len(rows),
            "usable_videos": report.get("usable_videos"),
            "total_chars": report.get("total_chars"),
            "theme_counts": dict(theme_counts),
        },
        "takeaways": [
            "视频资料优先强化短线过程判断：盘中异动、热点板块、龙头辨识、低吸位置、仓位纪律和系统化止损。",
            "盘中异动不是单看涨速，要结合板块联动、前排辨识度、资金承接和是否出现新主线来判断。",
            "低吸买点更重视共振位置：热点未死、龙头或前排回到关键均线/支撑附近、分时恐慌释放后有承接。",
            "止损和仓位纪律应作为 AI 打分硬约束：买错后先判断是选股错、买点错、情绪周期错，不能靠补仓掩盖错误。",
            "建仓、拉升、出货课程只作为盘口行为理解，不等于能预测单一主力行为；AI 必须用数据和风控交叉验证。",
        ],
        "factor_adjustments": [
            "ai_quality_scoring 中的 youzi_experience 可加强 watch_tape、leader_hotspot、entry_setup、exit_risk 四类标签。",
            "当候选股只有个股异动、没有板块共振和主线确认时，热点龙头因子应降权或标记为 watch_only。",
            "当候选股处在5日/10日线附近低吸形态，但公告风险或情绪周期不支持时，只能进入观察池，不直接推荐购买。",
        ],
        "video_summaries": video_summaries[:12],
    }
    appended = strategy_memory_service.append_learning_note(note)
    print(json.dumps({"appended_title": appended.get("title"), "coverage": note["coverage"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
