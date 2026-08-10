#!/usr/bin/env python
"""Fetch daily continuous futures data from xtdata and rebuild dashboard data."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHARED_ROOT = Path(os.environ.get("E_SHARED_DATA_ROOT", r"E:\data"))
MARKET_DIR = SHARED_ROOT / "market" / "futures_daily"
REPORT_DIR = SHARED_ROOT / "reports"
CATALOG_PATH = SHARED_ROOT / "catalog.sqlite"
MANIFEST_PATH = SHARED_ROOT / "manifest.jsonl"
OUTPUT_PATH = PROJECT_ROOT / "app" / "data" / "arbitrage.json"
HISTORY_START = ""
SHANGHAI = ZoneInfo("Asia/Shanghai")


CONTRACTS: dict[str, dict[str, float]] = {
    "IC00.IF": {"multiplier": 200, "margin_rate": 0.14},
    "IM00.IF": {"multiplier": 200, "margin_rate": 0.14},
    "IF00.IF": {"multiplier": 300, "margin_rate": 0.12},
    "a00.DF": {"multiplier": 10, "margin_rate": 0.09},
    "b00.DF": {"multiplier": 10, "margin_rate": 0.09},
    "OI00.ZF": {"multiplier": 10, "margin_rate": 0.09},
    "RM00.ZF": {"multiplier": 10, "margin_rate": 0.09},
    "rb00.SF": {"multiplier": 10, "margin_rate": 0.09},
    "hc00.SF": {"multiplier": 10, "margin_rate": 0.09},
    "cu00.SF": {"multiplier": 5, "margin_rate": 0.10},
    "al00.SF": {"multiplier": 5, "margin_rate": 0.10},
    "p00.DF": {"multiplier": 10, "margin_rate": 0.09},
    "SA00.ZF": {"multiplier": 20, "margin_rate": 0.10},
    "FG00.ZF": {"multiplier": 20, "margin_rate": 0.10},
    "j00.DF": {"multiplier": 100, "margin_rate": 0.20},
    "jm00.DF": {"multiplier": 60, "margin_rate": 0.20},
    "m00.DF": {"multiplier": 10, "margin_rate": 0.09},
    "y00.DF": {"multiplier": 10, "margin_rate": 0.09},
    "i00.DF": {"multiplier": 100, "margin_rate": 0.15},
    "au00.SF": {"multiplier": 1000, "margin_rate": 0.12},
    "ag00.SF": {"multiplier": 15, "margin_rate": 0.13},
}


def ratio(left: pd.Series, right: pd.Series) -> pd.Series:
    return left / right


def spread(left: pd.Series, right: pd.Series) -> pd.Series:
    return left - right


def gold_silver(left: pd.Series, right: pd.Series) -> pd.Series:
    return left * 1000 / right


PAIRS: list[dict[str, Any]] = [
    {"pair": "IM-IC价差", "left": "IM00.IF", "right": "IC00.IF", "formula": spread, "kind": "spread"},
    {"pair": "豆一豆二比", "left": "a00.DF", "right": "b00.DF", "formula": ratio, "kind": "ratio"},
    {"pair": "菜油菜粕比", "left": "OI00.ZF", "right": "RM00.ZF", "formula": ratio, "kind": "ratio"},
    {"pair": "IC/IF比价", "left": "IC00.IF", "right": "IF00.IF", "formula": ratio, "kind": "ratio"},
    {"pair": "螺卷差", "left": "hc00.SF", "right": "rb00.SF", "formula": spread, "kind": "spread"},
    {"pair": "铜铝比", "left": "cu00.SF", "right": "al00.SF", "formula": ratio, "kind": "ratio"},
    {"pair": "棕榈油菜油比", "left": "p00.DF", "right": "OI00.ZF", "formula": ratio, "kind": "ratio"},
    {"pair": "IM/IF比价", "left": "IM00.IF", "right": "IF00.IF", "formula": ratio, "kind": "ratio"},
    {"pair": "纯碱玻璃比", "left": "SA00.ZF", "right": "FG00.ZF", "formula": ratio, "kind": "ratio"},
    {"pair": "焦炭焦煤比", "left": "j00.DF", "right": "jm00.DF", "formula": ratio, "kind": "ratio"},
    {"pair": "豆粕豆油比", "left": "m00.DF", "right": "y00.DF", "formula": ratio, "kind": "ratio"},
    {"pair": "豆油菜油比", "left": "y00.DF", "right": "OI00.ZF", "formula": ratio, "kind": "ratio"},
    {"pair": "螺矿比", "left": "rb00.SF", "right": "i00.DF", "formula": ratio, "kind": "ratio"},
    {"pair": "金银比", "left": "au00.SF", "right": "ag00.SF", "formula": gold_silver, "kind": "gold_silver"},
    {"pair": "豆粕价差", "left": "m00.DF", "right": "a00.DF", "formula": spread, "kind": "spread"},
]


def load_xt_token() -> str:
    token = os.environ.get("XTQUANT_TOKEN", "").strip()
    if token:
        return token

    config_dir = Path(os.environ.get("XTQUANT_CONFIG_DIR", r"E:\IM"))
    sys.path.insert(0, str(config_dir))
    try:
        from config import xt_token  # type: ignore
    except Exception as exc:
        raise RuntimeError("XTQUANT_TOKEN 未设置，且无法从 E:\\IM\\config.py 读取 xt_token") from exc
    finally:
        sys.path.pop(0)
    return str(xt_token)


def connect_xtdata():
    from xtquant import xtdata
    from xtquant import xtdatacenter as xtdc

    SHARED_ROOT.mkdir(parents=True, exist_ok=True)
    xtdc.set_token(load_xt_token())
    xtdc.set_data_home_dir(str(SHARED_ROOT))
    xtdc.init(start_local_service=False)
    port = xtdc.listen(port=(58610, 58660))[1]
    xtdata.enable_hello = False
    xtdata.connect(port=port)
    return xtdata, port


def normalize_market_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "close" not in frame.columns:
        return pd.DataFrame(columns=["close"])

    result = frame[["close"]].copy().reset_index()
    time_col = result.columns[0]
    raw_time = result[time_col]
    if pd.api.types.is_numeric_dtype(raw_time):
        result["date"] = pd.to_datetime(raw_time, unit="ms", errors="coerce")
    else:
        result["date"] = pd.to_datetime(raw_time, errors="coerce")
    result["close"] = pd.to_numeric(result["close"], errors="coerce")
    result = result.dropna(subset=["date", "close"])
    result = result[result["close"] > 0]
    result["date"] = result["date"].dt.normalize()
    result = result.drop_duplicates(subset=["date"], keep="last").set_index("date").sort_index()
    return result[["close"]]


def update_catalog(symbol: str, frame: pd.DataFrame, csv_path: Path, updated_at: str) -> None:
    with sqlite3.connect(CATALOG_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS datasets (
              dataset_key TEXT PRIMARY KEY,
              source TEXT NOT NULL,
              symbol TEXT NOT NULL,
              period TEXT NOT NULL,
              path TEXT NOT NULL,
              start_date TEXT,
              end_date TEXT,
              row_count INTEGER NOT NULL,
              status TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO datasets
              (dataset_key, source, symbol, period, path, start_date, end_date, row_count, status, updated_at)
            VALUES (?, 'xtdata', ?, '1d', ?, ?, ?, ?, 'ok', ?)
            ON CONFLICT(dataset_key) DO UPDATE SET
              path=excluded.path,
              start_date=excluded.start_date,
              end_date=excluded.end_date,
              row_count=excluded.row_count,
              status=excluded.status,
              updated_at=excluded.updated_at
            """,
            (
                f"xtdata:futures:{symbol}:1d",
                symbol,
                str(csv_path),
                frame.index.min().strftime("%Y-%m-%d"),
                frame.index.max().strftime("%Y-%m-%d"),
                len(frame),
                updated_at,
            ),
        )
        connection.commit()


