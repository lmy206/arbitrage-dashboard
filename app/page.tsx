"use client";

import { Fragment, useMemo, useRef, useState } from "react";
import dashboardData from "./data/arbitrage.json";

type Signal = "偏高" | "中性" | "极度偏低";
type SourceStatus = "双源一致" | "口径不同" | "仅xtdata" | "需复核" | "待校验";

type ContractRow = {
  expiry: string;
  current: string;
  leftSymbol: string;
  rightSymbol: string;
  leftVolume: number;
  rightVolume: number;
  pairedVolume: number;
};

type ChartPoint = {
  date: string;
  value: number;
};

type HistoryChartData = {
  id: string;
  pair: string;
  title: string;
  unit: "比值" | "点差";
  grain: string;
  source: string;
  current: string;
  percentile: number;
  startDate: string;
  endDate: string;
  points: ChartPoint[];
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
  pairType: "期货套利" | "现货参考";
  sourceStatus: SourceStatus;
  contracts: ContractRow[];
};

const rows: PairRow[] = dashboardData.rows.map((row) => ({
  ...row,
  signal: row.signal as Signal,
  sourceStatus: row.sourceStatus as SourceStatus,
}));
const historyCharts: HistoryChartData[] = dashboardData.charts as HistoryChartData[];

type SortKey = "pair" | "current" | "previous" | "change" | "allTime" | "percentile" | "lots" | "deviation" | "notional" | "margin";

const columns: { key: SortKey | "bar" | "signal" | "source"; label: string }[] = [
  { key: "pair", label: "品种对" },
  { key: "current", label: "当前值" },
  { key: "previous", label: "前日值" },
  { key: "change", label: "变动" },
  { key: "allTime", label: "全历史分位" },
  { key: "percentile", label: "近3年分位" },
  { key: "bar", label: "分位条" },
  { key: "signal", label: "判断" },
  { key: "source", label: "校验" },
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
  const parsed = Number.parseFloat(value.replace(/[%,万]/g, ""));
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}

function sourceStatusClass(status: SourceStatus) {
  if (status === "双源一致") return "consistent";
  if (status === "口径不同") return "contract-mismatch";
  if (status === "需复核") return "review";
  if (status === "仅xtdata") return "primary-only";
  return "pending";
}

function formatChartNumber(value: number) {
  if (Math.abs(value) >= 100) return value.toFixed(0);
  if (Math.abs(value) >= 10) return value.toFixed(2);
  return value.toFixed(4);
}

function HistoryLineChart({ chart }: { chart: HistoryChartData }) {
  const width = 640;
  const height = 250;
  const inset = { top: 18, right: 22, bottom: 30, left: 54 };
  const plotWidth = width - inset.left - inset.right;
  const plotHeight = height - inset.top - inset.bottom;
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const values = chart.points.map((point) => point.value);
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const rawRange = rawMax - rawMin || Math.max(Math.abs(rawMax) * 0.1, 1);
  const yMin = rawMin - rawRange * 0.08;
  const yMax = rawMax + rawRange * 0.08;
  const x = (index: number) => inset.left + (index / Math.max(chart.points.length - 1, 1)) * plotWidth;
  const y = (value: number) => inset.top + ((yMax - value) / (yMax - yMin)) * plotHeight;
  const linePath = chart.points.map((point, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(2)},${y(point.value).toFixed(2)}`).join(" ");
  const yTicks = Array.from({ length: 5 }, (_, index) => yMin + ((yMax - yMin) * index) / 4);
  const xTickIndexes = Array.from(new Set([0, Math.floor((chart.points.length - 1) / 4), Math.floor((chart.points.length - 1) / 2), Math.floor(((chart.points.length - 1) * 3) / 4), chart.points.length - 1]));
  const hoveredPoint = hoveredIndex === null ? null : chart.points[hoveredIndex];

  function updateHover(clientX: number) {
    const bounds = svgRef.current?.getBoundingClientRect();
    if (!bounds) return;
    const viewBoxX = ((clientX - bounds.left) / bounds.width) * width;
    const index = Math.round(((viewBoxX - inset.left) / plotWidth) * (chart.points.length - 1));
    setHoveredIndex(Math.max(0, Math.min(chart.points.length - 1, index)));
  }

  return (
    <article className={`chart-card history-chart ${chart.unit === "点差" ? "spread-chart" : "ratio-chart"}`}>
      <header className="chart-card-header">
        <div>
          <h3>{chart.title}</h3>
          <p>{chart.startDate}—{chart.endDate} · {chart.grain} · {chart.source}</p>
        </div>
        <div className="chart-kpi">
          <strong className="tabular">{chart.current}</strong>
          <span>近3年 {chart.percentile.toFixed(2)}%</span>
        </div>
      </header>
      <svg
        ref={svgRef}
        className="line-chart"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${chart.title}，${chart.startDate}至${chart.endDate}，当前值${chart.current}`}
        onPointerMove={(event) => updateHover(event.clientX)}
        onPointerLeave={() => setHoveredIndex(null)}
      >
        <title>{chart.title}</title>
        {yTicks.map((tick) => (
          <g key={tick}>
            <line className="chart-grid-line" x1={inset.left} x2={width - inset.right} y1={y(tick)} y2={y(tick)} />
            <text className="chart-axis-label" x={inset.left - 9} y={y(tick) + 3} textAnchor="end">{formatChartNumber(tick)}</text>
          </g>
        ))}
        {chart.unit === "点差" && yMin < 0 && yMax > 0 && (
          <line className="chart-zero-line" x1={inset.left} x2={width - inset.right} y1={y(0)} y2={y(0)} />
        )}
        {xTickIndexes.map((index) => (
          <text key={index} className="chart-axis-label" x={x(index)} y={height - 8} textAnchor={index === 0 ? "start" : index === chart.points.length - 1 ? "end" : "middle"}>
            {chart.points[index].date}
          </text>
        ))}
        <path className="history-line" d={linePath} />
        <circle className="history-endpoint" cx={x(chart.points.length - 1)} cy={y(chart.points[chart.points.length - 1].value)} r="4" />
        {hoveredPoint && hoveredIndex !== null && (
          <g className="chart-hover">
            <line x1={x(hoveredIndex)} x2={x(hoveredIndex)} y1={inset.top} y2={height - inset.bottom} />
            <circle cx={x(hoveredIndex)} cy={y(hoveredPoint.value)} r="4" />
            <g transform={`translate(${Math.min(Math.max(x(hoveredIndex) - 50, inset.left), width - inset.right - 100)}, ${Math.max(y(hoveredPoint.value) - 48, inset.top)})`}>
              <rect width="100" height="37" rx="5" />
              <text x="8" y="14">{hoveredPoint.date}</text>
              <text x="8" y="29">{formatChartNumber(hoveredPoint.value)}</text>
            </g>
          </g>
        )}
      </svg>
    </article>
  );
}

