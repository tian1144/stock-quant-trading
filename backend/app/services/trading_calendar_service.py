"""
A-share trading calendar helpers.

The 2026 holiday ranges follow the official SSE/SZSE 2026 holiday notices. For
years without a configured holiday table, weekends are still treated as closed
and weekdays as tentative trading days.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


HOLIDAY_RANGES = {
    2026: [
        ("2026-01-01", "2026-01-04", "元旦休市"),
        ("2026-02-14", "2026-02-23", "春节休市"),
        ("2026-02-28", "2026-02-28", "周末休市"),
        ("2026-04-04", "2026-04-06", "清明节休市"),
        ("2026-05-01", "2026-05-05", "劳动节休市"),
        ("2026-05-09", "2026-05-09", "周末休市"),
        ("2026-06-19", "2026-06-21", "端午节休市"),
        ("2026-09-20", "2026-09-20", "周末休市"),
        ("2026-09-25", "2026-09-27", "中秋节休市"),
        ("2026-10-01", "2026-10-07", "国庆节休市"),
        ("2026-10-10", "2026-10-10", "周末休市"),
    ],
}


def _parse(value) -> date:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()[:10]
    return date.fromisoformat(text)


def _holiday_reason(day: date) -> str:
    for start, end, reason in HOLIDAY_RANGES.get(day.year, []):
        if _parse(start) <= day <= _parse(end):
            return reason
    return ""


def is_trading_day(value) -> bool:
    day = _parse(value)
    if day.weekday() >= 5:
        return False
    if _holiday_reason(day):
        return False
    return True


def trading_day_reason(value) -> str:
    day = _parse(value)
    reason = _holiday_reason(day)
    if reason:
        return reason
    if day.weekday() >= 5:
        return "周末休市"
    return "A股交易日"


def previous_trading_day(value, include_self: bool = True) -> date:
    day = _parse(value)
    if not include_self:
        day -= timedelta(days=1)
    for _ in range(370):
        if is_trading_day(day):
            return day
        day -= timedelta(days=1)
    raise ValueError("无法找到前一个交易日")


def next_trading_day(value, include_self: bool = True) -> date:
    day = _parse(value)
    if not include_self:
        day += timedelta(days=1)
    for _ in range(370):
        if is_trading_day(day):
            return day
        day += timedelta(days=1)
    raise ValueError("无法找到下一个交易日")


def normalize_trustee_end_date(value) -> dict:
    requested = _parse(value)
    final_day = previous_trading_day(requested, include_self=True)
    return {
        "requested_date": requested.isoformat(),
        "final_trading_day": final_day.isoformat(),
        "is_requested_trading_day": requested == final_day and is_trading_day(requested),
        "requested_reason": trading_day_reason(requested),
        "final_reason": trading_day_reason(final_day),
        "note": (
            "选择日期为交易日，AI将在该日封盘前清仓。"
            if requested == final_day and is_trading_day(requested)
            else f"选择日期不是交易日，AI将提前到 {final_day.isoformat()} 封盘前清仓。"
        ),
    }


def month_calendar(year: int, month: int) -> dict:
    first = date(int(year), int(month), 1)
    if month == 12:
        after = date(first.year + 1, 1, 1)
    else:
        after = date(first.year, first.month + 1, 1)
    start = first - timedelta(days=first.weekday())
    end = after + timedelta(days=(6 - (after - timedelta(days=1)).weekday()))
    rows = []
    day = start
    while day < end:
        rows.append({
            "date": day.isoformat(),
            "year": day.year,
            "month": day.month,
            "day": day.day,
            "in_month": day.month == first.month,
            "is_today": day == date.today(),
            "is_trading_day": is_trading_day(day),
            "reason": trading_day_reason(day),
            "normalized_end_date": normalize_trustee_end_date(day)["final_trading_day"],
            "weekday": day.weekday(),
        })
        day += timedelta(days=1)
    return {
        "year": first.year,
        "month": first.month,
        "days": rows,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "holiday_source": "SSE/SZSE 2026 holiday notices; weekends closed by rule",
    }