def write_manifest(entry: dict[str, Any]) -> None:
    SHARED_ROOT.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def fetch_history() -> tuple[dict[str, pd.Series], int]:
    xtdata, port = connect_xtdata()
    symbols = list(CONTRACTS)
    MARKET_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(SHANGHAI).isoformat(timespec="seconds")

    xtdata.download_history_data2(
        symbols,
        period="1d",
        start_time=HISTORY_START,
        end_time="",
        callback=None,
        incrementally=False,
    )
    raw = xtdata.get_market_data_ex(
        field_list=["close"],
        stock_list=symbols,
        period="1d",
        start_time=HISTORY_START,
        end_time="",
        count=-1,
        fill_data=False,
    )

    histories: dict[str, pd.Series] = {}
    missing: list[str] = []
    for symbol in symbols:
        frame = normalize_market_frame(raw.get(symbol, pd.DataFrame()))
        if frame.empty:
            missing.append(symbol)
            continue
        csv_path = MARKET_DIR / f"{symbol.replace('.', '_')}.csv"
        frame.reset_index().to_csv(csv_path, index=False, encoding="utf-8-sig")
        update_catalog(symbol, frame, csv_path, now)
        histories[symbol] = frame["close"].rename(symbol)

    if missing:
        raise RuntimeError(f"xtdata 未返回以下合约数据: {', '.join(missing)}")
    return histories, port