export default function Home() {
  const [query, setQuery] = useState("");
  const [pairTypeFilter, setPairTypeFilter] = useState<"全部" | PairRow["pairType"]>("全部");
  const [sortKey, setSortKey] = useState<SortKey>("percentile");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [expandedPairs, setExpandedPairs] = useState<Set<string>>(() => new Set());

  const visibleRows = useMemo(() => {
    const filtered = rows.filter(
      (row) =>
        row.pair.toLowerCase().includes(query.trim().toLowerCase()) &&
        (pairTypeFilter === "全部" || row.pairType === pairTypeFilter),
    );
    return [...filtered].sort((a, b) => {
      const av = numericValue(a, sortKey);
      const bv = numericValue(b, sortKey);
      const result = typeof av === "string" && typeof bv === "string" ? av.localeCompare(bv, "zh-CN") : Number(av) - Number(bv);
      return sortDirection === "asc" ? result : -result;
    });
  }, [pairTypeFilter, query, sortDirection, sortKey]);

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
              <span>{dashboardData.dataDate} · 双源校验</span>
            </div>
          </div>
        </header>

        <div className="toolbar">
          <div className="toolbar-controls">
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
            <div className="pair-type-filter" aria-label="品种对类型筛选">
              {(["全部", "期货套利", "现货参考"] as const).map((filter) => (
                <button
                  type="button"
                  key={filter}
                  aria-pressed={pairTypeFilter === filter}
                  onClick={() => setPairTypeFilter(filter)}
                >
                  {filter === "期货套利" ? "期货" : filter === "现货参考" ? "指数" : filter}
                </button>
              ))}
            </div>
          </div>
          <div className="legend" aria-label="判断图例">
            <span><i className="legend-dot high" />偏高</span>
            <span><i className="legend-dot neutral" />中性</span>
            <span><i className="legend-dot low" />偏低</span>
            <b>{visibleRows.length} 组</b>
          </div>
        </div>

        <details className="source-audit">
          <summary>
            <div className="source-audit-title">
              <span className={`audit-dot ${dashboardData.sourceValidation.summary.review > 0 ? "warning" : dashboardData.sourceValidation.summary.contractMismatch > 0 ? "scope" : "ok"}`} aria-hidden="true" />
              <strong>数据源校验</strong>
              <span>xtdata 主值 · AkShare 补充校对</span>
            </div>
            <div className="audit-summary">
              <span className="audit-count consistent">一致 {dashboardData.sourceValidation.summary.consistent}</span>
              <span className="audit-count contract-mismatch">主力口径不同 {dashboardData.sourceValidation.summary.contractMismatch}</span>
              <span className={`audit-count ${dashboardData.sourceValidation.summary.review > 0 ? "review" : "quiet"}`}>异常 {dashboardData.sourceValidation.summary.review}</span>
              <span className="audit-expand">查看 {dashboardData.sourceValidation.summary.total} 项明细</span>
            </div>
          </summary>
          <div className="source-audit-body">
            <p>{dashboardData.sourceValidation.policy}；收盘价差异不超过 {dashboardData.sourceValidation.thresholdPct}% 判为一致。</p>
            <div className="source-check-grid source-check-header">
              <span>品种</span>
              <span>数据日</span>
              <span>xtdata</span>
              <span>AkShare</span>
              <span>差异</span>
              <span>结果</span>
            </div>
            {dashboardData.sourceValidation.checks.map((check) => (
              <div className="source-check-grid" key={check.xtSymbol}>
                <span><strong>{check.name}</strong><small>{check.xtSymbol} / {check.akSymbol}</small></span>
                <span className="tabular">{check.date}</span>
                <span className="tabular">{check.xtClose ?? "—"}</span>
                <span className="tabular">{check.akClose ?? "—"}</span>
                <span className="tabular">{check.relativeDiffPct === null ? "—" : `${check.relativeDiffPct.toFixed(4)}%`}</span>
                <span>
                  <i className={`check-status ${check.status === "一致" ? "consistent" : check.status === "主力口径不同" ? "contract-mismatch" : "review"}`}>{check.status}</i>
                  {check.matchedContract && <small>AkShare 对应 {check.matchedContract}</small>}
                </span>
              </div>
            ))}
          </div>
        </details>

        <div className="table-frame">
          <table>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column.key} scope="col">
                    {column.key === "bar" || column.key === "signal" || column.key === "source" ? (
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
                const hasContracts = row.contracts.length > 0;
                const detailId = `contracts-${row.pair.replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, "-")}`;
                return (
                  <Fragment key={row.pair}>
                    <tr className={`pair-row ${isExpanded ? "expanded" : ""} ${row.pairType === "现货参考" ? "reference" : ""}`} title={`${row.leftSymbol} / ${row.rightSymbol}`}>
                      <th scope="row">
                        <div className="pair-cell">
                          {hasContracts ? (
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
                          ) : (
                            <span className="reference-mark" title="现货指数参考，不对应可交易期货组合">参考</span>
                          )}
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
                      <td><span className={`source-badge ${sourceStatusClass(row.sourceStatus)}`}>{row.sourceStatus}</span></td>
                      <td className="tabular">{row.lots}</td>
                      <td className="tabular">{row.deviation}</td>
                      <td className="tabular">{row.notional}</td>
                      <td className="tabular">{row.margin}</td>
                    </tr>
                    {isExpanded && hasContracts && (
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
          <span>保证金：中金所组合取较大单边；其他期货组合两腿相加；现货指数仅作参考。</span>
          <span>数据日：{dashboardData.dataDate} · 更新时间：每日 20:00</span>
        </footer>
      </section>

      <section className="analytics-section" aria-labelledby="analytics-title">
        <header className="analytics-header">
          <div>
            <div className="eyebrow">CHART ANALYSIS</div>
            <h2 id="analytics-title">图表分析</h2>
            <p>分位排名与关键组合最近 60 个月走势</p>
          </div>
          <span>{dashboardData.dataDate} · xtdata 主值</span>
        </header>

        <article className="chart-card percentile-chart-card">
          <header className="chart-card-header">
            <div>
              <h3>近3年分位总览</h3>
              <p>全部 {rows.length} 个品种对 · 0%—100% · 按分位降序</p>
            </div>
          </header>
          <div className="percentile-chart-grid">
            {[...rows].sort((a, b) => b.percentile - a.percentile).map((row) => (
              <div className="percentile-chart-row" key={`chart-${row.pair}`}>
                <span title={row.pair}>{row.pair}</span>
                <div className="percentile-chart-track" aria-label={`${row.pair}近3年分位${row.percentile}%`}>
                  <i className={row.signal === "偏高" ? "high" : row.signal === "极度偏低" ? "low" : "neutral"} style={{ width: `${Math.max(row.percentile, 1)}%` }} />
                </div>
                <strong className="tabular">{row.percentile.toFixed(2)}%</strong>
              </div>
            ))}
          </div>
        </article>

        <div className="history-chart-grid">
          {historyCharts.map((chart) => <HistoryLineChart chart={chart} key={chart.id} />)}
        </div>
        <p className="analytics-note">历史走势图采用月末值；当前月使用截至数据日的最新收盘。现货指数图仍以 xtdata 为主，并由 AkShare 校验。</p>
      </section>
    </main>
  );
}
