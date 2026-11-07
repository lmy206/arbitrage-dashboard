"""Move the former IM term charts using the same model as the IC term charts."""
from __future__ import annotations
import contextlib
import hashlib
import importlib.util
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


def build_history_queries(*, dataset_reader, root, index_record, index_rows, metadata,
                          cutoff, lower_pct=9, upper_pct=12):
    project = Path(__file__).resolve().parents[1]
    script = project / "scripts/update_xtdata.py"
    spec = importlib.util.spec_from_file_location("im_original_term_model", script)
    original = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    spot = pd.Series({pd.Timestamp(r["date"]): float(r["close"]) for r in index_rows
                      if r["date"] <= cutoff}, name="000852.SH").sort_index()
    records = [index_record]
    monthly = {}
    with contextlib.closing(sqlite3.connect((Path(root) / "catalog.sqlite").as_uri() + "?mode=ro", uri=True)) as con:
        symbols = sorted({r[0] for r in con.execute(
            "SELECT symbol FROM datasets WHERE source='xtdata' AND period='1d' AND status='ok' AND symbol LIKE 'IM%.IF'")
            if re.fullmatch(r"IM\d{4}\.IF", r[0])})
    for symbol in symbols:
        record, rows = dataset_reader(symbol)
        records.append(record)
        frame = pd.DataFrame(rows)
        frame["date"] = pd.to_datetime(frame.date)
        frame["close"] = pd.to_numeric(frame.close)
        monthly[symbol] = frame.loc[frame.date <= cutoff].set_index("date")
    # Past exchange sessions are present in the verified index daily series.
    # Known future expiry dates resolve the original near-month roll rule without
    # fabricating future calendar sessions or using any future price.
    expiries = [pd.Timestamp(datetime.strptime(str(d["ExpireDate"]), "%Y%m%d"))
                for d in metadata["contracts"].values()]
    calendar = spot.index.union(pd.DatetimeIndex(expiries)).sort_values()
    definition = {"pair": "IM期限套", "left": "IM00.IF", "right": "IM00.IF", "kind": "ratio",
                  "term_root": "IM", "term_spot_symbol": "000852.SH", "term_spot_label": "中证1000",
                  "term_start_date": "2022-07-22"}
    queries, info = {}, {}
    now = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    for view in original.DATA_CONTRACT["imTerm"]["historyViews"]:
        query_id, label, rank = view["queryId"], view["label"], view["farRank"]
        values, legs = original.build_index_term_series(definition, {"000852.SH": spot}, monthly,
                                                       pd.Timestamp(cutoff), calendar, rank)
        expected = spot.index[(spot.index >= "2022-07-22") & (spot.index <= cutoff)]
        if not values.index.equals(expected):
            raise ValueError(f"IM {label} daily history has missing sessions")
        latest = legs[values.index[-1]]
        chart = original.build_observation_history_chart(definition, label, latest["nearSymbol"],
            latest["farSymbol"], values, pd.Timestamp(cutoff))
        title = f"IM期限套（当月-{label}）走势"
        rows = []
        for point in chart["series"][0]["points"]:
            leg = legs[pd.Timestamp(point["date"])]
            rows.append({"date": point["date"], "annualized(%)": point["value"] * 100,
                         "lower(%)": lower_pct, "upper(%)": upper_pct,
                         "rawAnnualizedRate": point["value"], "nearSymbol": leg["nearSymbol"],
                         "farSymbol": leg["farSymbol"], "monthGap": leg["monthGap"]})
        queries[query_id] = {"rows": rows, "source": {
            "name": title, "type": "file", "provider": "xtdata",
            "period": f"{chart['startDate']} — {chart['endDate']}", "executedAt": now,
            "freshness": now, "files": [r["path"] for r in records],
            "metricDefinitions": [{"label": "年化贴水率", "definition":
                f"(IM当月收盘−IM{label}收盘)×12÷合约自然月份差÷中证1000收盘×100%，按原IC/IM期限套换月和绘图算法计算。"}],
            "evidenceFlow": [
                {"title": "原图迁移", "detail": "复用套利看板update_xtdata.py的build_index_term_series及build_observation_history_chart，不改历史曲线或换月口径。"},
                {"title": "换月", "detail": original.INDEX_TERM_ROLL_RULE + "；远月沿用原im_far_quarter_period的下季/隔季选择。"},
                {"title": "绘图", "detail": chart["grain"] + f"；完整日线{len(values)}条，绘图{len(rows)}点。百分数显示为原值×100，固定参考线{lower_pct}%/{upper_pct}%。"},
                {"title": "模型版本", "detail": hashlib.sha256(script.read_bytes()).hexdigest()}],
            "caveats": ["滚动当月历史与上方所选具体组合独立；这是历史描述图，不是策略回测结果。"]},
            "methods": [{"language": "python", "code": "build_index_term_series -> build_observation_history_chart; display percentage = stored rate * 100"}]}
        info[query_id] = {"title": title, "startDate": chart["startDate"], "endDate": chart["endDate"],
                          "statisticsPointCount": len(values), "renderPointCount": len(rows),
                          "grain": chart["grain"], "status": "ok", "farRank": rank}
    return queries, info, records
