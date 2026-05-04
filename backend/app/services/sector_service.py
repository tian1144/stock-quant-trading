"""
板块服务：行业/概念板块、资金流、新闻归因与详情聚合。
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List

from loguru import logger

from app.services import data_fetcher, state_store


POSITIVE_KEYWORDS = [
    "利好", "上涨", "大涨", "涨停", "增长", "突破", "新高", "增持", "回购",
    "中标", "签约", "获批", "政策支持", "景气", "复苏", "扩产", "提价",
    "国产替代", "订单", "超预期", "龙头", "机构买入", "上调", "放量", "净流入",
    "补贴", "扶持", "试点", "推进", "加快", "落地", "并购", "重组", "降准",
    "降息", "免税", "减税", "出口增长", "需求回暖", "价格上涨", "供给收缩",
    "产业升级", "突破关键", "自主可控", "国产化", "首发", "创新高",
    "大涨价", "涨价", "供需紧张", "电算协同", "算电协同", "扩需求",
    "鸽派", "降息预期", "缓和", "停火", "谈判", "达成协议",
]
NEGATIVE_KEYWORDS = [
    "利空", "下跌", "大跌", "下滑", "亏损", "减持", "处罚", "调查", "风险",
    "预警", "退市", "违约", "诉讼", "禁令", "暂停", "产能过剩", "低于预期",
    "下调", "净流出", "暴跌", "闪崩", "爆雷", "问询", "立案", "制裁",
    "加税", "关税", "出口受限", "需求疲弱", "价格下跌", "库存高企", "停产",
    "裁员", "取消订单", "延期", "事故", "召回", "监管趋严", "禁售",
    "鹰派", "不降息", "推迟降息", "冲突升级", "局势升级", "袭击",
    "战争风险", "封锁海峡", "霍尔木兹", "断供", "出口管制",
]
MAJOR_KEYWORDS = [
    "国务院", "央行", "证监会", "发改委", "财政部", "商务部", "工信部",
    "降息", "降准", "关税", "制裁", "战争", "封锁", "重大", "首次",
    "突破", "暴跌", "涨停潮", "退市", "立案", "获批", "中标", "并购重组",
    "美联储", "特朗普", "伊朗", "霍尔木兹", "稀土", "电算协同",
]

SECTOR_KEYWORDS: Dict[str, List[str]] = {
    "人工智能": ["人工智能", "AI", "大模型", "算力", "智能体", "机器人", "AIGC"],
    "半导体": ["半导体", "芯片", "晶圆", "光刻", "封测", "存储", "先进制程"],
    "新能源": ["新能源", "光伏", "风电", "储能", "锂电", "电池", "充电桩"],
    "新能源汽车": ["新能源汽车", "汽车", "智能驾驶", "车企", "整车", "零部件"],
    "医药": ["医药", "创新药", "疫苗", "医疗", "器械", "CXO", "中药"],
    "白酒": ["白酒", "酿酒", "酒企", "茅台", "五粮液", "泸州老窖"],
    "券商": ["券商", "证券", "资本市场", "并购重组", "两融", "投行"],
    "银行": ["银行", "信贷", "息差", "存款", "贷款", "金融监管"],
    "房地产": ["房地产", "地产", "楼市", "房企", "保障房", "城中村"],
    "军工": ["军工", "国防", "航空", "航天", "导弹", "无人机"],
    "低空经济": ["低空经济", "eVTOL", "飞行汽车", "通航", "无人机"],
    "消费电子": ["消费电子", "手机", "苹果", "华为", "折叠屏", "MR", "AR"],
    "传媒": ["传媒", "游戏", "影视", "短剧", "出版", "广告"],
    "有色金属": ["有色", "铜", "铝", "黄金", "稀土", "锂矿", "钴", "镍"],
    "稀土": ["稀土", "氧化镨钕", "磁材", "永磁", "重稀土", "轻稀土"],
    "煤炭": ["煤炭", "煤价", "焦煤", "动力煤"],
    "电力": ["电力", "火电", "水电", "核电", "电网", "特高压"],
    "算力": ["算力", "数据中心", "智算", "液冷", "服务器", "IDC", "电算协同", "算电协同"],
    "农业": ["农业", "种业", "猪肉", "养殖", "粮食", "农产品"],
    "化工": ["化工", "化肥", "磷化工", "氟化工", "材料"],
}

POSITIVE_KEYWORDS = [
    "利好", "上涨", "大涨", "涨停", "增长", "突破", "新高", "增持", "回购",
    "中标", "签约", "获批", "政策支持", "景气", "复苏", "扩产", "提价",
    "国产替代", "订单", "超预期", "龙头", "机构买入", "上调", "放量", "净流入",
    "补贴", "扶持", "试点", "推进", "加快", "落地", "并购", "重组", "降准",
    "降息", "免税", "减税", "出口增长", "需求回暖", "价格上涨", "供给收缩",
    "产业升级", "突破关键", "自主可控", "国产化", "首发", "创新高",
    "涨价", "供需紧张", "电算协同", "算电协同", "扩需求",
    "鸽派", "降息预期", "缓和", "停火", "谈判", "达成协议",
]
NEGATIVE_KEYWORDS = [
    "利空", "下跌", "大跌", "下滑", "亏损", "减持", "处罚", "调查", "风险",
    "预警", "退市", "违约", "诉讼", "禁令", "暂停", "产能过剩", "低于预期",
    "下调", "净流出", "暴跌", "闪崩", "爆雷", "问询", "立案", "制裁",
    "加税", "关税", "出口受限", "需求疲弱", "价格下跌", "库存高企", "停产",
    "裁员", "取消订单", "延期", "事故", "召回", "监管趋严", "禁售",
    "鹰派", "不降息", "推迟降息", "冲突升级", "局势升级", "袭击",
    "战争风险", "封锁海峡", "霍尔木兹", "断供", "出口管制",
]
MAJOR_KEYWORDS = [
    "国务院", "央行", "证监会", "发改委", "财政部", "商务部", "工信部",
    "降息", "降准", "关税", "制裁", "战争", "封锁", "重大", "首次",
    "突破", "暴跌", "涨停潮", "退市", "立案", "获批", "中标", "并购重组",
    "美联储", "特朗普", "伊朗", "霍尔木兹", "稀土", "电算协同",
]

SECTOR_KEYWORDS: Dict[str, List[str]] = {
    "人工智能": ["人工智能", "AI", "大模型", "算力", "智能体", "机器人", "AIGC"],
    "半导体": ["半导体", "芯片", "晶圆", "光刻", "封测", "存储", "先进制程"],
    "新能源": ["新能源", "光伏", "风电", "储能", "锂电", "电池", "充电桩"],
    "新能源汽车": ["新能源汽车", "汽车", "智能驾驶", "车企", "整车", "零部件"],
    "医药": ["医药", "创新药", "疫苗", "医疗", "器械", "CXO", "中药"],
    "白酒": ["白酒", "酿酒", "酒企", "茅台", "五粮液", "泸州老窖"],
    "券商": ["券商", "证券", "资本市场", "并购重组", "两融", "投行"],
    "银行": ["银行", "信贷", "息差", "存款", "贷款", "金融监管"],
    "房地产": ["房地产", "地产", "楼市", "房企", "保障房", "城中村"],
    "军工": ["军工", "国防", "航空", "航天", "导弹", "无人机"],
    "低空经济": ["低空经济", "eVTOL", "飞行汽车", "通航", "无人机"],
    "消费电子": ["消费电子", "手机", "苹果", "华为", "折叠屏", "MR", "AR"],
    "传媒": ["传媒", "游戏", "影视", "短剧", "出版", "广告"],
    "有色金属": ["有色", "铜", "铝", "黄金", "稀土", "锂矿", "钴", "镍"],
    "稀土": ["稀土", "氧化镨钕", "磁材", "永磁", "重稀土", "轻稀土"],
    "煤炭": ["煤炭", "煤价", "焦煤", "动力煤"],
    "电力": ["电力", "火电", "水电", "核电", "电网", "特高压"],
    "算力": ["算力", "数据中心", "智算", "液冷", "服务器", "IDC", "电算协同", "算电协同"],
    "农业": ["农业", "种业", "猪肉", "养殖", "粮食", "农产品"],
    "化工": ["化工", "化肥", "磷化工", "氟化工", "材料"],
}

_flow_history: List[dict] = []
_sector_news_archive: Dict[str, list] = {}
_sector_detail_cache: Dict[str, dict] = {}
_sector_overview_cache: dict = {"updated_at": 0.0, "payload": None}
SECTOR_OVERVIEW_TTL = 12
SECTOR_CACHE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "sector_cache"))
SECTOR_NEWS_ARCHIVE_PATH = os.path.join(SECTOR_CACHE_DIR, "sector_news_archive.json")
SECTOR_NEWS_NORMAL_DAYS = 31
SECTOR_NEWS_IMPORTANT_DAYS = 62
_sector_cache_lock = threading.RLock()


def _sector_cache_path(name: str) -> str:
    safe_name = "".join(ch for ch in str(name) if ch.isalnum() or ch in ("_", "-", "."))
    return os.path.join(SECTOR_CACHE_DIR, f"{safe_name}.json")


def _write_sector_cache(name: str, payload):
    temp_path = None
    try:
        with _sector_cache_lock:
            os.makedirs(SECTOR_CACHE_DIR, exist_ok=True)
            path = _sector_cache_path(name)
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            fd, temp_path = tempfile.mkstemp(
                prefix=f".{os.path.basename(path)}.",
                suffix=".tmp",
                dir=SECTOR_CACHE_DIR,
                text=True,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            for attempt in range(5):
                try:
                    os.replace(temp_path, path)
                    temp_path = None
                    return
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.08 * (attempt + 1))
    except Exception as e:
        logger.warning(f"写入板块缓存失败 {name}: {e}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _read_sector_cache(name: str, default=None):
    path = _sector_cache_path(name)
    if not os.path.exists(path):
        return default
    try:
        with _sector_cache_lock:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"读取板块缓存失败 {name}: {e}")
        return default


def _parse_news_datetime(value: str | None) -> datetime:
    text = str(value or "").strip()
    now = datetime.now()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m-%d %H:%M", "%H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt.startswith("%m"):
                parsed = parsed.replace(year=now.year)
            elif fmt == "%H:%M":
                parsed = parsed.replace(year=now.year, month=now.month, day=now.day)
            return parsed
        except Exception:
            continue
    return now


def _archive_sector_news(sector_name: str, item: dict, *, persist: bool = True):
    if not sector_name or item.get("sentiment") not in ("positive", "negative"):
        return
    _load_sector_news_archive()
    bucket = _sector_news_archive.setdefault(sector_name, [])
    key = item.get("fingerprint") or item.get("dedupe_key") or data_fetcher._news_fingerprint(item) or item.get("title") or ""
    existing = next((x for x in bucket if key and (x.get("fingerprint") or x.get("dedupe_key") or x.get("title")) == key), None)
    payload = {
        **item,
        "fingerprint": key,
        "dedupe_key": item.get("dedupe_key") or key,
        "archive_level": item.get("archive_level") or "normal",
        "manual_marked": bool(item.get("manual_marked")),
        "archived_at": item.get("archived_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if existing:
        existing.update({k: v for k, v in payload.items() if v not in (None, "", [])})
    else:
        bucket.append(payload)
    _prune_sector_news_archive()
    if persist:
        _write_sector_news_archive()


def _sector_news_retention_days(item: dict) -> int:
    return SECTOR_NEWS_IMPORTANT_DAYS if item.get("archive_level") in ("major", "super_major") else SECTOR_NEWS_NORMAL_DAYS


def _prune_sector_news_archive():
    now = datetime.now()
    for sector_name, bucket in list(_sector_news_archive.items()):
        kept = []
        for item in bucket or []:
            age_days = (now - _parse_news_datetime(item.get("time"))).days
            if age_days <= _sector_news_retention_days(item):
                kept.append(item)
        kept.sort(key=lambda x: _parse_news_datetime(x.get("time")), reverse=True)
        _sector_news_archive[sector_name] = kept[:240]


def _load_sector_news_archive():
    if _sector_news_archive:
        return _sector_news_archive
    payload = _read_sector_cache("sector_news_archive", {})
    if not isinstance(payload, dict):
        logger.warning("板块新闻归档为空或已损坏，将使用空归档继续运行")
        payload = {}
    if isinstance(payload, dict):
        data = payload.get("items", payload)
        if isinstance(data, dict):
            _sector_news_archive.update(data)
            _prune_sector_news_archive()
    return _sector_news_archive


def _write_sector_news_archive():
    payload = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "normal_retention_days": SECTOR_NEWS_NORMAL_DAYS,
        "important_retention_days": SECTOR_NEWS_IMPORTANT_DAYS,
        "items": _sector_news_archive,
    }
    _write_sector_cache("sector_news_archive", payload)


def _sector_news_key(item: dict) -> str:
    return str(
        item.get("fingerprint")
        or item.get("dedupe_key")
        or data_fetcher._news_fingerprint(item)
        or item.get("title")
        or ""
    )


def _same_sector_news(item: dict, news_key: str | None = None, title: str | None = None) -> bool:
    item_key = _sector_news_key(item)
    return bool((news_key and item_key == news_key) or (title and item.get("title") == title))


def mark_sector_news(sector_code: str, title: str | None, level: str, sentiment: str | None = None, news_key: str | None = None) -> dict:
    sectors = state_store.get_sector_list() or refresh_sector_data()
    sector = next((s for s in sectors if s.get("code") == sector_code), {})
    sector_name = sector.get("name") or sector_code
    _load_sector_news_archive()
    bucket = _sector_news_archive.setdefault(sector_name, [])
    target = next((item for item in bucket if _same_sector_news(item, news_key, title)), None)
    if not target:
        current_bucket = build_sector_news_map(sectors).get(sector_name, {}).get("news", [])
        current = next((item for item in current_bucket if _same_sector_news(item, news_key, title)), None)
        if current:
            current = {**current}
            if sentiment in ("positive", "negative"):
                current["sentiment"] = sentiment
                current["impact_score"] = abs(_to_number(current.get("impact_score"), 1)) * (1 if sentiment == "positive" else -1)
            current["archive_level"] = level if level in ("normal", "major", "super_major") else "normal"
            current["manual_marked"] = True
            _archive_sector_news(sector_name, current)
            bucket = _sector_news_archive.setdefault(sector_name, [])
            target = next((item for item in bucket if _same_sector_news(item, news_key, title)), None)
    if not target:
        return {"ok": False, "message": "未找到这条板块新闻", "code": sector_code, "title": title, "news_key": news_key}
    level = level if level in ("normal", "major", "super_major") else "normal"
    target["archive_level"] = level
    target["manual_marked"] = True
    target["marked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    target["fingerprint"] = _sector_news_key(target)
    target["dedupe_key"] = target.get("dedupe_key") or target["fingerprint"]
    if sentiment in ("positive", "negative"):
        target["sentiment"] = sentiment
        target["impact_score"] = abs(_to_number(target.get("impact_score"), 1)) * (1 if sentiment == "positive" else -1)
    _prune_sector_news_archive()
    _write_sector_news_archive()
    _sector_detail_cache.pop(sector_code, None)
    _sector_overview_cache["updated_at"] = 0.0
    return {"ok": True, "code": sector_code, "sector_name": sector_name, "level": level, "retention_days": _sector_news_retention_days(target)}


def _to_number(value, default: float = 0) -> float:
    try:
        if value in (None, "", "-"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _merge_by_code(*groups: list) -> list:
    merged: Dict[str, dict] = {}
    for group in groups:
        for item in group or []:
            code = item.get("code")
            if not code:
                continue
            merged[code] = {**merged.get(code, {}), **item}
    return list(merged.values())


def _load_cached_sector_data() -> tuple[list, list]:
    cached_sectors = _read_sector_cache("sector_list", []) or []
    cached_flows = _read_sector_cache("sector_money_flow", []) or []
    if cached_sectors:
        state_store.set_sector_list(cached_sectors)
    if cached_flows:
        state_store.set_sector_money_flow(cached_flows)
        if not _flow_history:
            _snapshot_flow(cached_flows)
    return cached_sectors, cached_flows


def _snapshot_flow(flows: list):
    total = sum(_to_number(item.get("main_net_inflow")) for item in flows)
    top = sorted(flows, key=lambda x: abs(_to_number(x.get("main_net_inflow"))), reverse=True)[:10]
    _flow_history.append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M:%S"),
        "total_main_net_inflow": round(total, 2),
        "inflow_count": sum(1 for item in flows if _to_number(item.get("main_net_inflow")) > 0),
        "outflow_count": sum(1 for item in flows if _to_number(item.get("main_net_inflow")) < 0),
        "top": [
            {
                "code": item.get("code"),
                "name": item.get("name"),
                "main_net_inflow": _to_number(item.get("main_net_inflow")),
                "pct_change": _to_number(item.get("pct_change")),
            }
            for item in top
        ],
        "sectors": [
            {
                "code": item.get("code"),
                "name": item.get("name"),
                "main_net_inflow": _to_number(item.get("main_net_inflow")),
                "main_net_pct": _to_number(item.get("main_net_pct")),
                "pct_change": _to_number(item.get("pct_change")),
                "sector_type": item.get("sector_type", ""),
            }
            for item in flows
        ],
    })
    del _flow_history[:-120]


def get_sector_flow_momentum() -> Dict[str, dict]:
    """按最近两次快照计算板块主力资金增量，用于盘中秒级异动捕捉。"""
    if not _flow_history:
        return {}
    latest = _flow_history[-1]
    prev = _flow_history[-2] if len(_flow_history) >= 2 else {"sectors": []}
    prev_map = {item.get("code"): item for item in prev.get("sectors", []) if item.get("code")}
    has_prev = len(_flow_history) >= 2
    result: Dict[str, dict] = {}
    for item in latest.get("sectors", []):
        code = item.get("code")
        if not code:
            continue
        prev_item = prev_map.get(code, {})
        main_net = _to_number(item.get("main_net_inflow"))
        prev_main = _to_number(prev_item.get("main_net_inflow"))
        delta = main_net - prev_main if has_prev else 0
        result[code] = {
            **item,
            "main_net_delta": round(delta, 2),
            "delta_direction": "accelerating" if delta > 0 else ("cooling" if delta < 0 else "flat"),
            "snapshot_count": len(_flow_history),
        }
    return result


def refresh_sector_data():
    """刷新行业+概念板块与资金流。"""
    try:
        logger.info("[板块] 刷新行业/概念板块数据...")
        sectors = _merge_by_code(
            data_fetcher.fetch_sector_list("industry"),
            data_fetcher.fetch_sector_list("concept"),
        )
        flows = _merge_by_code(
            data_fetcher.fetch_sector_money_flow("industry"),
            data_fetcher.fetch_sector_money_flow("concept"),
        )
        if not sectors:
            cached_sectors, cached_flows = _load_cached_sector_data()
            if cached_sectors:
                logger.warning("[板块] 外部板块接口返回空，已回退本地板块缓存。")
                return cached_sectors
        if sectors and not flows:
            _, cached_flows = _load_cached_sector_data()
            flows = cached_flows
        if sectors:
            state_store.set_sector_list(sectors)
            _write_sector_cache("sector_list", sectors)
        if flows:
            state_store.set_sector_money_flow(flows)
            _write_sector_cache("sector_money_flow", flows)
            _snapshot_flow(flows)
        _sector_detail_cache.clear()
        _sector_overview_cache["updated_at"] = 0.0
        logger.info(f"[板块] 获取到 {len(sectors)} 个板块，{len(flows)} 条资金流。")
        return sectors
    except Exception as e:
        logger.error(f"刷新板块数据失败: {e}")
        cached_sectors, cached_flows = _load_cached_sector_data()
        return cached_sectors or state_store.get_sector_list()


def classify_news_for_sectors(item: dict, sectors: list | None = None) -> dict:
    """给单条新闻打情绪与板块标签。"""
    text = f"{item.get('title', '')} {item.get('content', '')}"
    positive_hits = [kw for kw in POSITIVE_KEYWORDS if kw in text]
    negative_hits = [kw for kw in NEGATIVE_KEYWORDS if kw in text]
    major_hits = [kw for kw in MAJOR_KEYWORDS if kw in text]

    matched = []
    sector_pool = sectors or state_store.get_sector_list()
    for sector in sector_pool:
        name = sector.get("name", "")
        if name and name in text:
            matched.append(name)
    for sector_name, keywords in SECTOR_KEYWORDS.items():
        if any(keyword in text for keyword in keywords) and sector_name not in matched:
            matched.append(sector_name)

    positive_score = len(positive_hits)
    negative_score = len(negative_hits)
    # 有明确板块但没有强方向词时，政策推进、订单、价格、资金、产业链变化也应该给到轻微方向，
    # 只有纯资讯、无板块、无价格/政策/订单含义的内容才保持中性。
    if matched and not positive_score and any(word in text for word in ("计划", "发布", "建设", "投资", "合作", "采购", "扩建", "应用", "需求")):
        positive_score += 1
        positive_hits.append("板块相关推进")
    if matched and not negative_score and any(word in text for word in ("收紧", "限制", "检查", "整改", "停工", "延迟", "下架", "库存", "亏损")):
        negative_score += 1
        negative_hits.append("板块相关压力")

    if positive_score > negative_score:
        sentiment = "positive"
        score = 2 if major_hits or positive_score >= 2 else 1
    elif negative_score > positive_score:
        sentiment = "negative"
        score = -2 if major_hits or negative_score >= 2 else -1
    elif positive_score and negative_score:
        sentiment = "positive" if positive_score >= negative_score else "negative"
        score = 1 if sentiment == "positive" else -1
    else:
        sentiment = "neutral"
        score = 0

    return {
        "sentiment": sentiment,
        "impact_score": score,
        "sector_tags": matched[:8],
        "positive_keywords": positive_hits[:5],
        "negative_keywords": negative_hits[:5],
        "major_keywords": major_hits[:5],
    }


def build_sector_news_map(sectors: list | None = None) -> Dict[str, dict]:
    """把新闻按板块聚合，供列表和详情复用。"""
    sector_pool = sectors or state_store.get_sector_list()
    name_to_sector = {s.get("name"): s for s in sector_pool if s.get("name")}
    news = state_store.get_news()
    result: Dict[str, dict] = {
        name: {"news": [], "positive": 0, "negative": 0, "neutral": 0, "impact_score": 0}
        for name in name_to_sector
    }

    for item in news:
        tags = classify_news_for_sectors(item, sector_pool)
        enriched = {**item, **tags}
        for sector_name in tags["sector_tags"]:
            if sector_name not in result:
                result[sector_name] = {"news": [], "positive": 0, "negative": 0, "neutral": 0, "impact_score": 0}
            bucket = result[sector_name]
            bucket["news"].append(enriched)
            bucket[tags["sentiment"]] += 1
            bucket["impact_score"] += tags["impact_score"]
            _archive_sector_news(sector_name, enriched, persist=False)

    for bucket in result.values():
        bucket["news"] = bucket["news"][:50]
    _write_sector_news_archive()
    return result


def get_sector_rankings() -> list:
    """获取板块排名，合并资金流与新闻归因。"""
    sectors = state_store.get_sector_list()
    flows = state_store.get_sector_money_flow()
    if not sectors:
        cached_sectors, cached_flows = _load_cached_sector_data()
        sectors = cached_sectors
        flows = flows or cached_flows
    if not sectors or not flows:
        sectors = refresh_sector_data()
        flows = state_store.get_sector_money_flow()
    if sectors and not flows:
        _, flows = _load_cached_sector_data()

    flow_map = {f.get("code"): f for f in flows}
    momentum_map = get_sector_flow_momentum()
    news_map = build_sector_news_map(sectors)
    rows = []
    for sector in sectors:
        name = sector.get("name", "")
        flow = flow_map.get(sector.get("code"), {})
        news_bucket = news_map.get(name, {"news": [], "positive": 0, "negative": 0, "neutral": 0, "impact_score": 0})
        main_net = _to_number(flow.get("main_net_inflow"))
        momentum = momentum_map.get(sector.get("code"), {})
        rows.append({
            **sector,
            "main_net_inflow": main_net,
            "main_net_pct": _to_number(flow.get("main_net_pct")),
            "main_net_delta": _to_number(momentum.get("main_net_delta")),
            "delta_direction": momentum.get("delta_direction", "flat"),
            "super_large_inflow": _to_number(flow.get("super_large_inflow")),
            "large_inflow": _to_number(flow.get("large_inflow")),
            "medium_inflow": _to_number(flow.get("medium_inflow")),
            "small_inflow": _to_number(flow.get("small_inflow")),
            "news_count": len(news_bucket["news"]),
            "positive_news": news_bucket["positive"],
            "negative_news": news_bucket["negative"],
            "neutral_news": news_bucket["neutral"],
            "news_impact_score": news_bucket["impact_score"],
            "flow_direction": "inflow" if main_net > 0 else ("outflow" if main_net < 0 else "flat"),
        })
    return sorted(
        rows,
        key=lambda x: (
            _to_number(x.get("main_net_inflow")),
            _to_number(x.get("main_net_delta")),
            _to_number(x.get("pct_change")),
            _to_number(x.get("news_impact_score")),
        ),
        reverse=True,
    )


def get_sector_full_detail(sector_code: str) -> dict:
    """获取板块完整详情：成分股、资金流、新闻、龙头/热门股与行情概况。"""
    if sector_code in _sector_detail_cache:
        return {**_sector_detail_cache[sector_code], "cache_hit": True}

    sectors = state_store.get_sector_list()
    if not sectors:
        sectors = refresh_sector_data()
    sector = next((s for s in sectors if s.get("code") == sector_code), {})
    sector_name = sector.get("name", "")

    detail = state_store.get_sector_detail(sector_code) or _read_sector_cache(f"sector_detail_{sector_code}", {})
    stocks = (detail or {}).get("stocks") or data_fetcher.fetch_sector_detail(sector_code)
    if stocks:
        state_store.set_sector_detail(sector_code, {"stocks": stocks, "cached_at": datetime.now().isoformat(timespec="seconds")})
        _write_sector_cache(f"sector_detail_{sector_code}", {"stocks": stocks, "cached_at": datetime.now().isoformat(timespec="seconds")})
    sorted_stocks = sorted(stocks, key=lambda x: _to_number(x.get("pct_change")), reverse=True)
    hot_stocks = sorted_stocks[:10]
    leader = next((s for s in sorted_stocks if s.get("code") == sector.get("leader_code")), None) or (sorted_stocks[0] if sorted_stocks else {})

    flows = state_store.get_sector_money_flow()
    flow = next((f for f in flows if f.get("code") == sector_code), {})
    _load_sector_news_archive()
    news_bucket = build_sector_news_map(sectors).get(sector_name, {"news": [], "positive": 0, "negative": 0, "neutral": 0, "impact_score": 0})
    timeline = sorted(
        {item.get("title", ""): item for item in [*news_bucket.get("news", []), *_sector_news_archive.get(sector_name, [])] if item.get("title")}.values(),
        key=lambda item: _parse_news_datetime(item.get("time")),
        reverse=True,
    )[:120]
    up_count = sum(1 for s in stocks if _to_number(s.get("pct_change")) > 0)
    down_count = sum(1 for s in stocks if _to_number(s.get("pct_change")) < 0)

    payload = {
        "code": sector_code,
        "name": sector_name,
        "sector_type": sector.get("sector_type", ""),
        "summary": {
            "pct_change": _to_number(sector.get("pct_change")),
            "advance_count": sector.get("advance_count", up_count),
            "decline_count": sector.get("decline_count", down_count),
            "stock_count": len(stocks),
            "up_count": up_count,
            "down_count": down_count,
            "news_count": len(news_bucket["news"]),
        },
        "money_flow": {
            **flow,
            "main_net_inflow": _to_number(flow.get("main_net_inflow")),
            "main_net_pct": _to_number(flow.get("main_net_pct")),
            "super_large_inflow": _to_number(flow.get("super_large_inflow")),
            "large_inflow": _to_number(flow.get("large_inflow")),
            "medium_inflow": _to_number(flow.get("medium_inflow")),
            "small_inflow": _to_number(flow.get("small_inflow")),
        },
        "leader": leader,
        "hot_stocks": hot_stocks,
        "stocks": stocks,
        "news": news_bucket["news"],
        "news_timeline": timeline,
        "news_stats": {
            "positive": news_bucket["positive"],
            "negative": news_bucket["negative"],
            "neutral": news_bucket["neutral"],
            "impact_score": news_bucket["impact_score"],
        },
        "flow_history": _flow_history[-80:],
    }
    _sector_detail_cache[sector_code] = payload
    return payload


def get_sector_overview() -> dict:
    now_ts = datetime.now().timestamp()
    if (
        _sector_overview_cache.get("payload")
        and (_sector_overview_cache["payload"].get("sectors") or [])
        and now_ts - _sector_overview_cache.get("updated_at", 0) < SECTOR_OVERVIEW_TTL
    ):
        return {**_sector_overview_cache["payload"], "cache_hit": True}

    rankings = get_sector_rankings()
    total_inflow = sum(_to_number(item.get("main_net_inflow")) for item in rankings)
    inflow_count = sum(1 for item in rankings if _to_number(item.get("main_net_inflow")) > 0)
    outflow_count = sum(1 for item in rankings if _to_number(item.get("main_net_inflow")) < 0)
    hot_momentum = sorted(
        rankings,
        key=lambda item: (_to_number(item.get("main_net_delta")), _to_number(item.get("main_net_inflow"))),
        reverse=True,
    )
    payload = {
        "sectors": rankings,
        "flow_history": _flow_history[-80:],
        "summary": {
            "sector_count": len(rankings),
            "total_main_net_inflow": round(total_inflow, 2),
            "inflow_count": inflow_count,
            "outflow_count": outflow_count,
            "hot_sector": rankings[0] if rankings else {},
            "hot_momentum_sector": hot_momentum[0] if hot_momentum else {},
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        },
    }
    if rankings:
        _sector_overview_cache["updated_at"] = now_ts
        _sector_overview_cache["payload"] = payload
    return payload
