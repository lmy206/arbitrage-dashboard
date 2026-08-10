"use client";

import { useMemo, useState } from "react";
import dashboardData from "./data/arbitrage.json";

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
  leftSymbol: string;
  rightSymbol: string;
};

const rows: PairRow[] = dashboardData.rows.map((row) => ({
  ...row,
  signal: row.signal as Signal,
}));

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
              <span>{dashboardData.dataDate} · xtdata</span>
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
            <b>{visibleRows.length} 组 · {dashboardData.contractMode}</b>
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
                <tr key={row.pair} title={`${row.leftSymbol} / ${row.rightSymbol}`}>
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
          <span>保证金：中金所组合取较大单边；其他组合两腿相加。</span>
          <span>数据日：{dashboardData.dataDate} · 更新时间：每日 20:00</span>
        </footer>
      </section>
    </main>
  );
}
