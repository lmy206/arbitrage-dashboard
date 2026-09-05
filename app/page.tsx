"use client";

import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import dashboardData from "./data/arbitrage.json";

type Signal = "极度偏高" | "偏高" | "中性" | "偏低" | "极度偏低";
type SourceStatus = "双源一致" | "口径不同" | "仅xtdata" | "需复核" | "待校验" | "外部补充";
type StrategyType = "回归" | "趋势" | "外盘监控";

type TermStructure = {
  state: "Contango" | "Back";
  nearExpiry: string;
  farExpiry: string;
  nearPrice: number;
  farPrice: number;
  changePct: number;
  contractCount: number;
};

type ContractHistoryPoint = {
  date: string;
  value: number;
};

type ContractHistorySeries = {
  expiry: string;
  leftSymbol: string;
  rightSymbol: string;
  thirdSymbol?: string;
  formulaLabel?: string;
  points: ContractHistoryPoint[];
};

type ContractHistoryOverlaySeries = {
  label: string;
  symbol: string;
  unit: "人民币/美元" | "点位";
  points: ContractHistoryPoint[];
};

type ContractHistoryCorrelation = {
  label: string;
  value: number;
  sampleSize: number;
  method: string;
};

type ContractHistoryChartData = {
  title: string;
  unit: "比值" | "点差" | "百分比" | "基点";
  month: string;
  startDate: string;
  endDate: string;
  source: string;
  grain: string;
  statisticsPointCount?: number;
  renderPointCount?: number;
  quantileThresholds?: { label: string; value: number }[];
  series: ContractHistorySeries[];
  overlaySeries?: ContractHistoryOverlaySeries;
  correlations?: ContractHistoryCorrelation[];
  fixedThresholds?: { label: string; value: number }[];
};

type ContractRow = {
  expiry: string;
  current: string;
  previous: string;
  change: string;
  changeValue: number;
  allTime: string;
  allTimeRange: string;
  percentile: number;
  fiveYearRange: string;
  signal: Signal;
  lots: string;
  deviation: string;
  notional: string;
  margin: string;
  sourceStatus: SourceStatus;
  leftSymbol: string;
  rightSymbol: string;
  thirdSymbol?: string;
  leftChangePct: number | null;
  rightChangePct: number | null;
  thirdChangePct?: number | null;
  leftVolume: number;
  rightVolume: number;
  thirdVolume?: number;
  pairedVolume: number;
  historyChart: ContractHistoryChartData | null;
};

type SpotObservation = Omit<ContractRow, "expiry" | "leftVolume" | "rightVolume" | "pairedVolume" | "historyChart"> & {
  key: "spot";
  label: string;
  historyChart: ContractHistoryChartData | null;
};

type MainContinuousObservation = Omit<ContractRow, "expiry" | "leftVolume" | "rightVolume" | "pairedVolume" | "historyChart"> & {
  key: "main";
  label: "主连";
  historyChart: ContractHistoryChartData | null;
};

type RelatedObservation = Omit<ContractRow, "expiry" | "leftVolume" | "rightVolume" | "pairedVolume" | "historyChart"> & {
  key: string;
  label: string;
  formulaLabel: string;
  historyChart: ContractHistoryChartData | null;
};

type TermObservation = Omit<ContractRow, "expiry" | "leftVolume" | "rightVolume" | "pairedVolume" | "historyChart"> & {
  key: "term-down" | "term-skip";
  label: "下季" | "隔季";
  denominatorSymbol: string;
  formulaLabel: string;
  nearPrice: number;
  farPrice: number;
  spotPrice: number;
  monthGap: number;
  historyChart: ContractHistoryChartData | null;
};

type ObservationOption = {
  key: string;
  label: string;
  detail?: string;
  current: string;
  percentile: number;
  signal: Signal;
  leftSymbol: string;
  rightSymbol: string;
  thirdSymbol?: string;
  leftChangePct: number | null;
  rightChangePct: number | null;
  thirdChangePct?: number | null;
  leftVolume: number | null;
  rightVolume: number | null;
  thirdVolume?: number | null;
  pairedVolume: number | null;
  pinned: boolean;
  spot: boolean;
  term: boolean;
  denominatorSymbol?: string;
  historyChart: ContractHistoryChartData | null;
};

type PairRow = {
  strategyType: StrategyType;
  marketCategory: "股指" | "农产品" | "工业品";
  pair: string;
  current: string;
  previous: string;
  change: string;
  changeValue: number | null;
  allTime: string;
  allTimeRange: string;
  percentile: number;
  fiveYearRange: string;
  signal: Signal;
  lots: string;
  deviation: string;
  notional: string;
  margin: string;
  leftSymbol: string;
  rightSymbol: string;
  thirdSymbol?: string;
  leftChangePct: number | null;
  rightChangePct: number | null;
  thirdChangePct?: number | null;
  denominatorSymbol?: string;
  seriesMode: "weighted" | "main" | "spot" | "term" | "external";
  pairType: "期货套利" | "现货参考" | "期限套利" | "跨市场套利" | "外盘参考";
  externalSourceDate?: string;
  externalSourceDates?: Record<string, string>;
  externalSourceMaxLagDays?: number;
  formulaLabel?: string;
  rollRule?: string;
  sourceStatus: SourceStatus;
  leftStructure: TermStructure | null;
  rightStructure: TermStructure | null;
  thirdStructure?: TermStructure | null;
  mainHistoryChart: ContractHistoryChartData | null;
  spotObservation: SpotObservation | null;
  mainContinuousObservation: MainContinuousObservation | null;
  relatedObservations?: RelatedObservation[];
  termObservations?: TermObservation[];
  contracts: ContractRow[];
  formulaKind: "spread" | "ratio";
};

const rows: PairRow[] = dashboardData.rows.map((row) => ({
  ...row,
  signal: row.signal as Signal,
  sourceStatus: row.sourceStatus as SourceStatus,
  formulaKind: (
    row.pair.includes("差")
    || row.pair.includes("利润")
    || row.pair.includes("加工费")
  ) ? "spread" : "ratio",
}));
const xtdataOnly = dashboardData.sourceValidation.mode === "xtdata_only";
const externalSources = dashboardData.externalSources ?? [];
const hasExternalSources = externalSources.length > 0;
const primaryObservationStorageKey = "arbitrage-primary-observations-v1";
const favoriteStorageKey = "arbitrage-favorites-v1";
const legacyPairNamesByCurrent: Record<string, string[]> = {
  "棕榈油/菜油比价": ["棕榈油菜油比"],
  "菜油/豆油比价": ["豆油菜油比"],
  "豆一/豆二比价": ["豆一豆二比"],
  "螺/矿比价": ["螺矿比"],
  "油/粕比价": ["油粕比"],
  "卷-螺价差": ["卷螺价差"],
  "铜/铝比价": ["铜铝比"],
  "金/银比价": ["金银比"],
  "玻璃/纯碱比价": ["玻璃/纯碱比", "玻璃纯碱比", "纯碱玻璃比"],
  "焦炭/焦煤比价": ["焦炭/焦煤比", "焦炭焦煤比"],
};
const legacyFavoriteNamesByCurrent: Record<string, string[]> = {
  "棕榈油/菜油比价": ["棕榈油菜油比"],
  "菜油/豆油比价": ["豆油菜油比"],
  "豆一/豆二比价": ["豆一豆二比"],
  "聚丙烯/甲醇比价": ["MTO盘面利润"],
  "螺/矿比价": ["螺矿比"],
  "油/粕比价": ["油粕比"],
  "卷-螺价差": ["卷螺价差"],
  "铜/铝比价": ["铜铝比"],
  "金/银比价": ["金银比"],
  "玻璃/纯碱比价": ["玻璃/纯碱比", "玻璃纯碱比", "纯碱玻璃比", "玻璃生产利润"],
  "焦炭/焦煤比价": ["焦炭/焦煤比", "焦炭焦煤比", "焦化利润"],
};

