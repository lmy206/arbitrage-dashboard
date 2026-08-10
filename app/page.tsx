"use client";

import { useMemo, useState } from "react";

type Signal = "偏高" | "中性" | "极度偏低";

type PairRow = {
  pair: string;
  current: string;
  previous: string;
  change: string;
  changeValue: number | null;
  allTime: string;
  percentile: number;
  signal: Signal;
  lots: string;
  deviation: string;
  notional: string;
  margin: string;
};

const rows: PairRow[] = [
  { pair: "IC/IM比价", current: "1.0391", previous: "1.0391", change: "-", changeValue: null, allTime: "94.42%", percentile: 86.41, signal: "偏高", lots: "26:27", deviation: "0.07%", notional: "8297万", margin: "995.6万" },
  { pair: "豆一豆二比", current: "1.2870", previous: "1.2762", change: "+0.0108", changeValue: 0.0108, allTime: "-", percentile: 79.0, signal: "偏高", lots: "7:9", deviation: "0.1%", notional: "69万", margin: "5.5万" },
  { pair: "菜油菜粕比", current: "4.652", previous: "4.668", change: "-0.0159", changeValue: -0.0159, allTime: "-", percentile: 71.74, signal: "中性", lots: "3:14", deviation: "0.31%", notional: "61万", margin: "4.9万" },
  { pair: "IC/IF比价", current: "1.6999", previous: "1.6999", change: "-", changeValue: null, allTime: "70.46%", percentile: 68.7, signal: "中性", lots: "5:6", deviation: "2.86%", notional: "1643万", margin: "197.2万" },
  { pair: "螺卷差", current: "238", previous: "235", change: "+3.0000", changeValue: 3, allTime: "-", percentile: 64.0, signal: "中性", lots: "25:27", deviation: "0.05%", notional: "162万", margin: "19.4万" },
  { pair: "铜铝比", current: "4.463", previous: "4.509", change: "-0.0461", changeValue: -0.0461, allTime: "-", percentile: 58.52, signal: "中性", lots: "2:9", deviation: "0.82%", notional: "217万", margin: "26.0万" },
  { pair: "棕榈油菜油比", current: "0.9601", previous: "0.9525", change: "+0.0076", changeValue: 0.0076, allTime: "-", percentile: 57.79, signal: "中性", lots: "25:24", deviation: "0.01%", notional: "485万", margin: "38.8万" },
  { pair: "IM/IF比价", current: "1.6359", previous: "1.6359", change: "-", changeValue: null, allTime: "27.47%", percentile: 57.16, signal: "中性", lots: "5:6", deviation: "4.78%", notional: "1613万", margin: "193.6万" },
  { pair: "纯碱玻璃比", current: "1.087", previous: "1.061", change: "+0.0256", changeValue: 0.0256, allTime: "-", percentile: 48.33, signal: "中性", lots: "23:25", deviation: "0.03%", notional: "89万", margin: "10.7万" },
  { pair: "焦炭焦煤比", current: "1.464", previous: "1.474", change: "-0.0097", changeValue: -0.0097, allTime: "-", percentile: 44.08, signal: "中性", lots: "9:22", deviation: "0.15%", notional: "336万", margin: "40.3万" },
  { pair: "豆粕豆油比", current: "0.373", previous: "0.374", change: "-0.0008", changeValue: -0.0008, allTime: "-", percentile: 40.92, signal: "中性", lots: "8:3", deviation: "0.6%", notional: "51万", margin: "4.0万" },
  { pair: "豆油菜油比", current: "0.8350", previous: "0.8323", change: "+0.0027", changeValue: 0.0027, allTime: "-", percentile: 33.75, signal: "中性", lots: "6:5", deviation: "0.2%", notional: "101万", margin: "8.1万" },
  { pair: "矿螺比", current: "0.234", previous: "0.238", change: "-0.0041", changeValue: -0.0041, allTime: "-", percentile: 33.63, signal: "中性", lots: "3:7", deviation: "0.31%", notional: "42万", margin: "5.0万" },
  { pair: "金银比", current: "60.38", previous: "59.91", change: "+0.4614", changeValue: 0.4614, allTime: "-", percentile: 25.47, signal: "中性", lots: "1:4", deviation: "0.62%", notional: "189万", margin: "22.7万" },
  { pair: "豆粕价差", current: "-1265", previous: "-1219", change: "-46.0000", changeValue: -46, allTime: "-", percentile: 5.88, signal: "极度偏低", lots: "23:20", deviation: "0.02%", notional: "388万", margin: "31.1万" },
];

type SortKey = "pair" | "current" | "previous" | "change" | "allTime" | "percentile" | "lots" | "deviation" | "notional" | "margin";