def percentile(series: pd.Series) -> float:
    current = float(series.iloc[-1])
    return round(float((series <= current).mean() * 100), 2)


def display_number(value: float, kind: str) -> str:
    if kind == "spread":
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.2f}"
    return f"{value:.4f}"


def display_change(value: float, kind: str) -> str:
    decimals = 0 if kind == "spread" else (2 if abs(value) >= 10 else 4)
    return f"{value:+.{decimals}f}"


def signal_for(value: float) -> str:
    if value >= 75:
        return "偏高"
    if value <= 10:
        return "极度偏低"
    return "中性"


def balance_metrics(
    left: str,
    right: str,
    left_price: float,
    right_price: float,
    force_one_to_one: bool = False,
) -> tuple[str, str, str, str]:
    left_contract = CONTRACTS[left]
    right_contract = CONTRACTS[right]
    if force_one_to_one:
        left_lots, right_lots = 1, 1
    else:
        candidates: list[tuple[float, int, int, int, int]] = []
        for candidate_left in range(1, 21):
            for candidate_right in range(1, 21):
                candidate_left_notional = left_price * left_contract["multiplier"] * candidate_left
                candidate_right_notional = right_price * right_contract["multiplier"] * candidate_right
                candidate_average = (candidate_left_notional + candidate_right_notional) / 2
                candidate_deviation = abs(candidate_left_notional - candidate_right_notional) / candidate_average
                candidates.append(
                    (
                        candidate_deviation,
                        candidate_left + candidate_right,
                        max(candidate_left, candidate_right),
                        candidate_left,
                        candidate_right,
                    )
                )
        _, _, _, left_lots, right_lots = min(candidates)
    left_notional = left_price * left_contract["multiplier"] * left_lots
    right_notional = right_price * right_contract["multiplier"] * right_lots
    average = (left_notional + right_notional) / 2
    deviation = abs(left_notional - right_notional) / average * 100 if average else 0
    total_notional = left_notional + right_notional
    margin = (
        left_notional * left_contract["margin_rate"]
        + right_notional * right_contract["margin_rate"]
    )
    return (
        f"{left_lots}:{right_lots}",
        f"{deviation:.2f}%",
        f"{total_notional / 10000:.0f}万",
        f"{margin / 10000:.1f}万",
    )


