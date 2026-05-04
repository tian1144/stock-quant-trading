"""
Model-independent strategy memory.

This is not model fine-tuning. It is a portable knowledge and preference layer
that every configured LLM receives in its system context, so switching providers
does not erase the site's trading habits.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "ai")
MEMORY_PATH = os.path.join(DATA_DIR, "strategy_memory.json")


DEFAULT_MEMORY = {
    "version": "short-hunter-memory-v1",
    "updated_at": None,
    "scope": "A股短线研究、模拟盘复盘、AI选股质量打分",
    "principles": [
        "先做模拟盘和研究判断，不允许绕过风控直接真实下单。",
        "短线不是追高冲动，优先寻找低位箱体、回落支撑、资金重新确认的机会。",
        "AI必须能解释买点、等待原因、失效条件和风控证据，不能只给结论。",
        "样本不足时使用中性判断，不把偶然盈利当作有效规律。",
        "公告、问询函、减持、诉讼、审计非标、业绩雷属于硬风险源，宁可错过也不硬买。",
    ],
    "short_term_playbook": {
        "preferred_setups": [
            "箱体震荡后回落到支撑位，未破位，近5日不过热。",
            "板块有资金或新闻催化，但个股未处在连续加速高位。",
            "主力/大单边际改善，同时散户压力没有明显升高。",
            "历史相似规则有效性为 ready 且胜率、平均收益、回撤结构较好。",
            "成交额足够、换手适中，避免极低流动性和过度换手。",
        ],
        "avoid_setups": [
            "连续大涨后才出现利好解释，容易是兑现而不是新买点。",
            "高换手、高量比、散户占比上升但主力净流出。",
            "公告风险命中问询、减持、诉讼、审计非标或业绩大幅下滑。",
            "龙虎榜或资金异动只有单日脉冲，次日承接不足。",
            "历史相似样本少、止损命中率高、平均收益为负。",
        ],
        "entry_rules": [
            "优先支撑位附近、缩量回落后放量确认的低吸点。",
            "若涨幅已偏高，必须等待回踩或分时承接确认，不追秒板。",
            "买入计划必须给出建议时间、挂单价、止损价、失效条件。",
        ],
        "exit_rules": [
            "短线先保护本金，跌破结构支撑或风控一票否决则退出模拟观察。",
            "若达到目标但量价背离、主力转流出，优先减仓或结束模拟单。",
            "涨停/连板类机会必须额外检查开板次数、封单强度和次日承接。",
        ],
    },
    "data_sources_to_prefer": [
        {
            "name": "AkShare 龙虎榜接口",
            "usage": "后续用于营业部席位、机构席位、个股上榜统计和游资行为观察。",
            "interfaces": [
                "stock_lhb_detail_daily_sina",
                "stock_lhb_ggtj_sina",
                "stock_lhb_yytj_sina",
                "stock_lhb_jgzz_sina",
                "stock_lhb_jgmx_sina",
            ],
            "source_url": "https://akshare.akfamily.xyz/tutorial.html",
        },
        {
            "name": "东方财富涨停池",
            "usage": "后续用于涨停、连板、封板强度、炸板和短线情绪观察。",
            "interfaces": ["stock_zt_pool_em", "stock_zt_pool_previous_em", "stock_dt_pool_em"],
            "source_url": "https://blog.csdn.net/myqijin/article/details/144425164",
        },
    ],
    "factor_learning_policy": {
        "can_adjust": [
            "historical_rule",
            "support_pullback",
            "capital_flow",
            "retail_institution_flow",
            "news",
            "disclosure_risk",
            "volume_turnover",
            "sector_momentum",
        ],
        "adjustment_rules": [
            "只允许基于模拟盘日志和足够样本提出调参建议。",
            "每次单因子权重调整建议不超过 2 个百分点。",
            "新权重先作为 B 策略模拟验证，不直接替换主策略。",
            "如果样本少于 30 笔，最多只能给观察建议，不能升级为正式权重。",
            "亏损复盘要区分选股错误、买点错误、卖点错误、风控错误和数据缺失。",
        ],
        "hard_limits": {
            "max_single_factor_weight_pct": 25,
            "min_core_risk_weight_pct": 8,
            "max_position_without_manual_confirm_pct": 0,
            "live_trading_default": "disabled",
        },
    },
    "review_questions": [
        "这只票是低位支撑确认，还是高位追涨解释？",
        "主力与散户结构是否支持短线承接？",
        "公告/财报/监管风险有没有一票否决项？",
        "历史相似规则是否有足够样本，胜率和回撤是否匹配？",
        "如果买错，哪个条件触发退出？",
    ],
}


def _ensure_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _read_json(path: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_json(path: str, payload: dict) -> None:
    _ensure_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def ensure_strategy_memory() -> dict:
    current = _read_json(MEMORY_PATH)
    if current:
        merged = {**DEFAULT_MEMORY, **current}
        merged["short_term_playbook"] = {
            **DEFAULT_MEMORY["short_term_playbook"],
            **(current.get("short_term_playbook") or {}),
        }
        merged["factor_learning_policy"] = {
            **DEFAULT_MEMORY["factor_learning_policy"],
            **(current.get("factor_learning_policy") or {}),
        }
        return merged
    payload = {**DEFAULT_MEMORY, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    _write_json(MEMORY_PATH, payload)
    return payload


def get_strategy_memory() -> dict:
    return ensure_strategy_memory()


def get_model_memory_context(task_key: str = "") -> str:
    memory = ensure_strategy_memory()
    playbook = memory.get("short_term_playbook") or {}
    policy = memory.get("factor_learning_policy") or {}
    learning_notes = memory.get("learning_notes") or []
    lines = [
        f"站内可继承策略记忆版本：{memory.get('version')}",
        f"适用范围：{memory.get('scope')}",
        "核心原则：" + "；".join(memory.get("principles", [])[:5]),
        "偏好的短线形态：" + "；".join(playbook.get("preferred_setups", [])[:5]),
        "应避开的形态：" + "；".join(playbook.get("avoid_setups", [])[:5]),
        "入场规则：" + "；".join(playbook.get("entry_rules", [])[:3]),
        "退出规则：" + "；".join(playbook.get("exit_rules", [])[:3]),
        "因子学习纪律：" + "；".join(policy.get("adjustment_rules", [])[:5]),
        "复核问题：" + "；".join(memory.get("review_questions", [])[:5]),
        "注意：这是模型无关的站内记忆，不是底层模型微调；所有结论仅用于研究和模拟盘。",
    ]
    if learning_notes:
        note_lines = []
        for note in learning_notes[:3]:
            title = note.get("title") or note.get("type") or "未命名学习笔记"
            takeaways = note.get("takeaways") or note.get("principles") or note.get("factor_adjustments") or []
            if isinstance(takeaways, list):
                brief = "；".join(str(item) for item in takeaways[:4])
            else:
                brief = str(takeaways)
            if brief:
                note_lines.append(f"{title}：{brief}")
        if note_lines:
            lines.append("最近学习笔记：" + " || ".join(note_lines))
    if task_key in ("ai_quality_scoring", "trade_decision", "deep_analysis"):
        lines.append("执行本任务时必须显式考虑 historical_rule、主力/散户结构、公告财报风险和短线位置。")
    return "\n".join(lines)


def append_learning_note(note: dict) -> dict:
    memory = ensure_strategy_memory()
    notes = memory.setdefault("learning_notes", [])
    payload = {"created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), **(note or {})}
    notes.insert(0, payload)
    memory["learning_notes"] = notes[:200]
    memory["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write_json(MEMORY_PATH, memory)
    return payload
