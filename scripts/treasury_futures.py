"""Same-quarter TL/T prices and DV01-neutral quantities; no notional fallback."""

import json
import math
from pathlib import Path

import pandas as pd


def balance_dv01(tl_dv01: float, t_dv01: float, max_lots: int = 20) -> dict:
    if not all(math.isfinite(value) and value > 0 for value in (tl_dv01, t_dv01)):
        raise ValueError("DV01必须为每手人民币/bp的有效正数")
    candidates = []
    for tl_lots in range(1, max_lots + 1):
        for t_lots in range(1, max_lots + 1):
            left, right = tl_dv01 * tl_lots, t_dv01 * t_lots
            error = abs(left - right) / ((left + right) / 2) * 100
            candidates.append((error, tl_lots + t_lots, max(tl_lots, t_lots), tl_lots, t_lots))
    error, _, _, tl_lots, t_lots = min(candidates)
    return {"tlLots": tl_lots, "tLots": t_lots, "lots": f"{tl_lots}:{t_lots}",
            "dv01DeviationPct": round(error, 6), "tlDv01PerLot": tl_dv01, "tDv01PerLot": t_dv01}


def verified_contract_dv01(record: dict | None, symbol: str, data_date: str) -> float | None:
    if not record or record.get("source") not in {"xtdata", "chinabond", "user_verified"} or record.get("unit") != "CNY/contract/bp" or record.get("status") != "verified" or record.get("dataDate") != data_date:
        return None
    try:
        leg = record["contracts"][symbol]
        if not leg.get("ctdSymbol") or leg.get("dataDate", data_date) != data_date:
            return None
        ctd, factor, futures = (float(leg[key]) for key in ("ctdDv01PerLot", "conversionFactor", "dv01PerLot"))
        if not all(math.isfinite(value) and value > 0 for value in (ctd, factor, futures)):
            return None
        if abs(ctd / factor - futures) > max(1e-6, abs(futures) * 1e-6):
            return None
        return futures
    except (KeyError, TypeError, ValueError):
        return None


def load_verified_risk(root: Path, data_date: str) -> dict | None:
    path = root / "market/treasury_futures_hedge/dv01" / f"{data_date}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def build_quarter_ratios(monthly_contracts: dict, histories: dict, asof: pd.Timestamp, risk: dict | None = None) -> list[dict]:
    tl_months, t_months = monthly_contracts.get("TL00.IF", {}), monthly_contracts.get("T00.IF", {})
    result = []
    for expiry in sorted(set(tl_months) & set(t_months)):
        if int(expiry[-2:]) not in (3, 6, 9, 12) or expiry < asof.strftime("%y%m"):
            continue
        tl_symbol, t_symbol = tl_months[expiry], t_months[expiry]
        row = {"expiry": expiry, "leftSymbol": tl_symbol, "rightSymbol": t_symbol,
               "formulaLabel": f"{tl_symbol} / {t_symbol}", "source": "xtdata",
               "current": "—", "previous": "—", "change": "—", "ratio": None,
               "leftPrice": None, "rightPrice": None, "priceDate": None,
               "priceStatus": "unavailable", "leftVolume": None, "rightVolume": None,
               "hedge": {"method": "dv01", "status": "xtdata_unavailable", "lots": "待DV01",
                         "dv01DeviationPct": None, "reason": "缺少该季度同日的已核验CTD/DV01"}}
        tl, t = histories.get(tl_symbol), histories.get(t_symbol)
        if tl is not None and t is not None:
            aligned = pd.concat([tl["close"].rename("tl"), t["close"].rename("t")], axis=1, join="inner")
            aligned = aligned.loc[aligned.index <= asof].replace([math.inf, -math.inf], float("nan")).dropna().sort_index()
            aligned = aligned[(aligned["tl"] > 0) & (aligned["t"] > 0) & (aligned["tl"] < 1e100) & (aligned["t"] < 1e100)]
            if not aligned.empty:
                date = aligned.index[-1]
                ratio = float(aligned.iloc[-1]["tl"] / aligned.iloc[-1]["t"])
                row.update({"leftPrice": float(aligned.iloc[-1]["tl"]), "rightPrice": float(aligned.iloc[-1]["t"]),
                            "ratio": round(ratio, 8), "current": f"{ratio:.4f}", "priceDate": date.strftime("%Y-%m-%d"),
                            "priceStatus": "ok" if date == asof else "stale"})
                if len(aligned) >= 2:
                    previous = float(aligned.iloc[-2]["tl"] / aligned.iloc[-2]["t"])
                    row.update({"previous": f"{previous:.4f}", "change": f"{ratio - previous:+.4f}"})
                for frame, key in ((tl, "leftVolume"), (t, "rightVolume")):
                    if "volume" in frame and date in frame.index and pd.notna(frame.loc[date, "volume"]):
                        row[key] = max(0, int(frame.loc[date, "volume"]))
                if date == asof:
                    tl_dv01 = verified_contract_dv01(risk, tl_symbol, row["priceDate"])
                    t_dv01 = verified_contract_dv01(risk, t_symbol, row["priceDate"])
                    if tl_dv01 is not None and t_dv01 is not None:
                        row["hedge"] = {"method": "dv01", "status": "verified", "dataDate": row["priceDate"],
                                        "reason": "CTD DV01 / 转换因子，按每手利率风险配平", **balance_dv01(tl_dv01, t_dv01)}
        result.append(row)
    return result


def quarter_ratios_complete(rows: list[dict], data_date: str) -> bool:
    if not rows or len({r["expiry"] for r in rows}) != len(rows):
        return False
    for row in rows:
        if int(row["expiry"][-2:]) not in (3, 6, 9, 12) or row["hedge"]["method"] != "dv01":
            return False
        if row["leftSymbol"] != f"TL{row['expiry']}.IF" or row["rightSymbol"] != f"T{row['expiry']}.IF":
            return False
        if row["priceStatus"] == "unavailable":
            if row["ratio"] is not None or row["current"] != "—":
                return False
        else:
            if not row["priceDate"] or row["priceDate"] > data_date:
                return False
            if row["priceStatus"] == "ok" and row["priceDate"] != data_date:
                return False
            if not row["leftPrice"] or not row["rightPrice"] or abs(row["ratio"] - row["leftPrice"] / row["rightPrice"]) > 1e-8:
                return False
        hedge = row["hedge"]
        if hedge["status"] == "verified":
            if hedge["lots"] != balance_dv01(hedge["tlDv01PerLot"], hedge["tDv01PerLot"])["lots"]:
                return False
        elif hedge["status"] != "xtdata_unavailable" or hedge["lots"] != "待DV01" or hedge["dv01DeviationPct"] is not None:
            return False
    return True