const columns: { key: SortKey | "bar" | "signal"; label: string }[] = [
  { key: "pair", label: "品种对" },
  { key: "current", label: "当前值" },
  { key: "previous", label: "前日值" },
  { key: "change", label: "变动" },
  { key: "allTime", label: "全历史分位" },
  { key: "percentile", label: "近3年分位" },
  { key: "bar", label: "分位条" },
  { key: "signal", label: "判断" },
  { key: "lots", label: "平衡手数" },
  { key: "deviation", label: "偏差" },
  { key: "notional", label: "总名义值" },
  { key: "margin", label: "保证金" },
];

function numericValue(row: PairRow, key: SortKey) {
  if (key === "pair") return row.pair;
  if (key === "change") return row.changeValue ?? Number.NEGATIVE_INFINITY;
  if (key === "percentile") return row.percentile;
  if (key === "lots") return Number(row.lots.split(":")[0]);
  const value = row[key];
  return Number.parseFloat(value.replace(/[%,万]/g, "")) || Number.NEGATIVE_INFINITY;
}

export default function Home() {
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("percentile");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");

  const visibleRows = useMemo(() => {
    const filtered = rows.filter((row) => row.pair.toLowerCase().includes(query.trim().toLowerCase()));
    return [...filtered].sort((a, b) => {
      const av = numericValue(a, sortKey);
      const bv = numericValue(b, sortKey);
      const result = typeof av === "string" && typeof bv === "string" ? av.localeCompare(bv, "zh-CN") : Number(av) - Number(bv);
      return sortDirection === "asc" ? result : -result;
    });
  }, [query, sortDirection, sortKey]);

  function updateSort(key: SortKey) {
    if (key === sortKey) setSortDirection((direction) => (direction === "desc" ? "asc" : "desc"));
    else {
      setSortKey(key);
      setSortDirection(key === "pair" ? "asc" : "desc");
    }
  }

  return (
    <main className="dashboard-shell">
      <section className="dashboard" aria-labelledby="dashboard-title">
        <header className="dashboard-header">
          <div>
            <div className="eyebrow">ARBITRAGE MONITOR</div>
            <h1 id="dashboard-title">套利监测看板</h1>
            <p>跟踪跨品种比价、价差与历史分位</p>
          </div>
          <div className="update-status" aria-label="数据更新时间">
            <span className="status-dot" aria-hidden="true" />
            <div>
              <strong>每日 20:00 更新</strong>
              <span>当前为示例快照</span>
            </div>
          </div>
        </header>

        <div className="toolbar">
          <label className="search-field">
            <span aria-hidden="true">⌕</span>
            <span className="sr-only">搜索品种对</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索品种对"
              type="search"
            />
          </label>
          <div className="legend" aria-label="判断图例">
            <span><i className="legend-dot high" />偏高</span>
            <span><i className="legend-dot neutral" />中性</span>
            <span><i className="legend-dot low" />偏低</span>
            <b>{visibleRows.length} 组</b>
          </div>
        </div>

        <div className="table-frame">
          <table>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column.key} scope="col">
                    {column.key === "bar" || column.key === "signal" ? (
                      column.label
                    ) : (
                      <button type="button" onClick={() => updateSort(column.key)} aria-label={`按${column.label}排序`}>
                        {column.label}
                        <span className={`sort-mark ${sortKey === column.key ? "active" : ""}`} aria-hidden="true">
                          {sortKey === column.key ? (sortDirection === "desc" ? "↓" : "↑") : "↕"}
                        </span>
                      </button>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((row) => (
                <tr key={row.pair}>
                  <th scope="row">{row.pair}</th>
                  <td className="tabular current-value">{row.current}</td>
                  <td className="tabular muted">{row.previous}</td>
                  <td className={`tabular change ${row.changeValue === null ? "flat" : row.changeValue > 0 ? "up" : "down"}`}>{row.change}</td>
                  <td className="tabular">{row.allTime}</td>
                  <td className="tabular percentile-value">{row.percentile.toFixed(row.percentile % 1 === 0 ? 1 : 2)}%</td>
                  <td>
                    <div className="percentile-track" aria-label={`近3年分位 ${row.percentile}%`}>
                      <span className={`percentile-fill ${row.signal === "偏高" ? "high" : row.signal === "极度偏低" ? "low" : "neutral"}`} style={{ width: `${Math.max(row.percentile, 4)}%` }} />
                    </div>
                  </td>
                  <td><span className={`signal ${row.signal === "偏高" ? "high" : row.signal === "极度偏低" ? "low" : "neutral"}`}>{row.signal}</span></td>
                  <td className="tabular">{row.lots}</td>
                  <td className="tabular">{row.deviation}</td>
                  <td className="tabular">{row.notional}</td>
                  <td className="tabular">{row.margin}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {visibleRows.length === 0 && <div className="empty-state">没有匹配的品种对</div>}
        </div>

        <footer className="dashboard-footer">
          <span>分位值越接近 100%，当前比价越处于近三年高位。</span>
          <span>数据时间：每日 20:00</span>
        </footer>
      </section>
    </main>
  );
}
