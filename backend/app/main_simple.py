from fastapi import FastAPI, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
import logging
import os
import time
import re
import json
import math
import socket
import requests
import threading
import asyncio
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

_ai_pick_jobs: dict = {}
_ai_pick_jobs_lock = threading.Lock()
_screening_jobs: dict = {}
_screening_jobs_lock = threading.Lock()

# 量化服务模块
from app.services import (
    trading_engine, stock_screener, signal_detector,
    portfolio_manager, risk_manager, state_store,
    news_service, data_fetcher, sector_service, agent_workspace,
    technical_analysis, ai_model_service, ai_stock_picker, market_data_hub,
    disclosure_service, strategy_memory_service, trade_review_service
)
from app.backtest.engine import BacktestEngine, create_context_ma_crossover_strategy
from app.backtest.context import build_context_provider
from app.analysis.decision_schema import generate_score_card, generate_decision
from app.analysis.risk_review import risk_review, full_risk_pipeline
from app.analysis.event_scoring import score_event, score_news_batch, get_event_score_for_symbol
from app.analysis.sentiment_scoring import calc_sentiment_score
from app.analysis.kline_scoring import calc_kline_score
from app.analysis.fund_flow_scoring import calc_fund_flow_score
from app.analysis.multi_model_verify import multi_model_verify
from app.reports.daily_report import (
    generate_daily_report,
    generate_backtest_report,
    generate_paper_trade_log,
    generate_weekly_report,
    get_paper_trade_log_path,
)
from app.execution.kill_switch import activate_kill_switch, deactivate_kill_switch, get_kill_switch_status, is_kill_switch_active

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SERVER_BOOT_ID = f"{os.getpid()}-{int(time.time())}"

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0'


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化量化系统"""
    logger.info("FastAPI 应用启动，正在初始化量化系统...")
    await trading_engine.startup_quant_system()
    agent_workspace.bootstrap_logs()
    market_data_hub.start_hub()
    threading.Thread(target=_realtime_refresh_loop, daemon=True).start()
    threading.Thread(target=_post_close_validation_loop, daemon=True).start()
    threading.Thread(target=_stock_universe_monitor_loop, daemon=True).start()
    threading.Thread(target=_market_data_hub_loop, daemon=True).start()
    yield
    logger.info("FastAPI 应用关闭")


app = FastAPI(
    title="股票量化智能选股与实时模拟盘",
    version="1.0.0",
    description="股票量化智能选股与实时模拟盘小程序后端 API",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_stock_cache = {"stocks": [], "updated_at": 0}
_stock_detail_cache = {}
CACHE_TTL = 300
_market_cache_job = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "total": 0,
    "done": 0,
    "success": 0,
    "failed": 0,
    "current": None,
    "message": "尚未启动",
    "params": {},
    "errors": [],
}
_disclosure_backfill_job = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "total": 0,
    "done": 0,
    "success": 0,
    "failed": 0,
    "risk_hits": 0,
    "current": None,
    "message": "尚未启动",
    "params": {},
    "errors": [],
}
_realtime_watch_codes = set()
_realtime_refresh_job = {
    "running": False,
    "interval_seconds": 1,
    "last_run_at": None,
    "last_count": 0,
    "message": "尚未启动",
}
_post_close_job = {
    "enabled": True,
    "last_run_date": None,
    "run_at": "15:05",
    "message": "等待闭市校验",
}
_stock_universe_job = {
    "running": False,
    "last_run_at": None,
    "last_total": 0,
    "interval_seconds": 60,
    "message": "等待股票主数据刷新",
}
_market_data_hub_job = {
    "running": False,
    "last_run_at": None,
    "last_intraday_run_at": None,
    "last_universe_open_date": None,
    "last_universe_close_date": None,
    "message": "行情数据引入中枢等待调度",
}

DEMO_STOCKS = [
    {"code": "600519", "name": "贵州茅台", "exchange": "sh", "market": "主板", "industry": "白酒", "is_st": False, "price": 1688.00, "pct_change": 1.26, "volume": 32600, "amount": 5500000000.0},
    {"code": "300750", "name": "宁德时代", "exchange": "sz", "market": "创业板", "industry": "新能源", "is_st": False, "price": 212.35, "pct_change": -0.84, "volume": 185000, "amount": 3920000000.0},
    {"code": "601318", "name": "中国平安", "exchange": "sh", "market": "主板", "industry": "保险", "is_st": False, "price": 48.72, "pct_change": 0.38, "volume": 420000, "amount": 2040000000.0},
    {"code": "000858", "name": "五粮液", "exchange": "sz", "market": "主板", "industry": "白酒", "is_st": False, "price": 143.18, "pct_change": 0.92, "volume": 156000, "amount": 2230000000.0},
    {"code": "600036", "name": "招商银行", "exchange": "sh", "market": "主板", "industry": "银行", "is_st": False, "price": 36.28, "pct_change": 0.67, "volume": 510000, "amount": 1850000000.0},
    {"code": "002594", "name": "比亚迪", "exchange": "sz", "market": "中小板", "industry": "汽车", "is_st": False, "price": 226.40, "pct_change": -1.12, "volume": 198000, "amount": 4480000000.0},
    {"code": "688981", "name": "中芯国际", "exchange": "sh", "market": "科创板", "industry": "半导体", "is_st": False, "price": 55.66, "pct_change": 2.18, "volume": 690000, "amount": 3840000000.0},
    {"code": "601899", "name": "紫金矿业", "exchange": "sh", "market": "主板", "industry": "有色金属", "is_st": False, "price": 18.92, "pct_change": 1.74, "volume": 980000, "amount": 1850000000.0},
]

def _ensure_stock_universe(stocks: list):
    if stocks:
        state_store.update_stock_universe(stocks)
        agent_workspace.record_event("data", "stock_universe", f"股票池已更新：{len(stocks)} 只。")

def _demo_stock(code: str):
    return next((s for s in DEMO_STOCKS if s["code"] == code), None)

def _classify_stock(symbol: str):
    code = symbol.replace("sh", "").replace("sz", "").replace("bj", "")
    if code.startswith('6'):
        exchange = 'sh'
    elif code.startswith('0') or code.startswith('3'):
        exchange = 'sz'
    else:
        exchange = 'bj'

    if code.startswith('60'):
        market = '主板'
    elif code.startswith('000') or code.startswith('001'):
        market = '主板'
    elif code.startswith('002') or code.startswith('003'):
        market = '中小板'
    elif code.startswith('300') or code.startswith('301'):
        market = '创业板'
    elif code.startswith('688') or code.startswith('689'):
        market = '科创板'
    else:
        market = '北交所'

    return exchange, market, code


def _classify_stock_code(code: str):
    code = str(code or "").strip()
    if code.startswith(("4", "8", "920")):
        exchange = "bj"
    elif code.startswith(("6", "9")):
        exchange = "sh"
    elif code.startswith(("0", "2", "3")):
        exchange = "sz"
    else:
        exchange = ""

    if code.startswith(("688", "689")):
        market = "科创板"
    elif code.startswith(("300", "301")):
        market = "创业板"
    elif exchange == "bj":
        market = "北交所"
    elif exchange == "sh":
        market = "沪市"
    elif exchange == "sz":
        market = "深市"
    else:
        market = ""
    return exchange, market


def _normalize_stock_universe(stocks: list) -> list:
    normalized = []
    seen = set()
    for item in stocks or []:
        code = str(item.get("code", "")).strip()
        if not code or code in seen:
            continue
        seen.add(code)
        exchange, market = _classify_stock_code(code)
        normalized.append({
            **item,
            "code": code,
            "exchange": exchange or item.get("exchange") or "",
            "market": market or item.get("market") or "",
        })
    return normalized


def _active_stock_universe(stocks: list) -> list:
    return data_fetcher.apply_active_stock_scope(stocks or [])


def _stock_universe_incomplete(stocks: list) -> bool:
    codes = [str(s.get("code", "")) for s in stocks or []]
    if len(codes) < 3000:
        return True
    active_limit = data_fetcher.active_stock_universe_limit()
    if active_limit and len(codes) >= active_limit:
        return False
    has_sh = any(c.startswith("6") for c in codes)
    has_sz = any(c.startswith(("0", "2", "3")) for c in codes)
    has_bj = any(c.startswith(("4", "8", "920")) for c in codes)
    return not (has_sh and has_sz and has_bj)


def _load_stock_universe_fast(force_refresh: bool = False) -> list:
    stocks = _normalize_stock_universe(_stock_cache.get("stocks") or [])
    if not stocks or force_refresh:
        stocks = _normalize_stock_universe(data_fetcher.read_stock_universe_cache())
    if force_refresh or _stock_universe_incomplete(stocks):
        fresh = _normalize_stock_universe(data_fetcher.fetch_all_stocks_eastmoney())
        if not fresh or _stock_universe_incomplete(fresh):
            fresh = _normalize_stock_universe(data_fetcher.fetch_all_stocks_sina())
        if fresh and len(fresh) >= len(stocks):
            stocks = fresh
    if not stocks:
        stocks = _normalize_stock_universe(DEMO_STOCKS)
    stocks = _active_stock_universe(stocks)
    _stock_cache["stocks"] = stocks
    _stock_cache["updated_at"] = time.time()
    _ensure_stock_universe(stocks)
    return stocks


def _update_screening_job(job_id: str, **updates):
    with _screening_jobs_lock:
        job = _screening_jobs.get(job_id) or {}
        job.update(updates)
        job["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _screening_jobs[job_id] = job
        return job.copy()


def _run_screening_job(job_id: str, params: dict):
    started = time.time()
    strategy = params.get("strategy")
    _update_screening_job(
        job_id,
        status="running",
        stage="prepare",
        message="正在准备股票池",
        started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        finished_at=None,
        params=params,
        result=None,
        error=None,
    )
    try:
        if strategy in ("short", "long", "event_driven"):
            state_store.update_user_settings({"trading_style": strategy})
        if not state_store.get_stock_universe():
            stocks = _load_stock_universe_fast()
            _ensure_stock_universe(stocks)
        total = len(state_store.get_stock_universe())
        _update_screening_job(
            job_id,
            stage="screening",
            message=f"正在运行智能选股：全市场{total}只，策略={strategy or state_store.get_user_settings().get('trading_style', 'short')}",
            total=total,
        )
        def progress_callback(progress: dict):
            _update_screening_job(job_id, **(progress or {}))

        results = stock_screener.run_screening(
            strategy=strategy if strategy in ("short", "long", "event_driven") else None,
            progress_callback=progress_callback,
        )
        state_store.update_system_state({
            "last_screening_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        agent_workspace.record_event("score", "screening", f"后台选股完成：{len(results)} 个候选。")
        result = {
            "message": "选股完成",
            "count": len(results),
            "results": _json_safe(results),
            "logic": stock_screener.get_screening_logic_summary(),
            "elapsed_seconds": round(time.time() - started, 1),
        }
        _update_screening_job(
            job_id,
            status="done",
            stage="done",
            message=f"选股完成：{len(results)}只候选",
            done=len(results),
            result=result,
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
    except Exception as exc:
        logger.exception("screening job failed")
        _update_screening_job(
            job_id,
            status="failed",
            stage="failed",
            message=f"选股失败：{exc}",
            error=str(exc),
            finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )


def _run_disclosure_backfill(params: dict):
    stocks = _load_stock_universe_fast(force_refresh=bool(params.get("force_universe_refresh")))
    limit = int(params.get("limit") or 0)
    offset = int(params.get("offset") or 0)
    days = int(params.get("days") or 180)
    sleep_seconds = float(params.get("sleep_seconds") or 0.35)
    force_refresh = bool(params.get("force_refresh"))
    selected = stocks[offset:]
    if limit > 0:
        selected = selected[:limit]
    _disclosure_backfill_job.update({
        "running": True,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": None,
        "total": len(selected),
        "done": 0,
        "success": 0,
        "failed": 0,
        "risk_hits": 0,
        "current": None,
        "message": "正式公告/财报风险缓存回填中",
        "params": params,
        "errors": [],
    })
    try:
        for stock in selected:
            code = str(stock.get("code", "")).strip()
            if not code:
                continue
            _disclosure_backfill_job["current"] = code
            try:
                profile = disclosure_service.get_disclosure_risk_profile(
                    code,
                    days=days,
                    force_refresh=force_refresh,
                )
                _disclosure_backfill_job["success"] += 1
                if profile.get("risk_flags"):
                    _disclosure_backfill_job["risk_hits"] += 1
            except Exception as exc:
                _disclosure_backfill_job["failed"] += 1
                errors = _disclosure_backfill_job.setdefault("errors", [])
                if len(errors) < 20:
                    errors.append({"code": code, "error": str(exc)})
            finally:
                _disclosure_backfill_job["done"] += 1
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)
        _disclosure_backfill_job["message"] = "正式公告/财报风险缓存回填完成"
    except Exception as exc:
        _disclosure_backfill_job["message"] = f"正式公告/财报风险缓存回填异常：{exc}"
    finally:
        _disclosure_backfill_job["running"] = False
        _disclosure_backfill_job["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _disclosure_backfill_job["current"] = None

def _fetch_all_stocks_sina():
    """通过新浪API分页获取全部A股数据"""
    url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    headers = {'Referer': 'https://finance.sina.com.cn/', 'User-Agent': UA}
    all_stocks = []
    page = 1

    while True:
        params = {
            'page': page,
            'num': 80,
            'sort': 'symbol',
            'asc': 1,
            'node': 'hs_a',
            'symbol': '',
            '_s_r_a': 'init'
        }
        try:
            response = requests.get(url, params=params, headers=headers, timeout=4)
            data = json.loads(response.text)
            if not data:
                break

            for item in data:
                symbol = item.get("symbol", "")
                exchange, market, code = _classify_stock(symbol)
                name = item.get("name", "")
                all_stocks.append({
                    "code": code,
                    "name": name,
                    "exchange": exchange,
                    "market": market,
                    "industry": "",
                    "is_st": 'ST' in name.upper(),
                    "price": float(item.get("trade", 0)),
                    "pct_change": float(item.get("changepercent", 0)),
                    "volume": int(float(item.get("volume", 0))),
                    "amount": float(item.get("amount", 0)),
                })

            if len(data) < 80:
                break

            page += 1
            if page > 80:
                break
        except Exception as e:
            logger.error(f"新浪API第{page}页请求失败: {e}")
            break

    return all_stocks

def _fetch_ths_quote(code: str):
    """通过同花顺API获取单只股票实时行情"""
    try:
        r = requests.get(
            f'http://d.10jqka.com.cn/v6/line/hs_{code}/01/today.js',
            headers={'User-Agent': UA, 'Referer': 'http://stockpage.10jqka.com.cn/'},
            timeout=5
        )
        if r.status_code == 200:
            match = re.search(r'\((.*)\)', r.text, re.S)
            if match:
                data = json.loads(match.group(1))
                key = list(data.keys())[0]
                info = data[key]
                return {
                    "name": info.get("name", ""),
                    "open": float(info.get("7", 0)),
                    "price": float(info.get("11", 0)),
                    "volume": int(info.get("13", 0)),
                    "amount": float(info.get("19", 0)),
                }
    except Exception as e:
        logger.debug(f"同花顺行情获取失败 {code}: {e}")
    return None


def _load_stock_universe_for_cache() -> list:
    return _load_stock_universe_fast()


def _run_market_cache_warmup(params: dict):
    global _market_cache_job
    try:
        stocks = _load_stock_universe_for_cache()
        offset = max(int(params.get("offset", 0)), 0)
        limit = int(params.get("limit", 0))
        selected = stocks[offset: offset + limit] if limit > 0 else stocks[offset:]
        periods = [int(p) for p in params.get("periods", [101]) if str(p).strip()]
        days = int(params.get("days", 1000))
        include_realtime = bool(params.get("include_realtime", True))
        include_intraday = bool(params.get("include_intraday", True))
        include_money_flow = bool(params.get("include_money_flow", True))
        include_chips = bool(params.get("include_chips", True))

        _market_cache_job.update({
            "running": True,
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": None,
            "total": len(selected),
            "done": 0,
            "success": 0,
            "failed": 0,
            "current": None,
            "stage": "prepare",
            "stage_label": "准备股票池",
            "current_batch": "",
            "realtime_batches_total": 0,
            "realtime_batches_done": 0,
            "realtime_codes_done": 0,
            "kline_periods_total": len(periods),
            "kline_periods_done": 0,
            "money_flow_done": 0,
            "chips_done": 0,
            "message": "正在预热市场缓存",
            "params": params,
            "errors": [],
        })

        codes = [s.get("code") for s in selected if s.get("code")]
        if include_realtime:
            batches = list(range(0, len(codes), 50))
            _market_cache_job.update({
                "stage": "realtime",
                "stage_label": "全市场实时快照三源校验",
                "realtime_batches_total": len(batches),
                "message": "正在批量拉取全市场实时快照",
            })
            for batch_index, i in enumerate(batches, start=1):
                batch = codes[i:i + 50]
                _market_cache_job["current_batch"] = f"{batch[0]}-{batch[-1]}" if batch else ""
                _market_cache_job["current"] = batch[0] if batch else None
                data_fetcher.fetch_realtime_batch(batch)
                _market_cache_job["realtime_batches_done"] = batch_index
                _market_cache_job["realtime_codes_done"] = min(i + len(batch), len(codes))
                _market_cache_job["message"] = (
                    f"实时快照校验进度：{_market_cache_job['realtime_codes_done']}/{len(codes)}"
                )

        _market_cache_job.update({
            "stage": "history",
            "stage_label": "历史K线/资金流/筹码补库",
            "current_batch": "",
            "message": "正在补齐历史K线、资金流和筹码缓存",
        })
        for stock in selected:
            code = stock.get("code")
            if not code:
                continue
            _market_cache_job["current"] = code
            ok = False
            try:
                period_done = 0
                for period in periods:
                    _market_cache_job["current_period"] = period
                    df = data_fetcher.fetch_kline(code, period=period, days=days, allow_fallback=False, prefer_cache=False, force_refresh=True)
                    ok = ok or (df is not None and not df.empty)
                    period_done += 1
                    _market_cache_job["kline_periods_done"] += 1
                if include_money_flow:
                    data_fetcher.fetch_money_flow(code)
                    _market_cache_job["money_flow_done"] += 1
                if include_intraday:
                    data_fetcher.fetch_intraday_minutes(code, allow_fallback=False)
                if include_chips:
                    data_fetcher.fetch_chip_distribution(code)
                    _market_cache_job["chips_done"] += 1
                _market_cache_job["success"] += 1 if ok else 0
                _market_cache_job["failed"] += 0 if ok else 1
            except Exception as e:
                _market_cache_job["failed"] += 1
                if len(_market_cache_job["errors"]) < 20:
                    _market_cache_job["errors"].append({"code": code, "error": str(e)})
            finally:
                _market_cache_job["done"] += 1
                if _market_cache_job["done"] % 50 == 0:
                    agent_workspace.record_event("data", "market_cache", f"市场缓存预热进度：{_market_cache_job['done']}/{_market_cache_job['total']}。")

        _market_cache_job["message"] = "市场缓存预热完成"
    except Exception as e:
        _market_cache_job["message"] = f"市场缓存预热失败：{e}"
        if len(_market_cache_job["errors"]) < 20:
            _market_cache_job["errors"].append({"error": str(e)})
    finally:
        _market_cache_job["running"] = False
        _market_cache_job["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _market_cache_job["current"] = None
        _market_cache_job["stage"] = "finished"
        _market_cache_job["stage_label"] = "已完成"
        agent_workspace.record_event("data", "market_cache", _market_cache_job["message"], payload=_market_cache_job.copy())


def _enrich_news_for_market(news: list) -> list:
    """给新闻补充板块标签和利好/利空方向，供新闻页直接使用。"""
    sectors = state_store.get_sector_list()
    enriched = []
    for item in news or []:
        tags = sector_service.classify_news_for_sectors(item, sectors)
        enriched.append({**item, **tags})
    return enriched


def _track_realtime_code(code: str):
    if code:
        _realtime_watch_codes.add(str(code))


def _realtime_refresh_loop():
    _realtime_refresh_job.update({"running": True, "message": "实时行情 1 秒三源校验刷新中"})
    while True:
        try:
            codes = sorted(_realtime_watch_codes)
            if codes:
                for i in range(0, len(codes), 50):
                    data_fetcher.fetch_verified_realtime_batch(codes[i:i + 50], require_verified_for_cache=True)
                _realtime_refresh_job["last_run_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                _realtime_refresh_job["last_count"] = len(codes)
        except Exception as e:
            _realtime_refresh_job["message"] = f"实时行情刷新异常：{e}"
        time.sleep(max(float(_realtime_refresh_job.get("interval_seconds", 2)), 1.0))


def _post_close_validation_loop():
    while True:
        try:
            now = datetime.now()
            if _post_close_job.get("enabled") and now.weekday() < 5:
                run_hour, run_minute = [int(x) for x in _post_close_job.get("run_at", "15:05").split(":")]
                today = now.strftime("%Y-%m-%d")
                if (
                    now.hour > run_hour or (now.hour == run_hour and now.minute >= run_minute)
                ) and _post_close_job.get("last_run_date") != today and not _market_cache_job.get("running"):
                    _post_close_job["last_run_date"] = today
                    _post_close_job["message"] = "闭市后全市场校验缓存已启动"
                    params = {
                        "limit": 0,
                        "offset": 0,
                        "days": 1000,
                        "periods": [101, 102],
                        "include_realtime": True,
                        "include_intraday": True,
                        "include_money_flow": True,
                        "include_chips": True,
                        "reason": "post_close_validation",
                    }
                    threading.Thread(target=_run_market_cache_warmup, args=(params,), daemon=True).start()
                    agent_workspace.record_event("data", "post_close_validation", "闭市后全市场校验缓存任务已启动。")
        except Exception as e:
            _post_close_job["message"] = f"闭市后校验调度异常：{e}"
        time.sleep(60)


def _stock_universe_monitor_loop():
    """定时刷新股票主数据：新股、退市/消失、更名、ST、停复牌。"""
    while True:
        try:
            now = datetime.now()
            is_trading_window = now.weekday() < 5 and (
                (9 <= now.hour < 12) or (13 <= now.hour < 16)
            )
            interval = 60 if is_trading_window else 600
            _stock_universe_job["interval_seconds"] = interval
            _stock_universe_job["running"] = True
            stocks = _load_stock_universe_fast(force_refresh=True)
            changes = data_fetcher.read_stock_universe_changes()
            _stock_universe_job.update({
                "last_run_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "last_total": len(stocks),
                "message": "股票主数据已刷新",
                "last_change_summary": changes.get("summary", {}),
            })
            summary = changes.get("summary", {})
            if any(summary.get(k, 0) for k in ("new_listed", "removed_or_delisted", "name_changed", "st_changed", "suspension_changed")):
                agent_workspace.record_event("data", "stock_universe_change", "股票主数据发生变化。", payload=changes)
        except Exception as e:
            _stock_universe_job["message"] = f"股票主数据刷新异常：{e}"
        finally:
            _stock_universe_job["running"] = False
        time.sleep(max(int(_stock_universe_job.get("interval_seconds", 60)), 30))


def _is_trading_day_now(now: datetime) -> bool:
    return now.weekday() < 5


def _is_realtime_window(now: datetime) -> bool:
    if not _is_trading_day_now(now):
        return False
    current = now.hour * 60 + now.minute
    return 9 * 60 + 25 <= current <= 15 * 60


def _is_preopen_window(now: datetime) -> bool:
    if not _is_trading_day_now(now):
        return False
    current = now.hour * 60 + now.minute
    return 8 * 60 + 45 <= current <= 9 * 60 + 20


def _is_postclose_window(now: datetime) -> bool:
    if not _is_trading_day_now(now):
        return False
    current = now.hour * 60 + now.minute
    return 15 * 60 + 3 <= current <= 16 * 60


def _market_data_hub_loop():
    """统一调度行情数据引入：主数据、实时快照、重点分时和覆盖率队列。"""
    market_data_hub.start_hub()
    while True:
        now = datetime.now()
        try:
            _market_data_hub_job["running"] = True
            stocks = _load_stock_universe_fast()
            queues = market_data_hub.build_priority_queues(
                watchlist_codes=[],
                volatile_codes=[s.get("code") for s in (state_store.get_screening_results() or [])[:120]],
                stocks=stocks,
            )
            today = now.strftime("%Y-%m-%d")
            if _is_preopen_window(now) and _market_data_hub_job.get("last_universe_open_date") != today:
                market_data_hub.sync_universe(lambda: _load_stock_universe_fast(force_refresh=True))
                _market_data_hub_job["last_universe_open_date"] = today
            if _is_postclose_window(now) and _market_data_hub_job.get("last_universe_close_date") != today:
                market_data_hub.sync_universe(lambda: _load_stock_universe_fast(force_refresh=True))
                _market_data_hub_job["last_universe_close_date"] = today
            if _is_realtime_window(now):
                realtime_codes = queues.get("first", []) + queues.get("second", [])[:300] + queues.get("third_sample", [])[:700]
                market_data_hub.refresh_realtime(realtime_codes, batch_size=50)
                if not _market_data_hub_job.get("last_intraday_run_at") or time.time() - _market_data_hub_job.get("last_intraday_ts", 0) >= 30:
                    market_data_hub.refresh_intraday_priority(first_limit=120, second_limit=80)
                    _market_data_hub_job["last_intraday_ts"] = time.time()
                    _market_data_hub_job["last_intraday_run_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _market_data_hub_job.update({
                "last_run_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "message": "行情数据引入中枢调度正常",
                "priority_counts": queues.get("counts", {}),
            })
        except Exception as e:
            _market_data_hub_job["message"] = f"行情数据引入中枢异常：{e}"
        finally:
            _market_data_hub_job["running"] = False
        time.sleep(1 if _is_realtime_window(datetime.now()) else 60)

@app.get("/", response_class=HTMLResponse)
async def root():
    html_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(html_file):
        with open(html_file, "r", encoding="utf-8") as f:
            return HTMLResponse(
                content=f.read(),
                headers={
                    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                    "Pragma": "no-cache",
                },
            )
    return HTMLResponse(content="<h1>股票行情系统</h1><p>网页文件未找到</p>")

@app.get("/api/v1/health")
async def health_check():
    return {
        "status": "ok",
        "message": "服务运行正常",
        "boot_id": SERVER_BOOT_ID,
        "pid": os.getpid(),
        "cwd": os.getcwd(),
        "project_root": PROJECT_ROOT,
        "hostname": socket.gethostname(),
        "code_mtime": datetime.fromtimestamp(os.path.getmtime(__file__)).strftime("%Y-%m-%d %H:%M:%S"),
    }

@app.get("/api/v1/stocks")
async def get_stocks(
    limit: int = Query(100, ge=1, le=10000),
    offset: int = Query(0, ge=0)
):
    """获取股票列表（带分页，数据来自新浪财经）"""
    try:
        now = time.time()
        if not _stock_cache["stocks"] or _stock_universe_incomplete(_stock_cache["stocks"]):
            _load_stock_universe_fast()

        all_stocks = _stock_cache["stocks"]
        total = len(all_stocks)
        paginated_stocks = all_stocks[offset:offset + limit]

        return {"total": total, "stocks": paginated_stocks}

    except Exception as e:
        logger.error(f"获取股票列表失败: {e}")
        return {"total": 0, "stocks": [], "error": str(e)}

@app.get("/api/v1/stocks/search")
async def search_stocks(
    keyword: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100)
):
    """搜索股票（本地缓存过滤）"""
    try:
        now = time.time()
        if not _stock_cache["stocks"] or _stock_universe_incomplete(_stock_cache["stocks"]):
            _load_stock_universe_fast()

        all_stocks = _stock_cache["stocks"]
        kw = keyword.lower()
        results = [
            s for s in all_stocks
            if kw in s["code"].lower() or kw in s["name"].lower()
        ]

        return results[:limit]

    except Exception as e:
        logger.error(f"搜索股票失败: {e}")
        return []

@app.post("/api/v1/stocks/sync")
async def sync_stock_list():
    """强制刷新股票缓存"""
    stocks = _load_stock_universe_fast(force_refresh=True)
    _stock_cache["stocks"] = stocks
    _stock_cache["updated_at"] = time.time()
    _ensure_stock_universe(stocks)
    return {"message": "同步成功", "total": len(stocks), "changes": data_fetcher.read_stock_universe_changes()}

@app.get("/api/v1/market/cache/status")
async def get_market_cache_status():
    """查看本地市场数据仓库状态。"""
    status = data_fetcher.get_market_cache_status()
    status["warmup_job"] = _market_cache_job.copy()
    status["realtime_refresh"] = {**_realtime_refresh_job.copy(), "watch_count": len(_realtime_watch_codes), "watch_codes": sorted(_realtime_watch_codes)[:100]}
    status["post_close_validation"] = _post_close_job.copy()
    status["stock_universe"] = {
        **_stock_universe_job.copy(),
        **data_fetcher.read_stock_universe_cache_meta(),
    }
    status["market_data_hub"] = {**market_data_hub.get_hub_status(), "runtime": _market_data_hub_job.copy()}
    return status


@app.get("/api/v1/market/data-hub/status")
async def get_market_data_hub_status():
    """行情数据引入中枢状态：调度规则、优先级队列和任务状态。"""
    stocks = _load_stock_universe_fast()
    queues = market_data_hub.build_priority_queues(
        volatile_codes=[s.get("code") for s in (state_store.get_screening_results() or [])[:120]],
        stocks=stocks,
    )
    return {**market_data_hub.get_hub_status(), "runtime": _market_data_hub_job.copy(), "priority_queue": queues}


@app.get("/api/v1/market/data-hub/coverage")
async def get_market_data_coverage(sample_limit: int = Query(0, ge=0, le=100)):
    """数据覆盖率面板：日K、实时、分时、资金流、盘口、财务等覆盖情况。"""
    stocks = _load_stock_universe_fast()
    return market_data_hub.get_coverage_report(stocks=stocks, sample_limit=sample_limit)


@app.get("/api/v1/market/ths-local/status")
async def get_ths_local_status():
    """查看同花顺本地只读历史缓存覆盖情况。"""
    return data_fetcher.scan_ths_local_day_files()


@app.post("/api/v1/market/data-hub/import-all")
async def import_all_market_data(
    days: int = Body(1000, embed=True),
    periods: list = Body([101, 102, 103], embed=True),
    include_realtime: bool = Body(True, embed=True),
    include_money_flow: bool = Body(True, embed=True),
    include_chips: bool = Body(True, embed=True),
):
    """启动全市场数据导入：股票池、实时快照、日/周/月K、资金流和筹码。分时仍由优先队列高频刷新。"""
    if _market_cache_job.get("running"):
        return {"status": "running", "message": "已有全市场导入任务正在运行", "job": _market_cache_job.copy()}
    stocks = _load_stock_universe_fast(force_refresh=True)
    params = {
        "limit": 0,
        "offset": 0,
        "days": days,
        "periods": periods or [101, 102, 103],
        "include_realtime": include_realtime,
        "include_intraday": False,
        "include_money_flow": include_money_flow,
        "include_chips": include_chips,
        "reason": "full_market_import",
    }
    threading.Thread(target=_run_market_cache_warmup, args=(params,), daemon=True).start()
    return {
        "status": "started",
        "message": "全市场数据导入已启动；分时数据将按自选/持仓/AI推荐/震荡池优先队列刷新。",
        "total": len(stocks),
        "cache_root": data_fetcher.market_cache_root(),
        "ths_local": data_fetcher.scan_ths_local_day_files(),
        "params": params,
    }


@app.get("/api/v1/stocks/{code}/data-availability")
async def get_stock_data_availability(code: str):
    """单股数据可用性：每类数据的数据源、校验状态和缺失说明。"""
    return market_data_hub.get_stock_data_availability(code)


@app.get("/api/v1/stocks/{code}/disclosure-risk")
async def get_stock_disclosure_risk(
    code: str,
    days: int = Query(180, ge=30, le=1200),
    force_refresh: bool = Query(False),
):
    """获取个股公告/财报风险结构化摘要。"""
    return disclosure_service.get_disclosure_risk_profile(code, days=days, force_refresh=force_refresh)


@app.get("/api/v1/market/disclosures/status")
async def get_disclosure_backfill_status():
    """正式公告/财报风险缓存任务状态。"""
    stocks = _load_stock_universe_fast()
    coverage = market_data_hub.get_coverage_report(stocks=stocks, sample_limit=0)
    disclosure_row = next((r for r in coverage.get("rows", []) if r.get("key") == "disclosure_risk"), {})
    return {
        "job": _disclosure_backfill_job.copy(),
        "coverage": disclosure_row,
        "cache_dir": disclosure_service.DISCLOSURE_CACHE_DIR,
        "token_visible_to_backend": bool(os.getenv("TUSHARE_TOKEN", "").strip()),
    }


@app.post("/api/v1/market/disclosures/backfill")
async def start_disclosure_backfill(
    limit: int = Body(0, embed=True),
    offset: int = Body(0, embed=True),
    days: int = Body(180, embed=True),
    force_refresh: bool = Body(False, embed=True),
    sleep_seconds: float = Body(0.35, embed=True),
):
    """启动正式公告/财报风险缓存回填。默认低速批量，避免触发 Tushare 限流。"""
    if _disclosure_backfill_job.get("running"):
        return {"status": "running", "message": "公告/财报风险回填任务正在运行", "job": _disclosure_backfill_job.copy()}
    params = {
        "limit": max(0, int(limit or 0)),
        "offset": max(0, int(offset or 0)),
        "days": max(30, min(1200, int(days or 180))),
        "force_refresh": bool(force_refresh),
        "sleep_seconds": max(0.1, min(5.0, float(sleep_seconds or 0.35))),
    }
    threading.Thread(target=_run_disclosure_backfill, args=(params,), daemon=True).start()
    return {
        "status": "started",
        "message": "正式公告/财报风险缓存回填已启动",
        "params": params,
        "cache_dir": disclosure_service.DISCLOSURE_CACHE_DIR,
    }


@app.get("/api/v1/stocks/universe/changes")
async def get_stock_universe_changes():
    """查看股票主数据变更：新股、退市/消失、更名、ST、停复牌。"""
    return data_fetcher.read_stock_universe_changes()


@app.post("/api/v1/market/cache/warmup")
async def warmup_market_cache(
    limit: int = Body(0, embed=True),
    offset: int = Body(0, embed=True),
    days: int = Body(1000, embed=True),
    periods: list = Body([101], embed=True),
    include_realtime: bool = Body(True, embed=True),
    include_intraday: bool = Body(True, embed=True),
    include_money_flow: bool = Body(True, embed=True),
    include_chips: bool = Body(True, embed=True),
):
    """后台预热全市场行情缓存，适合节假日/闭市时运行。"""
    if _market_cache_job.get("running"):
        return {"status": "running", "message": "市场缓存预热任务正在运行", "job": _market_cache_job.copy()}
    params = {
        "limit": limit,
        "offset": offset,
        "days": days,
        "periods": periods or [101],
        "include_realtime": include_realtime,
        "include_intraday": include_intraday,
        "include_money_flow": include_money_flow,
        "include_chips": include_chips,
    }
    thread = threading.Thread(target=_run_market_cache_warmup, args=(params,), daemon=True)
    thread.start()
    return {
        "status": "started",
        "message": "市场缓存预热已在后台启动",
        "cache_root": data_fetcher.market_cache_root(),
        "params": params,
    }


@app.post("/api/v1/market/realtime/watch")
async def watch_realtime_codes(
    codes: list = Body(..., embed=True),
    interval_seconds: int = Body(1, embed=True),
    all_market: bool = Body(False, embed=True),
):
    """加入实盘实时校验刷新列表，后台默认每 1 秒刷新一次。"""
    if all_market:
        stocks = _load_stock_universe_fast()
        codes = [s.get("code") for s in stocks if s.get("code")]
    for code in codes:
        _track_realtime_code(str(code))
    _realtime_refresh_job["interval_seconds"] = max(int(interval_seconds), 1)
    return {
        "status": "ok",
        "interval_seconds": _realtime_refresh_job["interval_seconds"],
        "watch_count": len(_realtime_watch_codes),
        "watch_codes": sorted(_realtime_watch_codes),
    }


@app.post("/api/v1/market/post-close/validate")
async def run_post_close_validation_now():
    """手动启动闭市后校验：多源复核后写入最终缓存。"""
    if _market_cache_job.get("running"):
        return {"status": "running", "message": "已有市场缓存任务正在运行", "job": _market_cache_job.copy()}
    params = {
        "limit": 0,
        "offset": 0,
        "days": 1000,
        "periods": [101, 102],
        "include_realtime": True,
        "include_intraday": True,
        "include_money_flow": True,
        "include_chips": True,
        "reason": "manual_post_close_validation",
    }
    threading.Thread(target=_run_market_cache_warmup, args=(params,), daemon=True).start()
    return {"status": "started", "message": "闭市后全市场校验缓存已启动", "params": params}


@app.get("/api/v1/market/snapshot/{stock_code}")
async def get_snapshot(stock_code: str):
    """获取单只股票实时行情（同花顺数据源）"""
    _track_realtime_code(stock_code)
    verified = data_fetcher.fetch_verified_realtime_batch([stock_code]).get(stock_code)
    if verified:
        return {
            "code": stock_code,
            "name": verified.get("name", ""),
            "current_price": verified.get("price", 0),
            "open": verified.get("open", 0),
            "high": verified.get("high", 0),
            "low": verified.get("low", 0),
            "pre_close": verified.get("pre_close", 0),
            "pct_change": verified.get("pct_change", 0),
            "volume": verified.get("volume", 0),
            "amount": verified.get("amount", 0),
            "source": verified.get("source", "verified_realtime"),
            "validation_status": verified.get("validation_status"),
            "validated_sources": verified.get("validated_sources", []),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    quote = _fetch_ths_quote(stock_code)
    if quote:
        return {
            "code": stock_code,
            "name": quote["name"],
            "current_price": quote["price"],
            "open": quote["open"],
            "volume": quote["volume"],
            "amount": quote["amount"],
            "source": "同花顺",
        }
    demo = _demo_stock(stock_code)
    if demo:
        return {
            "code": stock_code,
            "name": demo["name"],
            "current_price": demo["price"],
            "open": round(demo["price"] / (1 + demo["pct_change"] / 100), 2),
            "volume": demo["volume"],
            "amount": demo["amount"],
            "source": "本地演示数据",
        }
    return {"error": "获取行情数据失败"}

@app.get("/api/v1/market/snapshots")
async def get_snapshots(
    codes: str = Query(..., description="股票代码，逗号分隔")
):
    """批量获取股票实时行情（同花顺数据源）"""
    stock_codes = [code.strip() for code in codes.split(",") if code.strip()][:20]
    for code in stock_codes:
        _track_realtime_code(code)
    verified_batch = data_fetcher.fetch_verified_realtime_batch(stock_codes)
    snapshots = []

    for code in stock_codes:
        verified = verified_batch.get(code)
        if verified:
            snapshots.append({
                "code": code,
                "name": verified.get("name", ""),
                "current_price": verified.get("price", 0),
                "open": verified.get("open", 0),
                "volume": verified.get("volume", 0),
                "amount": verified.get("amount", 0),
                "source": verified.get("source", "verified_realtime"),
                "validation_status": verified.get("validation_status"),
                "validated_sources": verified.get("validated_sources", []),
            })
            continue
        quote = _fetch_ths_quote(code)
        if quote:
            snapshots.append({
                "code": code,
                "name": quote["name"],
                "price": quote["price"],
                "open": quote["open"],
                "volume": quote["volume"],
                "amount": quote["amount"],
            })

    return {"snapshots": snapshots}


# ==================== 量化交易系统 API ====================

@app.get("/api/v1/quant/screening/results")
async def get_screening_results():
    """获取选股结果 Top50"""
    results = state_store.get_screening_results()
    return {
        "count": len(results),
        "results": results,
        "logic": stock_screener.get_screening_logic_summary(),
        "updated_at": state_store.get_system_state().get("last_screening_time"),
    }


@app.post("/api/v1/quant/screening/run")
async def run_screening(payload: dict | None = Body(default=None)):
    """手动触发选股"""
    payload = payload or {}
    strategy = payload.get("strategy")
    if strategy in ("short", "long", "event_driven"):
        state_store.update_user_settings({"trading_style": strategy})
    if not state_store.get_stock_universe():
        stocks = _stock_cache["stocks"] or DEMO_STOCKS
        _stock_cache["stocks"] = stocks
        _stock_cache["updated_at"] = time.time()
        _ensure_stock_universe(stocks)
    results = await asyncio.to_thread(trading_engine.manual_screening)
    agent_workspace.record_event("score", "screening", f"选股完成：{len(results)} 个候选。")
    return {
        "message": "选股完成",
        "count": len(results),
        "results": results,
        "logic": stock_screener.get_screening_logic_summary(),
    }


@app.post("/api/v1/quant/screening/run/start")
async def start_screening_job(payload: dict | None = Body(default=None)):
    """启动后台智能选股任务，避免浏览器等待长请求超时。"""
    payload = payload or {}
    strategy = payload.get("strategy")
    with _screening_jobs_lock:
        running = next((j for j in _screening_jobs.values() if j.get("status") == "running"), None)
    if running:
        return {
            "status": "running",
            "message": "已有智能选股任务正在运行",
            "job_id": running.get("job_id"),
            "job": running,
        }
    job_id = f"screening-{int(time.time())}-{len(_screening_jobs) + 1}"
    job = {
        "job_id": job_id,
        "status": "queued",
        "stage": "queued",
        "message": "智能选股任务已进入后台队列",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "params": {"strategy": strategy},
    }
    with _screening_jobs_lock:
        _screening_jobs[job_id] = job
    threading.Timer(0.2, _run_screening_job, args=(job_id, job["params"])).start()
    return {"status": "started", "job_id": job_id, "job": job}


@app.get("/api/v1/quant/screening/run/status/{job_id}")
async def get_screening_job_status(job_id: str):
    """查询后台智能选股任务状态。"""
    with _screening_jobs_lock:
        job = (_screening_jobs.get(job_id) or {}).copy()
    if not job:
        return {"status": "missing", "job_id": job_id, "message": "未找到该选股任务"}
    return job


@app.get("/api/v1/quant/signals")
async def get_signals():
    """获取活跃买卖信号"""
    signals = signal_detector.detect_all_signals()
    ai_recommendations = _json_safe(state_store.get_ai_recommendations())
    ai_signals = [
        {
            "signal_id": f"AI_CACHE_{item.get('code', '')}",
            "type": "ai_buy",
            "code": item.get("code"),
            "name": item.get("name", ""),
            "price": (item.get("trade_plan") or {}).get("current_price"),
            "entry_price": (item.get("trade_plan") or {}).get("suggested_buy_price"),
            "target_price": (item.get("trade_plan") or {}).get("suggested_sell_price"),
            "stop_loss_price": (item.get("trade_plan") or {}).get("stop_loss_price"),
            "strength": "strong" if float(item.get("ai_rank_score") or 0) >= 75 else "medium",
            "score": item.get("ai_rank_score"),
            "reason": item.get("ai_reason", ""),
            "ai_recommendation": True,
            "generated_at": ai_recommendations.get("generated_at"),
        }
        for item in (ai_recommendations.get("recommendations") or [])
        if item.get("code") and item.get("recommend_buy") is True
    ]
    signals["buy_signals"].extend(ai_signals)
    signals["total"] += len(ai_signals)
    agent_workspace.record_event("decision", "signals", f"信号检测完成：{signals['total']} 条。")
    return {
        "buy_signals": signals["buy_signals"],
        "sell_signals": signals["sell_signals"],
        "total": signals["total"],
        "ai_recommendations": ai_recommendations,
    }


@app.post("/api/v1/quant/signals/detect")
async def manual_signal_detection():
    """手动触发信号检测"""
    signals = trading_engine.manual_signal_detection()
    agent_workspace.record_event("decision", "signals", f"手动信号检测完成：{signals['total']} 条。")
    return {
        "message": "信号检测完成",
        "buy_signals": signals["buy_signals"],
        "sell_signals": signals["sell_signals"],
        "total": signals["total"],
    }


@app.post("/api/v1/quant/signals/ai-pick")
async def run_ai_signal_pick(payload: dict | None = Body(default=None)):
    """启动AI选股复核，并把推荐写入交易信号。"""
    payload = payload or {}
    strategy = payload.get("strategy") or state_store.get_user_settings().get("trading_style", "short")
    limit = int(payload.get("limit", 8) or 8)
    universe_limit = int(payload.get("universe_limit", 20) or 20)
    scope = payload.get("scope") or "focus"
    focus_codes = payload.get("focus_codes") or []
    result = await asyncio.to_thread(
        ai_stock_picker.run_ai_stock_picking,
        strategy=strategy,
        limit=limit,
        universe_limit=universe_limit,
        scope=scope,
        focus_codes=focus_codes,
    )
    agent_workspace.record_event(
        "decision",
        "ai_stock_pick",
        f"AI选股完成：推荐{len(result.get('recommendations', []))}只，写入信号{result.get('signal_count', 0)}条。",
        payload={
            "strategy": strategy,
            "scope": result.get("scope"),
            "focus_count": result.get("focus_count", 0),
            "used_ai": (result.get("ai_meta") or {}).get("used_ai"),
            "model": (result.get("ai_meta") or {}).get("model"),
            "signal_count": result.get("signal_count", 0),
        },
    )
    return result


def _run_ai_pick_job(job_id: str, payload: dict):
    def update_progress(progress: dict):
        with _ai_pick_jobs_lock:
            job = _ai_pick_jobs.get(job_id) or {}
            job.update({
                "status": "running",
                "message": progress.get("message") or job.get("message") or "AI选股运行中",
                "progress": progress,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            _ai_pick_jobs[job_id] = job

    with _ai_pick_jobs_lock:
        job = _ai_pick_jobs.get(job_id) or {}
        job.update({"status": "running", "message": "AI选股运行中", "progress": {"stage": "start", "message": "AI选股运行中"}, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        _ai_pick_jobs[job_id] = job
    try:
        strategy = payload.get("strategy") or state_store.get_user_settings().get("trading_style", "short")
        limit = int(payload.get("limit", 8) or 8)
        universe_limit = int(payload.get("universe_limit", 20) or 20)
        scope = payload.get("scope") or "focus"
        focus_codes = payload.get("focus_codes") or []
        result = ai_stock_picker.run_ai_stock_picking(
            strategy=strategy,
            limit=limit,
            universe_limit=universe_limit,
            scope=scope,
            focus_codes=focus_codes,
            progress_callback=update_progress,
        )
        status = "failed" if result.get("error") else "done"
        with _ai_pick_jobs_lock:
            _ai_pick_jobs[job_id].update({
                "status": status,
                "message": result.get("error") or "AI选股完成",
                "result": result,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
        agent_workspace.record_event(
            "decision",
            "ai_stock_pick",
            f"AI选股{('失败' if result.get('error') else '完成')}：推荐{len(result.get('recommendations', []))}只，写入信号{result.get('signal_count', 0)}条。",
            payload={
                "job_id": job_id,
                "strategy": strategy,
                "scope": result.get("scope"),
                "focus_count": result.get("focus_count", 0),
                "used_ai": (result.get("ai_meta") or {}).get("used_ai"),
                "model": (result.get("ai_meta") or {}).get("model"),
                "signal_count": result.get("signal_count", 0),
            },
        )
    except Exception as exc:
        message = f"AI选股后台任务异常：{exc}"
        result = ai_stock_picker._persist_ai_error_result(message, strategy=payload.get("strategy") or "short", scope=payload.get("scope") or "focus", focus_codes=payload.get("focus_codes") or [])
        with _ai_pick_jobs_lock:
            _ai_pick_jobs[job_id].update({
                "status": "failed",
                "message": message,
                "result": result,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })


@app.post("/api/v1/quant/signals/ai-pick/start")
async def start_ai_signal_pick(payload: dict | None = Body(default=None)):
    """后台启动AI选股，前端轮询状态，避免浏览器长请求中断。"""
    payload = payload or {}
    job_id = f"AI_PICK_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    with _ai_pick_jobs_lock:
        _ai_pick_jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "message": "AI选股已排队",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "payload": payload,
        }
    thread = threading.Thread(target=_run_ai_pick_job, args=(job_id, payload), daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "queued", "message": "AI选股已启动"}


@app.get("/api/v1/quant/signals/ai-pick/status/{job_id}")
async def get_ai_signal_pick_status(job_id: str):
    """读取AI选股后台任务状态。"""
    with _ai_pick_jobs_lock:
        job = (_ai_pick_jobs.get(job_id) or {}).copy()
    if not job:
        return {"job_id": job_id, "status": "not_found", "message": "未找到AI选股任务"}
    return _json_safe(job)


@app.post("/api/v1/quant/stocks/{code}/ai-analysis")
async def run_single_stock_ai_analysis(code: str, payload: dict | None = Body(default=None)):
    """对单只股票执行AI分析，并加入AI推荐/分析列表。"""
    payload = payload or {}
    strategy = payload.get("strategy") or state_store.get_user_settings().get("trading_style", "short")
    try:
        result = ai_stock_picker.analyze_single_stock(code, strategy=strategy)
        analysis = result.get("analysis", {})
        agent_workspace.record_event(
            "decision",
            "single_stock_ai_analysis",
            f"{code} 单股AI分析完成：{analysis.get('ai_action', '观察')}。",
            payload={
                "code": code,
                "strategy": strategy,
                "used_ai": (result.get("ai_meta") or {}).get("used_ai"),
                "model": (result.get("ai_meta") or {}).get("model"),
                "ai_rank_score": analysis.get("ai_rank_score"),
            },
        )
        return result
    except Exception as e:
        logger.exception(f"{code} 单股AI分析失败")
        agent_workspace.record_event(
            "decision",
            "single_stock_ai_analysis_error",
            f"{code} 单股AI分析失败：{e}",
            level="error",
            payload={"code": code, "strategy": strategy, "error": str(e)},
        )
        return {"error": str(e), "code": code, "strategy": strategy, "analysis": {}, "ai_meta": {"ok": False, "used_ai": False}}


def _site_ai_stock_universe() -> list:
    stocks = state_store.get_stock_universe() or _stock_cache.get("stocks") or []
    if isinstance(stocks, dict):
        stocks = list(stocks.values())
    if not stocks:
        stocks = data_fetcher.read_stock_universe_cache() or DEMO_STOCKS
    if isinstance(stocks, dict):
        stocks = list(stocks.values())
    return stocks


def _site_ai_match_stocks(message: str, current_stock: dict | None = None, limit: int = 6) -> list:
    text = message or ""
    stocks = _site_ai_stock_universe()
    by_code = {str(s.get("code", "")): s for s in stocks if s.get("code")}
    matched = []
    seen = set()

    def add(stock):
        code = str((stock or {}).get("code", "")).strip()
        if code and code not in seen:
            matched.append(stock)
            seen.add(code)

    for code in re.findall(r"(?<!\d)(\d{6})(?!\d)", text):
        add(by_code.get(code) or state_store.get_stock_info(code) or {"code": code})

    if current_stock and current_stock.get("code"):
        code = str(current_stock.get("code"))
        if code in text or str(current_stock.get("name", "")) in text:
            add(by_code.get(code) or current_stock)

    for stock in stocks:
        name = str(stock.get("name", "")).strip()
        code = str(stock.get("code", "")).strip()
        if name and name in text:
            add(stock)
        elif code and code in text:
            add(stock)
        if len(matched) >= limit:
            break

    if not matched:
        keyword = text.strip()
        if keyword:
            scored = []
            for stock in stocks:
                name = str(stock.get("name", ""))
                code = str(stock.get("code", ""))
                if keyword and (keyword in name or keyword in code):
                    scored.append((0 if name.startswith(keyword) or code.startswith(keyword) else 1, stock))
            for _, stock in sorted(scored, key=lambda x: x[0])[:limit]:
                add(stock)

    return matched[:limit]


def _site_ai_stock_context(stock: dict, strategy: str) -> dict:
    code = str(stock.get("code", "")).strip()
    name = stock.get("name", "")
    realtime = data_fetcher.read_realtime_cache(code) or state_store.get_realtime(code) or {}
    if not realtime:
        try:
            data_fetcher.fetch_realtime_batch([code])
            realtime = state_store.get_realtime(code) or {}
        except Exception:
            realtime = {}
    daily_df = state_store.get_daily_bars(code)
    if daily_df is None:
        daily_df = data_fetcher._read_kline_cache(code, 101, 260)
    kline_tail = []
    previous_day = {}
    try:
        if daily_df is not None and len(daily_df) > 0:
            tail = daily_df.tail(8)
            for _, row in tail.iterrows():
                item = row.to_dict()
                kline_tail.append({
                    "date": str(item.get("date", "")),
                    "open": item.get("open"),
                    "close": item.get("close"),
                    "high": item.get("high"),
                    "low": item.get("low"),
                    "volume": item.get("volume"),
                    "amount": item.get("amount"),
                    "pct_change": item.get("pct_change"),
                })
            last = kline_tail[-1] if kline_tail else {}
            prev = kline_tail[-2] if len(kline_tail) >= 2 else {}
            if last:
                pct_value = last.get("pct_change")
                if pct_value in (None, "") and prev.get("close"):
                    pct_value = (float(last.get("close") or 0) - float(prev.get("close") or 0)) / float(prev.get("close")) * 100
                previous_day = {
                    "date": last.get("date"),
                    "close": last.get("close"),
                    "pct_change": round(float(pct_value or 0), 2),
                    "direction": "上涨" if float(pct_value or 0) > 0 else ("下跌" if float(pct_value or 0) < 0 else "平盘"),
                }
    except Exception as exc:
        previous_day = {"error": f"K线摘要生成失败：{exc}"}

    if not previous_day:
        pct_value = realtime.get("pct_change", stock.get("pct_change"))
        price_value = realtime.get("price", stock.get("price"))
        if pct_value not in (None, ""):
            previous_day = {
                "date": realtime.get("date") or realtime.get("trade_date") or "最新可用交易日",
                "close": price_value,
                "pct_change": round(float(pct_value or 0), 2),
                "direction": "上涨" if float(pct_value or 0) > 0 else ("下跌" if float(pct_value or 0) < 0 else "平盘"),
                "source": realtime.get("source") or stock.get("source") or "stock_universe_or_realtime_cache",
                "note": "本地K线不足时，使用站内股票池/实时行情缓存的最新涨跌幅兜底。",
            }

    stock_news = []
    for item in state_store.get_news()[:300]:
        title = str(item.get("title", ""))
        content = str(item.get("content", ""))
        if code in title or code in content or (name and (name in title or name in content)):
            stock_news.append(item)
        if len(stock_news) >= 10:
            break

    score_card = {}
    decision = {}
    risk = {}
    try:
        score_card = generate_score_card(code, strategy)
    except Exception as exc:
        score_card = {"error": str(exc)}
    try:
        decision = generate_decision(code, strategy)
    except Exception as exc:
        decision = {"error": str(exc)}
    try:
        risk = full_risk_pipeline(code, strategy)
    except Exception as exc:
        risk = {"error": str(exc)}

    return _json_safe({
        "code": code,
        "name": name or realtime.get("name"),
        "matched_from_site": True,
        "basic": stock,
        "realtime": realtime,
        "previous_trading_day": previous_day,
        "recent_daily_kline": kline_tail,
        "score_card": score_card,
        "decision": decision,
        "risk_report": (risk or {}).get("risk_report", risk),
        "ai_recommendation": next(
            (item for item in (state_store.get_ai_recommendations().get("recommendations") or []) if item.get("code") == code),
            None,
        ),
        "watchlist": [w for w in payload_watchlist_safe() if w.get("code") == code],
        "position": (state_store.get_positions() or {}).get(code),
        "related_news": stock_news,
    })


def payload_watchlist_safe() -> list:
    # 前端自选主要存在浏览器 localStorage；后端只能读取已通过研究/AI/详情同步到状态里的数据。
    return []


@app.post("/api/v1/ai/chat")
async def ai_chat(payload: dict = Body(...)):
    """站内AI对话：带上网站当前状态摘要，让模型理解本系统。"""
    message = str(payload.get("message", "")).strip()
    if not message:
        return {"ok": False, "answer": "请先输入问题。", "ai_meta": {"used_ai": False}}

    current_stock = payload.get("current_stock") if isinstance(payload.get("current_stock"), dict) else None
    strategy = state_store.get_user_settings().get("trading_style", "short")
    matched_stocks = _site_ai_match_stocks(message, current_stock=current_stock)
    stock_context = [_site_ai_stock_context(stock, strategy) for stock in matched_stocks]
    context = {
        "project": {
            "name": "量化智能猎人",
            "positioning": "小型、灵活、信息理解能力强的A股量化投研和模拟交易工具",
            "safety": "真实交易默认关闭，当前以研究、信号、风控复核和模拟盘为主",
        },
        "assistant_permissions": {
            "scope": "只读问答助手",
            "can_query": "可以查询本网站股票池、实时行情缓存、K线缓存、分时、评分卡、决策、风控、新闻、板块、选股结果、AI推荐、模拟盘、持仓、熔断和Agent状态。",
            "cannot_do": "不能修改网站参数，不能替用户下单，不能泄露或复述API密钥、密钥片段、鉴权头、后端本地敏感配置。",
        },
        "current_page": payload.get("page"),
        "current_stock": current_stock,
        "client_watchlist": payload.get("watchlist", [])[:80] if isinstance(payload.get("watchlist"), list) else [],
        "matched_stocks": stock_context,
        "strategy": strategy,
        "stock_universe_count": len(state_store.get_stock_universe()),
        "screening_top": state_store.get_screening_results()[:8],
        "ai_recommendations": (state_store.get_ai_recommendations().get("recommendations") or [])[:8],
        "trade_review_learning": trade_review_service.get_trade_review_candidates(limit=8),
        "portfolio": state_store.get_portfolio(),
        "positions": list(state_store.get_positions().values())[:10],
        "risk": risk_manager.get_risk_config(),
        "kill_switch": get_kill_switch_status(),
        "news_sample": state_store.get_news()[:8],
        "system_state": state_store.get_system_state(),
    }
    system_prompt = (
        "你是本网站内置的AI助手，熟悉本项目所有功能：行情、板块、新闻风控、智能选股、交易信号、"
        "个股详情、AI模型配置、Agent工作台、回测、模拟盘和熔断。"
        "你对本网站拥有只读查询能力：可以根据站内上下文回答股票、行情、K线、分时、选股、信号、风控、新闻、板块、持仓、模拟盘和Agent状态。"
        "你不能修改网站参数，不能替用户下单，不能泄露API密钥、密钥片段、鉴权头或本地敏感配置。"
        "回答必须使用中文，结合站内上下文；如果 matched_stocks 中有命中的股票，必须优先使用其中的数据直接回答，不要说站内没有这只股票。"
        "涉及买卖时必须提醒这只是研究和模拟盘参考，不能跳过风控复核。"
        "如果用户问功能怎么用，要给出页面入口和操作步骤；如果问股票，要说明你查到的数据来源、最新交易日或是否缺少K线/实时缓存。"
        "如果用户问交割单学习，要说明 OCR候选、PDF原则、已校验复盘 三类证据边界；未校验OCR不能当成真实交易流水。"
        "站内上下文里可能包含历史文件遗留的乱码字段，遇到乱码请忽略，不要说用户输入是乱码。"
    )
    answer, meta = ai_model_service.chat_text("deep_analysis", system_prompt, message, context)
    agent_workspace.record_event(
        "decision",
        "site_ai_chat",
        "站内AI对话已响应。",
        payload={"used_ai": meta.get("used_ai"), "model": meta.get("model"), "page": payload.get("page")},
    )
    return {"ok": meta.get("ok", False), "answer": answer, "ai_meta": meta}


@app.get("/api/v1/ai/trade-review/candidates")
async def get_trade_review_candidates(
    status: str = Query("", max_length=40),
    search: str = Query("", max_length=120),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
):
    """读取 OCR/PDF 交割单复盘候选表。候选字段不是事实，需要人工校验。"""
    return trade_review_service.get_trade_review_candidates(status=status, search=search, offset=offset, limit=limit)


@app.post("/api/v1/ai/trade-review/verify")
async def verify_trade_review(payload: dict = Body(default=None)):
    """保存人工校验后的交割单复盘记录，可选择写入AI策略记忆。"""
    result = trade_review_service.upsert_verified_trade_review(payload or {})
    agent_workspace.record_event(
        "decision",
        "trade_review_verify",
        result.get("message", "交割单复盘校验已处理。"),
        payload={"candidate_id": (payload or {}).get("candidate_id"), "ok": result.get("ok"), "learned": result.get("learned")},
        level="info" if result.get("ok") else "warn",
    )
    return result


@app.post("/api/v1/quant/portfolio/buy")
async def buy_stock(
    code: str = Body(..., embed=True),
    price: float = Body(..., embed=True),
    quantity: int = Body(..., embed=True),
    reason: str = Body("手动买入", embed=True),
):
    """手动买入"""
    result = portfolio_manager.execute_buy(code, price, quantity, reason)
    if result["success"]:
        agent_workspace.record_event("execution", "paper_buy", f"模拟买入 {code} {quantity} 股。", payload={"price": price, "reason": reason})
        return {"message": "买入成功", "order": result["order"]}
    agent_workspace.record_event("execution", "paper_buy_rejected", f"模拟买入 {code} 被拒绝。", level="warn", payload={"error": result.get("error")})
    return {"message": "买入失败", "error": result.get("error", "未知错误")}


@app.post("/api/v1/quant/portfolio/sell")
async def sell_stock(
    code: str = Body(..., embed=True),
    price: float = Body(..., embed=True),
    quantity: int = Body(..., embed=True),
    reason: str = Body("手动卖出", embed=True),
):
    """手动卖出"""
    result = portfolio_manager.execute_sell(code, price, quantity, reason)
    if result["success"]:
        agent_workspace.record_event("execution", "paper_sell", f"模拟卖出 {code} {quantity} 股。", payload={"price": price, "reason": reason})
        return {"message": "卖出成功", "order": result["order"]}
    agent_workspace.record_event("execution", "paper_sell_rejected", f"模拟卖出 {code} 被拒绝。", level="warn", payload={"error": result.get("error")})
    return {"message": "卖出失败", "error": result.get("error", "未知错误")}


@app.get("/api/v1/quant/portfolio")
async def get_portfolio():
    """获取组合概览"""
    return portfolio_manager.get_portfolio_summary()


@app.get("/api/v1/quant/portfolio/positions")
async def get_positions():
    """获取持仓列表"""
    return {"positions": portfolio_manager.get_position_list()}


@app.get("/api/v1/quant/portfolio/orders")
async def get_orders(limit: int = Query(50, ge=1, le=500)):
    """获取交易记录"""
    return {"orders": portfolio_manager.get_order_history(limit)}


@app.get("/api/v1/quant/portfolio/statistics")
async def get_trade_statistics():
    """获取交易统计"""
    return portfolio_manager.get_trade_statistics()


@app.post("/api/v1/quant/portfolio/reset")
async def reset_portfolio():
    """重置组合"""
    portfolio_manager.reset_portfolio()
    return {"message": "组合已重置为初始状态（20万资金）"}


@app.get("/api/v1/quant/system/status")
async def get_system_status():
    """获取系统状态"""
    return trading_engine.get_system_status()


@app.post("/api/v1/quant/system/auto-trade")
async def toggle_auto_trade(enabled: bool = Body(..., embed=True)):
    """开启/关闭自动交易"""
    trading_engine.enable_auto_trade(enabled)
    return {"message": f"自动交易已{'开启' if enabled else '关闭'}"}


@app.get("/api/v1/quant/news")
async def get_news(limit: int = Query(500, ge=1, le=2000)):
    """获取最新新闻"""
    news = news_service.ensure_news_loaded()
    sentiment = news_service.get_market_sentiment()
    meta = state_store.get_news_meta()
    enriched_news = _enrich_news_for_market(news)
    return {
        "news": enriched_news[:limit],
        "sentiment": sentiment,
        "source_meta": meta,
    }


@app.post("/api/v1/quant/news/refresh")
async def refresh_news(payload: dict = Body(None)):
    """手动刷新新闻监控"""
    payload = payload or {}
    watchlist_codes = payload.get("watchlist_codes") or []
    news = news_service.refresh_news(watchlist_codes=watchlist_codes)
    sentiment = news_service.get_market_sentiment()
    meta = state_store.get_news_meta()
    agent_workspace.record_event(
        "news",
        "refresh",
        f"新闻刷新完成：{len(news or [])} 条，来源 {meta.get('source_count', 0)} 个，去重 {meta.get('duplicate_count', 0)} 条，自选 {len(watchlist_codes)} 只。",
        payload={"source_meta": meta},
    )
    return {
        "message": "新闻刷新完成" if news else "新闻获取失败",
        "count": len(news or []),
        "news": _enrich_news_for_market(news or [])[:500],
        "sentiment": sentiment,
        "source_meta": meta,
    }


@app.get("/api/v1/quant/risk")
async def get_risk_status():
    """获取风控状态"""
    return risk_manager.get_risk_status()


@app.get("/api/v1/quant/risk/config")
async def get_risk_config():
    """获取风控配置"""
    return risk_manager.get_risk_config()


@app.post("/api/v1/quant/risk/config")
async def update_risk_config(updates: dict = Body(...)):
    """更新风控配置"""
    risk_manager.update_risk_config(updates)
    return {"message": "风控配置已更新", "config": risk_manager.get_risk_config()}


def _json_safe(value):
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    try:
        if hasattr(value, "item"):
            return _json_safe(value.item())
    except Exception:
        pass
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


# ==================== 股票详情 API ====================

@app.get("/api/v1/stocks/{code}/minutes")
async def get_stock_minutes(code: str):
    """获取分时图数据"""
    _track_realtime_code(code)
    minutes = state_store.get_intraday(code)
    if (
        not minutes
        or (minutes and minutes[0].get("source") == "estimated")
        or not data_fetcher.intraday_minutes_valid(minutes)
    ):
        minutes = data_fetcher.fetch_intraday_minutes(code, allow_fallback=False)
    source = minutes[0].get("source") if minutes else None
    return {
        "code": code,
        "minutes": minutes,
        "source": source or "unavailable",
        "status": "ok" if minutes else "unavailable",
        "message": "" if minutes else "分时数据源暂不可用，已停止使用估算曲线。",
    }


@app.get("/api/v1/stocks/{code}/kline")
async def get_stock_kline(code: str, period: int = Query(101), days: int = Query(120)):
    """获取K线数据
    period: 1=1分, 5=5分, 15=15分, 30=30分, 60=60分, 101=日K, 102=周K
    """
    _track_realtime_code(code)
    df = data_fetcher._read_kline_cache(code, period, days)
    min_required = min(int(days or 0), 30) if int(period) == 101 else min(int(days or 0), 8)
    if df is not None and min_required and len(df) < min_required:
        df = data_fetcher.fetch_kline(code, period, days, allow_fallback=False, prefer_cache=False, force_refresh=True)
    if df is None:
        df = state_store.get_kline(code, period)
    if df is None or (not df.empty and "source" in df.columns and df["source"].iloc[0] == "estimated"):
        df = data_fetcher.fetch_kline(code, period, days, allow_fallback=False)
    if df is None:
        return {
            "code": code,
            "period": period,
            "klines": [],
            "source": "unavailable",
            "status": "unavailable",
            "message": "K线数据源暂不可用，已停止使用估算K线。",
        }
    if period == 101 and state_store.get_daily_bars(code) is None:
        state_store.set_daily_bars(code, df)
    klines = _json_safe(df.to_dict("records"))
    source = klines[0].get("source") if klines else None
    validation = {}
    if klines:
        validation = {
            "status": klines[0].get("validation_status"),
            "validated_sources": klines[0].get("validated_sources"),
            "accepted_sources": klines[0].get("accepted_sources"),
            "rejected_sources": klines[0].get("rejected_sources"),
            "checked_at": klines[0].get("validation_checked_at"),
        }
    validation_report = data_fetcher._read_json_cache(data_fetcher._validation_report_path(code, f"kline_{period}")) or {}
    message = ""
    if period == 101 and validation_report:
        trusted_rows = int(validation_report.get("trusted_rows") or len(klines))
        candidate_rows = int(validation_report.get("candidate_rows") or 0)
        if trusted_rows < days and candidate_rows:
            message = "当前只返回已通过至少双源一致校验的日K；未通过校验的样本已进入候选缓存和校验报告。"
    return {
        "code": code,
        "period": period,
        "klines": klines,
        "source": source or "unavailable",
        "status": "ok" if klines else "unavailable",
        "validation": validation,
        "validation_report": validation_report,
        "message": message,
    }


@app.get("/api/v1/stocks/{code}/chips")
async def get_stock_chips(code: str):
    """获取筹码分布"""
    chips = state_store.get_chip_distribution(code)
    if not chips:
        chips = data_fetcher.fetch_chip_distribution(code)
    return {"code": code, "chips": chips}


@app.get("/api/v1/stocks/{code}/detail")
async def get_stock_detail(code: str):
    """获取股票综合详情（行情+资金+技术+新闻）"""
    _track_realtime_code(code)
    cached = _stock_detail_cache.get(code)
    if cached and time.time() - cached.get("updated_at", 0) < 8:
        return {**cached["payload"], "cache_hit": True}

    stock_info = state_store.get_stock_info(code) or _demo_stock(code) or {}
    if not stock_info:
        stock_info = next((s for s in (_stock_cache.get("stocks") or []) if s.get("code") == code), {})

    # 实时行情
    realtime = data_fetcher.read_realtime_cache(code) or state_store.get_realtime(code)
    if not realtime and stock_info:
        realtime = {
            "code": code,
            "name": stock_info.get("name", ""),
            "price": stock_info.get("price", 0),
            "pct_change": stock_info.get("pct_change", 0),
            "volume": stock_info.get("volume", 0),
            "amount": stock_info.get("amount", 0),
            "source": "stock_universe_cache",
        }
        state_store.set_realtime(code, realtime)
    realtime_batch = data_fetcher.fetch_realtime_batch([code])
    if realtime_batch.get(code):
        realtime = realtime_batch.get(code)
    elif not realtime:
        realtime = state_store.get_realtime(code) or {}
    if not realtime:
        quote = _fetch_ths_quote(code) or {}
        if quote:
            realtime = {"code": code, **quote}
            state_store.set_realtime(code, realtime)
    if not realtime:
        demo = _demo_stock(code)
        if demo:
            base = demo["price"] / (1 + demo["pct_change"] / 100)
            realtime = {
                "code": code,
                "name": demo["name"],
                "price": demo["price"],
                "pct_change": demo["pct_change"],
                "open": round(base, 2),
                "high": round(demo["price"] * 1.018, 2),
                "low": round(demo["price"] * 0.982, 2),
                "volume": demo["volume"],
                "amount": demo["amount"],
                "turnover_rate": 1.26,
                "volume_ratio": 1.18,
            }
            state_store.set_realtime(code, realtime)

    # 资金流向
    flow = state_store.get_money_flow(code)
    # 详情页优先快速展示，不在首屏阻塞等待外部资金流接口。

    # 技术指标
    daily_df = state_store.get_daily_bars(code)
    if daily_df is None:
        daily_df = data_fetcher._read_kline_cache(code, 101, 120)
        if daily_df is not None:
            state_store.set_daily_bars(code, daily_df)
    tech = {}
    if daily_df is not None and len(daily_df) >= 20:
        df = technical_analysis.calc_all_indicators(daily_df.copy())
        last = df.iloc[-1]
        tech = {
            "ma5": round(last.get("ma5", 0), 2),
            "ma10": round(last.get("ma10", 0), 2),
            "ma20": round(last.get("ma20", 0), 2),
            "ma60": round(last.get("ma60", 0), 2),
            "dif": round(last.get("dif", 0), 4),
            "dea": round(last.get("dea", 0), 4),
            "macd_hist": round(last.get("macd_hist", 0), 4),
            "rsi_6": round(last.get("rsi_6", 0), 2),
            "kdj_j": round(last.get("kdj_j", 0), 2),
            "boll_upper": round(last.get("boll_upper", 0), 2),
            "boll_mid": round(last.get("boll_mid", 0), 2),
            "boll_lower": round(last.get("boll_lower", 0), 2),
        }

    # 相关新闻
    news = state_store.get_news()
    stock_name = stock_info.get("name", "") if stock_info else ""
    stock_news = [n for n in news if code in n.get("title", "") or stock_name in n.get("title", "")]

    chips = state_store.get_chip_distribution(code) or data_fetcher.read_chip_cache(code)
    if not chips and daily_df is not None and len(daily_df) >= 10:
        chips = data_fetcher.fetch_chip_distribution(code)

    pre_close = float(realtime.get("pre_close") or 0) if realtime else 0
    last_price = float(realtime.get("price") or 0) if realtime else 0
    high = float(realtime.get("high") or 0) if realtime else 0
    low = float(realtime.get("low") or 0) if realtime else 0
    amplitude = round((high - low) / pre_close * 100, 2) if pre_close else 0
    stock_info_panel = {
        "limit_up": realtime.get("limit_up") or (round(pre_close * 1.1, 2) if pre_close else None),
        "limit_down": realtime.get("limit_down") or (round(pre_close * 0.9, 2) if pre_close else None),
        "pre_close": pre_close or None,
        "avg_price": realtime.get("avg_price") or (round(float((chips or {}).get("avg_cost") or 0), 2) if chips else None),
        "amplitude": realtime.get("amplitude") or amplitude,
        "total_volume": realtime.get("volume"),
        "inner_volume": realtime.get("inner_volume"),
        "outer_volume": realtime.get("outer_volume"),
        "entrust_ratio": realtime.get("entrust_ratio"),
        "turnover_rate": realtime.get("turnover_rate"),
        "volume_ratio": realtime.get("volume_ratio"),
        "amount": realtime.get("amount"),
        "float_shares": realtime.get("float_shares") or stock_info.get("float_shares"),
        "float_market_cap": realtime.get("float_market_cap") or stock_info.get("float_market_cap") or stock_info.get("market_cap"),
        "total_shares": realtime.get("total_shares") or stock_info.get("total_shares"),
        "market_cap": realtime.get("market_cap") or stock_info.get("market_cap"),
        "pe_ttm": realtime.get("pe_ttm") or stock_info.get("pe_ttm"),
        "pe_dynamic": realtime.get("pe_dynamic") or stock_info.get("pe_dynamic"),
        "pe_static": realtime.get("pe_static") or stock_info.get("pe_static"),
        "pb": realtime.get("pb") or stock_info.get("pb"),
        "data_note": "盘口优先使用腾讯证券五档字段；F10财务深层字段仍等待正式数据源，不伪造。",
    }
    limit_gene = {
        "stock_score": None,
        "limit_up_count_1y": None,
        "latest_limit_up_date": None,
        "seal_success_rate": None,
        "next_open_after_limit": None,
        "next_close_after_limit": None,
        "data_note": "涨停基因需历史涨停事件库，当前仅预留真实字段。",
    }
    data_availability = market_data_hub.get_stock_data_availability(code)

    payload = _json_safe({
        "code": code,
        "name": stock_name,
        "realtime": realtime,
        "money_flow": flow,
        "technical": tech,
        "chips": chips or {},
        "stock_info_panel": stock_info_panel,
        "limit_gene": limit_gene,
        "data_availability": data_availability,
        "news": stock_news[:20],
        "ai_recommendation": next(
            (item for item in (state_store.get_ai_recommendations().get("recommendations") or []) if item.get("code") == code),
            None,
        ),
    })
    _stock_detail_cache[code] = {"updated_at": time.time(), "payload": payload}
    return payload


# ==================== 板块 API ====================

@app.get("/api/v1/sectors")
async def get_sectors():
    """获取行业/概念板块、资金流和新闻归因概览"""
    return sector_service.get_sector_overview()


@app.post("/api/v1/sectors/refresh")
async def refresh_sectors():
    """刷新行业/概念板块与资金流"""
    sector_service.refresh_sector_data()
    overview = sector_service.get_sector_overview()
    agent_workspace.record_event(
        "data",
        "sector_refresh",
        f"板块刷新完成：{overview.get('summary', {}).get('sector_count', 0)} 个，主力净流入 {overview.get('summary', {}).get('total_main_net_inflow', 0)}。",
    )
    return overview


@app.get("/api/v1/sectors/{code}")
async def get_sector_detail(code: str):
    """获取板块详情"""
    detail = sector_service.get_sector_full_detail(code)
    return detail


@app.post("/api/v1/sectors/{code}/news/mark")
async def mark_sector_news(
    code: str,
    title: str = Body(None, embed=True),
    news_key: str = Body(None, embed=True),
    level: str = Body(..., embed=True),
    sentiment: str = Body(None, embed=True),
):
    """手动标记板块新闻重要程度：normal / major / super_major。"""
    result = sector_service.mark_sector_news(code, title, level, sentiment, news_key)
    agent_workspace.record_event(
        "news",
        "sector_news_mark",
        f"板块新闻已标记：{code} {level}。",
        payload={"code": code, "title": title, "news_key": news_key, "level": level, "sentiment": sentiment, "result": result},
    )
    return result


# ==================== 交易偏好 API ====================

@app.get("/api/v1/quant/settings")
async def get_settings():
    """获取交易偏好设置"""
    return state_store.get_user_settings()


@app.post("/api/v1/quant/settings")
async def update_settings(updates: dict = Body(...)):
    """更新交易偏好设置"""
    state_store.update_user_settings(updates)
    return {"message": "设置已更新", "settings": state_store.get_user_settings()}


# ==================== 回测系统 API ====================

# ==================== AI 模型接口配置 API ====================

@app.get("/api/v1/ai/providers")
async def get_ai_providers():
    """获取主流 AI 供应商适配清单与当前本地配置。"""
    return ai_model_service.get_provider_catalog()


@app.get("/api/v1/ai/config")
async def get_ai_config():
    """获取当前 AI 模型配置，API Key 只返回脱敏状态。"""
    return ai_model_service.get_config_public()


@app.get("/api/v1/ai/strategy-memory")
async def get_ai_strategy_memory():
    """查看模型无关的站内策略记忆。"""
    return {
        "ok": True,
        "path": strategy_memory_service.MEMORY_PATH,
        "memory": strategy_memory_service.get_strategy_memory(),
    }


@app.post("/api/v1/ai/strategy-memory/notes")
async def append_ai_strategy_memory_note(payload: dict = Body(default=None)):
    """追加一条人工/复盘学习笔记，供后续模型继承。"""
    note = strategy_memory_service.append_learning_note(payload or {})
    return {"ok": True, "note": note, "memory": strategy_memory_service.get_strategy_memory()}


@app.post("/api/v1/ai/models/detect")
async def detect_ai_models(
    provider: str = Body("openai_compatible", embed=True),
    base_url: str = Body("", embed=True),
    api_key: str = Body("", embed=True),
    save: bool = Body(True, embed=True),
):
    """根据用户输入的 URL 和密钥检测可用模型列表。"""
    result = ai_model_service.detect_models(provider, base_url, api_key, save=save)
    agent_workspace.record_event(
        "decision",
        "ai_model_detect",
        f"AI 模型检测{'成功' if result.get('ok') else '失败'}：{result.get('provider', provider)}。",
        level="info" if result.get("ok") else "warn",
        payload={
            "provider": result.get("provider", provider),
            "base_url": result.get("base_url", base_url),
            "model_count": result.get("model_count", 0),
            "error": result.get("error", ""),
        },
    )
    return result


@app.post("/api/v1/ai/risk-verifier/models/detect")
async def detect_risk_verifier_models(
    provider: str = Body("openai_compatible", embed=True),
    base_url: str = Body("", embed=True),
    api_key: str = Body("", embed=True),
    save: bool = Body(True, embed=True),
):
    """检测并保存独立风控复核模型。"""
    result = ai_model_service.detect_risk_verifier_models(provider, base_url, api_key, save=save)
    agent_workspace.record_event(
        "risk",
        "risk_verifier_detect",
        "独立风控复核模型检测完成。" if result.get("ok") else f"独立风控复核模型检测失败：{result.get('error')}",
        level="info" if result.get("ok") else "warn",
        payload={"ok": result.get("ok"), "provider": result.get("provider"), "model_count": result.get("model_count")},
    )
    return result


@app.post("/api/v1/ai/config")
async def update_ai_connection_config(
    provider: str = Body("openai_compatible", embed=True),
    base_url: str = Body("", embed=True),
    api_key: str = Body("", embed=True),
):
    """保存 AI 供应商、接口地址和密钥；接口地址允许留空。"""
    return ai_model_service.update_connection_config(provider, base_url, api_key)


@app.post("/api/v1/ai/risk-verifier/config")
async def update_risk_verifier_config(
    provider: str = Body("openai_compatible", embed=True),
    base_url: str = Body("", embed=True),
    api_key: str = Body("", embed=True),
    selected_model: str = Body("", embed=True),
    enabled: bool = Body(None, embed=True),
):
    """保存独立风控复核模型配置。"""
    result = ai_model_service.update_risk_verifier_config(provider, base_url, api_key, selected_model, enabled)
    agent_workspace.record_event("risk", "risk_verifier_config", "独立风控复核模型配置已保存。", payload={"ok": result.get("ok")})
    return result


@app.post("/api/v1/ai/models/select")
async def select_ai_model(
    selected_model: str = Body(..., alias="model_id", embed=True),
    provider: str = Body(None, embed=True),
):
    """选择默认模型，后续评分、新闻理解、风控复核等接口统一读取此配置。"""
    result = ai_model_service.select_model(selected_model, provider)
    agent_workspace.record_event(
        "decision",
        "ai_model_select",
        f"默认 AI 模型已切换为 {selected_model}。" if result.get("ok") else "默认 AI 模型切换失败。",
        level="info" if result.get("ok") else "warn",
        payload={"model_id": selected_model, "provider": provider, "error": result.get("error", "")},
    )
    return result


@app.post("/api/v1/ai/risk-verifier/models/select")
async def select_risk_verifier_model(
    selected_model: str = Body(..., alias="model_id", embed=True),
    provider: str = Body(None, embed=True),
):
    """选择独立风控复核模型。"""
    result = ai_model_service.select_risk_verifier_model(selected_model, provider)
    agent_workspace.record_event("risk", "risk_verifier_select", "独立风控复核模型已选择。", payload={"ok": result.get("ok"), "model": selected_model})
    return result


@app.post("/api/v1/ai/policy")
async def update_ai_policy(updates: dict = Body(...)):
    """更新 AI 调用管理策略，例如超时、温度和风控复核要求。"""
    return ai_model_service.update_usage_policy(updates)


@app.post("/api/v1/ai/config/clear")
async def clear_ai_config():
    """清空本地 AI 配置与密钥。"""
    result = ai_model_service.clear_config()
    agent_workspace.record_event("decision", "ai_model_clear", "AI 模型本地配置已清空。")
    return result


@app.post("/api/v1/quant/backtest/run")
async def run_backtest(
    code: str = Body(..., embed=True),
    strategy_type: str = Body("short", alias="strategy", embed=True),
    short_window: int = Body(5, embed=True),
    long_window: int = Body(20, embed=True),
    days: int = Body(120, embed=True),
    news_window_days: int = Body(3, embed=True),
    announcement_window_days: int = Body(5, embed=True),
):
    """运行新闻、公告、情绪环境联合回测"""
    daily_df = state_store.get_daily_bars(code)
    if daily_df is None:
        daily_df = data_fetcher.fetch_kline(code, period=101, days=days)
    if daily_df is None or daily_df.empty:
        return {"error": f"无法获取{code}的K线数据"}

    stock_info = state_store.get_stock_info(code) or {}
    market_snapshot = news_service.get_market_sentiment()
    sentiment_snapshot = calc_sentiment_score(code)
    context_provider = build_context_provider(
        news=state_store.get_news(),
        stock_name=stock_info.get("name", ""),
        market_snapshot=market_snapshot,
        sentiment_snapshot=sentiment_snapshot,
        news_window_days=news_window_days,
        announcement_window_days=announcement_window_days,
    )
    strategy_func = create_context_ma_crossover_strategy(short_window, long_window)
    engine = BacktestEngine(initial_cash=200000.0)
    result = engine.run(daily_df, strategy_func, symbol=code, name=stock_info.get("name", ""), context_provider=context_provider)

    report = generate_backtest_report(result)
    report["strategy_type"] = strategy_type
    report["context_summary"] = result.get("context_summary", {})
    report["context_samples"] = result.get("context_samples", [])
    report["joint_context"] = {
        "enabled": True,
        "description": "新闻、公告、情绪环境与当时K线市场状态联合参与买入过滤、风险退出和仓位倍率。",
        "weights": {
            "news": 0.25,
            "announcement": 0.20,
            "sentiment_env": 0.20,
            "market_state": 0.35,
        },
        "news_window_days": news_window_days,
        "announcement_window_days": announcement_window_days,
    }
    return report


@app.get("/api/v1/quant/backtest/strategies")
async def get_backtest_strategies():
    """获取可用回测策略列表"""
    return {
        "strategies": [
            {"id": "short", "name": "短线猎人", "description": "MA5/MA20，偏资金流、盘口和短线K线确认"},
            {"id": "long", "name": "长线观察", "description": "MA20/MA60，偏事件质量、中期趋势和更宽止损止盈"},
            {"id": "event_driven", "name": "事件驱动", "description": "MA3/MA10，偏新闻公告影响因子、情绪同振和事件窗口风控"},
            {"id": "ma_5_20", "name": "MA5/MA20均线交叉", "description": "5日均线上穿20日均线买入，下穿卖出"},
            {"id": "ma_10_30", "name": "MA10/MA30均线交叉", "description": "10日均线上穿30日均线买入，下穿卖出"},
        ]
    }


# ==================== 评分系统 API ====================

@app.get("/api/v1/quant/score/{code}")
async def get_score_card(code: str, strategy: str = Query("short")):
    """获取股票评分卡（score_card.json）"""
    try:
        card = generate_score_card(code, strategy)
        agent_workspace.record_event("score", "score_card", f"{code} 评分卡已生成。", payload={"strategy": strategy, "final_score": card.get("final_score")})
        return _json_safe(card)
    except Exception as e:
        agent_workspace.record_event("score", "score_card_error", f"{code} 评分卡生成失败。", level="error", payload={"error": str(e)})
        return {"error": str(e), "symbol": code}


# ==================== 决策系统 API ====================

@app.get("/api/v1/quant/decision/{code}")
async def get_decision(code: str, strategy: str = Query("short")):
    """获取结构化交易建议（decision.json）"""
    try:
        decision = generate_decision(code, strategy)
        agent_workspace.record_event("decision", "decision", f"{code} 结构化决策已生成。", payload={"strategy": strategy, "direction": decision.get("direction")})
        return _json_safe(decision)
    except Exception as e:
        agent_workspace.record_event("decision", "decision_error", f"{code} 结构化决策生成失败。", level="error", payload={"error": str(e)})
        return {"error": str(e), "symbol": code}


@app.post("/api/v1/quant/risk-review/{code}")
async def run_risk_review(code: str, strategy: str = Body("short", embed=True)):
    """运行完整风控流水线（决策+风控复核）"""
    try:
        result = full_risk_pipeline(code, strategy)
        report = result.get("risk_report", {}) if isinstance(result, dict) else {}
        agent_workspace.record_event("risk", "risk_review", f"{code} 风控复核完成：{report.get('risk_level', 'unknown')}。", payload={"approved": report.get("approved"), "strategy": strategy})
        return _json_safe(result)
    except Exception as e:
        agent_workspace.record_event("risk", "risk_review_error", f"{code} 风控复核失败。", level="error", payload={"error": str(e)})
        return {"error": str(e), "symbol": code}


# ==================== 多模型验证 API ====================

@app.get("/api/v1/quant/multi-model/{code}")
async def get_multi_model_verify(code: str):
    """获取多模型交叉验证结果"""
    try:
        result = multi_model_verify(code)
        return result
    except Exception as e:
        return {"error": str(e), "symbol": code}


# ==================== 新闻评分 API ====================

@app.post("/api/v1/quant/news/score")
async def score_news_item(
    title: str = Body(..., embed=True),
    content: str = Body("", embed=True),
    source: str = Body("", embed=True),
):
    """对单条新闻进行评分"""
    return score_event(title, content, source)


@app.get("/api/v1/quant/news/event-score/{code}")
async def get_event_score(code: str):
    """获取股票相关事件评分"""
    return get_event_score_for_symbol(code)


# ==================== 情绪评分 API ====================

@app.get("/api/v1/quant/sentiment")
async def get_sentiment_score(code: str = Query(None)):
    """获取市场/个股情绪评分"""
    return calc_sentiment_score(code)


# ==================== 报告系统 API ====================

@app.get("/api/v1/quant/report/daily")
async def get_daily_report():
    """生成/获取今日日报"""
    try:
        report = generate_daily_report()
        return report
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/v1/quant/report/paper-trade")
async def get_paper_trade_log():
    """获取模拟交易记录"""
    logs = generate_paper_trade_log()
    return {"logs": logs, "csv_path": get_paper_trade_log_path(), "count": len(logs)}


@app.get("/api/v1/quant/report/weekly")
async def get_weekly_report():
    """生成/获取本周简报"""
    try:
        return generate_weekly_report()
    except Exception as e:
        return {"error": str(e)}


# ==================== Agent 工作台 API ====================

@app.get("/api/v1/quant/agents")
async def get_agent_workspace():
    """获取数据、新闻、评分、决策、风控、执行 Agent 状态与日志。"""
    return agent_workspace.get_workspace_state()


@app.post("/api/v1/quant/agents/snapshot")
async def snapshot_agent_workspace(reason: str = Body("manual", embed=True)):
    """写入各 Agent state.json，供后续 holaOS Harness 接管。"""
    agent_workspace.record_event("data", "snapshot", f"Agent 工作台快照已写入：{reason}。")
    return agent_workspace.snapshot_all(reason=reason)


@app.get("/api/v1/quant/agents/logs")
async def get_agent_logs(
    agent_id: str = Query(None),
    limit: int = Query(50, ge=1, le=300),
):
    """获取 Agent 事件日志。"""
    return agent_workspace.get_agent_logs(agent_id=agent_id, limit=limit)


# ==================== 熔断开关 API ====================

@app.post("/api/v1/quant/kill-switch/activate")
async def activate_kill(reason: str = Body("手动触发", embed=True)):
    """激活熔断开关"""
    result = activate_kill_switch(reason)
    agent_workspace.record_event("risk", "kill_switch_on", f"熔断已激活：{reason}。", level="warn")
    return result


@app.post("/api/v1/quant/kill-switch/deactivate")
async def deactivate_kill():
    """关闭熔断开关"""
    result = deactivate_kill_switch()
    agent_workspace.record_event("risk", "kill_switch_off", "熔断已解除。")
    return result


@app.get("/api/v1/quant/kill-switch/status")
async def get_kill_switch():
    """获取熔断开关状态"""
    return get_kill_switch_status()

