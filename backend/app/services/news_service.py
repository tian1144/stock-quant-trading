"""
新闻服务 - 抓取财经新闻、解析股票提及、检测负面舆情
"""
import json
import os
import re
from datetime import datetime, timedelta
from typing import Dict, List
from loguru import logger

from app.services import state_store, data_fetcher

# 负面关键词
NEGATIVE_KEYWORDS = [
    "暴雷", "爆雷", "ST", "*ST", "退市", "违规", "处罚", "亏损",
    "立案", "减持", "质押", "商誉减值", "财务造假", "信披违规",
    "被调查", "被处罚", "风险警示", "暂停上市", "终止上市",
    "重大违法", "欺诈", "内幕交易", "操纵市场", "债务违约",
    "业绩暴跌", "净利润下降", "营收下滑", "诉讼", "仲裁",
    "被冻结", "被查封", "资金链", "跑路", "失联",
]

# 正面关键词
POSITIVE_KEYWORDS = [
    "涨停", "大涨", "突破", "新高", "利好", "增持", "回购",
    "业绩增长", "净利润增长", "超预期", "中标", "签约",
    "战略合作", "收购", "重组", "获批", "政策支持",
    "北向资金", "机构买入", "龙头", "景气度", "高增长",
]

NEWS_CACHE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "news_cache"))
NEWS_ARCHIVE_PATH = os.path.join(NEWS_CACHE_DIR, "news_archive.json")
NEWS_RETENTION_DAYS = 14


def _ensure_news_cache_dir():
    os.makedirs(NEWS_CACHE_DIR, exist_ok=True)


def _parse_news_time(value: str | None) -> datetime:
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


def _news_key(item: dict) -> str:
    if item.get("dedupe_key"):
        return str(item.get("dedupe_key"))
    return data_fetcher._news_fingerprint(item)


def _prune_news(news: list, retention_days: int = NEWS_RETENTION_DAYS) -> list:
    cutoff = datetime.now() - timedelta(days=retention_days)
    rows = [item for item in news or [] if _parse_news_time(item.get("time")) >= cutoff]
    rows.sort(key=lambda item: _parse_news_time(item.get("time")), reverse=True)
    return rows


