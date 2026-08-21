#!/usr/bin/env python
"""Backfill five years of expired and active futures contracts with xtdata only."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

import update_xtdata as dashboard


ROOT_INCEPTION_YEAR = {
    "IF00.IF": 2010,
    "IC00.IF": 2015,
    "IM00.IF": 2022,
    "a00.DF": 2000,
    "b00.DF": 2004,
    "OI00.ZF": 2013,
    "RM00.ZF": 2012,
    "rb00.SF": 2009,
    "hc00.SF": 2014,
    "cu00.SF": 2000,
    "al00.SF": 2000,
    "p00.DF": 2007,
    "SA00.ZF": 2019,
    "FG00.ZF": 2012,
    "j00.DF": 2011,
    "jm00.DF": 2013,
    "m00.DF": 2000,
    "y00.DF": 2006,
    "i00.DF": 2013,
    "au00.SF": 2008,
    "ag00.SF": 2012,
}

# Zhengzhou futures use three-digit YMM codes.  Xtdata resolves those codes to
# the current decade and does not expose the previous-decade contract under a
# distinct symbol, so pre-2020 monthly contracts cannot be addressed safely.
XTDATA_ADDRESSABLE_START_YEAR = {
    continuous: 2020
    for continuous in dashboard.CONTRACTS
    if continuous.endswith(".ZF")
}


def contract_symbol(continuous_symbol: str, year: int, month: int) -> str:
    stem, suffix = continuous_symbol.split(".", maxsplit=1)
    root = stem[:-2]
    if suffix == "ZF":
        code = f"{year % 10}{month:02d}"
    else:
        code = f"{year % 100:02d}{month:02d}"
    return f"{root}{code}.{suffix}"


def contract_expiry(symbol: str) -> str:
    stem, suffix = symbol.split(".", maxsplit=1)
    matching_roots = sorted(
        (
            continuous.split(".", maxsplit=1)[0][:-2]
            for continuous in dashboard.CONTRACTS
            if continuous.endswith(f".{suffix}")
            and stem.lower().startswith(
                continuous.split(".", maxsplit=1)[0][:-2].lower()
            )
        ),
        key=len,
        reverse=True,
    )
    if not matching_roots:
        raise ValueError(f"Unknown futures root: {symbol}")
    root = matching_roots[0]
    code = stem[len(root) :]
    if len(code) == 4:
        year = 2000 + int(code[:2])
        month = int(code[2:])
    else:
        decade = datetime.now(dashboard.SHANGHAI).year // 10 * 10
        year = decade + int(code[0])
        if year > datetime.now(dashboard.SHANGHAI).year + 2:
            year -= 10
        month = int(code[1:])
    return f"{year:04d}{month:02d}"


def read_existing(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists():
        return pd.DataFrame(columns=["close", "volume"])
    try:
        raw = pd.read_csv(csv_path, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame(columns=["close", "volume"])
    if "date" not in raw.columns or "close" not in raw.columns:
        return pd.DataFrame(columns=["close", "volume"])
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw["close"] = pd.to_numeric(raw["close"], errors="coerce")
    if "volume" not in raw.columns:
        raw["volume"] = 0
    raw["volume"] = pd.to_numeric(raw["volume"], errors="coerce").fillna(0)
    raw = raw.dropna(subset=["date", "close"])
    raw = raw[(raw["close"] > 0) & (raw["date"].dt.date <= datetime.now(dashboard.SHANGHAI).date())]
    return raw.drop_duplicates(subset=["date"], keep="last").set_index("date").sort_index()[["close", "volume"]]


def write_contract(symbol: str, frame: pd.DataFrame, updated_at: str) -> Path:
    dashboard.MARKET_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = dashboard.MARKET_DIR / f"{symbol.replace('.', '_')}.csv"
    temporary_path = csv_path.with_suffix(".tmp")
    frame.reset_index().to_csv(temporary_path, index=False, encoding="utf-8-sig")
    temporary_path.replace(csv_path)
    dashboard.update_catalog(symbol, frame, csv_path, updated_at)
    return csv_path


def chunks(items: list[str], size: int):
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def make_candidates(start_year: int, end_year: int) -> tuple[list[str], dict[str, str]]:
    candidates: list[str] = []
    roots: dict[str, str] = {}
    for continuous_symbol in dashboard.CONTRACTS:
        first_year = max(
            start_year,
            ROOT_INCEPTION_YEAR.get(continuous_symbol, start_year),
            XTDATA_ADDRESSABLE_START_YEAR.get(continuous_symbol, start_year),
        )
        for year in range(first_year, end_year + 1):
            for month in range(1, 13):
                symbol = contract_symbol(continuous_symbol, year, month)
                candidates.append(symbol)
                roots[symbol] = continuous_symbol
    return sorted(set(candidates)), roots


def validate_coverage(
    stored: dict[str, pd.DataFrame],
    roots_by_symbol: dict[str, str],
    start_year: int,
    current_year: int,
) -> tuple[dict[str, Any], dict[str, Any], bool, list[str]]:
    expiries_by_root: dict[str, set[str]] = defaultdict(set)
    future_data_detected = False
    invalid_files: list[str] = []
    today = datetime.now(dashboard.SHANGHAI).date()

    for symbol, frame in stored.items():
        if frame.empty:
            continue
        if frame.index.has_duplicates or frame["close"].isna().any() or (frame["close"] <= 0).any():
            invalid_files.append(symbol)
        if frame.index.max().date() > today:
            future_data_detected = True
        expiries_by_root[roots_by_symbol[symbol]].add(contract_expiry(symbol))

    root_coverage: dict[str, Any] = {}
    for continuous_symbol in dashboard.CONTRACTS:
        requested_first_year = max(
            start_year,
            ROOT_INCEPTION_YEAR.get(continuous_symbol, start_year),
        )
        addressable_first_year = max(
            requested_first_year,
            XTDATA_ADDRESSABLE_START_YEAR.get(continuous_symbol, requested_first_year),
        )
        expiries = sorted(expiries_by_root.get(continuous_symbol, set()))
        covered_years = {int(expiry[:4]) for expiry in expiries if int(expiry[:4]) <= current_year}
        first_available_year = min(covered_years) if covered_years else None
        required_years = (
            set(range(first_available_year, current_year + 1))
            if first_available_year is not None
            else set(range(addressable_first_year, current_year + 1))
        )
        unavailable_end = (first_available_year or addressable_first_year) - 1
        root_coverage[continuous_symbol] = {
            "contractCount": len(expiries),
            "firstExpiry": expiries[0] if expiries else None,
            "lastExpiry": expiries[-1] if expiries else None,
            "requestedFirstYear": requested_first_year,
            "addressableFirstYear": addressable_first_year,
            "firstAvailableYear": first_available_year,
            "coveredYears": sorted(covered_years),
            "missingYears": sorted(required_years - covered_years),
            "xtdataUnavailableYears": list(
                range(requested_first_year, unavailable_end + 1)
            ),
        }

    pair_coverage: dict[str, Any] = {}
    for definition in dashboard.PAIRS:
        if not definition.get("tradable", True):
            continue
        left = definition["left"]
        right = definition["right"]
        common = sorted(expiries_by_root.get(left, set()) & expiries_by_root.get(right, set()))
        left_first = root_coverage[left]["firstAvailableYear"]
        right_first = root_coverage[right]["firstAvailableYear"]
        first_year = max(year for year in (left_first, right_first) if year is not None)
        required_years = set(range(first_year, current_year + 1))
        common_years = {int(expiry[:4]) for expiry in common if int(expiry[:4]) <= current_year}
        pair_coverage[definition["pair"]] = {
            "left": left,
            "right": right,
            "commonContractCount": len(common),
            "firstAvailableYear": first_year,
            "commonYears": sorted(common_years),
            "missingYears": sorted(required_years - common_years),
        }

    return root_coverage, pair_coverage, future_data_detected, invalid_files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=2000)
    parser.add_argument("--end-year", type=int, default=datetime.now(dashboard.SHANGHAI).year + 1)
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--refresh-existing", action="store_true")
    args = parser.parse_args()

    current_year = datetime.now(dashboard.SHANGHAI).year
    history_start = f"{args.start_year - 1}0101"
    candidates, roots_by_symbol = make_candidates(args.start_year, args.end_year)
    stored: dict[str, pd.DataFrame] = {}
    pending: list[str] = []

    for symbol in candidates:
        csv_path = dashboard.MARKET_DIR / f"{symbol.replace('.', '_')}.csv"
        existing = read_existing(csv_path)
        if not existing.empty and not args.refresh_existing:
            stored[symbol] = existing
        else:
            pending.append(symbol)

    xtdata, port = dashboard.connect_xtdata()
    updated_at = datetime.now(dashboard.SHANGHAI).isoformat(timespec="seconds")
    empty_candidates: list[str] = []
    errors: list[dict[str, str]] = []

    total_batches = math.ceil(len(pending) / args.batch_size) if pending else 0
    for batch_number, batch in enumerate(chunks(pending, args.batch_size), start=1):
        print(f"batch {batch_number}/{total_batches}: {len(batch)} contracts", flush=True)
        raw = None
        last_error: Exception | None = None
        for attempt in range(1, args.retries + 2):
            try:
                xtdata.download_history_data2(
                    batch,
                    period="1d",
                    start_time=history_start,
                    end_time="",
                    callback=None,
                    incrementally=False,
                )
                raw = xtdata.get_market_data_ex(
                    field_list=["close", "volume"],
                    stock_list=batch,
                    period="1d",
                    start_time=history_start,
                    end_time="",
                    count=-1,
                    fill_data=False,
                )
                break
            except Exception as exc:
                last_error = exc
                print(
                    f"batch {batch_number} attempt {attempt} failed: {exc}",
                    flush=True,
                )
                if attempt <= args.retries:
                    time.sleep(2)
        if raw is None:
            errors.append(
                {"batch": str(batch_number), "error": str(last_error)}
            )
            continue

        for symbol in batch:
            frame = dashboard.normalize_market_frame(raw.get(symbol, pd.DataFrame()), include_volume=True)
            if frame.empty:
                empty_candidates.append(symbol)
                continue
            frame = frame[frame.index.date <= datetime.now(dashboard.SHANGHAI).date()]
            if frame.empty:
                empty_candidates.append(symbol)
                continue
            write_contract(symbol, frame, updated_at)
            stored[symbol] = frame

    root_coverage, pair_coverage, future_data_detected, invalid_files = validate_coverage(
        stored,
        roots_by_symbol,
        args.start_year,
        current_year,
    )
    missing_root_years = {
        root: detail["missingYears"]
        for root, detail in root_coverage.items()
        if detail["missingYears"]
    }
    missing_pair_years = {
        pair: detail["missingYears"]
        for pair, detail in pair_coverage.items()
        if detail["missingYears"]
    }
    status = "ok" if not errors and not invalid_files and not future_data_detected and not missing_root_years and not missing_pair_years else "warning"
    report = {
        "status": status,
        "availabilityStatus": (
            "xtdata_unavailable"
            if any(
                detail["xtdataUnavailableYears"]
                for detail in root_coverage.values()
            )
            else "complete"
        ),
        "availabilityNote": (
            "Only xtdata-addressable individual contracts are stored. "
            "Zhengzhou YMM codes before 2020 are decade-ambiguous, and several "
            "other products have no individual-contract rows before xtdata's "
            "first available year; continuous-contract data is not substituted."
        ),
        "checkedAt": datetime.now(dashboard.SHANGHAI).isoformat(timespec="seconds"),
        "source": "xtdata",
        "startYear": args.start_year,
        "endYear": args.end_year,
        "candidateContractCount": len(candidates),
        "preexistingContractCount": len(candidates) - len(pending),
        "downloadAttemptCount": len(pending),
        "storedContractCount": len(stored),
        "emptyCandidateCount": len(empty_candidates),
        "emptyCandidates": empty_candidates,
        "errors": errors,
        "futureDataDetected": future_data_detected,
        "invalidFiles": invalid_files,
        "missingRootYears": missing_root_years,
        "missingPairYears": missing_pair_years,
        "availabilityLimits": {
            root: detail["xtdataUnavailableYears"]
            for root, detail in root_coverage.items()
            if detail["xtdataUnavailableYears"]
        },
        "rootCoverage": root_coverage,
        "pairCoverage": pair_coverage,
        "xtdataPort": port,
    }
    dashboard.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = dashboard.REPORT_DIR / "arbitrage_historical_contracts_integrity.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dashboard.write_manifest(
        {
            "dataset_key": "xtdata:arbitrage-dashboard:historical-contracts:1d",
            "source": "xtdata",
            "status": status,
            "start_year": args.start_year,
            "end_year": args.end_year,
            "contract_count": len(stored),
            "report": str(report_path),
            "updated_at": report["checkedAt"],
        }
    )
    print(json.dumps({key: report[key] for key in ("status", "startYear", "endYear", "candidateContractCount", "preexistingContractCount", "downloadAttemptCount", "storedContractCount", "emptyCandidateCount", "futureDataDetected", "missingRootYears", "missingPairYears", "errors")}, ensure_ascii=False, indent=2))
    return 0 if status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
