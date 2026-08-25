#!/usr/bin/env python
"""Fetch xtdata market data and rebuild the local dashboard."""

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
from io import StringIO

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHARED_ROOT = Path(os.environ.get("E_SHARED_DATA_ROOT", r"E:\data"))
MARKET_DIR = SHARED_ROOT / "market" / "futures_daily"
INDEX_DIR = SHARED_ROOT / "market" / "index_daily"
AKSHARE_DIR = SHARED_ROOT / "market" / "external" / "akshare"
LME_EXTERNAL_DIR = SHARED_ROOT / "market" / "external" / "lme_sina"
FX_EXTERNAL_DIR = SHARED_ROOT / "market" / "external" / "safe"
CSINDEX_EXTERNAL_DIR = SHARED_ROOT / "market" / "external" / "csindex"
CHINABOND_EXTERNAL_DIR = SHARED_ROOT / "market" / "external" / "chinabond"
EASTMONEY_EXTERNAL_DIR = SHARED_ROOT / "market" / "external" / "eastmoney"
MULTPL_EXTERNAL_DIR = SHARED_ROOT / "market" / "external" / "multpl"
SINA_INDEX_EXTERNAL_DIR = SHARED_ROOT / "market" / "external" / "sina_us_index"
SINA_FUTURES_EXTERNAL_DIR = SHARED_ROOT / "market" / "external" / "sina_foreign_futures"
REPORT_DIR = SHARED_ROOT / "reports"
CATALOG_PATH = SHARED_ROOT / "catalog.sqlite"
MANIFEST_PATH = SHARED_ROOT / "manifest.jsonl"
OUTPUT_PATH = PROJECT_ROOT / "app" / "data" / "arbitrage.json"
HISTORY_START = ""
SHANGHAI = ZoneInfo("Asia/Shanghai")
MONTHLY_LOOKBACK_DAYS = 1100
SEASONAL_CONTRACT_YEARS = 10
CONTRACT_HISTORY_MAX_SPAN_DAYS = 400
IM_TERM_START_DATE = pd.Timestamp("2022-07-22")
IM_TERM_SPOT_SYMBOL = "000852.SH"
USD_CNY_MID_SYMBOL = "USDCNY_MID.SAFE"
CNY_MYR_MID_SYMBOL = "CNYMYR_MID.SAFE"
CSI300_PE_SYMBOL = "CSI300_PE_TTM.CSINDEX"
CN10Y_SYMBOL = "CN10Y.CHINABOND"
US10Y_SYMBOL = "US10Y.EASTMONEY"
SP500_PE_SYMBOL = "SP500_PE.MULTPL"
NASDAQ_SYMBOL = "IXIC.SINA"
SP500_SYMBOL = "INX.SINA"
FCPO_SYMBOL = "FCPO.SINA"
EXTERNAL_HISTORY_START = "20160825"


class ExternalDataError(RuntimeError):
    """Raised when an approved external series cannot be refreshed or recovered."""


SECTOR_BY_SUFFIX = {
    ".IF": "中金所期货",
    ".SF": "上期所期货",
    ".INE": "能源中心期货",
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
    "zn00.SF": {"multiplier": 5, "margin_rate": 0.10},
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
    "fu00.SF": {"multiplier": 10, "margin_rate": 0.16},
    "bu00.SF": {"multiplier": 10, "margin_rate": 0.12},
    "nr00.INE": {"multiplier": 10, "margin_rate": 0.10},
    "br00.SF": {"multiplier": 5, "margin_rate": 0.12},
    "SH00.ZF": {"multiplier": 30, "margin_rate": 0.10},
    "ni00.SF": {"multiplier": 1, "margin_rate": 0.12},
    "ss00.SF": {"multiplier": 5, "margin_rate": 0.10},
    "l00.DF": {"multiplier": 5, "margin_rate": 0.11},
    "pp00.DF": {"multiplier": 5, "margin_rate": 0.11},
    "lh00.DF": {"multiplier": 16, "margin_rate": 0.08},
    "c00.DF": {"multiplier": 10, "margin_rate": 0.07},
}


def weighted_symbol(continuous_symbol: str) -> str:
    """Return xtdata's open-interest-weighted continuous symbol for a commodity."""
    stem, suffix = continuous_symbol.split(".", maxsplit=1)
    if suffix == "IF":
        return continuous_symbol
    if not stem.endswith("00"):
        raise ValueError(f"无法转换为加权合约代码: {continuous_symbol}")
    return f"{stem[:-2]}JQ00.{suffix}"


def main_continuous_symbol(symbol: str) -> str:
    """Map a JQ00 display series back to the corresponding 00 main-continuous series."""
    stem, suffix = symbol.split(".", maxsplit=1)
    if stem.endswith("JQ00"):
        return f"{stem[:-4]}00.{suffix}"
    return symbol


def is_weighted_symbol(symbol: str) -> bool:
    return symbol.split(".", maxsplit=1)[0].endswith("JQ00")


def is_equity_index_definition(definition: dict[str, Any]) -> bool:
    return any(
        symbol.endswith(".IF") or symbol in INDEXES
        for symbol in (definition["left"], definition["right"])
    )


WEIGHTED_CONTRACTS: dict[str, dict[str, float]] = {
    weighted_symbol(symbol): spec
    for symbol, spec in CONTRACTS.items()
    if not symbol.endswith(".IF")
}
FUTURES_SERIES: dict[str, dict[str, float]] = {**CONTRACTS, **WEIGHTED_CONTRACTS}


INDEXES: dict[str, dict[str, str]] = {
    "000300.SH": {"name": "沪深300", "ak_symbol": "sh000300"},
    "000905.SH": {"name": "中证500", "ak_symbol": "sh000905"},
    "000852.SH": {"name": "中证1000", "ak_symbol": "sh000852"},
    "000688.SH": {"name": "科创50", "ak_symbol": "sh000688"},
    "000016.SH": {"name": "上证50", "ak_symbol": "sh000016"},
    "399006.SZ": {"name": "创业板指", "ak_symbol": "sz399006"},
}

AGRICULTURAL_PRODUCT_ROOTS = {
    "a",
    "b",
    "c",
    "cf",
    "cj",
    "cs",
    "cy",
    "jd",
    "lh",
    "m",
    "oi",
    "p",
    "pk",
    "rm",
    "rr",
    "sr",
    "y",
}
STRATEGY_TYPE_ORDER = {"回归": 0, "趋势": 1, "内外盘": 2}
MARKET_CATEGORY_ORDER = {"股指": 0, "农产品": 1, "工业品": 2}
PINNED_PAIR_ORDER = {
    "沪深300风险溢价指数": 0,
    "标普500风险溢价指数": 1,
}


