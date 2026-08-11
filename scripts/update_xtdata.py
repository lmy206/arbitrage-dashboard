#!/usr/bin/env python
"""Fetch xtdata market data, cross-check it with AkShare, and rebuild the dashboard."""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHARED_ROOT = Path(os.environ.get("E_SHARED_DATA_ROOT", r"E:\data"))
MARKET_DIR = SHARED_ROOT / "market" / "futures_daily"
INDEX_DIR = SHARED_ROOT / "market" / "index_daily"
AKSHARE_DIR = SHARED_ROOT / "market" / "external" / "akshare"
REPORT_DIR = SHARED_ROOT / "reports"
CATALOG_PATH = SHARED_ROOT / "catalog.sqlite"
MANIFEST_PATH = SHARED_ROOT / "manifest.jsonl"
OUTPUT_PATH = PROJECT_ROOT / "app" / "data" / "arbitrage.json"
HISTORY_START = ""
SHANGHAI = ZoneInfo("Asia/Shanghai")
MONTHLY_LOOKBACK_DAYS = 90


SECTOR_BY_SUFFIX = {
    ".IF": "中金所期货",
    ".SF": "上期所期货",
    ".DF": "大商所期货",
    ".ZF": "郑商所期货",
    ".GF": "广期所期货",
}


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


INDEXES: dict[str, dict[str, str]] = {
    "000300.SH": {"name": "沪深300", "ak_symbol": "sh000300"},
    "000905.SH": {"name": "中证500", "ak_symbol": "sh000905"},
    "000852.SH": {"name": "中证1000", "ak_symbol": "sh000852"},
    "000688.SH": {"name": "科创50", "ak_symbol": "sh000688"},
    "000016.SH": {"name": "上证50", "ak_symbol": "sh000016"},
    "399006.SZ": {"name": "创业板指", "ak_symbol": "sz399006"},
}


AKSHARE_FUTURES: dict[str, dict[str, str]] = {
    "au00.SF": {"name": "黄金", "ak_symbol": "AU0"},
    "ag00.SF": {"name": "白银", "ak_symbol": "AG0"},
    "cu00.SF": {"name": "沪铜", "ak_symbol": "CU0"},
    "al00.SF": {"name": "沪铝", "ak_symbol": "AL0"},
    "rb00.SF": {"name": "螺纹钢", "ak_symbol": "RB0"},
    "hc00.SF": {"name": "热卷", "ak_symbol": "HC0"},
    "i00.DF": {"name": "铁矿石", "ak_symbol": "I0"},
    "j00.DF": {"name": "焦炭", "ak_symbol": "J0"},
    "jm00.DF": {"name": "焦煤", "ak_symbol": "JM0"},
    "a00.DF": {"name": "豆一", "ak_symbol": "A0"},
    "b00.DF": {"name": "豆二", "ak_symbol": "B0"},
    "m00.DF": {"name": "豆粕", "ak_symbol": "M0"},
    "y00.DF": {"name": "豆油", "ak_symbol": "Y0"},
    "p00.DF": {"name": "棕榈油", "ak_symbol": "P0"},
    "SA00.ZF": {"name": "纯碱", "ak_symbol": "SA0"},
    "FG00.ZF": {"name": "玻璃", "ak_symbol": "FG0"},
    "OI00.ZF": {"name": "菜油", "ak_symbol": "OI0"},
    "RM00.ZF": {"name": "菜粕", "ak_symbol": "RM0"},
}


AKSHARE_SERIES: dict[str, dict[str, str]] = {
    **{symbol: {**spec, "asset_type": "商品期货"} for symbol, spec in AKSHARE_FUTURES.items()},
    **{symbol: {**spec, "asset_type": "现货指数"} for symbol, spec in INDEXES.items()},
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
    {"pair": "豆粕菜粕差", "left": "m00.DF", "right": "RM00.ZF", "formula": spread, "kind": "spread"},
    {"pair": "纯碱玻璃差", "left": "SA00.ZF", "right": "FG00.ZF", "formula": spread, "kind": "spread"},
    {"pair": "豆棕价差", "left": "y00.DF", "right": "p00.DF", "formula": spread, "kind": "spread"},
    {
        "pair": "科创50/上证50",
        "left": "000688.SH",
        "right": "000016.SH",
        "formula": ratio,
        "kind": "ratio",
        "tradable": False,
    },
    {
        "pair": "创业板/沪深300",
        "left": "399006.SZ",
        "right": "000300.SH",
        "formula": ratio,
        "kind": "ratio",
        "tradable": False,
    },
]