def build_rows(histories: dict[str, pd.Series]) -> tuple[list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
    latest_dates: list[pd.Timestamp] = []
    common_latest_date = min(series.index.max() for series in histories.values())

    for definition in PAIRS:
        left = definition["left"]
        right = definition["right"]
        aligned = pd.concat([histories[left], histories[right]], axis=1, join="inner").dropna()
        aligned = aligned[aligned.index <= common_latest_date]
        formula: Callable[[pd.Series, pd.Series], pd.Series] = definition["formula"]
        values = formula(aligned[left], aligned[right]).replace([math.inf, -math.inf], pd.NA).dropna()
        if len(values) < 2:
            raise RuntimeError(f"{definition['pair']} 的有效共同交易日不足")

        current = float(values.iloc[-1])
        previous = float(values.iloc[-2])
        change = current - previous
        latest_date = values.index[-1]
        latest_dates.append(latest_date)
        three_year_start = latest_date - pd.DateOffset(years=3)
        three_year = values[values.index >= three_year_start]
        all_time_percentile = percentile(values)
        three_year_percentile = percentile(three_year)
        left_price = float(aligned.loc[latest_date, left])
        right_price = float(aligned.loc[latest_date, right])
        lots, deviation, notional, margin = balance_metrics(
            left,
            right,
            left_price,
            right_price,
            force_one_to_one=definition["kind"] == "spread",
        )

        rows.append(
            {
                "pair": definition["pair"],
                "current": display_number(current, definition["kind"]),
                "previous": display_number(previous, definition["kind"]),
                "change": display_change(change, definition["kind"]),
                "changeValue": round(change, 8),
                "allTime": f"{all_time_percentile:.2f}%",
                "percentile": three_year_percentile,
                "signal": signal_for(three_year_percentile),
                "lots": lots,
                "deviation": deviation,
                "notional": notional,
                "margin": margin,
                "leftSymbol": left,
                "rightSymbol": right,
            }
        )

    rows.sort(key=lambda item: item["percentile"], reverse=True)
    unique_latest_dates = sorted({value.strftime("%Y-%m-%d") for value in latest_dates})
    if len(unique_latest_dates) != 1:
        raise RuntimeError(f"套利组合最新交易日不一致: {', '.join(unique_latest_dates)}")
    data_date = unique_latest_dates[0]
    return rows, data_date


def write_outputs(rows: list[dict[str, Any]], data_date: str, port: int) -> dict[str, Any]:
    now = datetime.now(SHANGHAI)
    payload = {
        "dataDate": data_date,
        "updatedAt": now.isoformat(timespec="seconds"),
        "source": "xtdata",
        "period": "1d",
        "contractMode": "主力连续(00)",
        "updateSchedule": "每日20:00 Asia/Shanghai",
        "rows": rows,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    latest = pd.Timestamp(data_date).date()
    lag_days = (now.date() - latest).days
    report = {
        "status": "ok" if lag_days <= 4 and len(rows) == len(PAIRS) else "warning",
        "checkedAt": now.isoformat(timespec="seconds"),
        "dataDate": data_date,
        "calendarLagDays": lag_days,
        "pairCount": len(rows),
        "expectedPairCount": len(PAIRS),
        "percentilesInRange": all(0 <= row["percentile"] <= 100 for row in rows),
        "futureDataDetected": latest > now.date(),
        "xtdataPort": port,
        "output": str(OUTPUT_PATH),
    }
    (REPORT_DIR / "arbitrage_dashboard_integrity.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_manifest(
        {
            "dataset_key": "xtdata:arbitrage-dashboard:daily",
            "source": "xtdata",
            "status": report["status"],
            "data_date": data_date,
            "pair_count": len(rows),
            "output": str(OUTPUT_PATH),
            "updated_at": now.isoformat(timespec="seconds"),
        }
    )
    return report


def record_failure(error: Exception) -> None:
    now = datetime.now(SHANGHAI).isoformat(timespec="seconds")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "xtdata_unavailable",
        "checkedAt": now,
        "error": str(error),
        "lastGoodOutputPreserved": OUTPUT_PATH.exists(),
    }
    (REPORT_DIR / "arbitrage_dashboard_integrity.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_manifest(
        {
            "dataset_key": "xtdata:arbitrage-dashboard:daily",
            "source": "xtdata",
            "status": "xtdata_unavailable",
            "error": str(error),
            "updated_at": now,
        }
    )


def main() -> int:
    try:
        histories, port = fetch_history()
        rows, data_date = build_rows(histories)
        report = write_outputs(rows, data_date, port)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "ok" else 2
    except Exception as error:
        record_failure(error)
        print(f"xtdata update failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
