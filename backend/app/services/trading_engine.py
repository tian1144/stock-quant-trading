"""
调度编排引擎 - 量化系统总控
管理定时任务、自动交易、系统状态
"""
import asyncio
import os
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from app.services import (
    state_store, data_fetcher, stock_screener,
    signal_detector, portfolio_manager, news_service, risk_manager
)

# 全局调度器
_scheduler: AsyncIOScheduler = None
_auto_trade_enabled: bool = False


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


DISABLE_BACKGROUND_LOOPS = _env_flag("LIANGHUA_DISABLE_BACKGROUND_LOOPS")
DISABLE_STARTUP_DATA_INIT = _env_flag("LIANGHUA_DISABLE_STARTUP_DATA_INIT", DISABLE_BACKGROUND_LOOPS)
DISABLE_SCHEDULER = _env_flag("LIANGHUA_DISABLE_SCHEDULER", DISABLE_BACKGROUND_LOOPS)


async def startup_quant_system():
    """量化系统启动"""
    logger.info("=" * 50)
    logger.info("量化智能选股与模拟交易系统启动中...")
    logger.info("=" * 50)

    state_store.update_system_state({
        "startup_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    # 尝试从文件恢复组合状态
    if state_store.load_portfolio_from_file():
        logger.info("已从文件恢复组合状态")
    else:
        logger.info("使用默认组合状态（20万资金）")

    # 初始化数据（后台执行）
    if DISABLE_STARTUP_DATA_INIT:
        logger.warning("启动数据初始化已通过环境变量关闭")
    else:
        asyncio.create_task(_init_data())

    logger.info("量化系统启动完成")


async def _init_data():
    """后台初始化数据"""
    try:
        logger.info("[初始化] 获取股票列表...")
        await asyncio.to_thread(data_fetcher.fetch_all_stocks_sina)

        logger.info("[初始化] 获取新闻...")
        await asyncio.to_thread(news_service.refresh_news)

        if DISABLE_SCHEDULER:
            logger.warning("定时任务调度器已通过环境变量关闭")
        else:
            _setup_scheduler()

        logger.info("[初始化] 轻量初始化完成！")
        logger.info(f"[初始化] 股票: {len(state_store.get_stock_universe())}只")

    except Exception as e:
        logger.error(f"数据初始化失败: {e}")


def _setup_scheduler():
    """设置定时任务"""
    global _scheduler
    try:
        _scheduler = AsyncIOScheduler()

        # 每5秒：实时信号检测（交易时段）
        _scheduler.add_job(
            _scheduled_signal_detection,
            'interval', seconds=5,
            id='signal_detection',
            replace_existing=True
        )

        # 每30分钟：选股更新（交易时段）
        _scheduler.add_job(
            _scheduled_screening,
            'interval', minutes=30,
            id='screening',
            replace_existing=True
        )

        # 每15分钟：新闻刷新
        _scheduler.add_job(
            _scheduled_news_refresh,
            'interval', minutes=15,
            id='news_refresh',
            replace_existing=True
        )

        # 每10分钟：候选股资金流向更新
        _scheduler.add_job(
            _scheduled_money_flow_refresh,
            'interval', minutes=10,
            id='money_flow',
            replace_existing=True
        )

        # 每60秒：保存组合状态到文件
        _scheduler.add_job(
            _scheduled_save_state,
            'interval', seconds=60,
            id='save_state',
            replace_existing=True
        )

        _scheduler.start()
        logger.info("定时任务调度器已启动")
    except Exception as e:
        logger.error(f"调度器启动失败: {e}")


async def _scheduled_signal_detection():
    """定时信号检测"""
    if not data_fetcher.is_trading_hours():
        return

    try:
        # 获取候选股和持仓股的实时行情
        screening = state_store.get_screening_results()
        positions = state_store.get_positions()

        codes_to_refresh = set()
        for s in screening[:50]:
            codes_to_refresh.add(s["code"])
        for code in positions:
            codes_to_refresh.add(code)

        if codes_to_refresh:
            data_fetcher.fetch_realtime_batch(list(codes_to_refresh))

        # 更新持仓实时数据
        portfolio_manager.update_positions_realtime()

        # 检测信号
        signals = signal_detector.detect_all_signals()

        # 自动执行交易
        if _auto_trade_enabled and signals["total"] > 0:
            await _auto_execute_signals(signals)

    except Exception as e:
        logger.error(f"信号检测任务失败: {e}")


async def _auto_execute_signals(signals: dict):
    """自动执行信号"""
    from app.execution.kill_switch import check_can_trade

    can_trade, reason = check_can_trade()
    if not can_trade:
        logger.warning(f"[自动交易暂停] {reason}")
        return

    # 先执行卖出信号
    for signal in signals.get("sell_signals", []):
        code = signal["code"]
        price = signal["price"]
        quantity = signal.get("quantity", 0)
        if quantity > 0:
            result = portfolio_manager.execute_sell(code, price, quantity, reason=signal["reason"])
            if result["success"]:
                logger.info(f"[自动卖出] {code} {quantity}股 @ {price}")

    # 再执行买入信号
    for signal in signals.get("buy_signals", []):
        code = signal["code"]
        price = signal["price"]
        quantity = risk_manager.calculate_position_size(price, signal["strength"])
        if quantity > 0:
            result = portfolio_manager.execute_buy(code, price, quantity, reason=signal["reason"])
            if result["success"]:
                logger.info(f"[自动买入] {code} {quantity}股 @ {price}")


async def _scheduled_screening():
    """定时选股"""
    if not data_fetcher.is_trading_hours():
        return
    try:
        logger.info("[定时任务] 开始选股更新...")
        stock_screener.run_screening()
        state_store.update_system_state({
            "last_screening_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    except Exception as e:
        logger.error(f"选股任务失败: {e}")


async def _scheduled_news_refresh():
    """定时新闻刷新"""
    try:
        news_service.refresh_news()
        state_store.update_system_state({
            "last_news_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    except Exception as e:
        logger.error(f"新闻刷新失败: {e}")


async def _scheduled_money_flow_refresh():
    """定时资金流向刷新"""
    if not data_fetcher.is_trading_hours():
        return
    try:
        screening = state_store.get_screening_results()
        for stock in screening[:30]:
            data_fetcher.fetch_money_flow(stock["code"])
    except Exception as e:
        logger.error(f"资金流向刷新失败: {e}")


async def _scheduled_save_state():
    """定时保存状态"""
    try:
        state_store.save_portfolio_to_file()
    except Exception as e:
        logger.error(f"状态保存失败: {e}")


def enable_auto_trade(enabled: bool):
    """开启/关闭自动交易"""
    global _auto_trade_enabled
    _auto_trade_enabled = enabled
    state_store.update_system_state({"auto_trade_enabled": enabled})
    logger.info(f"自动交易: {'已开启' if enabled else '已关闭'}")


def is_auto_trade_enabled() -> bool:
    return _auto_trade_enabled


def get_system_status() -> dict:
    """获取系统状态"""
    sys_state = state_store.get_system_state()
    universe = state_store.get_stock_universe()
    daily_bars = state_store.get_daily_bars_codes()
    screening = state_store.get_screening_results()
    signals = state_store.get_signals()

    return {
        "system_name": "股票量化智能选股与模拟交易系统",
        "version": "1.0.0",
        "startup_time": sys_state.get("startup_time"),
        "is_trading_hours": data_fetcher.is_trading_hours(),
        "is_trading_day": data_fetcher.is_trading_day(),
        "auto_trade_enabled": _auto_trade_enabled,
        "data_status": {
            "stock_count": len(universe),
            "daily_bars_count": len(daily_bars),
            "screening_count": len(screening),
            "active_signals": len(signals),
        },
        "last_update": {
            "screening": sys_state.get("last_screening_time"),
            "signal": sys_state.get("last_signal_time"),
            "news": sys_state.get("last_news_time"),
        },
        "portfolio": portfolio_manager.get_portfolio_summary(),
        "risk": risk_manager.get_risk_status(),
    }


def manual_screening() -> list:
    """手动触发选股"""
    logger.info("[手动] 触发选股...")
    results = stock_screener.run_screening()
    state_store.update_system_state({
        "last_screening_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    return results


def manual_signal_detection() -> dict:
    """手动触发信号检测"""
    logger.info("[手动] 触发信号检测...")
    return signal_detector.detect_all_signals()