def symbol_product_root(symbol: str) -> str:
    stem = symbol.split(".", maxsplit=1)[0]
    for suffix in ("JQ00", "00"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return stem.lower()


def market_category_for_definition(definition: dict[str, Any]) -> str:
    if definition.get("market_category"):
        return str(definition["market_category"])
    if is_equity_index_definition(definition):
        return "股指"
    roots = {
        symbol_product_root(symbol)
        for symbol in (definition["left"], definition["right"])
    }
    if roots and roots <= AGRICULTURAL_PRODUCT_ROOTS:
        return "农产品"
    return "工业品"


def dashboard_row_sort_key(row: dict[str, Any]) -> tuple[int, int, int, float, str]:
    pair = row["pair"]
    if pair in PINNED_PAIR_ORDER:
        return (0, PINNED_PAIR_ORDER[pair], 0, 0.0, pair)
    return (
        1,
        STRATEGY_TYPE_ORDER.get(row["strategyType"], len(STRATEGY_TYPE_ORDER)),
        MARKET_CATEGORY_ORDER.get(row["marketCategory"], len(MARKET_CATEGORY_ORDER)),
        -float(row["percentile"]),
        pair,
    )


AKSHARE_FUTURES: dict[str, dict[str, str]] = {
    "au00.SF": {"name": "黄金", "ak_symbol": "AU0"},
    "ag00.SF": {"name": "白银", "ak_symbol": "AG0"},
    "cu00.SF": {"name": "沪铜", "ak_symbol": "CU0"},
    "al00.SF": {"name": "沪铝", "ak_symbol": "AL0"},
    "zn00.SF": {"name": "沪锌", "ak_symbol": "ZN0"},
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


OILSEED_CONTRACT_MONTHS = {1, 5, 9}


LME_CROSS_MARKET_PAIRS: list[dict[str, str]] = [
    {
        "pair": "铜内外盘比价",
        "left": "cu00.SF",
        "right": "CAD.LME",
        "lme_symbol": "CAD",
        "lme_name": "LME铜3个月",
        "strategy_type": "内外盘",
    },
    {
        "pair": "铝内外盘比价",
        "left": "al00.SF",
        "right": "AHD.LME",
        "lme_symbol": "AHD",
        "lme_name": "LME铝3个月",
        "strategy_type": "内外盘",
    },
    {
        "pair": "锌内外盘比价",
        "left": "zn00.SF",
        "right": "ZSD.LME",
        "lme_symbol": "ZSD",
        "lme_name": "LME锌3个月",
        "strategy_type": "内外盘",
    },
]

ADDITIONAL_EXTERNAL_PAIRS = {
    "沪深300风险溢价指数",
    "标普500风险溢价指数",
    "纳斯达克/标普500",
    "马盘棕榈油与豆油比价",
}


PAIRS: list[dict[str, Any]] = [
    {"pair": "IM-IC价差", "left": "IM00.IF", "right": "IC00.IF", "formula": spread, "kind": "spread"},
    {
        "pair": "IM期限套",
        "left": "IM00.IF",
        "right": "IM00.IF",
        "formula": ratio,
        "kind": "ratio",
        "custom_builder": "im_term",
    },
    {"pair": "豆一豆二比", "left": "aJQ00.DF", "right": "bJQ00.DF", "formula": ratio, "kind": "ratio"},
    {"pair": "IC/IF比价", "left": "IC00.IF", "right": "IF00.IF", "formula": ratio, "kind": "ratio"},
    {"pair": "卷螺价差", "left": "hcJQ00.SF", "right": "rbJQ00.SF", "formula": spread, "kind": "spread"},
    {"pair": "铜铝比", "left": "cuJQ00.SF", "right": "alJQ00.SF", "formula": ratio, "kind": "ratio"},
    *[
        {
            **definition,
            "formula": ratio,
            "kind": "ratio",
            "tradable": False,
            "custom_builder": "lme_cross_market",
        }
        for definition in LME_CROSS_MARKET_PAIRS
    ],
    {"pair": "棕榈油菜油比", "left": "pJQ00.DF", "right": "OIJQ00.ZF", "formula": ratio, "kind": "ratio", "contract_months": OILSEED_CONTRACT_MONTHS},
    {"pair": "IM/IF比价", "left": "IM00.IF", "right": "IF00.IF", "formula": ratio, "kind": "ratio"},
    {"pair": "纯碱玻璃比", "left": "SAJQ00.ZF", "right": "FGJQ00.ZF", "formula": ratio, "kind": "ratio"},
    {
        "pair": "焦炭焦煤比",
        "left": "jJQ00.DF",
        "right": "jmJQ00.DF",
        "formula": ratio,
        "kind": "ratio",
        "contract_months": {1, 5, 9},
    },
    {"pair": "油粕比", "left": "yJQ00.DF", "right": "mJQ00.DF", "formula": ratio, "kind": "ratio", "strategy_type": "趋势", "contract_months": OILSEED_CONTRACT_MONTHS},
    {"pair": "豆油菜油比", "left": "yJQ00.DF", "right": "OIJQ00.ZF", "formula": ratio, "kind": "ratio", "contract_months": OILSEED_CONTRACT_MONTHS},
    {
        "pair": "螺矿比",
        "left": "rbJQ00.SF",
        "right": "iJQ00.DF",
        "formula": ratio,
        "kind": "ratio",
        "contract_months": {1, 5, 9},
    },
    {"pair": "金银比", "left": "auJQ00.SF", "right": "agJQ00.SF", "formula": gold_silver, "kind": "gold_silver", "strategy_type": "趋势"},
    {"pair": "燃料油/沥青比价", "left": "fuJQ00.SF", "right": "buJQ00.SF", "formula": ratio, "kind": "ratio"},
    {"pair": "20号胶/BR橡胶比价", "left": "nrJQ00.INE", "right": "brJQ00.SF", "formula": ratio, "kind": "ratio"},
    {"pair": "烧碱/玻璃比价", "left": "SHJQ00.ZF", "right": "FGJQ00.ZF", "formula": ratio, "kind": "ratio"},
    {"pair": "镍/不锈钢比价", "left": "niJQ00.SF", "right": "ssJQ00.SF", "formula": ratio, "kind": "ratio"},
    {"pair": "玻璃/聚乙烯比价", "left": "FGJQ00.ZF", "right": "lJQ00.DF", "formula": ratio, "kind": "ratio"},
    {"pair": "玻璃/聚丙烯比价", "left": "FGJQ00.ZF", "right": "ppJQ00.DF", "formula": ratio, "kind": "ratio"},
    {"pair": "猪肉/玉米比价", "left": "lhJQ00.DF", "right": "cJQ00.DF", "formula": ratio, "kind": "ratio"},
    {"pair": "豆粕价差", "left": "mJQ00.DF", "right": "aJQ00.DF", "formula": spread, "kind": "spread", "contract_months": OILSEED_CONTRACT_MONTHS},
    {
        "pair": "蛋白质价差",
        "left": "mJQ00.DF",
        "right": "RMJQ00.ZF",
        "formula": spread,
        "kind": "spread",
        "contract_months": OILSEED_CONTRACT_MONTHS,
    },
    {"pair": "纯碱玻璃差", "left": "SAJQ00.ZF", "right": "FGJQ00.ZF", "formula": spread, "kind": "spread"},
    {"pair": "豆棕价差", "left": "yJQ00.DF", "right": "pJQ00.DF", "formula": spread, "kind": "spread", "contract_months": OILSEED_CONTRACT_MONTHS},
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
    {
        "pair": "沪深300风险溢价指数",
        "left": CSI300_PE_SYMBOL,
        "right": CN10Y_SYMBOL,
        "formula": spread,
        "kind": "percentage",
        "tradable": False,
        "custom_builder": "cn_equity_risk_premium",
        "strategy_type": "趋势",
        "market_category": "股指",
    },
    {
        "pair": "标普500风险溢价指数",
        "left": SP500_PE_SYMBOL,
        "right": US10Y_SYMBOL,
        "formula": spread,
        "kind": "percentage",
        "tradable": False,
        "custom_builder": "us_equity_risk_premium",
        "strategy_type": "趋势",
        "market_category": "股指",
    },
    {
        "pair": "纳斯达克/标普500",
        "left": NASDAQ_SYMBOL,
        "right": SP500_SYMBOL,
        "formula": ratio,
        "kind": "ratio",
        "tradable": False,
        "custom_builder": "external_ratio",
        "strategy_type": "趋势",
        "market_category": "股指",
    },
    {
        "pair": "马盘棕榈油与豆油比价",
        "left": FCPO_SYMBOL,
        "right": "yJQ00.DF",
        "formula": ratio,
        "kind": "ratio",
        "tradable": False,
        "custom_builder": "malaysia_palm_soy_ratio",
        "strategy_type": "内外盘",
        "market_category": "农产品",
    },
]


SPOT_OBSERVATIONS: dict[str, dict[str, str]] = {
    "IC/IF比价": {
        "left": "000905.SH",
        "right": "000300.SH",
        "label": "中证500/沪深300",
    },
    "IM/IF比价": {
        "left": "000852.SH",
        "right": "000300.SH",
        "label": "中证1000/沪深300",
    },
    "IM-IC价差": {
        "left": "000852.SH",
        "right": "000905.SH",
        "label": "中证1000-中证500",
    },
}


def definition_xt_symbols(definition: dict[str, Any]) -> tuple[str, ...]:
    """Return only the symbols that must be supplied by xtdata."""
    if definition.get("custom_builder") == "lme_cross_market":
        return (definition["left"],)
    if definition.get("custom_builder") == "malaysia_palm_soy_ratio":
        return (definition["right"],)
    if definition.get("custom_builder") in {
        "cn_equity_risk_premium",
        "us_equity_risk_premium",
        "external_ratio",
    }:
        return ()
    return (definition["left"], definition["right"])


HISTORY_CHARTS: list[dict[str, Any]] = [
    {"id": "im-ic-spread", "pair": "IM-IC价差", "left": "IM00.IF", "right": "IC00.IF", "formula": spread, "kind": "spread"},
    {"id": "ic-if", "pair": "IC/IF比价", "left": "IC00.IF", "right": "IF00.IF", "formula": ratio, "kind": "ratio"},
    {"id": "im-if", "pair": "IM/IF比价", "left": "IM00.IF", "right": "IF00.IF", "formula": ratio, "kind": "ratio"},
    {"id": "rebar-ore", "pair": "螺矿比", "left": "rbJQ00.SF", "right": "iJQ00.DF", "formula": ratio, "kind": "ratio"},
    {"id": "soy-oil-meal", "pair": "油粕比", "left": "yJQ00.DF", "right": "mJQ00.DF", "formula": ratio, "kind": "ratio"},
    {"id": "copper-aluminum", "pair": "铜铝比", "left": "cuJQ00.SF", "right": "alJQ00.SF", "formula": ratio, "kind": "ratio"},
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


def contract_symbol_for_expiry(continuous_symbol: str, expiry: str) -> str:
    normalized = main_continuous_symbol(continuous_symbol)
    stem, suffix_code = normalized.split(".", maxsplit=1)
    root = stem[:-2]
    if suffix_code == "ZF":
        contract_code = f"{int(expiry[:2]) % 10}{expiry[2:]}"
    else:
        contract_code = expiry
    return f"{root}{contract_code}.{suffix_code}"


def im_far_quarter_period(trading_date: pd.Timestamp, rank: int) -> pd.Period:
    """Return the first/second quarterly IM contract after the next month."""
    if rank not in (1, 2):
        raise ValueError(f"IM远季序号只支持1或2，收到: {rank}")
    period = trading_date.to_period("M") + 2
    while period.month not in {3, 6, 9, 12}:
        period += 1
    return period + (rank - 1) * 3


def im_down_quarter_period(trading_date: pd.Timestamp) -> pd.Period:
    return im_far_quarter_period(trading_date, 1)


def im_skip_quarter_period(trading_date: pd.Timestamp) -> pd.Period:
    return im_far_quarter_period(trading_date, 2)


def im_expiry_trade_date(
    contract_period: pd.Period,
    trading_calendar: pd.DatetimeIndex,
) -> pd.Timestamp:
    """Resolve the CFFEX monthly expiry from the published third-Friday rule."""
    month_start = contract_period.to_timestamp(how="start")
    first_friday_offset = (4 - month_start.weekday()) % 7
    third_friday = month_start + pd.Timedelta(days=first_friday_offset + 14)
    eligible = trading_calendar[trading_calendar >= third_friday]
    if len(eligible) == 0:
        raise RuntimeError(f"无法确定 IM{contract_period.strftime('%y%m')} 的到期交易日")
    return pd.Timestamp(eligible[0])


def im_near_contract_period(
    trading_date: pd.Timestamp,
    trading_calendar: pd.DatetimeIndex,
) -> pd.Period:
    """Use the current-month contract through expiry, then its next listed month."""
    current_period = trading_date.to_period("M")
    expiry_date = im_expiry_trade_date(current_period, trading_calendar)
    return current_period + 1 if trading_date > expiry_date else current_period


def seasonal_expiries(expiry: str) -> list[str]:
    delivery_year = int(expiry[:2])
    month = expiry[2:]
    return [
        f"{year % 100:02d}{month}"
        for year in range(delivery_year - SEASONAL_CONTRACT_YEARS + 1, delivery_year + 1)
    ]


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


def fetch_contract_histories(
    xtdata,
    symbols: list[str],
    start_time: str,
    end_time: str,
    updated_at: str,
) -> dict[str, pd.DataFrame]:
    raw: dict[str, pd.DataFrame] = {}
    for offset in range(0, len(symbols), 50):
        batch = symbols[offset : offset + 50]
        xtdata.download_history_data2(
            batch,
            period="1d",
            start_time=start_time,
            end_time=end_time,
            callback=None,
            incrementally=False,
        )
        raw.update(
            xtdata.get_market_data_ex(
                field_list=["close", "volume"],
                stock_list=batch,
                period="1d",
                start_time=start_time,
                end_time=end_time,
                count=-1,
                fill_data=False,
            )
        )

    histories: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        frame = normalize_market_frame(raw.get(symbol, pd.DataFrame()), include_volume=True)
        if frame.empty:
            continue
        csv_path = MARKET_DIR / f"{symbol.replace('.', '_')}.csv"
        frame.reset_index().to_csv(csv_path, index=False, encoding="utf-8-sig")
        update_catalog(symbol, frame, csv_path, updated_at)
        histories[symbol] = frame
    return histories


def fetch_history() -> tuple[
    dict[str, pd.Series],
    dict[str, pd.DataFrame],
    dict[str, dict[str, str]],
    pd.DatetimeIndex,
    int,
]:
    xtdata, port = connect_xtdata()
    symbols = [*FUTURES_SERIES, *INDEXES]
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
        symbol for definition in PAIRS for symbol in definition_xt_symbols(definition)
    }
    common_latest_date = min(histories[symbol].index.max() for symbol in required_symbols)
    calendar_end = common_latest_date.to_period("M").end_time.strftime("%Y%m%d")
    trading_calendar = pd.DatetimeIndex(
        pd.to_datetime(
            xtdata.get_trading_calendar(
                "SH",
                start_time=IM_TERM_START_DATE.strftime("%Y%m%d"),
                end_time=calendar_end,
            ),
            format="%Y%m%d",
        )
    ).sort_values()
    monthly_contracts = discover_monthly_contracts(xtdata, common_latest_date)
    monthly_symbols = sorted(
        {
            symbol
            for definition in PAIRS
            if definition.get("tradable", True)
            or definition.get("custom_builder") == "lme_cross_market"
            for continuous_symbol in definition_xt_symbols(definition)
            for symbol in monthly_contracts[main_continuous_symbol(continuous_symbol)].values()
        }
    )
    monthly_start = (common_latest_date - timedelta(days=MONTHLY_LOOKBACK_DAYS)).strftime("%Y%m%d")
    monthly_histories = fetch_contract_histories(
        xtdata,
        monthly_symbols,
        monthly_start,
        "",
        now,
    )

    archive_symbols: set[str] = set()
    for definition in PAIRS:
        if not definition.get("tradable", True) or is_equity_index_definition(definition):
            continue
        preview_contracts = build_contract_rows(
            definition,
            monthly_histories,
            monthly_contracts,
            common_latest_date,
            include_history_chart=False,
        )
        for contract in preview_contracts:
            for historical_expiry in seasonal_expiries(contract["expiry"]):
                archive_symbols.add(
                    contract_symbol_for_expiry(definition["left"], historical_expiry)
                )
                archive_symbols.add(
                    contract_symbol_for_expiry(definition["right"], historical_expiry)
                )

    # IM期限套需要按历史时点选择具体的当月、下季与隔季合约。这里一次性补齐
    # IM上市以来的月度合约，选择规则在后续计算中只依赖已知交易日历，
    # 不按未来成交量倒推主力合约。
    latest_term_period = im_skip_quarter_period(common_latest_date)
    for period in pd.period_range(
        IM_TERM_START_DATE.to_period("M"),
        latest_term_period,
        freq="M",
    ):
        archive_symbols.add(
            contract_symbol_for_expiry("IM00.IF", period.strftime("%y%m"))
        )

    archive_symbols.difference_update(monthly_histories)
    archive_start = (
        common_latest_date - pd.DateOffset(years=SEASONAL_CONTRACT_YEARS)
    ).strftime("%Y%m%d")
    archive_end = common_latest_date.strftime("%Y%m%d")
    monthly_histories.update(
        fetch_contract_histories(
            xtdata,
            sorted(archive_symbols),
            archive_start,
            archive_end,
            now,
        )
    )

    return histories, monthly_histories, monthly_contracts, trading_calendar, port


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


def normalize_safe_usdcny(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "日期" not in frame.columns or "美元" not in frame.columns:
        return pd.DataFrame(columns=["close", "volume"])
    result = frame[["日期", "美元"]].copy().rename(
        columns={"日期": "date", "美元": "close"}
    )
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    # SAFE quotes 100 USD in CNY; convert to CNY per USD.
    result["close"] = pd.to_numeric(result["close"], errors="coerce") / 100
    result["volume"] = 0
    result = result.dropna(subset=["date", "close"])
    result = result[result["close"].between(4, 10)]
    result["date"] = result["date"].dt.normalize()
    return (
        result.drop_duplicates(subset=["date"], keep="last")
        .set_index("date")
        .sort_index()
    )


def normalize_safe_cnymyr(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert SAFE's MYR per 100 CNY midpoint into CNY per MYR."""
    if frame.empty or "日期" not in frame.columns or "林吉特" not in frame.columns:
        return pd.DataFrame(columns=["close", "volume"])
    result = frame[["日期", "林吉特"]].copy().rename(
        columns={"日期": "date", "林吉特": "myr_per_100_cny"}
    )
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["myr_per_100_cny"] = pd.to_numeric(
        result["myr_per_100_cny"], errors="coerce"
    )
    result["close"] = 100 / result["myr_per_100_cny"]
    result["volume"] = 0
    result = result.dropna(subset=["date", "close"])
    result = result[result["close"].between(1, 3)]
    result["date"] = result["date"].dt.normalize()
    return (
        result[["date", "close", "volume"]]
        .drop_duplicates(subset=["date"], keep="last")
        .set_index("date")
        .sort_index()
    )


def normalize_value_frame(
    frame: pd.DataFrame,
    date_column: str,
    value_column: str,
) -> pd.DataFrame:
    if frame.empty or date_column not in frame.columns or value_column not in frame.columns:
        return pd.DataFrame(columns=["close", "volume"])
    result = frame[[date_column, value_column]].copy().rename(
        columns={date_column: "date", value_column: "close"}
    )
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["close"] = pd.to_numeric(result["close"], errors="coerce")
    result["volume"] = 0
    result = result.dropna(subset=["date", "close"])
    result = result[result["close"] > 0]
    result["date"] = result["date"].dt.normalize()
    return (
        result.drop_duplicates(subset=["date"], keep="last")
        .set_index("date")
        .sort_index()[["close", "volume"]]
    )


def fetch_chinabond_cn10y(ak: Any) -> pd.DataFrame:
    start = pd.Timestamp(EXTERNAL_HISTORY_START)
    end = pd.Timestamp.now(tz=SHANGHAI).tz_localize(None).normalize()
    frames: list[pd.DataFrame] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + pd.DateOffset(months=11, days=25), end)
        frames.append(
            ak.bond_china_yield(
                start_date=cursor.strftime("%Y%m%d"),
                end_date=chunk_end.strftime("%Y%m%d"),
            )
        )
        cursor = chunk_end + pd.Timedelta(days=1)
    raw = pd.concat(frames, ignore_index=True)
    raw = raw[raw["曲线名称"] == "中债国债收益率曲线"]
    return normalize_value_frame(raw, "日期", "10年")


def fetch_multpl_sp500_pe() -> pd.DataFrame:
    import requests

    response = requests.get(
        "https://www.multpl.com/s-p-500-pe-ratio/table/by-month",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=35,
    )
    response.raise_for_status()
    table = pd.read_html(StringIO(response.text))[0]
    date_column, value_column = table.columns[:2]
    table[value_column] = (
        table[value_column]
        .astype(str)
        .str.replace(r"[^0-9.\-]", "", regex=True)
    )
    return normalize_value_frame(table, str(date_column), str(value_column))


def fetch_bnm_cnymyr_latest() -> tuple[str, float] | None:
    """Return BNM's latest CNY/MYR cross-check as CNY per MYR."""
    import requests

    try:
        response = requests.get(
            "https://api.bnm.gov.my/public/exchange-rate",
            headers={
                "Accept": "application/vnd.BNM.API.v1+json",
                "User-Agent": "Mozilla/5.0",
            },
            timeout=20,
        )
        response.raise_for_status()
        item = next(
            entry
            for entry in response.json()["data"]
            if entry["currency_code"] == "CNY"
        )
        return item["rate"]["date"], 1 / float(item["rate"]["middle_rate"])
    except Exception:
        return None


def persist_external_frame(
    frame: pd.DataFrame,
    csv_path: Path,
    symbol: str,
    source: str,
    dataset_type: str,
    updated_at: str,
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = csv_path.with_suffix(".tmp")
    frame.reset_index().to_csv(temporary_path, index=False, encoding="utf-8-sig")
    temporary_path.replace(csv_path)
    update_catalog(
        symbol,
        frame,
        csv_path,
        updated_at,
        source=source,
        dataset_type=dataset_type,
    )


def fetch_external_market_history() -> tuple[
    dict[str, pd.Series],
    list[dict[str, Any]],
    list[str],
]:
    """Fetch all user-approved external series with cache fallback."""
    histories: dict[str, pd.Series] = {}
    metadata: list[dict[str, Any]] = []
    errors: list[str] = []
    now = datetime.now(SHANGHAI).isoformat(timespec="seconds")

    try:
        import akshare as ak
    except Exception as exc:
        ak = None
        errors.append(f"AkShare 导入失败: {exc}")

    safe_raw: pd.DataFrame | None = None
    us_rate_raw: pd.DataFrame | None = None

    def fetch_safe_raw() -> pd.DataFrame:
        nonlocal safe_raw
        if safe_raw is None:
            if ak is None:
                raise RuntimeError("AkShare 不可用")
            safe_raw = ak.currency_boc_safe()
        return safe_raw

    def fetch_us_rate_raw() -> pd.DataFrame:
        nonlocal us_rate_raw
        if us_rate_raw is None:
            if ak is None:
                raise RuntimeError("AkShare 不可用")
            us_rate_raw = ak.bond_zh_us_rate(start_date=EXTERNAL_HISTORY_START)
        return us_rate_raw

    specifications: list[dict[str, Any]] = [
        {
            "symbol": definition["lme_symbol"],
            "name": definition["lme_name"],
            "provider": "AKShare/新浪",
            "source": "akshare_sina",
            "dataset_type": "lme_3m",
            "path": LME_EXTERNAL_DIR / f"{definition['lme_symbol']}.csv",
            "fetch": (
                (lambda symbol=definition["lme_symbol"]: ak.futures_foreign_hist(symbol=symbol))
                if ak is not None
                else None
            ),
            "normalize": lambda raw: normalize_akshare_frame(raw, "外盘期货"),
            "maxLagDays": 5,
        }
        for definition in LME_CROSS_MARKET_PAIRS
    ]
    specifications.append(
        {
            "symbol": USD_CNY_MID_SYMBOL,
            "name": "美元兑人民币中间价",
            "provider": "AKShare/国家外汇管理局",
            "source": "akshare_safe",
            "dataset_type": "fx_midpoint_chart_overlay",
            "path": FX_EXTERNAL_DIR / "USDCNY_MID.csv",
            "fetch": fetch_safe_raw if ak is not None else None,
            "normalize": normalize_safe_usdcny,
            "maxLagDays": 5,
        }
    )
    specifications.extend(
        [
            {
                "symbol": CNY_MYR_MID_SYMBOL,
                "name": "人民币兑林吉特中间价",
                "provider": "AKShare/国家外汇管理局；BNM最新值校对",
                "source": "akshare_safe",
                "dataset_type": "fx_midpoint",
                "path": FX_EXTERNAL_DIR / "CNYMYR_MID.csv",
                "fetch": fetch_safe_raw if ak is not None else None,
                "normalize": normalize_safe_cnymyr,
                "maxLagDays": 5,
            },
            {
                "symbol": CSI300_PE_SYMBOL,
                "name": "沪深300滚动市盈率",
                "provider": "AKShare/中证指数有限公司",
                "source": "akshare_csindex",
                "dataset_type": "equity_valuation",
                "path": CSINDEX_EXTERNAL_DIR / "CSI300_PE_TTM.csv",
                "fetch": (
                    lambda: ak.stock_zh_index_hist_csindex(
                        symbol="000300",
                        start_date=EXTERNAL_HISTORY_START,
                        end_date=pd.Timestamp.now(tz=SHANGHAI).strftime("%Y%m%d"),
                    )
                ) if ak is not None else None,
                "normalize": lambda raw: normalize_value_frame(raw, "日期", "滚动市盈率"),
                "maxLagDays": 5,
            },
            {
                "symbol": CN10Y_SYMBOL,
                "name": "中国10年期国债收益率",
                "provider": "AKShare/中国债券信息网",
                "source": "akshare_chinabond",
                "dataset_type": "bond_yield",
                "path": CHINABOND_EXTERNAL_DIR / "CN10Y.csv",
                "fetch": (lambda: fetch_chinabond_cn10y(ak)) if ak is not None else None,
                "normalize": lambda raw: raw,
                "maxLagDays": 7,
            },
            {
                "symbol": US10Y_SYMBOL,
                "name": "美国10年期国债收益率",
                "provider": "AKShare/东方财富",
                "source": "akshare_eastmoney",
                "dataset_type": "bond_yield",
                "path": EASTMONEY_EXTERNAL_DIR / "US10Y.csv",
                "fetch": fetch_us_rate_raw if ak is not None else None,
                "normalize": lambda raw: normalize_value_frame(raw, "日期", "美国国债收益率10年"),
                "maxLagDays": 7,
            },
            {
                "symbol": SP500_PE_SYMBOL,
                "name": "标普500市盈率",
                "provider": "Multpl",
                "source": "multpl",
                "dataset_type": "equity_valuation",
                "path": MULTPL_EXTERNAL_DIR / "SP500_PE.csv",
                "fetch": fetch_multpl_sp500_pe,
                "normalize": lambda raw: raw,
                "maxLagDays": 45,
            },
            {
                "symbol": NASDAQ_SYMBOL,
                "name": "纳斯达克综合指数",
                "provider": "AKShare/新浪",
                "source": "akshare_sina",
                "dataset_type": "us_equity_index",
                "path": SINA_INDEX_EXTERNAL_DIR / "IXIC.csv",
                "fetch": (lambda: ak.index_us_stock_sina(symbol=".IXIC")) if ak is not None else None,
                "normalize": lambda raw: normalize_akshare_frame(raw, "现货指数"),
                "maxLagDays": 7,
            },
            {
                "symbol": SP500_SYMBOL,
                "name": "标普500指数",
                "provider": "AKShare/新浪",
                "source": "akshare_sina",
                "dataset_type": "us_equity_index",
                "path": SINA_INDEX_EXTERNAL_DIR / "INX.csv",
                "fetch": (lambda: ak.index_us_stock_sina(symbol=".INX")) if ak is not None else None,
                "normalize": lambda raw: normalize_akshare_frame(raw, "现货指数"),
                "maxLagDays": 7,
            },
            {
                "symbol": FCPO_SYMBOL,
                "name": "马来西亚棕榈油期货",
                "provider": "AKShare/新浪",
                "source": "akshare_sina",
                "dataset_type": "foreign_futures",
                "path": SINA_FUTURES_EXTERNAL_DIR / "FCPO.csv",
                "fetch": (lambda: ak.futures_foreign_hist(symbol="FCPO")) if ak is not None else None,
                "normalize": lambda raw: normalize_akshare_frame(raw, "外盘期货"),
                "maxLagDays": 7,
            },
        ]
    )
    for specification in specifications:
        csv_path = Path(specification["path"])
        frame = pd.DataFrame(columns=["close", "volume"])
        state = "missing"
        fetcher = specification["fetch"]
        if fetcher is not None:
            try:
                frame = specification["normalize"](fetcher())
                if frame.empty:
                    raise RuntimeError("返回空数据")
                persist_external_frame(
                    frame,
                    csv_path,
                    specification["symbol"],
                    specification["source"],
                    specification["dataset_type"],
                    now,
                )
                state = "live"
            except Exception as exc:
                errors.append(f"{specification['symbol']}: {exc}")

        if frame.empty:
            frame = load_cached_akshare_frame(csv_path)
            if not frame.empty:
                state = "cache"

        if frame.empty:
            continue
        symbol = specification["symbol"]
        histories[symbol] = frame["close"].rename(symbol)
        source_metadata = {
                "symbol": symbol,
                "name": specification["name"],
                "provider": specification["provider"],
                "status": state,
                "path": str(csv_path),
                "startDate": frame.index.min().strftime("%Y-%m-%d"),
                "endDate": frame.index.max().strftime("%Y-%m-%d"),
                "rows": len(frame),
                "maxLagDays": int(specification["maxLagDays"]),
            }
        if symbol == CNY_MYR_MID_SYMBOL:
            bnm_latest = fetch_bnm_cnymyr_latest()
            if bnm_latest is not None:
                bnm_date, bnm_value = bnm_latest
                safe_asof = frame[frame.index <= pd.Timestamp(bnm_date)]
                if not safe_asof.empty:
                    safe_value = float(safe_asof["close"].iloc[-1])
                    source_metadata.update(
                        {
                            "bnmCrossCheckDate": bnm_date,
                            "bnmCnyPerMyr": round(bnm_value, 6),
                            "bnmRelativeDiffPct": round(
                                abs(safe_value / bnm_value - 1) * 100, 4
                            ),
                        }
                    )
        metadata.append(source_metadata)

    required = {
        *(definition["lme_symbol"] for definition in LME_CROSS_MARKET_PAIRS),
        USD_CNY_MID_SYMBOL,
        CNY_MYR_MID_SYMBOL,
        CSI300_PE_SYMBOL,
        CN10Y_SYMBOL,
        US10Y_SYMBOL,
        SP500_PE_SYMBOL,
        NASDAQ_SYMBOL,
        SP500_SYMBOL,
        FCPO_SYMBOL,
    }
    missing = sorted(required.difference(histories))
    if missing:
        detail = "; ".join(errors) if errors else "没有可用缓存"
        raise ExternalDataError(
            f"已批准外部补充数据不可用: {', '.join(missing)}；{detail}"
        )
    return histories, metadata, errors


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
        "mode": "xtdata_akshare",
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


def build_xtdata_only_validation(
    xt_histories: dict[str, pd.Series],
    data_date: pd.Timestamp,
) -> dict[str, Any]:
    """Build the dashboard integrity payload without reading any external quote source."""
    checks: list[dict[str, Any]] = []
    validation_series: dict[str, dict[str, str]] = {}
    for xt_symbol in FUTURES_SERIES:
        base_symbol = main_continuous_symbol(xt_symbol)
        if base_symbol in AKSHARE_FUTURES:
            base_name = AKSHARE_FUTURES[base_symbol]["name"]
        else:
            base_name = {
                "IC00.IF": "中证500股指",
                "IM00.IF": "中证1000股指",
                "IF00.IF": "沪深300股指",
                "fu00.SF": "燃料油",
                "bu00.SF": "沥青",
                "nr00.INE": "20号胶",
                "br00.SF": "BR橡胶",
                "SH00.ZF": "烧碱",
                "ni00.SF": "沪镍",
                "ss00.SF": "不锈钢",
                "l00.DF": "聚乙烯",
                "pp00.DF": "聚丙烯",
                "lh00.DF": "生猪",
                "c00.DF": "玉米",
            }.get(base_symbol, base_symbol)
        validation_series[xt_symbol] = {
            "name": f"{base_name}{'加权' if is_weighted_symbol(xt_symbol) else '主连'}",
            "asset_type": "期货",
        }
    validation_series.update(
        {
            symbol: {"name": spec["name"], "asset_type": "现货指数"}
            for symbol, spec in INDEXES.items()
        }
    )

    for xt_symbol, spec in validation_series.items():
        series = xt_histories.get(xt_symbol)
        available = series is not None and data_date in series.index
        checks.append(
            {
                "name": spec["name"],
                "assetType": spec["asset_type"],
                "xtSymbol": xt_symbol,
                "akSymbol": None,
                "date": data_date.strftime("%Y-%m-%d"),
                "xtClose": round(float(series.loc[data_date]), 6) if available else None,
                "akClose": None,
                "relativeDiffPct": None,
                "status": "完整" if available else "xtdata缺失",
                "akMode": "disabled",
                "matchedContract": None,
                "matchedContractClose": None,
                "xtStartDate": series.index.min().strftime("%Y-%m-%d") if series is not None else None,
                "xtEndDate": series.index.max().strftime("%Y-%m-%d") if series is not None else None,
                "xtRows": len(series) if series is not None else 0,
                "akStartDate": None,
                "akEndDate": None,
                "akRows": 0,
            }
        )

    complete = sum(check["status"] == "完整" for check in checks)
    unavailable = len(checks) - complete
    return {
        "mode": "xtdata_only",
        "policy": "行情仅使用xtdata；检查数据日覆盖、组合完整性与未来数据",
        "thresholdPct": None,
        "summary": {
            "status": "通过" if unavailable == 0 else "有异常",
            "total": len(checks),
            "consistent": complete,
            "contractMismatch": 0,
            "review": unavailable,
            "unavailable": unavailable,
            "coveragePct": round(complete / len(checks) * 100, 2),
            "maxRelativeDiffPct": None,
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


def display_range(series: pd.Series, kind: str) -> str:
    return f"{display_number(float(series.min()), kind)} ~ {display_number(float(series.max()), kind)}"


def display_percentage(value: float) -> str:
    return f"{value * 100:.2f}%"


def display_percentage_change(value: float) -> str:
    return f"{value * 100:+.2f}%"


def display_percentage_range(series: pd.Series) -> str:
    return f"{display_percentage(float(series.min()))} ~ {display_percentage(float(series.max()))}"


def latest_leg_change_pct(series: pd.Series, latest_date: pd.Timestamp) -> float | None:
    values = pd.to_numeric(series, errors="coerce").replace([math.inf, -math.inf], pd.NA).dropna()
    values = values[values.index <= latest_date].sort_index()
    if len(values) < 2 or pd.Timestamp(values.index[-1]) != pd.Timestamp(latest_date):
        return None
    previous = float(values.iloc[-2])
    if previous == 0:
        return None
    return round((float(values.iloc[-1]) / previous - 1) * 100, 4)


def signal_for(value: float) -> str:
    if value >= 95:
        return "极度偏高"
    if value >= 85:
        return "偏高"
    if value <= 5:
        return "极度偏低"
    if value <= 15:
        return "偏低"
    return "中性"


def balance_metrics(
    left: str,
    right: str,
    left_price: float,
    right_price: float,
    force_one_to_one: bool = False,
) -> tuple[str, str, str, str]:
    left_contract = CONTRACTS[main_continuous_symbol(left)]
    right_contract = CONTRACTS[main_continuous_symbol(right)]
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


def build_contract_history_series(
    definition: dict[str, Any],
    expiry: str,
    monthly_histories: dict[str, pd.DataFrame],
    common_latest_date: pd.Timestamp,
) -> list[dict[str, Any]]:
    formula: Callable[[pd.Series, pd.Series], pd.Series] = definition["formula"]
    start_date = common_latest_date - pd.DateOffset(years=SEASONAL_CONTRACT_YEARS)
    series: list[dict[str, Any]] = []

    for historical_expiry in seasonal_expiries(expiry):
        left_symbol = contract_symbol_for_expiry(definition["left"], historical_expiry)
        right_symbol = contract_symbol_for_expiry(definition["right"], historical_expiry)
        left_frame = monthly_histories.get(left_symbol)
        right_frame = monthly_histories.get(right_symbol)
        if left_frame is None or right_frame is None:
            continue

        aligned = pd.concat(
            [
                left_frame["close"].rename("leftClose"),
                right_frame["close"].rename("rightClose"),
            ],
            axis=1,
            join="inner",
        ).dropna()
        aligned = aligned[
            (aligned.index >= start_date) & (aligned.index <= common_latest_date)
        ]
        if aligned.empty:
            continue
        # A concrete Chinese futures contract should not contain many years of
        # observations.  Xtdata can resolve ambiguous Zhengzhou three-digit
        # codes such as OI001.ZF as a long pseudo-continuous series; admitting
        # that frame would make one "historical contract" overlap every other
        # delivery year and contaminate the chart thresholds.
        aligned_span_days = (aligned.index.max() - aligned.index.min()).days
        if aligned_span_days > CONTRACT_HISTORY_MAX_SPAN_DAYS:
            continue
        values = formula(aligned["leftClose"], aligned["rightClose"]).replace(
            [math.inf, -math.inf], pd.NA
        ).dropna()
        if len(values) < 2:
            continue
        weekly_values = values.groupby(values.index.to_period("W-FRI")).tail(1).round(6)

        series.append(
            {
                "expiry": historical_expiry,
                "leftSymbol": left_symbol,
                "rightSymbol": right_symbol,
                "values": weekly_values,
            }
        )

    return series


def build_contract_history_chart(
    definition: dict[str, Any],
    expiry: str,
    monthly_histories: dict[str, pd.DataFrame],
    common_latest_date: pd.Timestamp,
    history_series: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    start_date = common_latest_date - pd.DateOffset(years=SEASONAL_CONTRACT_YEARS)
    series = history_series if history_series is not None else build_contract_history_series(
        definition,
        expiry,
        monthly_histories,
        common_latest_date,
    )

    if not series:
        return None

    month = expiry[-2:]
    return {
        "title": f"{definition['pair']}历年{int(month)}月合约",
        "unit": "点差" if definition["kind"] == "spread" else "比值",
        "month": month,
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate": common_latest_date.strftime("%Y-%m-%d"),
        "source": "xtdata",
        "grain": "周末值",
        "series": [
            {
                "expiry": item["expiry"],
                "leftSymbol": item["leftSymbol"],
                "rightSymbol": item["rightSymbol"],
                "points": [
                    {
                        "date": timestamp.strftime("%Y-%m-%d"),
                        "value": float(value),
                    }
                    for timestamp, value in item["values"].items()
                ],
            }
            for item in series
        ],
    }


def build_observation_history_chart(
    definition: dict[str, Any],
    label: str,
    left_symbol: str,
    right_symbol: str,
    values: pd.Series,
    common_latest_date: pd.Timestamp,
) -> dict[str, Any] | None:
    start_date = common_latest_date - pd.DateOffset(years=SEASONAL_CONTRACT_YEARS)
    window = values[
        (values.index >= start_date) & (values.index <= common_latest_date)
    ].dropna()
    if len(window) < 2:
        return None
    weekly_values = window.groupby(window.index.to_period("W-FRI")).tail(1)
    return {
        "title": f"{definition['pair']}{label}走势",
        "unit": "点差" if definition["kind"] == "spread" else "比值",
        "month": "",
        "startDate": start_date.strftime("%Y-%m-%d"),
        "endDate": common_latest_date.strftime("%Y-%m-%d"),
        "source": "xtdata",
        "grain": "周末值",
        "series": [
            {
                "expiry": label,
                "leftSymbol": left_symbol,
                "rightSymbol": right_symbol,
                "points": [
                    {
                        "date": timestamp.strftime("%Y-%m-%d"),
                        "value": round(float(value), 6),
                    }
                    for timestamp, value in weekly_values.items()
                ],
            }
        ],
    }


def build_contract_rows(
    definition: dict[str, Any],
    monthly_histories: dict[str, pd.DataFrame],
    monthly_contracts: dict[str, dict[str, str]],
    common_latest_date: pd.Timestamp,
    include_history_chart: bool = True,
) -> list[dict[str, Any]]:
    if not definition.get("tradable", True):
        return []
    left_months = monthly_contracts[main_continuous_symbol(definition["left"])]
    right_months = monthly_contracts[main_continuous_symbol(definition["right"])]
    formula: Callable[[pd.Series, pd.Series], pd.Series] = definition["formula"]
    results: list[dict[str, Any]] = []

    for expiry in sorted(set(left_months) & set(right_months)):
        allowed_months = definition.get("contract_months")
        if allowed_months and int(expiry[-2:]) not in allowed_months:
            continue
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
        if len(current_series) < 2:
            continue

        latest_date = current_series.index[-1]
        current = float(current_series.iloc[-1])
        previous = float(current_series.iloc[-2])
        change = current - previous
        history_series = (
            build_contract_history_series(
                definition,
                expiry,
                monthly_histories,
                common_latest_date,
            )
            if include_history_chart and not is_equity_index_definition(definition)
            else []
        )
        statistical_series = (
            pd.concat([item["values"] for item in history_series]).sort_index()
            if history_series
            else current_series
        )
        five_year_start = latest_date - pd.DateOffset(years=5)
        five_year = statistical_series[statistical_series.index >= five_year_start]
        statistical_current = round(current, 6)
        all_time_percentile = round(float((statistical_series <= statistical_current).mean() * 100), 2)
        five_year_percentile = round(float((five_year <= statistical_current).mean() * 100), 2)
        lots, deviation, notional, margin = balance_metrics(
            definition["left"],
            definition["right"],
            float(aligned.loc[latest_date, "leftClose"]),
            float(aligned.loc[latest_date, "rightClose"]),
            force_one_to_one=definition["kind"] == "spread",
        )

        results.append(
            {
                "expiry": expiry,
                "current": display_number(current, definition["kind"]),
                "previous": display_number(previous, definition["kind"]),
                "change": display_change(change, definition["kind"]),
                "changeValue": round(change, 8),
                "allTime": f"{all_time_percentile:.2f}%",
                "allTimeRange": display_range(statistical_series, definition["kind"]),
                "percentile": five_year_percentile,
                "fiveYearRange": display_range(five_year, definition["kind"]),
                "signal": signal_for(five_year_percentile),
                "lots": lots,
                "deviation": deviation,
                "notional": notional,
                "margin": margin,
                "sourceStatus": "仅xtdata",
                "leftSymbol": left_symbol,
                "rightSymbol": right_symbol,
                "leftChangePct": latest_leg_change_pct(aligned["leftClose"], latest_date),
                "rightChangePct": latest_leg_change_pct(aligned["rightClose"], latest_date),
                "leftVolume": left_volume,
                "rightVolume": right_volume,
                "pairedVolume": paired_volume,
                "historyChart": (
                    build_contract_history_chart(
                        definition,
                        expiry,
                        monthly_histories,
                        common_latest_date,
                        history_series,
                    )
                    if include_history_chart and not is_equity_index_definition(definition)
                    else None
                ),
            }
        )

    results.sort(
        key=lambda item: (
            -item["pairedVolume"],
            -(item["leftVolume"] + item["rightVolume"]),
            item["expiry"],
        )
    )
    selected = results[:4]
    selected.sort(key=lambda item: item["expiry"])
    return selected


def classify_term_structure(
    continuous_symbol: str,
    monthly_histories: dict[str, pd.DataFrame],
    monthly_contracts: dict[str, dict[str, str]],
    common_latest_date: pd.Timestamp,
) -> dict[str, Any] | None:
    observations: list[dict[str, Any]] = []
    for expiry, symbol in monthly_contracts.get(continuous_symbol, {}).items():
        frame = monthly_histories.get(symbol)
        if frame is None or common_latest_date not in frame.index:
            continue
        latest = frame.loc[common_latest_date]
        if pd.isna(latest["close"]) or pd.isna(latest["volume"]):
            continue
        close = float(latest["close"])
        volume = max(0, int(round(float(latest["volume"]))))
        if not math.isfinite(close) or close <= 0 or volume <= 0:
            continue
        observations.append(
            {
                "expiry": expiry,
                "symbol": symbol,
                "price": close,
                "volume": volume,
            }
        )

    liquid_contracts = sorted(
        observations,
        key=lambda item: (-item["volume"], item["expiry"]),
    )[:4]
    curve = sorted(liquid_contracts, key=lambda item: item["expiry"])
    if len(curve) < 2:
        return None

    near = curve[0]
    far = curve[-1]
    change_pct = (far["price"] / near["price"] - 1) * 100
    return {
        "state": "Contango" if change_pct >= 0 else "Back",
        "nearExpiry": near["expiry"],
        "farExpiry": far["expiry"],
        "nearPrice": round(float(near["price"]), 6),
        "farPrice": round(float(far["price"]), 6),
        "changePct": round(change_pct, 4),
        "contractCount": len(curve),
    }


def pair_source_status(definition: dict[str, Any], source_validation: dict[str, Any]) -> str:
    if definition.get("custom_builder") == "lme_cross_market":
        return "外部补充"
    if source_validation.get("mode") == "xtdata_only":
        return "仅xtdata"
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


def build_spot_observation(
    definition: dict[str, Any],
    histories: dict[str, pd.Series],
    common_latest_date: pd.Timestamp,
    source_validation: dict[str, Any],
) -> dict[str, Any] | None:
    spot_definition = SPOT_OBSERVATIONS.get(definition["pair"])
    if not spot_definition:
        return None

    left = spot_definition["left"]
    right = spot_definition["right"]
    aligned = pd.concat([histories[left], histories[right]], axis=1, join="inner").dropna()
    aligned = aligned[aligned.index <= common_latest_date]
    formula: Callable[[pd.Series, pd.Series], pd.Series] = definition["formula"]
    values = formula(aligned[left], aligned[right]).replace([math.inf, -math.inf], pd.NA).dropna()
    if len(values) < 2 or values.index[-1] != common_latest_date:
        raise RuntimeError(f"{definition['pair']} 的现货指数共同交易日不足")

    current = float(values.iloc[-1])
    previous = float(values.iloc[-2])
    change = current - previous
    latest_date = values.index[-1]
    five_year = values[values.index >= latest_date - pd.DateOffset(years=5)]
    all_time_percentile = percentile(values)
    five_year_percentile = percentile(five_year)
    lots, deviation, notional, margin = balance_metrics(
        definition["left"],
        definition["right"],
        float(aligned.loc[latest_date, left]),
        float(aligned.loc[latest_date, right]),
        force_one_to_one=definition["kind"] == "spread",
    )
    return {
        "key": "spot",
        "label": spot_definition["label"],
        "current": display_number(current, definition["kind"]),
        "previous": display_number(previous, definition["kind"]),
        "change": display_change(change, definition["kind"]),
        "changeValue": round(change, 8),
        "allTime": f"{all_time_percentile:.2f}%",
        "allTimeRange": display_range(values, definition["kind"]),
        "percentile": five_year_percentile,
        "fiveYearRange": display_range(five_year, definition["kind"]),
        "signal": signal_for(five_year_percentile),
        "lots": lots,
        "deviation": deviation,
        "notional": notional,
        "margin": margin,
        "sourceStatus": pair_source_status(spot_definition, source_validation),
        "leftSymbol": left,
        "rightSymbol": right,
        "leftChangePct": latest_leg_change_pct(aligned[left], latest_date),
        "rightChangePct": latest_leg_change_pct(aligned[right], latest_date),
        "historyChart": build_observation_history_chart(
            definition,
            "现货指数",
            left,
            right,
            values,
            common_latest_date,
        ),
    }


def build_main_continuous_observation(
    definition: dict[str, Any],
    histories: dict[str, pd.Series],
    common_latest_date: pd.Timestamp,
    source_validation: dict[str, Any],
) -> dict[str, Any] | None:
    """Keep the 00 main-continuous pair available when the default uses JQ00."""
    if not definition.get("tradable", True):
        return None
    if not any(is_weighted_symbol(symbol) for symbol in (definition["left"], definition["right"])):
        return None

    left = main_continuous_symbol(definition["left"])
    right = main_continuous_symbol(definition["right"])
    aligned = pd.concat([histories[left], histories[right]], axis=1, join="inner").dropna()
    aligned = aligned[aligned.index <= common_latest_date]
    formula: Callable[[pd.Series, pd.Series], pd.Series] = definition["formula"]
    values = formula(aligned[left], aligned[right]).replace([math.inf, -math.inf], pd.NA).dropna()
    if len(values) < 2 or values.index[-1] != common_latest_date:
        raise RuntimeError(f"{definition['pair']} 的主连共同交易日不足")

    current = float(values.iloc[-1])
    previous = float(values.iloc[-2])
    change = current - previous
    latest_date = values.index[-1]
    five_year = values[values.index >= latest_date - pd.DateOffset(years=5)]
    all_time_percentile = percentile(values)
    five_year_percentile = percentile(five_year)
    lots, deviation, notional, margin = balance_metrics(
        left,
        right,
        float(aligned.loc[latest_date, left]),
        float(aligned.loc[latest_date, right]),
        force_one_to_one=definition["kind"] == "spread",
    )
    main_definition = {**definition, "left": left, "right": right}
    return {
        "key": "main",
        "label": "主连",
        "current": display_number(current, definition["kind"]),
        "previous": display_number(previous, definition["kind"]),
        "change": display_change(change, definition["kind"]),
        "changeValue": round(change, 8),
        "allTime": f"{all_time_percentile:.2f}%",
        "allTimeRange": display_range(values, definition["kind"]),
        "percentile": five_year_percentile,
        "fiveYearRange": display_range(five_year, definition["kind"]),
        "signal": signal_for(five_year_percentile),
        "lots": lots,
        "deviation": deviation,
        "notional": notional,
        "margin": margin,
        "sourceStatus": pair_source_status(main_definition, source_validation),
        "leftSymbol": left,
        "rightSymbol": right,
        "leftChangePct": latest_leg_change_pct(aligned[left], latest_date),
        "rightChangePct": latest_leg_change_pct(aligned[right], latest_date),
        "historyChart": None,
    }


def build_im_term_series(
    histories: dict[str, pd.Series],
    monthly_histories: dict[str, pd.DataFrame],
    common_latest_date: pd.Timestamp,
    trading_calendar: pd.DatetimeIndex,
    far_rank: int,
) -> tuple[pd.Series, dict[pd.Timestamp, dict[str, Any]]]:
    """Build a month-gap-adjusted IM calendar spread without future-price use."""
    spot = histories[IM_TERM_SPOT_SYMBOL].dropna().sort_index()
    spot_dates = pd.DatetimeIndex(spot.index.unique()).sort_values()
    trading_dates = spot_dates[
        (spot_dates >= IM_TERM_START_DATE)
        & (spot_dates <= common_latest_date)
    ]
    observations: dict[pd.Timestamp, float] = {}
    legs_by_date: dict[pd.Timestamp, dict[str, Any]] = {}

    for trading_date in trading_dates:
        near_period = im_near_contract_period(trading_date, trading_calendar)
        far_period = im_far_quarter_period(trading_date, far_rank)
        near_symbol = contract_symbol_for_expiry(
            "IM00.IF", near_period.strftime("%y%m")
        )
        far_symbol = contract_symbol_for_expiry(
            "IM00.IF", far_period.strftime("%y%m")
        )
        near_frame = monthly_histories.get(near_symbol)
        far_frame = monthly_histories.get(far_symbol)
        if (
            near_frame is None
            or far_frame is None
            or trading_date not in near_frame.index
            or trading_date not in far_frame.index
            or trading_date not in spot.index
        ):
            continue

        near_price = float(near_frame.loc[trading_date, "close"])
        far_price = float(far_frame.loc[trading_date, "close"])
        spot_price = float(spot.loc[trading_date])
        month_gap = far_period.ordinal - near_period.ordinal
        if not all(
            math.isfinite(value) and value > 0
            for value in (near_price, far_price, spot_price)
        ) or month_gap <= 0:
            continue
        value = (near_price - far_price) * 12 / month_gap / spot_price
        observations[pd.Timestamp(trading_date)] = value
        legs_by_date[pd.Timestamp(trading_date)] = {
            "nearSymbol": near_symbol,
            "farSymbol": far_symbol,
            "spotSymbol": IM_TERM_SPOT_SYMBOL,
            "nearPrice": near_price,
            "farPrice": far_price,
            "spotPrice": spot_price,
            "monthGap": month_gap,
        }

    values = pd.Series(observations, dtype="float64").sort_index()
    if len(values) < 2 or values.index[-1] != common_latest_date:
        latest = values.index[-1].strftime("%Y-%m-%d") if len(values) else "无"
        raise RuntimeError(
            f"IM期限套远季{far_rank}有效共同交易日不足或未覆盖数据日，最新值={latest}"
        )
    return values, legs_by_date


def build_im_term_observation(
    definition: dict[str, Any],
    histories: dict[str, pd.Series],
    monthly_histories: dict[str, pd.DataFrame],
    common_latest_date: pd.Timestamp,
    trading_calendar: pd.DatetimeIndex,
    source_validation: dict[str, Any],
    *,
    key: str,
    label: str,
    far_rank: int,
) -> tuple[dict[str, Any], pd.Timestamp]:
    values, legs_by_date = build_im_term_series(
        histories,
        monthly_histories,
        common_latest_date,
        trading_calendar,
        far_rank,
    )
    latest_date = pd.Timestamp(values.index[-1])
    latest_legs = legs_by_date[latest_date]
    current = float(values.iloc[-1])
    previous = float(values.iloc[-2])
    change = current - previous
    five_year = values[values.index >= latest_date - pd.DateOffset(years=5)]
    five_year_percentile = percentile(five_year)
    lots, deviation, notional, margin = balance_metrics(
        "IM00.IF",
        "IM00.IF",
        latest_legs["nearPrice"],
        latest_legs["farPrice"],
        force_one_to_one=True,
    )
    chart = build_observation_history_chart(
        definition,
        label,
        latest_legs["nearSymbol"],
        latest_legs["farSymbol"],
        values,
        common_latest_date,
    )
    if chart is None:
        raise RuntimeError(f"IM期限套{label}历史折线图数据不足")
    chart["title"] = f"IM期限套（当月-{label}）走势"
    chart["unit"] = "百分比"
    chart["startDate"] = chart["series"][0]["points"][0]["date"]
    formula_label = f"(IM当月 − IM{label}) × 12 / 月差 / 中证1000"
    near_history = monthly_histories[latest_legs["nearSymbol"]]["close"]
    far_history = monthly_histories[latest_legs["farSymbol"]]["close"]

    return (
        {
            "key": key,
            "label": label,
            "current": display_percentage(current),
            "previous": display_percentage(previous),
            "change": display_percentage_change(change),
            "changeValue": round(change, 8),
            "allTime": f"{percentile(values):.2f}%",
            "allTimeRange": display_percentage_range(values),
            "percentile": five_year_percentile,
            "fiveYearRange": display_percentage_range(five_year),
            "signal": signal_for(five_year_percentile),
            "lots": lots,
            "deviation": deviation,
            "notional": notional,
            "margin": margin,
            "leftSymbol": latest_legs["nearSymbol"],
            "rightSymbol": latest_legs["farSymbol"],
            "leftChangePct": latest_leg_change_pct(near_history, latest_date),
            "rightChangePct": latest_leg_change_pct(far_history, latest_date),
            "denominatorSymbol": latest_legs["spotSymbol"],
            "formulaLabel": formula_label,
            "nearPrice": round(float(latest_legs["nearPrice"]), 6),
            "farPrice": round(float(latest_legs["farPrice"]), 6),
            "spotPrice": round(float(latest_legs["spotPrice"]), 6),
            "monthGap": int(latest_legs["monthGap"]),
            "sourceStatus": pair_source_status(definition, source_validation),
            "historyChart": chart,
        },
        latest_date,
    )


def build_im_term_row(
    definition: dict[str, Any],
    histories: dict[str, pd.Series],
    monthly_histories: dict[str, pd.DataFrame],
    common_latest_date: pd.Timestamp,
    trading_calendar: pd.DatetimeIndex,
    source_validation: dict[str, Any],
) -> tuple[dict[str, Any], pd.Timestamp]:
    down, down_latest_date = build_im_term_observation(
        definition,
        histories,
        monthly_histories,
        common_latest_date,
        trading_calendar,
        source_validation,
        key="term-down",
        label="下季",
        far_rank=1,
    )
    skip, skip_latest_date = build_im_term_observation(
        definition,
        histories,
        monthly_histories,
        common_latest_date,
        trading_calendar,
        source_validation,
        key="term-skip",
        label="隔季",
        far_rank=2,
    )
    if down_latest_date != skip_latest_date:
        raise RuntimeError("IM期限套下季与隔季最新交易日不一致")

    return (
        {
            "strategyType": definition.get("strategy_type", "回归"),
            "pair": definition["pair"],
            "current": down["current"],
            "previous": down["previous"],
            "change": down["change"],
            "changeValue": down["changeValue"],
            "allTime": down["allTime"],
            "allTimeRange": down["allTimeRange"],
            "percentile": down["percentile"],
            "fiveYearRange": down["fiveYearRange"],
            "signal": down["signal"],
            "lots": down["lots"],
            "deviation": down["deviation"],
            "notional": down["notional"],
            "margin": down["margin"],
            "leftSymbol": down["leftSymbol"],
            "rightSymbol": down["rightSymbol"],
            "leftChangePct": down["leftChangePct"],
            "rightChangePct": down["rightChangePct"],
            "denominatorSymbol": down["denominatorSymbol"],
            "seriesMode": "term",
            "pairType": "期限套利",
            "formulaLabel": down["formulaLabel"],
            "rollRule": "当月合约正常跟踪至到期，到期后自然切换为次月合约",
            "nearPrice": down["nearPrice"],
            "farPrice": down["farPrice"],
            "spotPrice": down["spotPrice"],
            "monthGap": down["monthGap"],
            "sourceStatus": down["sourceStatus"],
            "leftStructure": None,
            "rightStructure": None,
            "mainHistoryChart": down["historyChart"],
            "termObservations": [down, skip],
            "spotObservation": None,
            "mainContinuousObservation": None,
            "contracts": [],
        },
        down_latest_date,
    )


def build_lme_cross_market_row(
    definition: dict[str, Any],
    histories: dict[str, pd.Series],
    external_histories: dict[str, pd.Series],
    common_latest_date: pd.Timestamp,
    source_validation: dict[str, Any],
    left_structure: dict[str, Any] | None,
) -> tuple[dict[str, Any], pd.Timestamp]:
    domestic_symbol = definition["left"]
    lme_symbol = definition["lme_symbol"]
    lme_key = lme_symbol
    aligned = pd.concat(
        [
            histories[domestic_symbol].rename("domestic"),
            external_histories[lme_key].rename("lme"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    aligned = aligned[aligned.index <= common_latest_date]
    values = (aligned["domestic"] / aligned["lme"]).replace(
        [math.inf, -math.inf], pd.NA
    ).dropna()
    if len(values) < 2 or values.index[-1] != common_latest_date:
        latest = values.index[-1].strftime("%Y-%m-%d") if len(values) else "无"
        raise ExternalDataError(
            f"{definition['pair']} 未覆盖国内数据日 {common_latest_date:%Y-%m-%d}，最新共同日期={latest}"
        )

    latest_date = pd.Timestamp(values.index[-1])
    current = float(values.iloc[-1])
    previous = float(values.iloc[-2])
    change = current - previous
    five_year = values[values.index >= latest_date - pd.DateOffset(years=5)]
    five_year_percentile = percentile(five_year)
    formula_label = f"{domestic_symbol} / {lme_symbol}.LME"
    chart = build_observation_history_chart(
        definition,
        "",
        domestic_symbol,
        f"{lme_symbol}.LME",
        values,
        common_latest_date,
    )
    if chart is None:
        raise ExternalDataError(f"{definition['pair']} 历史折线图数据不足")
    fx_series = external_histories[USD_CNY_MID_SYMBOL]
    chart_start = pd.Timestamp(chart["startDate"])
    fx_window = fx_series[
        (fx_series.index >= chart_start) & (fx_series.index <= common_latest_date)
    ].dropna()
    fx_weekly = fx_window.groupby(fx_window.index.to_period("W-FRI")).tail(1)
    if len(fx_weekly) < 2:
        raise ExternalDataError(f"{definition['pair']} 美元兑人民币叠加线数据不足")
    chart["series"][0]["expiry"] = "内外盘比价（左轴）"
    chart.update(
        {
            "title": f"{definition['pair']}走势",
            "source": "国内：xtdata 00主力连续；外盘：AKShare/新浪 LME三个月电子盘；汇率：AKShare/国家外汇管理局",
            "grain": "周末值 · 比价不做汇率换算 · 汇率仅作右轴参考",
            "overlaySeries": {
                "label": "美元兑人民币中间价（右轴）",
                "symbol": USD_CNY_MID_SYMBOL,
                "unit": "人民币/美元",
                "points": [
                    {
                        "date": timestamp.strftime("%Y-%m-%d"),
                        "value": round(float(value), 6),
                    }
                    for timestamp, value in fx_weekly.items()
                ],
            },
        }
    )
    latest_row = aligned.loc[latest_date]
    return (
        {
            "strategyType": definition.get("strategy_type", "回归"),
            "pair": definition["pair"],
            "current": display_number(current, "ratio"),
            "previous": display_number(previous, "ratio"),
            "change": display_change(change, "ratio"),
            "changeValue": round(change, 8),
            "allTime": f"{percentile(values):.2f}%",
            "allTimeRange": display_range(values, "ratio"),
            "percentile": five_year_percentile,
            "fiveYearRange": display_range(five_year, "ratio"),
            "signal": signal_for(five_year_percentile),
            "lots": "—",
            "deviation": "—",
            "notional": "—",
            "margin": "—",
            "leftSymbol": domestic_symbol,
            "rightSymbol": definition["right"],
            "leftChangePct": latest_leg_change_pct(aligned["domestic"], latest_date),
            "rightChangePct": latest_leg_change_pct(aligned["lme"], latest_date),
            "seriesMode": "external",
            "pairType": "跨市场套利",
            "formulaLabel": formula_label,
            "sourceStatus": pair_source_status(definition, source_validation),
            "leftStructure": left_structure,
            "rightStructure": None,
            "mainHistoryChart": chart,
            "spotObservation": None,
            "mainContinuousObservation": None,
            "contracts": [],
            "externalSourceDate": latest_date.strftime("%Y-%m-%d"),
            "domesticPrice": round(float(latest_row["domestic"]), 6),
            "lmePriceUsdPerTonne": round(float(latest_row["lme"]), 6),
        },
        latest_date,
    )


def align_external_asof(
    anchor: pd.DatetimeIndex,
    series: pd.Series,
    max_lag_days: int,
) -> pd.Series:
    desired = pd.DataFrame({"date": pd.DatetimeIndex(anchor).normalize()})
    desired = desired.drop_duplicates().sort_values("date")
    source = pd.DataFrame(
        {
            "sourceDate": pd.DatetimeIndex(series.index).normalize(),
            "value": pd.to_numeric(series, errors="coerce").to_numpy(),
        }
    ).dropna().drop_duplicates(subset=["sourceDate"], keep="last").sort_values("sourceDate")
    aligned = pd.merge_asof(
        desired,
        source,
        left_on="date",
        right_on="sourceDate",
        direction="backward",
    )
    lag = (aligned["date"] - aligned["sourceDate"]).dt.days
    aligned.loc[lag > max_lag_days, "value"] = pd.NA
    return aligned.set_index("date")["value"].dropna()


def build_external_reference_row(
    definition: dict[str, Any],
    histories: dict[str, pd.Series],
    external_histories: dict[str, pd.Series],
    common_latest_date: pd.Timestamp,
) -> tuple[dict[str, Any], pd.Timestamp]:
    builder = definition["custom_builder"]
    external_anchor = pd.DatetimeIndex([common_latest_date])
    pair_type = "现货参考"
    label = "外部"
    unit = "比值"

    if builder == "cn_equity_risk_premium":
        pe = external_histories[CSI300_PE_SYMBOL]
        anchor = pe.index.union(external_anchor)
        pe_aligned = align_external_asof(anchor, pe, 5)
        yield_aligned = align_external_asof(anchor, external_histories[CN10Y_SYMBOL], 7)
        aligned = pd.concat(
            [pe_aligned.rename("left"), yield_aligned.rename("right")],
            axis=1,
            join="inner",
        ).dropna()
        values = 1 / aligned["left"] - aligned["right"] / 100
        formula_label = "100 / 沪深300滚动市盈率 − 中国10年期国债收益率"
        source = "中证指数有限公司滚动市盈率；中国债券信息网10年期国债收益率"
        unit = "百分比"
    elif builder == "us_equity_risk_premium":
        us10y = external_histories[US10Y_SYMBOL]
        anchor = us10y.index.union(external_anchor)
        pe_aligned = align_external_asof(anchor, external_histories[SP500_PE_SYMBOL], 45)
        yield_aligned = align_external_asof(anchor, us10y, 7)
        aligned = pd.concat(
            [pe_aligned.rename("left"), yield_aligned.rename("right")],
            axis=1,
            join="inner",
        ).dropna()
        values = 1 / aligned["left"] - aligned["right"] / 100
        formula_label = "100 / 标普500市盈率 − 美国10年期国债收益率"
        source = "Multpl标普500月度市盈率；东方财富美国10年期国债收益率"
        unit = "百分比"
    elif builder == "external_ratio":
        sp500 = external_histories[SP500_SYMBOL]
        anchor = sp500.index.union(external_anchor)
        left_aligned = align_external_asof(anchor, external_histories[NASDAQ_SYMBOL], 7)
        right_aligned = align_external_asof(anchor, sp500, 7)
        aligned = pd.concat(
            [left_aligned.rename("left"), right_aligned.rename("right")],
            axis=1,
            join="inner",
        ).dropna()
        values = aligned["left"] / aligned["right"]
        formula_label = "纳斯达克综合指数 / 标普500指数"
        source = "新浪美股指数"
    elif builder == "malaysia_palm_soy_ratio":
        domestic = histories[definition["right"]]
        anchor = domestic.index[domestic.index <= common_latest_date].union(external_anchor)
        palm_aligned = align_external_asof(anchor, external_histories[FCPO_SYMBOL], 7)
        fx_aligned = align_external_asof(anchor, external_histories[CNY_MYR_MID_SYMBOL], 7)
        domestic_aligned = align_external_asof(anchor, domestic, 3)
        aligned = pd.concat(
            [
                palm_aligned.rename("left"),
                domestic_aligned.rename("right"),
                fx_aligned.rename("fx"),
            ],
            axis=1,
            join="inner",
        ).dropna()
        values = aligned["left"] * aligned["fx"] / aligned["right"]
        formula_label = "马盘FCPO（林吉特/吨）× 人民币/林吉特 ÷ 国内豆油加权（人民币/吨）"
        source = "马盘FCPO：新浪；国内豆油：xtdata JQ00；汇率：国家外汇管理局，BNM最新值校对"
        pair_type = "跨市场套利"
    else:
        raise RuntimeError(f"未知外部组合构建器: {builder}")

    values = values.replace([math.inf, -math.inf], pd.NA).dropna().sort_index()
    values = values[values.index <= common_latest_date]
    if len(values) < 2 or pd.Timestamp(values.index[-1]) != common_latest_date:
        latest = values.index[-1].strftime("%Y-%m-%d") if len(values) else "无"
        raise ExternalDataError(
            f"{definition['pair']} 未覆盖国内数据日 {common_latest_date:%Y-%m-%d}，最新={latest}"
        )

    latest_date = pd.Timestamp(values.index[-1])
    current = float(values.iloc[-1])
    previous = float(values.iloc[-2])
    change = current - previous
    five_year = values[values.index >= latest_date - pd.DateOffset(years=5)]
    five_year_percentile = percentile(five_year)
    chart = build_observation_history_chart(
        definition,
        label,
        definition["left"],
        definition["right"],
        values,
        common_latest_date,
    )
    if chart is None:
        raise ExternalDataError(f"{definition['pair']} 历史折线图数据不足")
    chart.update(
        {
            "title": f"{definition['pair']}走势",
            "unit": unit,
            "source": source,
            "grain": "周末值 · 仅向后匹配已公布数据",
        }
    )
    chart["series"][0]["expiry"] = "现货" if pair_type == "现货参考" else "跨市场"

    percentage = definition["kind"] == "percentage"
    latest_components = aligned.loc[latest_date]
    extra_fields: dict[str, Any] = {}
    if builder in {"cn_equity_risk_premium", "us_equity_risk_premium"}:
        extra_fields = {
            "priceEarningsRatio": round(float(latest_components["left"]), 6),
            "bondYieldPct": round(float(latest_components["right"]), 6),
        }
    elif builder == "external_ratio":
        extra_fields = {
            "leftIndexLevel": round(float(latest_components["left"]), 6),
            "rightIndexLevel": round(float(latest_components["right"]), 6),
        }
    elif builder == "malaysia_palm_soy_ratio":
        extra_fields = {
            "foreignPriceMyrPerTonne": round(float(latest_components["left"]), 6),
            "fxCnyPerMyr": round(float(latest_components["fx"]), 6),
            "domesticPriceCnyPerTonne": round(float(latest_components["right"]), 6),
        }
    return (
        {
            "strategyType": definition["strategy_type"],
            "pair": definition["pair"],
            "current": display_percentage(current) if percentage else display_number(current, "ratio"),
            "previous": display_percentage(previous) if percentage else display_number(previous, "ratio"),
            "change": display_percentage_change(change) if percentage else display_change(change, "ratio"),
            "changeValue": round(change, 8),
            "allTime": f"{percentile(values):.2f}%",
            "allTimeRange": display_percentage_range(values) if percentage else display_range(values, "ratio"),
            "percentile": five_year_percentile,
            "fiveYearRange": display_percentage_range(five_year) if percentage else display_range(five_year, "ratio"),
            "signal": signal_for(five_year_percentile),
            "lots": "—",
            "deviation": "—",
            "notional": "—",
            "margin": "—",
            "leftSymbol": definition["left"],
            "rightSymbol": definition["right"],
            "leftChangePct": latest_leg_change_pct(aligned["left"], latest_date),
            "rightChangePct": latest_leg_change_pct(aligned["right"], latest_date),
            "seriesMode": "external",
            "pairType": pair_type,
            "formulaLabel": formula_label,
            "sourceStatus": "外部补充",
            "leftStructure": None,
            "rightStructure": None,
            "mainHistoryChart": chart,
            "spotObservation": None,
            "mainContinuousObservation": None,
            "contracts": [],
            "externalSourceDate": latest_date.strftime("%Y-%m-%d"),
            **extra_fields,
        },
        latest_date,
    )


def build_rows(
    histories: dict[str, pd.Series],
    external_histories: dict[str, pd.Series],
    monthly_histories: dict[str, pd.DataFrame],
    monthly_contracts: dict[str, dict[str, str]],
    trading_calendar: pd.DatetimeIndex,
    source_validation: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
    latest_dates: list[pd.Timestamp] = []
    required_symbols = {
        symbol for definition in PAIRS for symbol in definition_xt_symbols(definition)
    }
    common_latest_date = min(histories[symbol].index.max() for symbol in required_symbols)
    required_futures_symbols = {
        symbol
        for definition in PAIRS
        if definition.get("tradable", True)
        or definition.get("custom_builder") == "lme_cross_market"
        for symbol in definition_xt_symbols(definition)
    }
    term_structures = {
        symbol: classify_term_structure(
            main_continuous_symbol(symbol),
            monthly_histories,
            monthly_contracts,
            common_latest_date,
        )
        for symbol in required_futures_symbols
    }

    for definition in PAIRS:
        if definition.get("custom_builder") == "im_term":
            row, latest_date = build_im_term_row(
                definition,
                histories,
                monthly_histories,
                common_latest_date,
                trading_calendar,
                source_validation,
            )
            rows.append(row)
            latest_dates.append(latest_date)
            continue

        if definition.get("custom_builder") == "lme_cross_market":
            row, latest_date = build_lme_cross_market_row(
                definition,
                histories,
                external_histories,
                common_latest_date,
                source_validation,
                term_structures.get(definition["left"]),
            )
            rows.append(row)
            latest_dates.append(latest_date)
            continue

        if definition.get("custom_builder") in {
            "cn_equity_risk_premium",
            "us_equity_risk_premium",
            "external_ratio",
            "malaysia_palm_soy_ratio",
        }:
            row, latest_date = build_external_reference_row(
                definition,
                histories,
                external_histories,
                common_latest_date,
            )
            rows.append(row)
            latest_dates.append(latest_date)
            continue

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
        five_year_start = latest_date - pd.DateOffset(years=5)
        five_year = values[values.index >= five_year_start]
        all_time_percentile = percentile(values)
        five_year_percentile = percentile(five_year)
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
                "strategyType": definition.get("strategy_type", "回归"),
                "pair": definition["pair"],
                "current": display_number(current, definition["kind"]),
                "previous": display_number(previous, definition["kind"]),
                "change": display_change(change, definition["kind"]),
                "changeValue": round(change, 8),
                "allTime": f"{all_time_percentile:.2f}%",
                "allTimeRange": display_range(values, definition["kind"]),
                "percentile": five_year_percentile,
                "fiveYearRange": display_range(five_year, definition["kind"]),
                "signal": signal_for(five_year_percentile),
                "lots": lots,
                "deviation": deviation,
                "notional": notional,
                "margin": margin,
                "leftSymbol": left,
                "rightSymbol": right,
                "leftChangePct": latest_leg_change_pct(aligned[left], latest_date),
                "rightChangePct": latest_leg_change_pct(aligned[right], latest_date),
                "seriesMode": (
                    "weighted"
                    if any(is_weighted_symbol(symbol) for symbol in (left, right))
                    else ("main" if tradable else "spot")
                ),
                "pairType": "期货套利" if tradable else "现货参考",
                "sourceStatus": pair_source_status(definition, source_validation),
                "leftStructure": term_structures.get(left) if tradable else None,
                "rightStructure": term_structures.get(right) if tradable else None,
                "mainHistoryChart": (
                    build_observation_history_chart(
                        definition,
                        (
                            "加权"
                            if any(is_weighted_symbol(symbol) for symbol in (left, right))
                            else ("主连" if tradable else "现货")
                        ),
                        left,
                        right,
                        values,
                        common_latest_date,
                    )
                    if (
                        is_equity_index_definition(definition)
                        or any(is_weighted_symbol(symbol) for symbol in (left, right))
                        or not tradable
                    )
                    else None
                ),
                "spotObservation": build_spot_observation(
                    definition,
                    histories,
                    common_latest_date,
                    source_validation,
                ),
                "mainContinuousObservation": build_main_continuous_observation(
                    definition,
                    histories,
                    common_latest_date,
                    source_validation,
                ),
                "contracts": build_contract_rows(
                    definition,
                    monthly_histories,
                    monthly_contracts,
                    common_latest_date,
                ),
            }
        )

    definitions_by_pair = {definition["pair"]: definition for definition in PAIRS}
    for row in rows:
        row["marketCategory"] = market_category_for_definition(definitions_by_pair[row["pair"]])
    rows.sort(key=dashboard_row_sort_key)
    unique_latest_dates = sorted({value.strftime("%Y-%m-%d") for value in latest_dates})
    if len(unique_latest_dates) != 1:
        raise RuntimeError(f"套利组合最新交易日不一致: {', '.join(unique_latest_dates)}")
    data_date = unique_latest_dates[0]
    return rows, data_date


def build_history_charts(
    histories: dict[str, pd.Series],
    data_date: pd.Timestamp,
) -> list[dict[str, Any]]:
    charts: list[dict[str, Any]] = []
    for definition in HISTORY_CHARTS:
        chart_id = definition["id"]
        pair_name = definition["pair"]
        left = definition["left"]
        right = definition["right"]
        aligned = pd.concat([histories[left], histories[right]], axis=1, join="inner").dropna()
        aligned = aligned[aligned.index <= data_date]
        formula: Callable[[pd.Series, pd.Series], pd.Series] = definition["formula"]
        values = formula(aligned[left], aligned[right]).replace([math.inf, -math.inf], pd.NA).dropna()
        if len(values) < 12:
            raise RuntimeError(f"{pair_name} 的历史图表数据不足 12 个观测值")

        daily_chart = pd.DataFrame({"value": values})
        for window in (5, 60, 250):
            daily_chart[f"ma{window}"] = values.rolling(
                window=window,
                min_periods=window,
            ).mean()
        monthly = daily_chart.groupby(daily_chart.index.to_period("M")).tail(1).tail(60)
        points = []
        for timestamp, point in monthly.iterrows():
            output_point: dict[str, Any] = {
                "date": str(timestamp.to_period("M")),
                "value": round(float(point["value"]), 6),
            }
            for window in (5, 60, 250):
                ma_value = point[f"ma{window}"]
                output_point[f"ma{window}"] = (
                    round(float(ma_value), 6) if pd.notna(ma_value) else None
                )
            points.append(output_point)
        latest_date = values.index[-1]
        five_year = values[values.index >= latest_date - pd.DateOffset(years=5)]
        charts.append(
            {
                "id": chart_id,
                "pair": pair_name,
                "title": f"{pair_name}走势",
                "unit": "点差" if definition["kind"] == "spread" else "比值",
                "grain": "月末值 · MA基于日频",
                "source": "xtdata",
                "leftSymbol": left,
                "rightSymbol": right,
                "current": display_number(float(values.iloc[-1]), definition["kind"]),
                "percentile": percentile(five_year),
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
    external_sources: list[dict[str, Any]],
    external_errors: list[str],
) -> dict[str, Any]:
    now = datetime.now(SHANGHAI)
    xtdata_only = source_validation.get("mode") == "xtdata_only"
    payload = {
        "dataDate": data_date,
        "updatedAt": now.isoformat(timespec="seconds"),
        "source": "xtdata（国内）+ 用户批准的中证指数、中国债券信息网、东方财富、新浪、Multpl、外管局与BNM校对数据",
        "sourceValidation": source_validation,
        "externalSources": external_sources,
        "externalSourcePolicy": "铜铝锌内外盘比价沿用国内主连÷LME三个月电子盘且不换汇；风险溢价分别使用沪深300/标普500盈利收益率减对应10年期国债收益率；马盘棕榈油与豆油比价使用FCPO×人民币/林吉特÷国内豆油加权，外管局汇率以BNM最新值校对。所有跨日合并只向后匹配已公布值。",
        "period": "1d",
        "contractMode": "商品期货持仓量加权(JQ00)；股指及铜铝锌内外盘国内腿使用主力连续(00)；LME使用三个月行情；IM期限套展示当月对下季及隔季；外部股指与估值指标使用各源公布值",
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
    definitions_by_pair = {definition["pair"]: definition for definition in PAIRS}
    contract_rows_complete = all(
        (
            0 < len(row["contracts"]) <= 4
            and all(
                int(contract["expiry"][-2:]) in definitions_by_pair[row["pair"]]["contract_months"]
                for contract in row["contracts"]
            )
        )
        if definitions_by_pair[row["pair"]].get("contract_months")
        else (
            0 < len(row["contracts"]) <= 4
            if is_equity_index_definition(definitions_by_pair[row["pair"]])
            else len(row["contracts"]) == 4
        )
        for row in tradable_rows
    )
    commodity_tradable_rows = [
        row
        for row in tradable_rows
        if not is_equity_index_definition(definitions_by_pair[row["pair"]])
    ]
    equity_index_rows = [
        row
        for row in tradable_rows
        if is_equity_index_definition(definitions_by_pair[row["pair"]])
    ]
    weighted_rows = [row for row in tradable_rows if row["seriesMode"] == "weighted"]
    weighted_observation_history_charts = [
        row.get("mainHistoryChart") for row in weighted_rows
    ]
    weighted_observation_histories_complete = all(
        chart is not None
        and chart["title"].endswith("加权走势")
        and chart["endDate"] == data_date
        and len(chart["series"]) == 1
        and chart["series"][0]["expiry"] == "加权"
        and len(chart["series"][0]["points"]) >= 8
        and all(
            point["date"] <= data_date
            for point in chart["series"][0]["points"]
        )
        for chart in weighted_observation_history_charts
    )
    contract_history_charts = [
        contract.get("historyChart")
        for row in commodity_tradable_rows
        for contract in row["contracts"]
    ]
    contract_history_charts_complete = all(
        chart is not None
        and 1 <= len(chart["series"]) <= SEASONAL_CONTRACT_YEARS
        and sum(len(item["points"]) for item in chart["series"]) >= 8
        for chart in contract_history_charts
    )
    equity_index_contract_history_disabled = all(
        contract.get("historyChart") is None
        for row in equity_index_rows
        for contract in row["contracts"]
    )
    equity_index_observation_history_charts = [
        chart
        for row in equity_index_rows
        for chart in (
            row.get("mainHistoryChart"),
            (row.get("spotObservation") or {}).get("historyChart"),
        )
    ]
    equity_index_observation_histories_complete = all(
        chart is not None
        and len(chart["series"]) == 1
        and sum(len(item["points"]) for item in chart["series"]) >= 8
        for chart in equity_index_observation_history_charts
    )
    spot_reference_history_charts = [
        row.get("mainHistoryChart")
        for row in rows
        if row["pairType"] == "现货参考"
    ]
    spot_reference_histories_complete = all(
        chart is not None
        and len(chart["series"]) == 1
        and chart["series"][0]["expiry"] == "现货"
        and len(chart["series"][0]["points"]) >= 8
        for chart in spot_reference_history_charts
    )
    spot_observation_count = sum(row["spotObservation"] is not None for row in rows)
    term_structure_count = sum(
        row[side] is not None
        for row in tradable_rows
        for side in ("leftStructure", "rightStructure")
    )
    expected_term_structure_count = len(tradable_rows) * 2
    im_term_rows = [row for row in rows if row["pairType"] == "期限套利"]
    im_term_observations = (
        im_term_rows[0].get("termObservations", []) if im_term_rows else []
    )
    im_term_history_complete = (
        len(im_term_rows) == 1
        and im_term_rows[0]["pair"] == "IM期限套"
        and im_term_rows[0]["contracts"] == []
        and im_term_rows[0]["denominatorSymbol"] == IM_TERM_SPOT_SYMBOL
        and im_term_rows[0]["rollRule"] == "当月合约正常跟踪至到期，到期后自然切换为次月合约"
        and [item["key"] for item in im_term_observations]
        == ["term-down", "term-skip"]
        and [item["label"] for item in im_term_observations] == ["下季", "隔季"]
        and all(
            item["denominatorSymbol"] == IM_TERM_SPOT_SYMBOL
            and item["historyChart"] is not None
            and item["historyChart"]["endDate"] == data_date
            and len(item["historyChart"]["series"]) == 1
            and len(item["historyChart"]["series"][0]["points"]) >= 8
            and all(
                point["date"] <= data_date
                for point in item["historyChart"]["series"][0]["points"]
            )
            for item in im_term_observations
        )
    )
    charts_complete = len(charts) == len(HISTORY_CHARTS) and all(len(chart["points"]) >= 12 for chart in charts)
    cross_market_rows = [row for row in rows if row["pairType"] == "跨市场套利"]
    expected_cross_market_count = len(LME_CROSS_MARKET_PAIRS) + 1
    cross_market_rows_complete = (
        len(cross_market_rows) == expected_cross_market_count
        and all(
            row["mainHistoryChart"] is not None
            and row["sourceStatus"] == "外部补充"
            and row["externalSourceDate"] == data_date
            for row in cross_market_rows
        )
    )
    expected_external_symbols = {
        *(definition["lme_symbol"] for definition in LME_CROSS_MARKET_PAIRS),
        USD_CNY_MID_SYMBOL,
        CNY_MYR_MID_SYMBOL,
        CSI300_PE_SYMBOL,
        CN10Y_SYMBOL,
        US10Y_SYMBOL,
        SP500_PE_SYMBOL,
        NASDAQ_SYMBOL,
        SP500_SYMBOL,
        FCPO_SYMBOL,
    }
    external_sources_complete = (
        {source["symbol"] for source in external_sources} == expected_external_symbols
        and all(
            pd.Timestamp(source["endDate"]).date() <= now.date()
            and pd.Timestamp(source["endDate"])
            >= pd.Timestamp(data_date) - pd.Timedelta(days=int(source["maxLagDays"]))
            for source in external_sources
        )
    )
    hierarchy_sorted = [row["pair"] for row in rows] == [
        row["pair"] for row in sorted(rows, key=dashboard_row_sort_key)
    ]
    integrity_checks = [
        lag_days <= 4,
        len(rows) == len(PAIRS),
        contract_rows_complete,
        contract_history_charts_complete,
        weighted_observation_histories_complete,
        equity_index_contract_history_disabled,
        equity_index_observation_histories_complete,
        spot_reference_histories_complete,
        spot_observation_count == len(SPOT_OBSERVATIONS),
        term_structure_count == expected_term_structure_count,
        im_term_history_complete,
        charts_complete,
        cross_market_rows_complete,
        external_sources_complete,
        hierarchy_sorted,
    ]
    report = {
        "status": "ok" if all(integrity_checks) else "warning",
        "checkedAt": now.isoformat(timespec="seconds"),
        "dataDate": data_date,
        "calendarLagDays": lag_days,
        "pairCount": len(rows),
        "expectedPairCount": len(PAIRS),
        "hierarchySorted": hierarchy_sorted,
        "marketCategoryCounts": {
            category: sum(row["marketCategory"] == category for row in rows)
            for category in MARKET_CATEGORY_ORDER
        },
        "percentilesInRange": all(0 <= row["percentile"] <= 100 for row in rows),
        "contractRowsAvailable": all(len(row["contracts"]) > 0 for row in tradable_rows),
        "contractRowsComplete": contract_rows_complete,
        "contractRowCounts": {row["pair"]: len(row["contracts"]) for row in rows},
        "contractHistoryChartCount": sum(chart is not None for chart in contract_history_charts),
        "expectedContractHistoryChartCount": len(contract_history_charts),
        "contractHistoryChartsComplete": contract_history_charts_complete,
        "weightedObservationHistoryCount": sum(
            chart is not None for chart in weighted_observation_history_charts
        ),
        "expectedWeightedObservationHistoryCount": len(weighted_rows),
        "weightedObservationHistoriesComplete": weighted_observation_histories_complete,
        "equityIndexContractHistoryDisabled": equity_index_contract_history_disabled,
        "equityIndexObservationHistoryCount": sum(
            chart is not None for chart in equity_index_observation_history_charts
        ),
        "expectedEquityIndexObservationHistoryCount": len(equity_index_rows) * 2,
        "equityIndexObservationHistoriesComplete": equity_index_observation_histories_complete,
        "spotReferenceHistoryCount": sum(
            chart is not None for chart in spot_reference_history_charts
        ),
        "expectedSpotReferenceHistoryCount": len(spot_reference_history_charts),
        "spotReferenceHistoriesComplete": spot_reference_histories_complete,
        "spotObservationCount": spot_observation_count,
        "expectedSpotObservationCount": len(SPOT_OBSERVATIONS),
        "termStructureCount": term_structure_count,
        "expectedTermStructureCount": expected_term_structure_count,
        "imTermHistoryComplete": im_term_history_complete,
        "imTermHistoryPointCounts": {
            item["label"]: len(item["historyChart"]["series"][0]["points"])
            for item in im_term_observations
            if item.get("historyChart")
        },
        "imTermLatestNear": im_term_rows[0]["leftSymbol"] if im_term_rows else None,
        "imTermLatestFar": im_term_rows[0]["rightSymbol"] if im_term_rows else None,
        "imTermLatestSkipFar": (
            im_term_observations[1]["rightSymbol"]
            if len(im_term_observations) == 2
            else None
        ),
        "imTermSpotSymbol": IM_TERM_SPOT_SYMBOL,
        "imTermRollRule": (
            im_term_rows[0]["rollRule"] if im_term_rows else None
        ),
        "chartCount": len(charts),
        "expectedChartCount": len(HISTORY_CHARTS),
        "chartsComplete": charts_complete,
        "crossMarketPairCount": len(cross_market_rows),
        "expectedCrossMarketPairCount": expected_cross_market_count,
        "crossMarketRowsComplete": cross_market_rows_complete,
        "externalSources": external_sources,
        "externalSourcesComplete": external_sources_complete,
        "externalErrors": external_errors,
        "sourceValidation": source_validation["summary"],
        "akshareErrors": [] if xtdata_only else akshare_errors,
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
            "source": "xtdata+approved_external_sources",
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
    status = "external_source_unavailable" if isinstance(error, ExternalDataError) else "xtdata_unavailable"
    report = {
        "status": status,
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
            "status": status,
            "error": str(error),
            "updated_at": now,
        }
    )


def main() -> int:
    try:
        histories, monthly_histories, monthly_contracts, trading_calendar, port = fetch_history()
        required_symbols = {
            symbol for definition in PAIRS for symbol in definition_xt_symbols(definition)
        }
        common_latest_date = min(histories[symbol].index.max() for symbol in required_symbols)
        external_histories, external_sources, external_errors = fetch_external_market_history()
        xtdata_only = os.environ.get("ARBITRAGE_XTDATA_ONLY", "1").strip() != "0"
        if xtdata_only:
            akshare_errors: list[str] = []
            source_validation = build_xtdata_only_validation(histories, common_latest_date)
        else:
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
            external_histories,
            monthly_histories,
            monthly_contracts,
            trading_calendar,
            source_validation,
        )
        charts = build_history_charts(histories, pd.Timestamp(data_date))
        report = write_outputs(
            rows,
            charts,
            data_date,
            port,
            source_validation,
            akshare_errors,
            external_sources,
            external_errors,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] == "ok" else 2
    except Exception as error:
        record_failure(error)
        print(f"dashboard update failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
