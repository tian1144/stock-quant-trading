import argparse
import os
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services import data_fetcher, state_store  # noqa: E402


def _safe_code(path: Path) -> str:
    return "".join(ch for ch in path.stem if ch.isalnum())


def _aggregate_period(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    df["trade_date"] = df["date"]
    for col in ["open", "close", "high", "low", "volume", "amount", "amplitude", "pct_change", "change", "turnover_rate"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        else:
            df[col] = 0
    if df.empty:
        return df

    grouped = df.set_index("date").resample(freq)
    out = pd.DataFrame({
        "trade_date": grouped["trade_date"].last(),
        "open": grouped["open"].first(),
        "close": grouped["close"].last(),
        "high": grouped["high"].max(),
        "low": grouped["low"].min(),
        "volume": grouped["volume"].sum(),
        "amount": grouped["amount"].sum(),
    }).dropna(subset=["open", "close"])
    prev = out["close"].shift(1)
    open_base = out["open"].replace(0, pd.NA)
    prev_base = prev.replace(0, pd.NA)
    out["change"] = out["close"] - prev.fillna(out["open"])
    out["pct_change"] = (out["change"] / prev_base * 100).fillna((out["close"] - out["open"]) / open_base * 100).fillna(0)
    out["amplitude"] = ((out["high"] - out["low"]) / prev_base * 100).fillna((out["high"] - out["low"]) / open_base * 100).fillna(0)
    out["turnover_rate"] = 0
    out["source"] = "derived_from_verified_daily"
    out["validation_status"] = "derived"
    out["validated_sources"] = "period_101"
    out["validation_checked_at"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    out = out.reset_index()
    out["date"] = out["trade_date"].dt.strftime("%Y-%m-%d")
    out = out.drop(columns=["trade_date"])
    for col in ["open", "close", "high", "low", "change", "pct_change", "amplitude"]:
        out[col] = out[col].round(4)
    for col in ["volume", "amount"]:
        out[col] = out[col].round(2)
    return out[[
        "date", "open", "close", "high", "low", "volume", "amount", "amplitude",
        "pct_change", "change", "turnover_rate", "source", "validation_status",
        "validated_sources", "validation_checked_at",
    ]]


def fill_weekly_monthly() -> dict:
    root = Path(data_fetcher.KLINE_CACHE_DIR)
    daily_dir = root / "period_101"
    weekly_dir = root / "period_102"
    monthly_dir = root / "period_103"
    weekly_dir.mkdir(parents=True, exist_ok=True)
    monthly_dir.mkdir(parents=True, exist_ok=True)

    written_weekly = 0
    written_monthly = 0
    failed = 0
    for path in daily_dir.glob("*.csv"):
        try:
            df = pd.read_csv(path)
            if df.empty or "date" not in df.columns:
                continue
            weekly = _aggregate_period(df, "W-FRI")
            monthly = _aggregate_period(df, "ME")
            if not weekly.empty:
                weekly.to_csv(weekly_dir / path.name, index=False, encoding="utf-8-sig")
                written_weekly += 1
            if not monthly.empty:
                monthly.to_csv(monthly_dir / path.name, index=False, encoding="utf-8-sig")
                written_monthly += 1
        except Exception:
            failed += 1
    return {"weekly_written": written_weekly, "monthly_written": written_monthly, "failed": failed}


def fill_money_and_chips(limit: int = 0) -> dict:
    daily_dir = Path(data_fetcher.KLINE_CACHE_DIR) / "period_101"
    codes = [_safe_code(path) for path in daily_dir.glob("*.csv")]
    total = len(codes)
    money_done = 0
    chip_done = 0
    attempts = 0
    for code in codes:
        if limit and attempts >= limit:
            break
        money_path = Path(data_fetcher.MONEY_FLOW_CACHE_DIR) / f"{code}.json"
        chip_path = Path(data_fetcher.CHIP_CACHE_DIR) / f"{code}.json"
        needs_money = not money_path.exists()
        needs_chip = not chip_path.exists()
        if not needs_money and not needs_chip:
            continue
        attempts += 1
        if needs_money and data_fetcher.fetch_money_flow(code):
            money_done += 1
        if needs_chip:
            df = data_fetcher._read_kline_cache(code, 101, 1000)
            if df is not None and not df.empty:
                state_store.set_daily_bars(code, df)
            chips = data_fetcher.fetch_chip_distribution(code)
            if chips:
                chip_done += 1
        if attempts % 100 == 0:
            print({"attempts": attempts, "money_done": money_done, "chip_done": chip_done}, flush=True)
    return {"total_daily_codes": total, "attempts": attempts, "money_done": money_done, "chip_done": chip_done}


def fill_intraday(limit: int = 0) -> dict:
    daily_dir = Path(data_fetcher.KLINE_CACHE_DIR) / "period_101"
    codes = [_safe_code(path) for path in daily_dir.glob("*.csv")]
    total = len(codes)
    done = 0
    skipped = 0
    failed = 0
    attempts = 0
    for code in codes:
        cached = data_fetcher.read_intraday_cache(code)
        if data_fetcher.intraday_minutes_valid(cached):
            skipped += 1
            continue
        if limit and attempts >= limit:
            break
        attempts += 1
        minutes = data_fetcher.fetch_intraday_minutes(code, allow_fallback=False)
        if data_fetcher.intraday_minutes_valid(minutes):
            done += 1
        else:
            failed += 1
        if attempts % 100 == 0:
            print({"intraday_attempts": attempts, "intraday_done": done, "intraday_failed": failed, "intraday_skipped": skipped}, flush=True)
    return {"total_daily_codes": total, "attempts": attempts, "done": done, "failed": failed, "skipped": skipped}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip-periods", action="store_true")
    parser.add_argument("--skip-money-chips", action="store_true")
    parser.add_argument("--include-intraday", action="store_true")
    parser.add_argument("--intraday-only", action="store_true")
    args = parser.parse_args()
    if args.intraday_only:
        print({"intraday": fill_intraday(limit=args.limit)}, flush=True)
        return
    if not args.skip_periods:
        print({"periods": fill_weekly_monthly()}, flush=True)
    if args.include_intraday:
        print({"intraday": fill_intraday(limit=args.limit)}, flush=True)
    if not args.skip_money_chips:
        print({"money_chips": fill_money_and_chips(limit=args.limit)}, flush=True)


if __name__ == "__main__":
    main()
