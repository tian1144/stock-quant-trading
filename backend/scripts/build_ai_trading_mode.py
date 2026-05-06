"""
Build the clean Chinese AI trading mode used by every model call.

The raw OCR/PDF learning notes remain as evidence, but this file writes a
stable, readable mode layer so model prompts do not depend on noisy OCR text.
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


def main() -> None:
    mode = {
        **strategy_memory_service.DEFAULT_TRADING_MODE,
        "updated_at": "2026-05-05 00:00:00",
        "evidence_summary": {
            "structured_documents": "已解析结构化短线课程和交割单文档，核心主题集中在情绪周期、主线板块、买卖点、仓位风控、公告信息、看盘盘口、龙虎榜复盘。",
            "pdf_text": "已抽取PDF文字资料，强化赚钱效应、龙头/前排确认、低吸边界、打板/半路确定性和仓位回撤控制。",
            "image_ocr": "图片交割单OCR可作为复盘线索；未人工校验前，不直接作为逐笔交易事实或权重训练样本。",
            "video_ocr": "视频关键帧强化盘中异动、热点龙头、共振低吸、系统化止损和仓位纪律。",
            "verified_trade_reviews": "当前人工确认交割单样本仍为空，正式权重训练需等校验样本积累。",
        },
        "tomorrow_start_rules": [
            "明天启动时先跑全市场量化筛选，再让AI分批质量打分，不直接把全市场原文塞进模型。",
            "AI只从候选池和复核池里选，不编造外部行情、公告、财务或席位事实。",
            "推荐结果默认写入模拟盘信号；真实下单默认禁用，需要人工确认。",
            "若AI超时或网关异常，不用本地规则伪装成AI推荐，应明确失败原因。",
        ],
    }
    strategy_memory_service._write_json(strategy_memory_service.TRADING_MODE_PATH, mode)
    context = strategy_memory_service.get_model_memory_context("trade_decision")
    print(json.dumps({
        "path": strategy_memory_service.TRADING_MODE_PATH,
        "version": mode["version"],
        "mode_name": mode["mode_name"],
        "context_preview": context[:800],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
