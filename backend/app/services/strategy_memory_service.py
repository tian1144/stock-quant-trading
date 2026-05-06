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
TRADING_MODE_PATH = os.path.join(DATA_DIR, "ai_trading_mode.json")


DEFAULT_TRADING_MODE = {
    "version": "youzi-short-hunter-mode-v1",
    "updated_at": None,
    "mode_name": "AI短线猎人交易模式",
    "source_scope": [
        "结构化短线课程与交割单摘要",
        "PDF文字资料摘要",
        "图片交割单OCR摘要",
        "视频关键帧OCR摘要",
        "站内量化筛选与模拟盘复盘",
    ],
    "identity": (
        "先做研究员和模拟盘交易员，不做真实自动下单执行器。"
        "所有结论必须可解释、可复核、可止损。"
    ),
    "core_style": [
        "围绕情绪周期、主线板块、前排辨识度、盘口承接和仓位纪律做短线概率选择。",
        "优先低位支撑、回落确认、主线仍在、资金重新承接的机会，不追连续加速后的情绪高点。",
        "公告、龙虎榜、名人席位和单日异动只能作为线索，必须被板块联动、成交承接和风险检查共同确认。",
        "亏损或连续判断失败时先降级到观察或小仓模拟，不允许用补仓掩盖错误。",
    ],
    "decision_pipeline": [
        "先看市场赚钱效应：涨跌家数、涨停/跌停、炸板、连板高度、昨日涨停红盘率和主线持续性。",
        "再看板块：是否有共同上涨、前排带动、后排跟随、资金持续流入，而不是单股孤立冲动。",
        "再看个股位置：低位箱体、关键均线/支撑附近、回落不过度破位、近5日不过热。",
        "再看盘口和资金：成交额可执行、换手不过热、主力或大单边际改善，散户压力没有明显放大。",
        "再看风险：公告/财报/监管/减持/诉讼/退市风险一票否决或降级。",
        "最后给计划：买点类型、建议买入时间、挂单区间、止损价、失效条件、仓位级别和次日验证点。",
    ],
    "setup_taxonomy": {
        "low_suck": "主线未死、前排或强相关个股回到支撑/均线附近，恐慌释放后出现承接。",
        "halfway": "趋势和题材仍在，分歧后资金重新确认，但不能是高位缩量硬冲。",
        "limit_board": "只在情绪、题材、封单、换手、次日溢价条件同时较强时观察，默认不盲目打板。",
        "reseal": "开板分歧后重新封回，必须检查炸板质量、成交承接和板块同步。",
        "leader_follow": "龙头或前排确认后，选择位置更好、承接更稳的跟随标的。",
        "watch_only": "证据不足、位置不舒服、风控不清晰或市场退潮时只观察。",
    },
    "scoring_rules": [
        "AI质量分必须显式说明 youzi_experience：情绪阶段、主线确认、龙头/前排地位、盘口承接、公告是否被板块确认、仓位建议。",
        "历史相似规则样本不足时保持中性，不把偶然盈利当成规律。",
        "市场退潮、盘口过热、缺主线、公告无板块确认、仓位建议仅观察时必须降分或进入watch/reject。",
        "强游资因子只能提高复核优先级，不能绕过风控、公告风险和止损计划。",
    ],
    "position_discipline": [
        "默认真实下单关闭，只生成模拟盘和人工复核信号。",
        "60分以下只观察；60-70分小仓模拟观察；70-80分中低仓模拟；80分以上也必须逐步验证。",
        "连续亏损、情绪退潮或买点归因错误时，自动降级仓位建议，不扩大候选池。",
        "每笔交易必须记录：选择理由、买点类型、是否按计划、次日验证、退出理由和亏损归因。",
    ],
    "hard_avoid": [
        "连续大涨后才用利好解释买入。",
        "把所有强势股都叫龙头，或把所有下跌都解释成低吸。",
        "只因龙虎榜席位、游资名号、课程心法或历史战绩提高买入评级。",
        "公告/财报/监管风险命中时仍硬买。",
        "买错后补仓摊平、扩大仓位或修改原计划。",
    ],
    "learning_boundary": [
        "未人工校验的OCR交割单只能作为复盘线索，不能直接当成逐笔交易事实或权重训练样本。",
        "已经验证的模拟盘/交割单样本达到30笔以上，才允许提出小幅因子权重调整建议。",
        "每次单因子权重调整建议不超过2个百分点，先作为B策略模拟验证。",
    ],
}


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


def ensure_trading_mode() -> dict:
    current = _read_json(TRADING_MODE_PATH)
    if current:
        return {**DEFAULT_TRADING_MODE, **current}
    payload = {**DEFAULT_TRADING_MODE, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    _write_json(TRADING_MODE_PATH, payload)
    return payload


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


def get_trading_mode() -> dict:
    return ensure_trading_mode()


def _mode_lines(mode: dict, task_key: str = "") -> list[str]:
    taxonomy = mode.get("setup_taxonomy") or {}
    lines = [
        f"AI自有交易模式：{mode.get('mode_name')}（{mode.get('version')}）",
        f"身份边界：{mode.get('identity')}",
        "核心风格：" + "；".join(mode.get("core_style", [])[:5]),
        "决策流水线：" + " -> ".join(mode.get("decision_pipeline", [])[:7]),
        "买点分类：" + "；".join(f"{key}={value}" for key, value in list(taxonomy.items())[:6]),
        "评分纪律：" + "；".join(mode.get("scoring_rules", [])[:5]),
        "仓位纪律：" + "；".join(mode.get("position_discipline", [])[:5]),
        "硬回避：" + "；".join(mode.get("hard_avoid", [])[:5]),
        "学习边界：" + "；".join(mode.get("learning_boundary", [])[:4]),
    ]
    if task_key in ("ai_quality_scoring", "trade_decision", "deep_analysis", "risk_review"):
        lines.append(
            "执行本任务时必须把候选归类为 low_suck/halfway/limit_board/reseal/"
            "leader_follow/watch_only，并说明情绪、主线、前排地位、盘口、风险和仓位。"
        )
    return lines


def _legacy_model_memory_context(task_key: str = "") -> str:
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


def get_model_memory_context(task_key: str = "") -> str:
    memory = ensure_strategy_memory()
    mode = ensure_trading_mode()
    playbook = memory.get("short_term_playbook") or {}
    policy = memory.get("factor_learning_policy") or {}
    learning_notes = memory.get("learning_notes") or []
    lines = _mode_lines(mode, task_key)
    lines.extend([
        "",
        f"站内可继承策略记忆版本：{memory.get('version')}",
        f"适用范围：{memory.get('scope')}",
    ])
    if memory.get("principles"):
        lines.append("旧策略核心原则：" + "；".join(str(x) for x in memory.get("principles", [])[:5]))
    if playbook.get("preferred_setups"):
        lines.append("旧偏好形态：" + "；".join(str(x) for x in playbook.get("preferred_setups", [])[:5]))
    if playbook.get("avoid_setups"):
        lines.append("旧回避形态：" + "；".join(str(x) for x in playbook.get("avoid_setups", [])[:5]))
    if policy.get("adjustment_rules"):
        lines.append("因子学习纪律：" + "；".join(str(x) for x in policy.get("adjustment_rules", [])[:5]))
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
    lines.append("注意：这是模型无关的站内记忆，不是底层模型微调；所有结论只用于研究、模拟盘和人工复核。")
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