def load_news_archive() -> list:
    if not os.path.exists(NEWS_ARCHIVE_PATH):
        return []
    try:
        with open(NEWS_ARCHIVE_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        rows = _prune_news(payload.get("news", []) if isinstance(payload, dict) else payload)
        return rows
    except Exception as e:
        logger.warning(f"读取新闻缓存失败: {e}")
        return []


def write_news_archive(news: list, meta: dict | None = None):
    try:
        _ensure_news_cache_dir()
        rows = _prune_news(news)
        payload = {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "retention_days": NEWS_RETENTION_DAYS,
            "count": len(rows),
            "source_meta": meta or {},
            "news": rows,
        }
        with open(NEWS_ARCHIVE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"写入新闻缓存失败: {e}")


def merge_news_archive(fresh_news: list, meta: dict | None = None) -> tuple[list, dict]:
    archived = load_news_archive()
    merged: Dict[str, dict] = {}
    for item in [*(archived or []), *(fresh_news or [])]:
        if not item or not item.get("title"):
            continue
        key = _news_key(item)
        if not key:
            continue
        if key not in merged:
            normalized = item.copy()
            normalized["dedupe_key"] = key
            sources = normalized.get("duplicate_sources") or [normalized.get("source", "未知")]
            normalized["duplicate_sources"] = [s for s in sources if s]
            merged[key] = normalized
            continue
        existing = merged[key]
        sources = set(existing.get("duplicate_sources") or [existing.get("source", "未知")])
        for source in item.get("duplicate_sources") or [item.get("source", "未知")]:
            if source:
                sources.add(source)
        existing["duplicate_sources"] = sorted(sources)
        if item.get("content") and len(item.get("content", "")) > len(existing.get("content", "")):
            existing["content"] = item.get("content")
        if _parse_news_time(item.get("time")) > _parse_news_time(existing.get("time")):
            existing["time"] = item.get("time", existing.get("time", ""))

    rows = _prune_news(list(merged.values()))
    merged_meta = {
        **(meta or {}),
        "archive_retention_days": NEWS_RETENTION_DAYS,
        "archive_count": len(rows),
        "fresh_count": len(fresh_news or []),
        "archive_path": NEWS_ARCHIVE_PATH,
    }
    write_news_archive(rows, merged_meta)
    return rows, merged_meta


def ensure_news_loaded() -> list:
    news = state_store.get_news()
    if news:
        return news
    archived = load_news_archive()
    if archived:
        state_store.set_news(archived)
        meta = state_store.get_news_meta()
        state_store.set_news_meta({
            **meta,
            "archive_retention_days": NEWS_RETENTION_DAYS,
            "archive_count": len(archived),
            "archive_path": NEWS_ARCHIVE_PATH,
            "loaded_from_archive": True,
        })
    return archived


def fetch_and_parse_news(watchlist_codes: list = None) -> list:
    """获取并解析多源新闻。"""
    result = data_fetcher.fetch_news_multi_source(watchlist_codes=watchlist_codes)
    news = result.get("news", [])
    meta = result.get("meta", {})
    if not news:
        fallback = data_fetcher.fetch_news_cls() + data_fetcher.fetch_news_sina()
        news = data_fetcher.dedupe_news(fallback)
        meta = data_fetcher.build_news_source_meta(fallback, news)
    merged_news, merged_meta = merge_news_archive(news, meta)
    state_store.set_news(merged_news)
    state_store.set_news_meta(merged_meta)
    return merged_news


def extract_stock_mentions(news: list) -> Dict[str, list]:
    """从新闻中提取股票代码提及"""
    universe = state_store.get_stock_universe()
    mentions: Dict[str, list] = {}

    # 构建名称到代码的映射
    name_to_code = {}
    for code, info in universe.items():
        name = info.get("name", "")
        if name:
            name_to_code[name] = code

    for item in news:
        text = item.get("title", "") + " " + item.get("content", "")
        # 匹配6位数字代码
        codes_found = re.findall(r'\b(\d{6})\b', text)
        for c in codes_found:
            if c in universe:
                if c not in mentions:
                    mentions[c] = []
                mentions[c].append(item)
        # 匹配股票名称
        for name, code in name_to_code.items():
            if len(name) >= 2 and name in text:
                if code not in mentions:
                    mentions[code] = []
                mentions[code].append(item)

    return mentions


def detect_negative_news(codes: list = None) -> Dict[str, list]:
    """检测负面新闻，返回 {code: [negative_keywords_found]}"""
    news = ensure_news_loaded()
    if not news:
        return {}

    mentions = extract_stock_mentions(news)
    result: Dict[str, list] = {}

    check_codes = codes or list(mentions.keys())
    for code in check_codes:
        related_news = mentions.get(code, [])
        negative_found = []
        for item in related_news:
            text = item.get("title", "") + " " + item.get("content", "")
            for kw in NEGATIVE_KEYWORDS:
                if kw in text and kw not in negative_found:
                    negative_found.append(kw)
        if negative_found:
            result[code] = negative_found

    state_store.set_negative_news(result)
    return result


def get_market_sentiment() -> dict:
    """获取市场整体情绪"""
    news = ensure_news_loaded()
    northbound = state_store.get_northbound_flow()
    universe = state_store.get_stock_universe()

    # 统计正面/负面新闻数量
    positive_count = 0
    negative_count = 0
    for item in news:
        text = item.get("title", "") + " " + item.get("content", "")
        for kw in POSITIVE_KEYWORDS:
            if kw in text:
                positive_count += 1
                break
        for kw in NEGATIVE_KEYWORDS[:10]:  # 只检查前10个强负面词
            if kw in text:
                negative_count += 1
                break

    # 计算涨跌比
    up_count = sum(1 for s in universe.values() if s.get("pct_change", 0) > 0)
    down_count = sum(1 for s in universe.values() if s.get("pct_change", 0) < 0)
    total = up_count + down_count
    advance_ratio = up_count / total if total > 0 else 0.5

    # 北向资金方向
    nb_direction = 1 if northbound.get("total_net", 0) > 0 else (-1 if northbound.get("total_net", 0) < 0 else 0)

    # 综合情绪分 (-100 ~ 100)
    news_score = 0
    if positive_count + negative_count > 0:
        news_score = (positive_count - negative_count) / (positive_count + negative_count) * 30
    advance_score = (advance_ratio - 0.5) * 100
    nb_score = nb_direction * 20

    sentiment_score = news_score + advance_score + nb_score
    sentiment_score = max(-100, min(100, sentiment_score))

    if sentiment_score > 30:
        level = "乐观"
    elif sentiment_score > 0:
        level = "中性偏多"
    elif sentiment_score > -30:
        level = "中性偏空"
    else:
        level = "悲观"

    return {
        "sentiment_score": round(sentiment_score, 1),
        "level": level,
        "positive_news": positive_count,
        "negative_news": negative_count,
        "advance_ratio": round(advance_ratio * 100, 1),
        "northbound_net": northbound.get("total_net", 0),
        "source_meta": state_store.get_news_meta(),
    }


def refresh_news(watchlist_codes: list = None):
    """刷新新闻并更新状态"""
    logger.info("开始刷新新闻...")
    news = fetch_and_parse_news(watchlist_codes=watchlist_codes)
    if news:
        detect_negative_news()
        sentiment = get_market_sentiment()
        meta = state_store.get_news_meta()
        logger.info(
            f"新闻刷新完成: {len(news)}条, 来源={meta.get('source_count', 0)}个, "
            f"去重={meta.get('duplicate_count', 0)}条, 情绪={sentiment['level']}"
        )
    else:
        logger.warning("新闻获取失败")
    return news