type SortKey = "pair" | "current" | "previous" | "change" | "allTime" | "percentile" | "lots" | "deviation" | "notional" | "margin";

const columns: { key: SortKey | "strategyType" | "bar" | "signal" | "leftStructure" | "rightStructure" | "favorite"; label: string }[] = [
  { key: "strategyType", label: "类型" },
  { key: "pair", label: "品种对" },
  { key: "current", label: "当前值" },
  { key: "previous", label: "前日值" },
  { key: "change", label: "变动" },
  { key: "allTime", label: "全历史分位" },
  { key: "percentile", label: "近5年分位" },
  { key: "bar", label: "分位条" },
  { key: "signal", label: "判断" },
  { key: "lots", label: "平衡手数" },
  { key: "deviation", label: "偏差" },
  { key: "notional", label: "总名义值" },
  { key: "margin", label: "保证金" },
  { key: "leftStructure", label: "左腿结构" },
  { key: "rightStructure", label: "右腿结构" },
  { key: "favorite", label: "收藏" },
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

const strategyTypeOrder: Record<StrategyType, number> = { 回归: 0, 趋势: 1, 外盘监控: 2 };
const strategyTypeClass: Record<StrategyType, string> = { 回归: "regression", 趋势: "trend", 外盘监控: "external-monitor" };
const marketCategoryOrder: Record<PairRow["marketCategory"], number> = { 股指: 0, 农产品: 1, 工业品: 2 };
const pinnedPairOrder: Record<string, number> = {
  "ERP：沪深300": 0,
  "ERP：标普500": 1,
  "美元银行融资压力代理": 2,
};

function pairCodeFormula(
  row: Pick<PairRow, "pair" | "formulaKind" | "leftSymbol" | "rightSymbol" | "thirdSymbol">,
  leftSymbol = row.leftSymbol,
  rightSymbol = row.rightSymbol,
  thirdSymbol = row.thirdSymbol,
) {
  if (thirdSymbol) {
    return `${leftSymbol} − 0.86 × ${rightSymbol} − 0.34 × ${thirdSymbol}`;
  }
  if (row.pair === "PTA盘面加工费") {
    return `${leftSymbol} − 0.655 × ${rightSymbol}`;
  }
  const operator = row.formulaKind === "spread" ? "−" : "/";
  return `${leftSymbol} ${operator} ${rightSymbol}`;
}

const codeOnlyFormulaPairs = new Set([
  "PTA盘面加工费",
]);

function pairHoverFormula(
  row: Pick<PairRow, "pair" | "formulaKind" | "leftSymbol" | "rightSymbol" | "thirdSymbol" | "formulaLabel">,
) {
  if (row.formulaLabel && !codeOnlyFormulaPairs.has(row.pair)) {
    return row.formulaLabel;
  }
  return pairCodeFormula(row);
}

function historyToggleLabel(pair: string, optionLabel: string, expanded: boolean) {
  const action = expanded ? "收起" : "展开";
  return /^\d{4}$/.test(optionLabel)
    ? `${action}${pair}${optionLabel}历年同月合约折线图`
    : `${action}${pair}${optionLabel}折线图`;
}

function signalClass(signal: Signal) {
  if (signal === "极度偏高") return "extreme-high";
  if (signal === "偏高") return "high";
  if (signal === "偏低") return "low";
  if (signal === "极度偏低") return "extreme-low";
  return "neutral";
}

function applyPrimaryObservation(row: PairRow, selection?: string): PairRow {
  const observation = selection === "spot"
    ? row.spotObservation
    : row.termObservations?.find((item) => item.key === selection)
      ?? row.relatedObservations?.find((item) => item.key === selection)
      ?? row.contracts.find((item) => item.expiry === selection);
  if (!observation) return row;

  return {
    ...row,
    current: observation.current,
    previous: observation.previous,
    change: observation.change,
    changeValue: observation.changeValue,
    allTime: observation.allTime,
    allTimeRange: observation.allTimeRange,
    percentile: observation.percentile,
    fiveYearRange: observation.fiveYearRange,
    signal: observation.signal,
    lots: observation.lots,
    deviation: observation.deviation,
    notional: observation.notional,
    margin: observation.margin,
    sourceStatus: observation.sourceStatus,
    leftSymbol: observation.leftSymbol,
    rightSymbol: observation.rightSymbol,
    thirdSymbol: observation.thirdSymbol,
    leftChangePct: observation.leftChangePct,
    rightChangePct: observation.rightChangePct,
    thirdChangePct: observation.thirdChangePct,
    denominatorSymbol: "denominatorSymbol" in observation ? observation.denominatorSymbol : row.denominatorSymbol,
    formulaLabel: "formulaLabel" in observation ? observation.formulaLabel : row.formulaLabel,
  };
}

function observationOptionsFor(row: PairRow): ObservationOption[] {
  if (row.termObservations?.length) {
    return row.termObservations.map((observation) => ({
      key: observation.key,
      label: observation.label,
      detail: observation.formulaLabel,
      current: observation.current,
      percentile: observation.percentile,
      signal: observation.signal,
      leftSymbol: observation.leftSymbol,
      rightSymbol: observation.rightSymbol,
      leftChangePct: observation.leftChangePct,
      rightChangePct: observation.rightChangePct,
      denominatorSymbol: observation.denominatorSymbol,
      leftVolume: null,
      rightVolume: null,
      pairedVolume: null,
      pinned: true,
      spot: false,
      term: true,
      historyChart: observation.historyChart,
    }));
  }
  const pinned: ObservationOption[] = [];
  if (row.spotObservation) {
    pinned.push({
      key: "spot",
      label: "现货指数",
      detail: row.spotObservation.label,
      current: row.spotObservation.current,
      percentile: row.spotObservation.percentile,
      signal: row.spotObservation.signal,
      leftSymbol: row.spotObservation.leftSymbol,
      rightSymbol: row.spotObservation.rightSymbol,
      leftChangePct: row.spotObservation.leftChangePct,
      rightChangePct: row.spotObservation.rightChangePct,
      leftVolume: null,
      rightVolume: null,
      pairedVolume: null,
      pinned: true,
      spot: true,
      term: false,
      historyChart: row.spotObservation.historyChart,
    });
  }
  const defaultObservation: ObservationOption = {
    key: "default",
    label: row.seriesMode === "weighted" ? "加权" : row.seriesMode === "term" ? "期限套" : "主连",
    detail: pairCodeFormula(row),
    current: row.current,
    percentile: row.percentile,
    signal: row.signal,
    leftSymbol: row.leftSymbol,
    rightSymbol: row.rightSymbol,
    thirdSymbol: row.thirdSymbol,
    leftChangePct: row.leftChangePct,
    rightChangePct: row.rightChangePct,
    thirdChangePct: row.thirdChangePct,
    leftVolume: null,
    rightVolume: null,
    thirdVolume: null,
    pairedVolume: null,
    pinned: true,
    spot: false,
    term: false,
    historyChart: row.mainHistoryChart,
  };
  const related = (row.relatedObservations ?? []).map((observation) => ({
    key: observation.key,
    label: observation.label,
    detail: observation.formulaLabel,
    current: observation.current,
    percentile: observation.percentile,
    signal: observation.signal,
    leftSymbol: observation.leftSymbol,
    rightSymbol: observation.rightSymbol,
    leftChangePct: observation.leftChangePct,
    rightChangePct: observation.rightChangePct,
    leftVolume: null,
    rightVolume: null,
    pairedVolume: null,
    pinned: true,
    spot: false,
    term: false,
    historyChart: observation.historyChart,
  }));
  return [
    ...pinned,
    ...related,
    defaultObservation,
    ...row.contracts.map((contract) => ({
      key: contract.expiry,
      label: contract.expiry,
      detail: pairCodeFormula(row, contract.leftSymbol, contract.rightSymbol, contract.thirdSymbol),
      current: contract.current,
      percentile: contract.percentile,
      signal: contract.signal,
      leftSymbol: contract.leftSymbol,
      rightSymbol: contract.rightSymbol,
      thirdSymbol: contract.thirdSymbol,
      leftChangePct: contract.leftChangePct,
      rightChangePct: contract.rightChangePct,
      thirdChangePct: contract.thirdChangePct,
      leftVolume: contract.leftVolume,
      rightVolume: contract.rightVolume,
      thirdVolume: contract.thirdVolume,
      pairedVolume: contract.pairedVolume,
      pinned: false,
      spot: false,
      term: false,
      historyChart: contract.historyChart,
    })),
  ];
}

function formatChartNumber(value: number) {
  if (Math.abs(value) >= 100) return value.toFixed(0);
  if (Math.abs(value) >= 10) return value.toFixed(2);
  return value.toFixed(4);
}

function formatLegChange(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "—";
  const normalized = Math.abs(value) < 0.005 ? 0 : value;
  return `${normalized > 0 ? "+" : ""}${normalized.toFixed(2)}%`;
}

function legChangeClass(value: number | null) {
  if (value === null || Math.abs(value) < 0.005) return "flat";
  return value > 0 ? "up" : "down";
}

function formatContractHistoryValue(value: number, unit: ContractHistoryChartData["unit"]) {
  if (unit === "百分比") return `${(value * 100).toFixed(2)}%`;
  if (unit === "基点") return `${value.toFixed(2)}bp`;
  return formatChartNumber(value);
}

function formatOverlayValue(value: number, unit: ContractHistoryOverlaySeries["unit"]) {
  return unit === "点位" ? value.toFixed(0) : value.toFixed(4);
}

function overlayTooltipLabel(label: string) {
  return label.replace(/（右轴）$/, "");
}

function formatCorrelation(value: number) {
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

function quantile(values: number[], percentile: number) {
  const sorted = [...values].sort((left, right) => left - right);
  if (sorted.length === 0) return 0;
  const position = (sorted.length - 1) * percentile;
  const lowerIndex = Math.floor(position);
  const upperIndex = Math.ceil(position);
  const weight = position - lowerIndex;
  return sorted[lowerIndex] + (sorted[upperIndex] - sorted[lowerIndex]) * weight;
}

const contractRootNames: Record<string, string> = {
  A: "豆一",
  B: "豆二",
  C: "玉米",
  M: "豆粕",
  Y: "豆油",
  P: "棕榈油",
  OI: "菜油",
  RM: "菜粕",
  LH: "生猪",
  HC: "热卷",
  RB: "螺纹钢",
  I: "铁矿石",
  J: "焦炭",
  JM: "焦煤",
  CU: "铜",
  AL: "铝",
  ZN: "锌",
  AU: "黄金",
  AG: "白银",
  SA: "纯碱",
  FG: "玻璃",
  FU: "燃料油",
  BU: "沥青",
  NR: "20号胶",
  BR: "BR橡胶",
  SH: "烧碱",
  NI: "镍",
  SS: "不锈钢",
  L: "聚乙烯",
  PP: "聚丙烯",
  MA: "甲醇",
  TA: "PTA",
  PX: "PX",
  PF: "涤纶短纤",
  EG: "乙二醇",
  IF: "沪深300",
  IC: "中证500",
  IM: "中证1000",
  IH: "上证50",
  CAD: "伦铜",
  AHD: "伦铝",
  ZSD: "伦锌",
};

const spotSymbolNames: Record<string, string> = {
  "000016.SH": "上证50",
  "000300.SH": "沪深300",
  "000688.SH": "科创50",
  "000852.SH": "中证1000",
  "000905.SH": "中证500",
  "399006.SZ": "创业板指",
};

function contractRootLabel(symbol: string) {
  if (spotSymbolNames[symbol]) return spotSymbolNames[symbol];
  const root = symbol.match(/^[A-Za-z]+/)?.[0].replace(/JQ$/i, "").toUpperCase();
  if (!root) return symbol;
  return contractRootNames[root] ?? root;
}

function termStructureTitle(symbol: string, structure: TermStructure) {
  const sign = structure.changePct > 0 ? "+" : "";
  return `${contractRootLabel(symbol)}：${structure.nearExpiry} ${structure.nearPrice} → ${structure.farExpiry} ${structure.farPrice}（${sign}${structure.changePct.toFixed(2)}%）`;
}

const seasonalSeriesStyles = [
  { color: "#2f6fca", dash: undefined },
  { color: "#d97706", dash: "8 4" },
  { color: "#6b7f2a", dash: "3 3" },
  { color: "#7c3aed", dash: "10 3 2 3" },
  { color: "#c2417a", dash: "2 4" },
  { color: "#2f6fca", dash: "12 4" },
  { color: "#d97706", dash: "4 3" },
  { color: "#6b7f2a", dash: "9 3 2 3" },
  { color: "#7c3aed", dash: "2 3" },
  { color: "#c2417a", dash: "12 3 2 3" },
];

function ContractHistoryChart({ chart, formula }: { chart: ContractHistoryChartData; formula?: string }) {
  const width = 920;
  const height = 270;
  const overlaySeries = chart.overlaySeries;
  const inset = { top: 18, right: overlaySeries ? 68 : 24, bottom: 32, left: 62 };
  const plotWidth = width - inset.left - inset.right;
  const plotHeight = height - inset.top - inset.bottom;
  const svgRef = useRef<SVGSVGElement>(null);
  const [hovered, setHovered] = useState<{ series: ContractHistorySeries; point: ContractHistoryPoint } | null>(null);
  const startTime = Date.parse(chart.startDate);
  const endTime = Date.parse(chart.endDate);
  const timeRange = Math.max(endTime - startTime, 1);
  const allPoints = chart.series.flatMap((series) => series.points.map((point) => ({ series, point })));
  const values = allPoints.map(({ point }) => point.value);
  const thresholds = chart.fixedThresholds ?? chart.quantileThresholds ?? [
      { label: "3%", value: quantile(values, 0.03) },
      { label: "97%", value: quantile(values, 0.97) },
    ];
  const thresholdSummary = chart.fixedThresholds
    ? `${thresholds.map((threshold) => threshold.label).join("/")}固定阈值`
    : chart.quantileThresholds
      ? "3%/97%阈值按完整日频历史值"
      : "3%/97%阈值按图内全部历史值";
  const isSeasonalHistory = chart.series.every((series) => /^\d{4}$/.test(series.expiry));
  const rawMin = Math.min(...values, ...thresholds.map((threshold) => threshold.value));
  const rawMax = Math.max(...values, ...thresholds.map((threshold) => threshold.value));
  const rawRange = rawMax - rawMin || Math.max(Math.abs(rawMax) * 0.1, 1);
  const yMin = rawMin - rawRange * 0.08;
  const yMax = rawMax + rawRange * 0.08;
  const x = (date: string) => inset.left + ((Date.parse(date) - startTime) / timeRange) * plotWidth;
  const y = (value: number) => inset.top + ((yMax - value) / (yMax - yMin)) * plotHeight;
  const overlayValues = overlaySeries?.points.map((point) => point.value) ?? [];
  const overlayRawMin = overlayValues.length ? Math.min(...overlayValues) : 0;
  const overlayRawMax = overlayValues.length ? Math.max(...overlayValues) : 1;
  const overlayRawRange = overlayRawMax - overlayRawMin || Math.max(Math.abs(overlayRawMax) * 0.01, 0.01);
  const overlayYMin = overlayRawMin - overlayRawRange * 0.08;
  const overlayYMax = overlayRawMax + overlayRawRange * 0.08;
  const overlayY = (value: number) => inset.top + ((overlayYMax - value) / (overlayYMax - overlayYMin)) * plotHeight;
  const gapThreshold = 21 * 24 * 60 * 60 * 1000;
  const paths = chart.series.map((series, seriesIndex) => {
    let previousTime: number | null = null;
    const path = series.points.map((point) => {
      const currentTime = Date.parse(point.date);
      const command = previousTime === null || currentTime - previousTime > gapThreshold ? "M" : "L";
      previousTime = currentTime;
      return `${command}${x(point.date).toFixed(2)},${y(point.value).toFixed(2)}`;
    }).join(" ");
    return { series, path, style: seasonalSeriesStyles[seriesIndex % seasonalSeriesStyles.length] };
  });
  const yTicks = Array.from({ length: 5 }, (_, index) => yMin + ((yMax - yMin) * index) / 4);
  const overlayYTicks = overlaySeries
    ? Array.from({ length: 5 }, (_, index) => overlayYMin + ((overlayYMax - overlayYMin) * index) / 4)
    : [];
  const xTicks = Array.from({ length: 6 }, (_, index) => startTime + (timeRange * index) / 5);
  let overlayPreviousTime: number | null = null;
  const overlayPath = overlaySeries?.points.map((point) => {
    const currentTime = Date.parse(point.date);
    const command = overlayPreviousTime === null || currentTime - overlayPreviousTime > gapThreshold ? "M" : "L";
    overlayPreviousTime = currentTime;
    return `${command}${x(point.date).toFixed(2)},${overlayY(point.value).toFixed(2)}`;
  }).join(" ") ?? "";
  const hoveredOverlayPoint = hovered && overlaySeries?.points.length
    ? overlaySeries.points.reduce((best, candidate) => (
        Math.abs(Date.parse(candidate.date) - Date.parse(hovered.point.date)) < Math.abs(Date.parse(best.date) - Date.parse(hovered.point.date))
          ? candidate
          : best
      ))
    : null;

  function updateHover(clientX: number) {
    const bounds = svgRef.current?.getBoundingClientRect();
    if (!bounds || allPoints.length === 0) return;
    const viewBoxX = ((clientX - bounds.left) / bounds.width) * width;
    const targetTime = startTime + ((viewBoxX - inset.left) / plotWidth) * timeRange;
    const nearest = allPoints.reduce((best, candidate) => (
      Math.abs(Date.parse(candidate.point.date) - targetTime) < Math.abs(Date.parse(best.point.date) - targetTime)
        ? candidate
        : best
    ));
    setHovered(nearest);
  }

  return (
    <section className={`contract-history-chart ${chart.unit === "点差" ? "spread" : "ratio"}`}>
      <header>
        <div>
          <h4>
            <span>{chart.title}</span>
            {formula && <span className="contract-history-formula">公式：{formula}</span>}
          </h4>
          <p>{chart.startDate}—{chart.endDate} · {chart.grain} · {thresholdSummary} · 断档处不连线 · {chart.source}</p>
        </div>
        <div className="contract-history-header-meta">
          <span className="contract-history-scope">{isSeasonalHistory ? `${chart.series.length} 个历年合约` : chart.series.map((series) => series.expiry).join(" / ")}</span>
          {chart.correlations && (
            <div className="chart-correlation-summary" aria-label="与中证1000现货的相关性">
              {chart.correlations.map((correlation) => (
                <span
                  className="chart-correlation"
                  key={correlation.label}
                  title={`${correlation.method} · 完整日频样本 ${correlation.sampleSize}`}
                >
                  <small>{correlation.label}</small>
                  <strong>{formatCorrelation(correlation.value)}</strong>
                </span>
              ))}
            </div>
          )}
        </div>
      </header>
      <div className="contract-history-legend" aria-label="历年合约图例">
        {paths.map(({ series, style }) => (
          <span key={series.expiry} title={series.formulaLabel ?? (
            series.thirdSymbol
              ? `${series.leftSymbol} − 0.86 × ${series.rightSymbol} − 0.34 × ${series.thirdSymbol}`
              : `${series.leftSymbol} ${chart.unit === "比值" ? "/" : "−"} ${series.rightSymbol}`
          )}>
            <i style={{ borderTopColor: style.color, borderTopStyle: style.dash ? "dashed" : "solid" }} aria-hidden="true" />
            {series.expiry}
          </span>
        ))}
        {overlaySeries && (
          <span className="overlay-legend" title={`${overlaySeries.symbol} · ${overlaySeries.unit}`}>
            <i aria-hidden="true" />
            {overlaySeries.label}
          </span>
        )}
        <span className="threshold-legend"><i aria-hidden="true" />{thresholds.map((threshold) => threshold.label).join(" / ")} 阈值</span>
      </div>
      <svg
        ref={svgRef}
        className="contract-history-svg"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${chart.title}折线图，包含${chart.series.map((series) => series.expiry).join("、")}${overlaySeries ? `、${overlaySeries.label}` : ""}`}
        onPointerMove={(event) => updateHover(event.clientX)}
        onPointerLeave={() => setHovered(null)}
      >
        <title>{chart.title}</title>
        {yTicks.map((tick) => (
          <g key={tick}>
            <line className="chart-grid-line" x1={inset.left} x2={width - inset.right} y1={y(tick)} y2={y(tick)} />
            <text className="chart-axis-label" x={inset.left - 10} y={y(tick) + 3} textAnchor="end">{formatContractHistoryValue(tick, chart.unit)}</text>
          </g>
        ))}
        {overlayYTicks.map((tick) => (
          <text className="chart-axis-label overlay-axis-label" key={`overlay-${tick}`} x={width - inset.right + 10} y={overlayY(tick) + 3} textAnchor="start">
            {overlaySeries ? formatOverlayValue(tick, overlaySeries.unit) : ""}
          </text>
        ))}
        {thresholds.map((threshold) => (
          <line
            className="contract-history-threshold-line"
            key={`${threshold.label}-line`}
            x1={inset.left}
            x2={width - inset.right}
            y1={y(threshold.value)}
            y2={y(threshold.value)}
          />
        ))}
        {xTicks.map((tick, index) => (
          <text className="chart-axis-label" key={tick} x={inset.left + (plotWidth * index) / 5} y={height - 8} textAnchor={index === 0 ? "start" : index === 5 ? "end" : "middle"}>
            {new Date(tick).toISOString().slice(0, 7)}
          </text>
        ))}
        {overlaySeries && (
          <path className="contract-history-overlay-line" d={overlayPath} />
        )}
        {paths.map(({ series, path, style }) => (
          <path
            className="contract-history-line"
            d={path}
            key={series.expiry}
            stroke={style.color}
            strokeDasharray={style.dash}
          />
        ))}
        {thresholds.map((threshold) => (
          <text
            className="contract-history-threshold-label"
            key={`${threshold.label}-label`}
            x={width - inset.right - 4}
            y={y(threshold.value) - 5}
            textAnchor="end"
          >
            {chart.fixedThresholds
              ? threshold.label
              : `${threshold.label}阈值 ${formatContractHistoryValue(threshold.value, chart.unit)}`}
          </text>
        ))}
        {hovered && (
          <g className="chart-hover">
            <line x1={x(hovered.point.date)} x2={x(hovered.point.date)} y1={inset.top} y2={height - inset.bottom} />
            <circle cx={x(hovered.point.date)} cy={y(hovered.point.value)} r="4" />
            {hoveredOverlayPoint && <circle className="overlay-hover-point" cx={x(hoveredOverlayPoint.date)} cy={overlayY(hoveredOverlayPoint.value)} r="3.5" />}
            <g transform={`translate(${Math.min(Math.max(x(hovered.point.date) - 80, inset.left), width - inset.right - 176)}, ${Math.max(y(hovered.point.value) - (hoveredOverlayPoint ? 70 : 52), inset.top)})`}>
              <rect width={hoveredOverlayPoint ? 176 : 132} height={hoveredOverlayPoint ? 58 : 41} rx="5" />
              <text x="8" y="15">{hovered.series.expiry} · {hovered.point.date}</text>
              <text x="8" y="32">{formatContractHistoryValue(hovered.point.value, chart.unit)}</text>
              {hoveredOverlayPoint && overlaySeries && (
                <text className="overlay-tooltip-value" x="8" y="49">
                  {overlayTooltipLabel(overlaySeries.label)} {formatOverlayValue(hoveredOverlayPoint.value, overlaySeries.unit)}
                </text>
              )}
            </g>
          </g>
        )}
      </svg>
    </section>
  );
}

export default function Home() {
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("percentile");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [expandedPairs, setExpandedPairs] = useState<Set<string>>(() => new Set());
  const [expandedContractCharts, setExpandedContractCharts] = useState<Set<string>>(() => new Set());
  const [primaryObservations, setPrimaryObservations] = useState<Record<string, string>>({});
  const [primaryObservationsLoaded, setPrimaryObservationsLoaded] = useState(false);
  const [favoriteTimes, setFavoriteTimes] = useState<Record<string, number>>({});
  const [favoritesLoaded, setFavoritesLoaded] = useState(false);
  const [manualUpdateStatus, setManualUpdateStatus] = useState<"idle" | "updating" | "error">("idle");
  const [manualUpdateMessage, setManualUpdateMessage] = useState("");
  const [manualUpdateAvailable, setManualUpdateAvailable] = useState(true);

  useEffect(() => {
    setManualUpdateAvailable(["localhost", "127.0.0.1", "::1"].includes(window.location.hostname));
  }, []);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(primaryObservationStorageKey);
      const parsed = stored ? JSON.parse(stored) as Record<string, unknown> : {};
      const validSelections: Record<string, string> = {};
      rows.forEach((row) => {
        const expiry = [row.pair, ...(legacyPairNamesByCurrent[row.pair] ?? [])]
          .map((pairName) => parsed[pairName])
          .find((value) => typeof value === "string");
        if (
          typeof expiry === "string" &&
          (
            (expiry === "spot" && row.spotObservation !== null) ||
            row.termObservations?.some((observation) => observation.key === expiry) ||
            row.relatedObservations?.some((observation) => observation.key === expiry) ||
            row.contracts.some((contract) => contract.expiry === expiry)
          )
        ) {
          validSelections[row.pair] = expiry;
        }
      });
      setPrimaryObservations(validSelections);
    } catch {
      setPrimaryObservations({});
    } finally {
      setPrimaryObservationsLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (!primaryObservationsLoaded) return;
    window.localStorage.setItem(primaryObservationStorageKey, JSON.stringify(primaryObservations));
  }, [primaryObservations, primaryObservationsLoaded]);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(favoriteStorageKey);
      const parsed = stored ? JSON.parse(stored) as Record<string, unknown> : {};
      const validFavoriteTimes: Record<string, number> = {};
      rows.forEach((row) => {
        const favoriteCandidates = [row.pair, ...(legacyFavoriteNamesByCurrent[row.pair] ?? [])]
          .map((pairName) => parsed[pairName])
          .filter((value): value is number => typeof value === "number" && Number.isFinite(value) && value > 0);
        if (favoriteCandidates.length > 0) {
          validFavoriteTimes[row.pair] = Math.max(...favoriteCandidates);
        }
      });
      setFavoriteTimes(validFavoriteTimes);
    } catch {
      setFavoriteTimes({});
    } finally {
      setFavoritesLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (!favoritesLoaded) return;
    window.localStorage.setItem(favoriteStorageKey, JSON.stringify(favoriteTimes));
  }, [favoriteTimes, favoritesLoaded]);

  const visibleRows = useMemo(() => {
    const observedRows = rows.map((row) => applyPrimaryObservation(row, primaryObservations[row.pair]));
    const filtered = observedRows.filter(
      (row) => {
        const relatedNames = (row.relatedObservations ?? []).map((observation) => observation.label).join(" ");
        const searchableName = `${row.pair} ${relatedNames} ${primaryObservations[row.pair] ?? ""}`.toLowerCase();
        return searchableName.includes(query.trim().toLowerCase());
      },
    );
    return [...filtered].sort((a, b) => {
      const aFavoriteTime = favoriteTimes[a.pair];
      const bFavoriteTime = favoriteTimes[b.pair];
      if (aFavoriteTime !== undefined || bFavoriteTime !== undefined) {
        if (aFavoriteTime !== undefined && bFavoriteTime !== undefined) {
          return bFavoriteTime - aFavoriteTime || a.pair.localeCompare(b.pair, "zh-CN");
        }
        return aFavoriteTime !== undefined ? -1 : 1;
      }

      const aPinned = pinnedPairOrder[a.pair];
      const bPinned = pinnedPairOrder[b.pair];
      if (aPinned !== undefined || bPinned !== undefined) {
        if (aPinned !== undefined && bPinned !== undefined) return aPinned - bPinned;
        return aPinned !== undefined ? -1 : 1;
      }

      const strategyPriority = strategyTypeOrder[a.strategyType] - strategyTypeOrder[b.strategyType];
      if (strategyPriority !== 0) return strategyPriority;

      const marketPriority = marketCategoryOrder[a.marketCategory] - marketCategoryOrder[b.marketCategory];
      if (marketPriority !== 0) return marketPriority;

      const av = numericValue(a, sortKey);
      const bv = numericValue(b, sortKey);
      const result = typeof av === "string" && typeof bv === "string" ? av.localeCompare(bv, "zh-CN") : Number(av) - Number(bv);
      return sortDirection === "asc" ? result : -result;
    });
  }, [favoriteTimes, primaryObservations, query, sortDirection, sortKey]);

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

  function toggleContractChart(pair: string, expiry: string) {
    const key = `${pair}:${expiry}`;
    setExpandedContractCharts((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function togglePrimaryObservation(pair: string, selection: string) {
    setPrimaryObservations((current) => {
      if (selection === "default" || selection === "term-down" || current[pair] === selection) {
        const next = { ...current };
        delete next[pair];
        return next;
      }
      return { ...current, [pair]: selection };
    });
  }

  function toggleFavorite(pair: string) {
    setFavoriteTimes((current) => {
      const next = { ...current };
      if (next[pair] !== undefined) {
        delete next[pair];
      } else {
        const latestExistingTime = Math.max(0, ...Object.values(current));
        next[pair] = Math.max(Date.now(), latestExistingTime + 1);
      }
      return next;
    });
  }

  function formatVolume(value: number | null) {
    return value === null ? "—" : value.toLocaleString("zh-CN");
  }

  async function runManualUpdate() {
    if (!manualUpdateAvailable || manualUpdateStatus === "updating") return;
    setManualUpdateStatus("updating");
    setManualUpdateMessage("正在读取 xtdata 与外盘数据…");
    try {
      const response = await fetch("/api/manual-update", { method: "POST" });
      const result = await response.json() as { ok?: boolean; dataDate?: string; error?: string };
      if (!response.ok || !result.ok) throw new Error(result.error || "更新失败");
      setManualUpdateMessage(`已更新至 ${result.dataDate}，正在刷新…`);
      window.setTimeout(() => window.location.reload(), 500);
    } catch (error) {
      setManualUpdateStatus("error");
      setManualUpdateMessage(error instanceof Error ? error.message : "更新失败，请稍后重试");
    }
  }

  return (
    <main className="dashboard-shell" data-snapshot-updated-at={dashboardData.updatedAt}>
      <section className="dashboard" aria-labelledby="dashboard-title">
        <header className="dashboard-header">
          <div>
            <div className="eyebrow">ARBITRAGE MONITOR</div>
            <h1 id="dashboard-title">套利监测看板</h1>
            <p>跟踪跨品种比价、价差与历史分位</p>
          </div>
          <button
            type="button"
            className={`update-status ${manualUpdateStatus}${manualUpdateAvailable ? "" : " remote"}`}
            aria-label={manualUpdateAvailable ? "立即使用xtdata更新看板数据" : "云端静态数据快照"}
            disabled={!manualUpdateAvailable || manualUpdateStatus === "updating"}
            onClick={runManualUpdate}
          >
            <span className="status-dot" aria-hidden="true" />
            <div>
              <strong>{manualUpdateAvailable ? (manualUpdateStatus === "updating" ? "正在更新…" : "立即更新数据") : "云端数据快照"}</strong>
              <span>{manualUpdateAvailable ? (manualUpdateMessage || `国内数据 ${dashboardData.dataDate} · 每日 20:00`) : `国内数据截止 ${dashboardData.dataDate}`}</span>
            </div>
            <span className="update-action" aria-hidden="true">{manualUpdateAvailable ? "↻" : "●"}</span>
          </button>
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
          </div>
          <div className="legend" aria-label="判断图例">
            <span><i className="legend-dot extreme-high" />极度偏高</span>
            <span><i className="legend-dot high" />偏高</span>
            <span><i className="legend-dot neutral" />中性</span>
            <span><i className="legend-dot low" />偏低</span>
            <span><i className="legend-dot extreme-low" />极度偏低</span>
            <b>{visibleRows.length} 组</b>
          </div>
        </div>

        <details className="source-audit">
          <summary>
            <div className="source-audit-title">
              <span className={`audit-dot ${dashboardData.sourceValidation.summary.review > 0 ? "warning" : dashboardData.sourceValidation.summary.contractMismatch > 0 ? "scope" : "ok"}`} aria-hidden="true" />
              <strong>数据源校验</strong>
              <span>{hasExternalSources ? "国内 xtdata · 已批准外部源补充" : xtdataOnly ? "仅使用 xtdata" : "xtdata 主值 · AkShare 补充校对"}</span>
            </div>
            <div className="audit-summary">
              <span className="audit-count consistent">{xtdataOnly ? "完整" : "一致"} {dashboardData.sourceValidation.summary.consistent}</span>
              {!xtdataOnly && <span className="audit-count contract-mismatch">主力口径不同 {dashboardData.sourceValidation.summary.contractMismatch}</span>}
              <span className={`audit-count ${dashboardData.sourceValidation.summary.review > 0 ? "review" : "quiet"}`}>异常 {dashboardData.sourceValidation.summary.review}</span>
              <span className="audit-expand">查看 {dashboardData.sourceValidation.summary.total} 项明细</span>
            </div>
          </summary>
          <div className="source-audit-body">
            <p>{dashboardData.sourceValidation.policy}{!xtdataOnly && `；收盘价差异不超过 ${dashboardData.sourceValidation.thresholdPct}% 判为一致。`}</p>
            {hasExternalSources && (
              <div className="external-source-summary">
                <strong>外部补充口径</strong>
                <span>{dashboardData.externalSourcePolicy}</span>
                <div>
                  {externalSources.map((source) => (
                    <i key={source.symbol} title={source.path}>
                      {source.name} · {source.provider} · {source.endDate}
                    </i>
                  ))}
                </div>
              </div>
            )}
            <div className="source-check-grid source-check-header">
              <span>品种</span>
              <span>数据日</span>
              <span>xtdata</span>
              <span>{xtdataOnly ? "记录数" : "AkShare"}</span>
              <span>差异</span>
              <span>结果</span>
            </div>
            {dashboardData.sourceValidation.checks.map((check) => (
              <div className="source-check-grid" key={check.xtSymbol}>
                <span><strong>{check.name}</strong><small>{check.xtSymbol} / {check.akSymbol}</small></span>
                <span className="tabular">{check.date}</span>
                <span className="tabular">{check.xtClose ?? "—"}</span>
                <span className="tabular">{xtdataOnly ? check.xtRows : (check.akClose ?? "—")}</span>
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
                    {column.key === "strategyType" || column.key === "bar" || column.key === "signal" || column.key === "leftStructure" || column.key === "rightStructure" || column.key === "favorite" ? (
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
                const baseRow = rows.find((candidate) => candidate.pair === row.pair) ?? row;
                const isExpanded = expandedPairs.has(row.pair);
                const hasContracts = baseRow.contracts.length > 0;
                const hasTermObservations = (baseRow.termObservations?.length ?? 0) > 0;
                const hasThreeLeg = Boolean(baseRow.thirdSymbol);
                const hasObservationPanel = hasContracts || hasTermObservations;
                const standaloneHistoryChart = ["现货参考", "跨市场套利", "外盘参考"].includes(baseRow.pairType)
                  ? baseRow.mainHistoryChart
                  : null;
                const hasExpandableContent = hasObservationPanel || standaloneHistoryChart !== null;
                const selectedObservation = primaryObservations[row.pair];
                const selectedTermLabel = baseRow.termObservations
                  ?.find((observation) => observation.key === selectedObservation)?.label;
                const selectedRelatedLabel = baseRow.relatedObservations
                  ?.find((observation) => observation.key === selectedObservation)?.label;
                const selectedLabel = selectedObservation === "spot"
                  ? "现货"
                  : selectedTermLabel ?? selectedRelatedLabel ?? (
                      baseRow.contracts.some((contract) => contract.expiry === selectedObservation)
                        ? selectedObservation
                        : undefined
                    );
                const observationOptions = observationOptionsFor(baseRow);
                const detailId = `contracts-${row.pair.replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, "-")}`;
                const isFavorite = favoriteTimes[row.pair] !== undefined;
                return (
                  <Fragment key={row.pair}>
                    <tr className={`pair-row ${isExpanded ? "expanded" : ""} ${selectedLabel ? "primary-observation" : ""} ${["现货参考", "跨市场套利", "外盘参考"].includes(row.pairType) ? "reference" : ""}`} title={pairHoverFormula(row)}>
                      <td><span className={`strategy-type ${strategyTypeClass[row.strategyType]}`}>{row.strategyType}</span></td>
                      <th scope="row">
                        <div className="pair-cell">
                          {hasExpandableContent ? (
                            <button
                              type="button"
                              className="expand-button"
                              aria-expanded={isExpanded}
                              aria-controls={detailId}
                              aria-label={`${isExpanded ? "收起" : "展开"}${row.pair}${hasContracts ? "合约月份" : hasTermObservations ? "观察口径" : baseRow.pairType === "外盘参考" ? "外盘折线图" : "现货折线图"}`}
                              onClick={() => togglePair(row.pair)}
                            >
                              {isExpanded ? "−" : "+"}
                            </button>
                          ) : (
                            <span className="reference-mark" title="现货指数参考，不对应可交易期货组合">参考</span>
                          )}
                          <span className="pair-name-stack">
                            <span>{row.pair}{selectedLabel ? `（${selectedLabel}）` : ""}</span>
                            {row.externalSourceDate && row.externalSourceDate < dashboardData.dataDate && (
                              <small className="external-source-date" title={`外部数据实际来源日：${row.externalSourceDate}`}>
                                外部截至 {row.externalSourceDate.slice(5)}
                              </small>
                            )}
                          </span>
                        </div>
                      </th>
                      <td className="tabular current-value">{row.current}</td>
                      <td className="tabular muted">{row.previous}</td>
                      <td className={`tabular change ${row.changeValue === null ? "flat" : row.changeValue > 0 ? "up" : "down"}`}>{row.change}</td>
                      <td className="tabular">
                        <div className="percentile-metric">
                          <span>{row.allTime}</span>
                          <small title="全历史区间">{row.allTimeRange}</small>
                        </div>
                      </td>
                      <td className="tabular percentile-value">
                        <div className="percentile-metric">
                          <span>{row.percentile.toFixed(row.percentile % 1 === 0 ? 1 : 2)}%</span>
                          <small title="近5年区间">{row.fiveYearRange}</small>
                        </div>
                      </td>
                      <td>
                        <div className="percentile-track" aria-label={`近5年分位 ${row.percentile}%`}>
                          <span className={`percentile-fill ${signalClass(row.signal)}`} style={{ width: `${Math.max(row.percentile, 4)}%` }} />
                        </div>
                      </td>
                      <td><span className={`signal ${signalClass(row.signal)}`}>{row.signal}</span></td>
                      <td className="tabular">{row.lots}</td>
                      <td className="tabular">{row.deviation}</td>
                      <td className="tabular">{row.notional}</td>
                      <td className="tabular">{row.margin}</td>
                      <td className="term-structure-cell">
                        {row.leftStructure ? (
                          <span className={`term-structure-badge ${row.leftStructure.state === "Contango" ? "contango" : "back"}`} title={termStructureTitle(baseRow.leftSymbol, row.leftStructure)}>
                            <small>{contractRootLabel(baseRow.leftSymbol)}</small>
                            <strong>{row.leftStructure.state}</strong>
                          </span>
                        ) : <span className="muted">—</span>}
                      </td>
                      <td className="term-structure-cell">
                        {row.rightStructure ? (
                          <span className={hasThreeLeg ? "term-structure-group" : undefined}>
                            <span className={`term-structure-badge ${row.rightStructure.state === "Contango" ? "contango" : "back"}`} title={termStructureTitle(baseRow.rightSymbol, row.rightStructure)}>
                              <small>{contractRootLabel(baseRow.rightSymbol)}</small>
                              <strong>{row.rightStructure.state}</strong>
                            </span>
                            {baseRow.thirdSymbol && row.thirdStructure && (
                              <span className={`term-structure-badge ${row.thirdStructure.state === "Contango" ? "contango" : "back"}`} title={termStructureTitle(baseRow.thirdSymbol, row.thirdStructure)}>
                                <small>{contractRootLabel(baseRow.thirdSymbol)}</small>
                                <strong>{row.thirdStructure.state}</strong>
                              </span>
                            )}
                          </span>
                        ) : <span className="muted">—</span>}
                      </td>
                      <td className="favorite-cell">
                        <button
                          type="button"
                          className={`favorite-button ${isFavorite ? "active" : ""}`}
                          aria-label={`${isFavorite ? "取消收藏" : "收藏"}${row.pair}`}
                          aria-pressed={isFavorite}
                          title={isFavorite ? "取消收藏" : "收藏并置顶"}
                          onClick={() => toggleFavorite(row.pair)}
                        >
                          <span aria-hidden="true">★</span>
                        </button>
                      </td>
                    </tr>
                    {isExpanded && hasObservationPanel && (
                      <tr className="contract-detail-row">
                        <td colSpan={columns.length} id={detailId}>
                          <div className="contract-panel" aria-label={hasTermObservations ? `${row.pair}下季与隔季观察口径` : `${row.pair}观察口径及成交量前四的合约月份`}>
                            <div className="contract-grid contract-grid-header">
                              <span>观察口径</span>
                              <span>当前值</span>
                              <span>{hasTermObservations ? "当月涨跌幅" : `${contractRootLabel(baseRow.leftSymbol)} 涨跌幅`}</span>
                              <span>{hasTermObservations ? "当月合约" : `${contractRootLabel(baseRow.contracts[0].leftSymbol)} 成交量`}</span>
                              <span>{hasTermObservations ? "远季涨跌幅" : hasThreeLeg ? "PTA / MEG 涨跌幅" : `${contractRootLabel(baseRow.rightSymbol)} 涨跌幅`}</span>
                              <span>{hasTermObservations ? "远季合约" : hasThreeLeg ? "PTA / MEG 成交量" : `${contractRootLabel(baseRow.contracts[0].rightSymbol)} 成交量`}</span>
                              <span>{hasTermObservations ? "现货指数" : "可配对成交量 ↓"}</span>
                              <span>近5年分位</span>
                              <span>判断</span>
                              <span>主要观察</span>
                            </div>
                            {observationOptions.map((option) => {
                              const isPrimaryObservation = option.key === "default" || option.key === "term-down"
                                ? selectedObservation === undefined
                                : selectedObservation === option.key;
                              const chartKey = `${row.pair}:${option.key}`;
                              const isHistoryExpanded = expandedContractCharts.has(chartKey);
                              const historyId = `history-${detailId}-${option.key}`;
                              return (
                                <Fragment key={`${row.pair}-${option.key}`}>
                                  <div className={`contract-grid ${option.pinned ? "pinned" : ""} ${option.spot ? "spot" : ""} ${isPrimaryObservation ? "primary" : ""}`}>
                                    <span className="observation-label" title={option.detail ?? pairCodeFormula(baseRow, option.leftSymbol, option.rightSymbol)}>
                                      <span className="observation-title">
                                        {option.historyChart && (
                                          <button
                                            type="button"
                                            className="contract-history-toggle"
                                            aria-expanded={isHistoryExpanded}
                                            aria-controls={historyId}
                                            aria-label={historyToggleLabel(row.pair, option.label, isHistoryExpanded)}
                                            onClick={() => toggleContractChart(row.pair, option.key)}
                                          >
                                            {isHistoryExpanded ? "−" : "+"}
                                          </button>
                                        )}
                                        <strong className="tabular">{option.label}</strong>
                                      </span>
                                      {option.detail && <small>{option.detail}</small>}
                                    </span>
                                    <span className="tabular contract-current">{option.current}</span>
                                    <span className={`tabular change ${legChangeClass(option.leftChangePct)}`} title={`${option.leftSymbol} 最近一个交易日涨跌幅`}>{formatLegChange(option.leftChangePct)}</span>
                                    <span className="tabular" title={option.leftSymbol}>{option.term ? option.leftSymbol.replace(".IF", "") : formatVolume(option.leftVolume)}</span>
                                    <span className={`tabular change ${legChangeClass(option.rightChangePct)}`} title={`${option.rightSymbol}${option.thirdSymbol ? ` / ${option.thirdSymbol}` : ""} 最近一个交易日涨跌幅`}>
                                      {option.thirdSymbol
                                        ? `${formatLegChange(option.rightChangePct)} / ${formatLegChange(option.thirdChangePct ?? null)}`
                                        : formatLegChange(option.rightChangePct)}
                                    </span>
                                    <span className="tabular" title={`${option.rightSymbol}${option.thirdSymbol ? ` / ${option.thirdSymbol}` : ""}`}>
                                      {option.term
                                        ? option.rightSymbol.replace(".IF", "")
                                        : option.thirdSymbol
                                          ? `${formatVolume(option.rightVolume)} / ${formatVolume(option.thirdVolume ?? null)}`
                                          : formatVolume(option.rightVolume)}
                                    </span>
                                    <span className="tabular paired-volume">{option.term ? option.denominatorSymbol?.replace(".SH", "") : formatVolume(option.pairedVolume)}</span>
                                    <span className="tabular contract-percentile">{option.percentile.toFixed(option.percentile % 1 === 0 ? 1 : 2)}%</span>
                                    <span><i className={`signal contract-signal ${signalClass(option.signal)}`}>{option.signal}</i></span>
                                    <span>
                                      <button
                                        type="button"
                                        className={`primary-observation-button ${isPrimaryObservation ? "active" : ""}`}
                                        aria-pressed={isPrimaryObservation}
                                        aria-label={`${isPrimaryObservation ? "当前为" : "设为"}${row.pair}${option.label}主要观察`}
                                        onClick={() => togglePrimaryObservation(row.pair, option.key)}
                                      >
                                        {isPrimaryObservation ? "主要观察中" : "设为主要观察"}
                                      </button>
                                    </span>
                                  </div>
                                  {isHistoryExpanded && option.historyChart && (
                                    <div className="contract-history-expanded" id={historyId}>
                                      <ContractHistoryChart chart={option.historyChart} formula={option.detail} />
                                    </div>
                                  )}
                                </Fragment>
                              );
                            })}
                          </div>
                        </td>
                      </tr>
                    )}
                    {isExpanded && !hasContracts && standaloneHistoryChart && (
                      <tr className="contract-detail-row reference-history-row">
                        <td colSpan={columns.length} id={detailId}>
                          <div className="contract-history-expanded">
                            <ContractHistoryChart chart={standaloneHistoryChart} formula={baseRow.formulaLabel} />
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
          <span>口径：国内商品默认 JQ00 持仓量加权，股指及铜铝锌内外盘国内腿使用 00 主连；风险溢价、美元银行融资压力代理、海外指数和马盘比价使用已批准外部源，跨日只向后匹配已公布数据。</span>
          <span>国内数据日：{dashboardData.dataDate} · 更新时间：每日 20:00</span>
        </footer>
      </section>

    </main>
  );
}
