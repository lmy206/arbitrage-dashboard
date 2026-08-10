"use client";

import { Fragment, useMemo, useState } from "react";
import dashboardData from "./data/arbitrage.json";

type Signal = "偏高" | "中性" | "极度偏低";

type ContractRow = {
  expiry: string;
  current: string;
  leftSymbol: string;
  rightSymbol: string;
  leftVolume: number;
  rightVolume: number;
  pairedVolume: number;
};

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
  contracts: ContractRow[];
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
  const [expandedPairs, setExpandedPairs] = useState<Set<string>>(() => new Set());

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

  function togglePair(pair: string) {
    setExpandedPairs((current) => {
      const next = new Set(current);
      if (next.has(pair)) next.delete(pair);
      else next.add(pair);
      return next;
    });
  }

  function formatVolume(value: number) {
    return value.toLocaleString("zh-CN");
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
              {visibleRows.map((row) => {
                const isExpanded = expandedPairs.has(row.pair);
                const detailId = `contracts-${row.pair.replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, "-")}`;
                return (
                  <Fragment key={row.pair}>
                    <tr className={`pair-row ${isExpanded ? "expanded" : ""}`} title={`${row.leftSymbol} / ${row.rightSymbol}`}>
                      <th scope="row">
                        <div className="pair-cell">
                          <button
                            type="button"
                            className="expand-button"
                            aria-expanded={isExpanded}
                            aria-controls={detailId}
                            aria-label={`${isExpanded ? "收起" : "展开"}${row.pair}合约月份`}
                            onClick={() => togglePair(row.pair)}
                          >
                            {isExpanded ? "−" : "+"}
                          </button>
                          <span>{row.pair}</span>
                        </div>
                      </th>
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
                    {isExpanded && (
                      <tr className="contract-detail-row">
                        <td colSpan={columns.length} id={detailId}>
                          <div className="contract-panel" aria-label={`${row.pair}成交量前四的合约月份`}>
                            <div className="contract-grid contract-grid-header">
                              <span>合约月</span>
                              <span>当前值</span>
                              <span>{row.leftSymbol.split("00")[0]} 成交量</span>
                              <span>{row.rightSymbol.split("00")[0]} 成交量</span>
                              <span>可配对成交量 ↓</span>
                            </div>
                            {row.contracts.map((contract) => (
                              <div className="contract-grid" key={`${row.pair}-${contract.expiry}`}>
                                <strong className="tabular">{contract.expiry}</strong>
                                <span className="tabular contract-current">{contract.current}</span>
                                <span className="tabular" title={contract.leftSymbol}>{formatVolume(contract.leftVolume)}</span>
                                <span className="tabular" title={contract.rightSymbol}>{formatVolume(contract.rightVolume)}</span>
                                <span className="tabular paired-volume">{formatVolume(contract.pairedVolume)}</span>
                              </div>
                            ))}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
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
