"""Independently audit displayed-month term structures against shared xtdata CSVs."""

import argparse
import json
import math
import os
from pathlib import Path

import pandas as pd


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else {"rows": []}
    prior = {row["pair"]: row for row in baseline["rows"]}
    root = Path(os.environ.get("E_SHARED_DATA_ROOT", r"E:\data")) / "market" / "futures_daily"
    frames = {}
    records, errors = [], []
    checked_legs = classified_pairs = changed_labels = 0
    for row in snapshot["rows"]:
        contracts = row.get("contracts", [])
        record = {"pair": row["pair"], "pairType": row["pairType"], "displayedMonths": [c["expiry"] for c in contracts], "legs": []}
        if len(contracts) >= 2:
            classified_pairs += 1
        for side in ("left", "right", "third"):
            if side == "third" and not row.get("thirdSymbol"):
                continue
            structure = row.get(side + "Structure")
            previous = prior.get(row["pair"], {}).get(side + "Structure")
            old_state = previous.get("state") if previous else None
            new_state = structure.get("state") if structure else None
            if args.baseline and old_state != new_state:
                changed_labels += 1
            entry = {"side": side, "previousState": old_state, "state": new_state}
            try:
                if len(contracts) < 2:
                    assert structure is None, "Structure exists without two displayed months"
                    entry["applicable"] = False
                else:
                    checked_legs += 1
                    curve = []
                    for contract in contracts:
                        symbol = contract[side + "Symbol"]
                        if symbol not in frames:
                            frames[symbol] = pd.read_csv(root / (symbol.replace(".", "_") + ".csv"), parse_dates=["date"], float_precision="round_trip").set_index("date")
                        price = float(frames[symbol].loc[pd.Timestamp(snapshot["dataDate"]), "close"])
                        assert math.isfinite(price) and price > 0, "Invalid closing price"
                        curve.append({"expiry": contract["expiry"], "symbol": symbol, "price": round(price, 6)})
                    prices = pd.Series([point["price"] for point in curve])
                    moves = prices.diff().dropna()
                    directions = set(1 if value > 1e-8 else -1 if value < -1e-8 else 0 for value in moves) - {0}
                    expected = "平坦" if not directions else "Contango" if directions == {1} else "Back" if directions == {-1} else "混合"
                    assert structure and structure["scope"] == "displayed_contracts", "Incorrect scope"
                    assert structure["curve"] == curve, "Curve differs from displayed months or raw quotes"
                    assert structure["contractCount"] == len(contracts), "Incorrect contract count"
                    assert structure["state"] == expected, "Incorrect direction summary"
                    assert structure["nearExpiry"] == curve[0]["expiry"] and structure["farExpiry"] == curve[-1]["expiry"], "Incorrect endpoints"
                    assert structure["nearPrice"] == curve[0]["price"] and structure["farPrice"] == curve[-1]["price"], "Incorrect endpoint prices"
                    expected_change = (prices.iloc[-1] / prices.iloc[0] - 1) * 100
                    assert abs(structure["changePct"] - expected_change) < 0.00011, "Incorrect endpoint percentage"
                    entry.update({"applicable": True, "curve": curve, "expectedState": expected})
            except Exception as error:
                entry["error"] = str(error)
                errors.append({"pair": row["pair"], "side": side, "error": str(error)})
            record["legs"].append(entry)
        records.append(record)
    report = {
        "status": "ok" if not errors else "failed", "source": "xtdata shared futures daily CSVs",
        "dataDate": snapshot["dataDate"], "snapshotUpdatedAt": snapshot["updatedAt"],
        "checkedPairs": len(records), "classifiedPairs": classified_pairs, "checkedLegs": checked_legs,
        "pairsWithoutTwoDisplayedMonths": len(records) - classified_pairs,
        "changedLabels": changed_labels if args.baseline else None, "errors": errors, "rows": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, ensure_ascii=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