HISTORY_CHART_PAIRS = [
    ("ic-if", "IC/IF比价"),
    ("im-if", "IM/IF比价"),
    ("star50-sse50", "科创50/上证50"),
    ("chinext-csi300", "创业板/沪深300"),
    ("im-ic-spread", "IM-IC价差"),
    ("meal-spread", "豆粕菜粕差"),
    ("soda-glass-spread", "纯碱玻璃差"),
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


def normalize_market_frame(frame: pd.DataFrame, include_volume: bool = False) -> pd.DataFrame:
    if frame.empty or "close" not in frame.columns:
        return pd.DataFrame(columns=["close", "volume"] if include_volume else ["close"])

    fields = ["close"]
    if include_volume and "volume" in frame.columns:
        fields.append("volume")
    result = frame[fields].copy().reset_index()
    time_col = result.columns[0]
    raw_time = result[time_col]
    if pd.api.types.is_numeric_dtype(raw_time):
        result["date"] = pd.to_datetime(raw_time, unit="ms", errors="coerce")
    else:
        result["date"] = pd.to_datetime(raw_time, errors="coerce")
    result["close"] = pd.to_numeric(result["close"], errors="coerce")
    if include_volume:
        if "volume" not in result.columns:
            result["volume"] = 0
        result["volume"] = pd.to_numeric(result["volume"], errors="coerce").fillna(0)
    result = result.dropna(subset=["date", "close"])
    result = result[result["close"] > 0]
    result["date"] = result["date"].dt.normalize()
    result = result.drop_duplicates(subset=["date"], keep="last").set_index("date").sort_index()
    return result[["close", "volume"]] if include_volume else result[["close"]]


def update_catalog(
    symbol: str,
    frame: pd.DataFrame,
    csv_path: Path,
    updated_at: str,
    *,
    source: str = "xtdata",
    dataset_type: str = "futures",
) -> None:
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
            VALUES (?, ?, ?, '1d', ?, ?, ?, ?, 'ok', ?)
            ON CONFLICT(dataset_key) DO UPDATE SET
              path=excluded.path,
              start_date=excluded.start_date,
              end_date=excluded.end_date,
              row_count=excluded.row_count,
              status=excluded.status,
              updated_at=excluded.updated_at
            """,
            (
                f"{source}:{dataset_type}:{symbol}:1d",
                source,
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


def normalize_expiry(code: str, asof: pd.Timestamp) -> str | None:
    if len(code) == 4:
        year = 2000 + int(code[:2])
        month = int(code[2:])
    elif len(code) == 3:
        year = (asof.year // 10) * 10 + int(code[0])
        if year < asof.year - 1:
            year += 10
        month = int(code[1:])
    else:
        return None
    if not 1 <= month <= 12:
        return None
    return f"{year % 100:02d}{month:02d}"


def discover_monthly_contracts(xtdata, asof: pd.Timestamp) -> dict[str, dict[str, str]]:
    contracts: dict[str, dict[str, str]] = {}
    sector_cache: dict[str, list[str]] = {}
    current_expiry = asof.strftime("%y%m")

    for continuous_symbol in CONTRACTS:
        stem, suffix_code = continuous_symbol.split(".", maxsplit=1)
        suffix = f".{suffix_code}"
        root = stem[:-2]
        sector = SECTOR_BY_SUFFIX[suffix]
        if sector not in sector_cache:
            sector_cache[sector] = xtdata.get_stock_list_in_sector(sector) or []

        pattern = re.compile(rf"^{re.escape(root)}(\d{{3,4}}){re.escape(suffix)}$", re.IGNORECASE)
        by_expiry: dict[str, str] = {}
        for symbol in sector_cache[sector]:
            match = pattern.match(symbol)
            if not match:
                continue
            expiry = normalize_expiry(match.group(1), asof)
            if expiry and expiry >= current_expiry:
                by_expiry[expiry] = symbol
        contracts[continuous_symbol] = by_expiry
    return contracts


def fetch_history() -> tuple[dict[str, pd.Series], dict[str, pd.DataFrame], dict[str, dict[str, str]], int]:
    xtdata, port = connect_xtdata()
    symbols = [*CONTRACTS, *INDEXES]
    MARKET_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
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
        output_dir = INDEX_DIR if symbol in INDEXES else MARKET_DIR
        csv_path = output_dir / f"{symbol.replace('.', '_')}.csv"
        frame.reset_index().to_csv(csv_path, index=False, encoding="utf-8-sig")
        update_catalog(
            symbol,
            frame,
            csv_path,
            now,
            dataset_type="index" if symbol in INDEXES else "futures",
        )
        histories[symbol] = frame["close"].rename(symbol)

    if missing:
        raise RuntimeError(f"xtdata 未返回以下行情数据: {', '.join(missing)}")

    required_symbols = {
        symbol for definition in PAIRS for symbol in (definition["left"], definition["right"])
    }
    common_latest_date = min(histories[symbol].index.max() for symbol in required_symbols)
    monthly_contracts = discover_monthly_contracts(xtdata, common_latest_date)
    monthly_symbols = sorted(
        {
            symbol
            for definition in PAIRS
            if definition.get("tradable", True)
            for continuous_symbol in (definition["left"], definition["right"])
            for symbol in monthly_contracts[continuous_symbol].values()
        }
    )
    monthly_start = (common_latest_date - timedelta(days=MONTHLY_LOOKBACK_DAYS)).strftime("%Y%m%d")
    monthly_raw: dict[str, pd.DataFrame] = {}
    for offset in range(0, len(monthly_symbols), 50):
        batch = monthly_symbols[offset : offset + 50]
        xtdata.download_history_data2(
            batch,
            period="1d",
            start_time=monthly_start,
            end_time="",
            callback=None,
            incrementally=False,
        )
        monthly_raw.update(
            xtdata.get_market_data_ex(
                field_list=["close", "volume"],
                stock_list=batch,
                period="1d",
                start_time=monthly_start,
                end_time="",
                count=-1,
                fill_data=False,
            )
        )

    monthly_histories: dict[str, pd.DataFrame] = {}
    for symbol in monthly_symbols:
        frame = normalize_market_frame(monthly_raw.get(symbol, pd.DataFrame()), include_volume=True)
        if frame.empty:
            continue
        csv_path = MARKET_DIR / f"{symbol.replace('.', '_')}.csv"
        frame.reset_index().to_csv(csv_path, index=False, encoding="utf-8-sig")
        update_catalog(symbol, frame, csv_path, now)
        monthly_histories[symbol] = frame

    return histories, monthly_histories, monthly_contracts, port


def normalize_akshare_frame(frame: pd.DataFrame, asset_type: str) -> pd.DataFrame:
    date_column = "date" if "date" in frame.columns else "日期"
    close_column = "close" if "close" in frame.columns else "收盘价"
    volume_column = "volume" if "volume" in frame.columns else "成交量"
    if frame.empty or date_column not in frame.columns or close_column not in frame.columns:
        return pd.DataFrame(columns=["close", "volume"])

    fields = [date_column, close_column]
    if volume_column in frame.columns:
        fields.append(volume_column)
    result = frame[fields].copy().rename(columns={date_column: "date", close_column: "close"})
    if volume_column in result.columns:
        result = result.rename(columns={volume_column: "volume"})
    else:
        result["volume"] = 0
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["close"] = pd.to_numeric(result["close"], errors="coerce")
    result["volume"] = pd.to_numeric(result["volume"], errors="coerce").fillna(0)
    if asset_type == "现货指数":
        # AkShare 指数成交量以股计，xtdata 以手计；这里只校验收盘价，不比较成交量。
        result["volume"] = 0
    result = result.dropna(subset=["date", "close"])
    result = result[result["close"] > 0]
    result["date"] = result["date"].dt.normalize()
    return result.drop_duplicates(subset=["date"], keep="last").set_index("date").sort_index()


def load_cached_akshare_frame(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists():
        return pd.DataFrame(columns=["close", "volume"])
    cached = pd.read_csv(csv_path, encoding="utf-8-sig")
    if "date" not in cached.columns or "close" not in cached.columns:
        return pd.DataFrame(columns=["close", "volume"])
    cached["date"] = pd.to_datetime(cached["date"], errors="coerce")
    cached["close"] = pd.to_numeric(cached["close"], errors="coerce")
    if "volume" not in cached.columns:
        cached["volume"] = 0
    cached["volume"] = pd.to_numeric(cached["volume"], errors="coerce").fillna(0)
    cached = cached.dropna(subset=["date", "close"])
    return cached.set_index("date").sort_index()[["close", "volume"]]


def fetch_akshare_history() -> tuple[dict[str, pd.Series], dict[str, str], list[str]]:
    histories: dict[str, pd.Series] = {}
    states: dict[str, str] = {}
    errors: list[str] = []
    now = datetime.now(SHANGHAI).isoformat(timespec="seconds")

    try:
        import akshare as ak
    except Exception as exc:
        ak = None
        errors.append(f"AkShare 导入失败: {exc}")

    for xt_symbol, spec in AKSHARE_SERIES.items():
        api_name = "stock_zh_index_daily" if spec["asset_type"] == "现货指数" else "futures_main_sina"
        output_dir = AKSHARE_DIR / api_name
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / f"{spec['ak_symbol']}.csv"
        frame = pd.DataFrame(columns=["close", "volume"])
        state = "missing"

        if ak is not None:
            try:
                if api_name == "stock_zh_index_daily":
                    raw = ak.stock_zh_index_daily(symbol=spec["ak_symbol"])
                else:
                    raw = ak.futures_main_sina(symbol=spec["ak_symbol"])
                frame = normalize_akshare_frame(raw, spec["asset_type"])
                if frame.empty:
                    raise RuntimeError("返回空数据")
                temporary_path = csv_path.with_suffix(".tmp")
                frame.reset_index().to_csv(temporary_path, index=False, encoding="utf-8-sig")
                temporary_path.replace(csv_path)
                update_catalog(
                    spec["ak_symbol"],
                    frame,
                    csv_path,
                    now,
                    source="akshare",
                    dataset_type="index" if spec["asset_type"] == "现货指数" else "futures",
                )
                state = "live"
            except Exception as exc:
                errors.append(f"{spec['ak_symbol']}: {exc}")

        if frame.empty:
            frame = load_cached_akshare_frame(csv_path)
            if not frame.empty:
                state = "cache"

        states[xt_symbol] = state
        if not frame.empty:
            histories[xt_symbol] = frame["close"].rename(xt_symbol)

    return histories, states, errors


def build_source_validation(
    xt_histories: dict[str, pd.Series],
    ak_histories: dict[str, pd.Series],
    ak_states: dict[str, str],
    data_date: pd.Timestamp,
    monthly_histories: dict[str, pd.DataFrame],
    monthly_contracts: dict[str, dict[str, str]],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for xt_symbol, spec in AKSHARE_SERIES.items():
        xt_series = xt_histories.get(xt_symbol)
        ak_series = ak_histories.get(xt_symbol)
        check: dict[str, Any] = {
            "name": spec["name"],
            "assetType": spec["asset_type"],
            "xtSymbol": xt_symbol,
            "akSymbol": spec["ak_symbol"],
            "date": data_date.strftime("%Y-%m-%d"),
            "xtClose": None,
            "akClose": None,
            "relativeDiffPct": None,
            "status": "AkShare缺失",
            "akMode": ak_states.get(xt_symbol, "missing"),
            "matchedContract": None,
            "matchedContractClose": None,
            "xtStartDate": xt_series.index.min().strftime("%Y-%m-%d") if xt_series is not None else None,
            "xtEndDate": xt_series.index.max().strftime("%Y-%m-%d") if xt_series is not None else None,
            "xtRows": len(xt_series) if xt_series is not None else 0,
            "akStartDate": ak_series.index.min().strftime("%Y-%m-%d") if ak_series is not None else None,
            "akEndDate": ak_series.index.max().strftime("%Y-%m-%d") if ak_series is not None else None,
            "akRows": len(ak_series) if ak_series is not None else 0,
        }
        if xt_series is None or data_date not in xt_series.index:
            check["status"] = "xtdata缺失"
        elif ak_series is None or data_date not in ak_series.index:
            check["xtClose"] = round(float(xt_series.loc[data_date]), 6)
            check["status"] = "日期不齐" if ak_series is not None else "AkShare缺失"
        else:
            xt_close = float(xt_series.loc[data_date])
            ak_close = float(ak_series.loc[data_date])
            relative_diff = abs(xt_close - ak_close) / max(abs(xt_close), 1) * 100
            check.update(
                {
                    "xtClose": round(xt_close, 6),
                    "akClose": round(ak_close, 6),
                    "relativeDiffPct": round(relative_diff, 4),
                    "status": "一致" if relative_diff <= 0.05 else "需复核",
                }
            )
            if check["status"] == "需复核" and xt_symbol in monthly_contracts:
                candidates: list[tuple[float, str, float]] = []
                for monthly_symbol in monthly_contracts[xt_symbol].values():
                    monthly_frame = monthly_histories.get(monthly_symbol)
                    if monthly_frame is None or data_date not in monthly_frame.index:
                        continue
                    monthly_close = float(monthly_frame.loc[data_date, "close"])
                    monthly_diff = abs(monthly_close - ak_close) / max(abs(ak_close), 1) * 100
                    candidates.append((monthly_diff, monthly_symbol, monthly_close))
                if candidates:
                    best_diff, matched_symbol, matched_close = min(candidates)
                    if best_diff <= 0.05:
                        check.update(
                            {
                                "status": "主力口径不同",
                                "matchedContract": matched_symbol,
                                "matchedContractClose": round(matched_close, 6),
                            }
                        )
        checks.append(check)

    status_priority = {"需复核": 0, "主力口径不同": 1, "日期不齐": 2, "AkShare缺失": 3, "xtdata缺失": 4, "一致": 5}
    checks.sort(key=lambda check: (status_priority.get(check["status"], 9), check["assetType"], check["name"]))
    consistent = sum(check["status"] == "一致" for check in checks)
    contract_mismatch = sum(check["status"] == "主力口径不同" for check in checks)
    review = sum(check["status"] == "需复核" for check in checks)
    unavailable = len(checks) - consistent - contract_mismatch - review
    comparable_differences = [
        check["relativeDiffPct"] for check in checks if check["relativeDiffPct"] is not None
    ]
    return {
        "policy": "xtdata为展示主源；AkShare仅补充与校验，不做均值混算",
        "thresholdPct": 0.05,
        "summary": {
            "status": (
                "通过"
                if consistent == len(checks)
                else ("有异常" if review else ("主力口径差异" if contract_mismatch else "待补齐"))
            ),
            "total": len(checks),
            "consistent": consistent,
            "contractMismatch": contract_mismatch,
            "review": review,
            "unavailable": unavailable,
            "coveragePct": round((consistent + contract_mismatch + review) / len(checks) * 100, 2),
            "maxRelativeDiffPct": round(max(comparable_differences), 4) if comparable_differences else None,
        },
        "checks": checks,
    }


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
    left_margin = left_notional * left_contract["margin_rate"]
    right_margin = right_notional * right_contract["margin_rate"]
    if left.endswith(".IF") and right.endswith(".IF"):
        margin = max(left_margin, right_margin)
    else:
        margin = left_margin + right_margin
    return (
        f"{left_lots}:{right_lots}",
        f"{deviation:.2f}%",
        f"{total_notional / 10000:.0f}万",
        f"{margin / 10000:.1f}万",
    )


def build_contract_rows(
    definition: dict[str, Any],
    monthly_histories: dict[str, pd.DataFrame],
    monthly_contracts: dict[str, dict[str, str]],
    common_latest_date: pd.Timestamp,
) -> list[dict[str, Any]]:
    if not definition.get("tradable", True):
        return []
    left_months = monthly_contracts[definition["left"]]
    right_months = monthly_contracts[definition["right"]]
    formula: Callable[[pd.Series, pd.Series], pd.Series] = definition["formula"]
    results: list[dict[str, Any]] = []

    for expiry in sorted(set(left_months) & set(right_months)):
        left_symbol = left_months[expiry]
        right_symbol = right_months[expiry]
        if left_symbol not in monthly_histories or right_symbol not in monthly_histories:
            continue

        left_frame = monthly_histories[left_symbol].rename(
            columns={"close": "leftClose", "volume": "leftVolume"}
        )
        right_frame = monthly_histories[right_symbol].rename(
            columns={"close": "rightClose", "volume": "rightVolume"}
        )
        aligned = pd.concat([left_frame, right_frame], axis=1, join="inner").dropna()
        aligned = aligned[aligned.index <= common_latest_date]
        if aligned.empty or aligned.index[-1] != common_latest_date:
            continue

        latest = aligned.iloc[-1]
        left_volume = max(0, int(round(float(latest["leftVolume"]))))
        right_volume = max(0, int(round(float(latest["rightVolume"]))))
        paired_volume = min(left_volume, right_volume)
        if paired_volume <= 0:
            continue
        current_series = formula(aligned["leftClose"], aligned["rightClose"]).replace(
            [math.inf, -math.inf], pd.NA
        ).dropna()
        if current_series.empty:
            continue

        results.append(
            {
                "expiry": expiry,
                "current": display_number(float(current_series.iloc[-1]), definition["kind"]),
                "leftSymbol": left_symbol,
                "rightSymbol": right_symbol,
                "leftVolume": left_volume,
                "rightVolume": right_volume,
                "pairedVolume": paired_volume,
            }
        )

    results.sort(
        key=lambda item: (
            -item["pairedVolume"],
            -(item["leftVolume"] + item["rightVolume"]),
            item["expiry"],
        )
    )
    return results[:4]


def pair_source_status(definition: dict[str, Any], source_validation: dict[str, Any]) -> str:
    checks_by_symbol = {
        check["xtSymbol"]: check for check in source_validation["checks"]
    }
    checks = [
        checks_by_symbol[symbol]
        for symbol in (definition["left"], definition["right"])
        if symbol in checks_by_symbol
    ]
    if not checks:
        return "仅xtdata"
    if all(check["status"] == "一致" for check in checks):
        return "双源一致"
    if any(check["status"] == "需复核" for check in checks):
        return "需复核"
    if any(check["status"] == "主力口径不同" for check in checks):
        return "口径不同"
    return "待校验"


def build_rows(
    histories: dict[str, pd.Series],
    monthly_histories: dict[str, pd.DataFrame],
    monthly_contracts: dict[str, dict[str, str]],
    source_validation: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
    latest_dates: list[pd.Timestamp] = []
    required_symbols = {
        symbol for definition in PAIRS for symbol in (definition["left"], definition["right"])
    }
    common_latest_date = min(histories[symbol].index.max() for symbol in required_symbols)

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
        tradable = definition.get("tradable", True)
        if tradable:
            lots, deviation, notional, margin = balance_metrics(
                left,
                right,
                left_price,
                right_price,
                force_one_to_one=definition["kind"] == "spread",
            )
        else:
            lots = deviation = notional = margin = "—"

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
                "pairType": "期货套利" if tradable else "现货参考",
                "sourceStatus": pair_source_status(definition, source_validation),
                "contracts": build_contract_rows(
                    definition,
                    monthly_histories,
                    monthly_contracts,
                    common_latest_date,
                ),
            }
        )

    rows.sort(key=lambda item: item["percentile"], reverse=True)
    unique_latest_dates = sorted({value.strftime("%Y-%m-%d") for value in latest_dates})
    if len(unique_latest_dates) != 1:
        raise RuntimeError(f"套利组合最新交易日不一致: {', '.join(unique_latest_dates)}")
    data_date = unique_latest_dates[0]
    return rows, data_date


def build_history_charts(
    histories: dict[str, pd.Series],
    data_date: pd.Timestamp,
) -> list[dict[str, Any]]:
    definitions = {definition["pair"]: definition for definition in PAIRS}
    charts: list[dict[str, Any]] = []
    for chart_id, pair_name in HISTORY_CHART_PAIRS:
        definition = definitions[pair_name]
        left = definition["left"]
        right = definition["right"]
        aligned = pd.concat([histories[left], histories[right]], axis=1, join="inner").dropna()
        aligned = aligned[aligned.index <= data_date]
        formula: Callable[[pd.Series, pd.Series], pd.Series] = definition["formula"]
        values = formula(aligned[left], aligned[right]).replace([math.inf, -math.inf], pd.NA).dropna()
        if len(values) < 12:
            raise RuntimeError(f"{pair_name} 的历史图表数据不足 12 个观测值")

        monthly = values.groupby(values.index.to_period("M")).last().tail(60)
        points = [
            {"date": str(period), "value": round(float(value), 6)}
            for period, value in monthly.items()
        ]
        latest_date = values.index[-1]
        three_year = values[values.index >= latest_date - pd.DateOffset(years=3)]
        charts.append(
            {
                "id": chart_id,
                "pair": pair_name,
                "title": f"{pair_name}走势",
                "unit": "点差" if definition["kind"] == "spread" else "比值",
                "grain": "月末值",
                "source": "xtdata",
                "current": display_number(float(values.iloc[-1]), definition["kind"]),
                "percentile": percentile(three_year),
                "startDate": points[0]["date"],
                "endDate": points[-1]["date"],
                "points": points,
            }
        )
    return charts


def write_outputs(
    rows: list[dict[str, Any]],
    charts: list[dict[str, Any]],
    data_date: str,
    port: int,
    source_validation: dict[str, Any],
    akshare_errors: list[str],
) -> dict[str, Any]:
    now = datetime.now(SHANGHAI)
    payload = {
        "dataDate": data_date,
        "updatedAt": now.isoformat(timespec="seconds"),
        "source": "xtdata（主）+ AkShare（补充校验）",
        "sourceValidation": source_validation,
        "period": "1d",
        "contractMode": "期货主力连续(00)；现货指数收盘",
        "updateSchedule": "每日20:00 Asia/Shanghai",
        "rows": rows,
        "charts": charts,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    latest = pd.Timestamp(data_date).date()
    lag_days = (now.date() - latest).days
    tradable_rows = [row for row in rows if row["pairType"] == "期货套利"]
    contract_rows_complete = all(len(row["contracts"]) == 4 for row in tradable_rows)
    charts_complete = len(charts) == len(HISTORY_CHART_PAIRS) and all(len(chart["points"]) >= 12 for chart in charts)
    report = {
        "status": "ok" if lag_days <= 4 and len(rows) == len(PAIRS) and contract_rows_complete and charts_complete else "warning",
        "checkedAt": now.isoformat(timespec="seconds"),
        "dataDate": data_date,
        "calendarLagDays": lag_days,
        "pairCount": len(rows),
        "expectedPairCount": len(PAIRS),
        "percentilesInRange": all(0 <= row["percentile"] <= 100 for row in rows),
        "contractRowsAvailable": all(len(row["contracts"]) > 0 for row in tradable_rows),
        "contractRowsComplete": contract_rows_complete,
        "contractRowCounts": {row["pair"]: len(row["contracts"]) for row in rows},
        "chartCount": len(charts),
        "expectedChartCount": len(HISTORY_CHART_PAIRS),
        "chartsComplete": charts_complete,
        "sourceValidation": source_validation["summary"],
        "akshareErrors": akshare_errors,
        "futureDataDetected": latest > now.date(),
        "xtdataPort": port,
        "output": str(OUTPUT_PATH),
    }
    (REPORT_DIR / "arbitrage_dashboard_integrity.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (REPORT_DIR / "arbitrage_source_validation.json").write_text(
        json.dumps(source_validation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_manifest(
        {
            "dataset_key": "xtdata:arbitrage-dashboard:daily",
            "source": "xtdata+akshare",
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
        histories, monthly_histories, monthly_contracts, port = fetch_history()
        required_symbols = {
            symbol for definition in PAIRS for symbol in (definition["left"], definition["right"])
        }
        common_latest_date = min(histories[symbol].index.max() for symbol in required_symbols)
        ak_histories, ak_states, akshare_errors = fetch_akshare_history()
        source_validation = build_source_validation(
            histories,
            ak_histories,
            ak_states,
            common_latest_date,
            monthly_histories,
            monthly_contracts,
        )
        rows, data_date = build_rows(
            histories,
            monthly_histories,
            monthly_contracts,
            source_validation,
        )
        charts = build_history_charts(histories, pd.Timestamp(data_date))
        report = write_outputs(rows, charts, data_date, port, source_validation, akshare_errors)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "ok" else 2
    except Exception as error:
        record_failure(error)
        print(f"xtdata update failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
