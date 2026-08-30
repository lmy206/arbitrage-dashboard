import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  const fetchHandler = typeof worker === "function" ? worker : worker.fetch.bind(worker);

  return fetchHandler(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

const DAY_MS = 24 * 60 * 60 * 1000;
const HYBRID_CHART_GRAIN = "更早周频 · 最近20个交易日日线收盘";

function weekEndingFriday(date) {
  const value = new Date(`${date}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + ((5 - value.getUTCDay() + 7) % 7));
  return value.toISOString().slice(0, 10);
}

function assertHybridHistory(points, label = "history chart") {
  assert.ok(points.length >= 2, `${label} should include at least two points`);
  assert.ok(points.every((point, index) => (
    Number.isFinite(point.value)
    && (index === 0 || point.date > points[index - 1].date)
  )), `${label} dates should be unique and increasing`);
  if (points.length <= 20) return;

  const older = points.slice(0, -20);
  const recent = points.slice(-20);
  const olderBuckets = older.map((point) => weekEndingFriday(point.date));
  assert.equal(new Set(olderBuckets).size, olderBuckets.length, `${label} older observations should be weekly`);
  assert.ok(older.at(-1).date < recent[0].date, `${label} weekly and daily sections should not overlap`);

  const recentGaps = recent.slice(1).map((point, index) => Date.parse(point.date) - Date.parse(recent[index].date));
  assert.ok(recentGaps.filter((gap) => gap <= 4 * DAY_MS).length >= 15, `${label} latest 20 observations should be daily`);
  assert.ok(recentGaps.every((gap) => gap <= 15 * DAY_MS), `${label} latest observations should not have weekly spacing`);
}

test("server-renders the arbitrage dashboard", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>套利监测看板<\/title>/i);
  assert.match(html, /立即更新数据/);
  assert.match(html, /立即使用xtdata更新看板数据/);
  assert.match(html, /IM-IC价差/);
  assert.match(html, /IM期限套/);
  assert.match(html, /title="\(IM当月 − IM下季\) × 12 \/ 月差 \/ 中证1000"/);
  assert.match(html, /展开IM期限套观察口径/);
  assert.match(html, /title="IM00\.IF − IC00\.IF"/);
  assert.doesNotMatch(html, /title="IM00\.IF \/ IC00\.IF"/);
  assert.match(html, /title="IC00\.IF \/ IF00\.IF"/);
  assert.match(html, /title="mJQ00\.DF − RMJQ00\.ZF"/);
  assert.match(html, /title="rbJQ00\.SF \/ iJQ00\.DF"/);
  assert.match(html, /展开IM-IC价差合约月份/);
  assert.match(html, /豆粕价差/);
  assert.match(html, /蛋白质价差/);
  assert.doesNotMatch(html, /豆粕菜粕差/);
  assert.match(html, /焦炭\/焦煤比/);
  assert.match(html, /燃料油\/沥青比价/);
  assert.match(html, /20号胶\/BR橡胶比价/);
  assert.match(html, /烧碱\/玻璃比价/);
  assert.match(html, /镍\/不锈钢比价/);
  assert.doesNotMatch(html, /玻璃\/聚乙烯比价/);
  assert.doesNotMatch(html, /玻璃\/聚丙烯比价/);
  assert.match(html, /塑料-聚丙烯价差/);
  assert.doesNotMatch(html, /聚乙烯-聚丙烯价差/);
  assert.doesNotMatch(html, /MTO盘面利润/);
  assert.match(html, /聚丙烯\/甲醇比价/);
  assert.match(html, /title="ppJQ00\.DF \/ MAJQ00\.ZF"/);
  assert.match(html, /PTA盘面加工费/);
  assert.doesNotMatch(html, /玻璃生产利润/);
  assert.doesNotMatch(html, /焦化利润/);
  assert.match(html, /玻璃\/纯碱比价/);
  assert.doesNotMatch(html, /纯碱玻璃比/);
  assert.match(html, /title="FGJQ00\.ZF \/ SAJQ00\.ZF"/);
  assert.doesNotMatch(html, /纯碱玻璃差/);
  assert.match(html, /title="lJQ00\.DF − ppJQ00\.DF"/);
  assert.doesNotMatch(html, /title="ppJQ00\.DF − 3 × MAJQ00\.ZF"/);
  assert.match(html, /title="TAJQ00\.ZF − 0\.655 × PXJQ00\.ZF"/);
  assert.match(html, /猪肉\/玉米比价/);
  assert.match(html, /卷-螺价差/);
  assert.match(html, /铜\/铝比价/);
  assert.match(html, /金\/银比价/);
  assert.match(html, /油\/粕比价/);
  assert.match(html, /螺\/矿比价/);
  assert.doesNotMatch(html, /螺卷差/);
  assert.match(html, /title="hcJQ00\.SF − rbJQ00\.SF"/);
  assert.match(html, /铜内外盘比价/);
  assert.match(html, /铝内外盘比价/);
  assert.match(html, /锌内外盘比价/);
  assert.match(html, /ERP：沪深300/);
  assert.match(html, /ERP：标普500/);
  assert.match(html, /美元银行融资压力代理/);
  assert.match(html, /纳斯达克\/标普500/);
  assert.match(html, /马盘棕榈油\/美盘豆油/);
  assert.match(html, /展开铜内外盘比价现货折线图/);
  assert.match(html, /title="cu00\.SF \/ CAD\.LME"/);
  assert.match(html, /科创50\/上证50/);
  assert.doesNotMatch(html, /菜油菜粕比/);
  assert.match(html, /展开科创50\/上证50现货折线图/);
  assert.match(html, /展开创业板\/沪深300现货折线图/);
  assert.match(html, /国内 xtdata · 已批准外部源补充/);
  assert.match(html, /LME三个月电子盘/);
  assert.match(html, /美元兑人民币中间价/);
  assert.match(html, /国内商品默认 JQ00 持仓量加权，股指及铜铝锌内外盘国内腿使用 00 主连/);
  assert.doesNotMatch(html, /AkShare 补充校对/);
  assert.match(html, /近5年分位/);
  assert.match(html, /<th scope="col">收藏<\/th>/);
  assert.match(html, /aria-label="收藏ERP：沪深300"/);
  assert.match(html, /class="favorite-button "/);
  assert.doesNotMatch(html, /按类型排序/);
  assert.match(html, /class="strategy-type regression">回归/);
  assert.match(html, /极度偏高/);
  assert.match(html, /极度偏低/);
  assert.match(html, /title="全历史区间"/);
  assert.match(html, /title="近5年区间"/);
  assert.doesNotMatch(html, /图表分析/);
  assert.doesNotMatch(html, /近5年分位总览/);
  assert.doesNotMatch(html, /近3年分位/);
  assert.doesNotMatch(html, /周末值/);
  assert.doesNotMatch(html, /月末值/);
  assert.doesNotMatch(html, /chart-zero-line/);
  assert.doesNotMatch(html, /IM-IC价差走势/);
  assert.doesNotMatch(html, /IC\/IF比价走势/);
  assert.doesNotMatch(html, /IM\/IF比价走势/);
  assert.doesNotMatch(html, /螺\/矿比价走势/);
  assert.doesNotMatch(html, /油\/粕比价走势/);
  assert.doesNotMatch(html, /豆粕豆油比|豆油豆粕比/);
  assert.doesNotMatch(html, /铜\/铝比价走势/);
  assert.match(html, /左腿结构/);
  assert.match(html, /右腿结构/);
  assert.match(html, /Contango|Back/);
  assert.doesNotMatch(html, /<th[^>]*>校验<\/th>/);
  assert.doesNotMatch(html, /class="source-badge/);
  assert.doesNotMatch(html, /codex-preview|Building your site|react-loading-skeleton/i);
});

test("dashboard rows follow strategy, market and percentile hierarchy", async () => {
  const payload = JSON.parse(await readFile(new URL("../app/data/arbitrage.json", import.meta.url), "utf8"));
  const pinnedOrder = new Map([["ERP：沪深300", 0], ["ERP：标普500", 1], ["美元银行融资压力代理", 2]]);
  const strategyOrder = new Map([["回归", 0], ["趋势", 1], ["外盘监控", 2]]);
  const marketOrder = new Map([["股指", 0], ["农产品", 1], ["工业品", 2]]);
  const expected = [...payload.rows].sort((a, b) => (
    (pinnedOrder.has(a.pair) || pinnedOrder.has(b.pair))
      ? (pinnedOrder.get(a.pair) ?? Number.MAX_SAFE_INTEGER) - (pinnedOrder.get(b.pair) ?? Number.MAX_SAFE_INTEGER)
      : strategyOrder.get(a.strategyType) - strategyOrder.get(b.strategyType)
    || marketOrder.get(a.marketCategory) - marketOrder.get(b.marketCategory)
    || b.percentile - a.percentile
    || (a.pair < b.pair ? -1 : a.pair > b.pair ? 1 : 0)
  ));

  assert.deepEqual(payload.rows.map((row) => row.pair), expected.map((row) => row.pair));
  assert.ok(payload.rows.every((row) => marketOrder.has(row.marketCategory)));
});

test("pinned risk and dollar-funding indicators stay first, followed by regression, trend and external-monitor pairs", async () => {
  const response = await render();
  const html = await response.text();
  const tableBody = html.slice(html.indexOf("<tbody>"), html.indexOf("</tbody>"));
  const cnRisk = tableBody.indexOf("ERP：沪深300");
  const usRisk = tableBody.indexOf("ERP：标普500");
  const usdFunding = tableBody.indexOf("美元银行融资压力代理");
  const remainingTableBody = tableBody.slice(usdFunding + "美元银行融资压力代理".length);
  const firstRegression = remainingTableBody.indexOf('class="strategy-type regression">回归');
  const lastRegression = remainingTableBody.lastIndexOf('class="strategy-type regression">回归');
  const firstTrend = remainingTableBody.indexOf('class="strategy-type trend">趋势');
  const lastTrend = remainingTableBody.lastIndexOf('class="strategy-type trend">趋势');
  const firstExternalMonitor = remainingTableBody.indexOf('class="strategy-type external-monitor">外盘监控');

  assert.ok(cnRisk >= 0 && usRisk > cnRisk && usdFunding > usRisk);
  assert.ok(firstRegression >= 0);
  assert.ok(lastRegression >= 0);
  assert.ok(firstTrend > lastRegression, "trend pairs should stay below every regression pair");
  assert.ok(firstExternalMonitor > lastTrend, "external-monitor pairs should stay at the very bottom");
});

test("expanded contract lists omit the extra main-continuous observation", async () => {
  const pageSource = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(pageSource, /const favoriteStorageKey = "arbitrage-favorites-v1"/);
  assert.match(pageSource, /"螺\/矿比价": \["螺矿比"\]/);
  assert.match(pageSource, /"油\/粕比价": \["油粕比"\]/);
  assert.match(pageSource, /"卷-螺价差": \["卷螺价差"\]/);
  assert.match(pageSource, /"铜\/铝比价": \["铜铝比"\]/);
  assert.match(pageSource, /"金\/银比价": \["金银比"\]/);
  assert.match(pageSource, /"聚丙烯\/甲醇比价": \["MTO盘面利润"\]/);
  assert.match(pageSource, /"玻璃\/纯碱比价": \["玻璃\/纯碱比", "玻璃纯碱比", "纯碱玻璃比"\]/);
  assert.match(pageSource, /"焦炭\/焦煤比": \["焦炭焦煤比"\]/);
  assert.match(pageSource, /"塑料-聚丙烯价差": \["聚乙烯-聚丙烯价差"\]/);
  assert.match(pageSource, /"玻璃\/纯碱比价": \["玻璃\/纯碱比", "玻璃纯碱比", "纯碱玻璃比", "玻璃生产利润"\]/);
  assert.match(pageSource, /"焦炭\/焦煤比": \["焦炭焦煤比", "焦化利润"\]/);
  assert.match(pageSource, /row\.relatedObservations\?\.find/);
  assert.match(pageSource, /\.\.\.related,\s*defaultObservation/);
  assert.match(pageSource, /window\.localStorage\.getItem\(favoriteStorageKey\)/);
  assert.match(pageSource, /window\.localStorage\.setItem\(favoriteStorageKey, JSON\.stringify\(favoriteTimes\)\)/);
  assert.match(pageSource, /return bFavoriteTime - aFavoriteTime/);
  assert.match(pageSource, /Math\.max\(Date\.now\(\), latestExistingTime \+ 1\)/);
  assert.match(pageSource, /aria-pressed={isFavorite}/);

  assert.doesNotMatch(pageSource, /if \(row\.mainContinuousObservation\)\s*{\s*pinned\.push/);
  assert.doesNotMatch(pageSource, /expiry === "main"/);
  assert.doesNotMatch(pageSource, /selectedObservation === "main"/);
});

test("contract month rows can expand same-month ten-year charts without bridging long gaps", async () => {
  const pageSource = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");

  assert.match(pageSource, /历年同月合约折线图/);
  assert.match(pageSource, /gapThreshold = 21 \* 24 \* 60 \* 60 \* 1000/);
  assert.match(pageSource, /const height = 270/);
  assert.match(pageSource, /quantile\(values, 0\.03\)/);
  assert.match(pageSource, /quantile\(values, 0\.97\)/);
  assert.match(pageSource, /chart\.fixedThresholds \?\?/);
  assert.match(pageSource, /thresholds\.map\(\(threshold\) => threshold\.label\)\.join\(" \/ "\)/);
  assert.match(pageSource, /3%\/97%阈值按图内全部历史值/);
  assert.match(pageSource, /chart\.fixedThresholds\s*\? threshold\.label\s*:\s*`\$\{threshold\.label\}阈值/);
  assert.match(pageSource, /historyChart: row\.spotObservation\.historyChart/);
  assert.match(pageSource, /historyChart: row\.mainHistoryChart/);
  assert.match(pageSource, /row\.termObservations\?\.length/);
  assert.match(pageSource, /hasTermObservations/);
  assert.match(pageSource, /option\.term \? option\.rightSymbol/);
  assert.match(pageSource, /<ContractHistoryChart chart={option\.historyChart} formula={option\.detail} \/>/);
  assert.match(pageSource, /<ContractHistoryChart chart={standaloneHistoryChart} formula={baseRow\.formulaLabel} \/>/);
  assert.match(pageSource, /className="contract-history-formula">公式：{formula}/);
  assert.match(pageSource, /<span>近5年分位<\/span>/);
  assert.match(pageSource, /<span>判断<\/span>/);
  assert.match(pageSource, /当月涨跌幅/);
  assert.match(pageSource, /远季涨跌幅/);
  assert.match(pageSource, /contractRootLabel\(baseRow\.leftSymbol\).*涨跌幅/);
  assert.match(pageSource, /contractRootLabel\(baseRow\.rightSymbol\).*涨跌幅/);
  assert.match(pageSource, /M: "豆粕"/);
  assert.match(pageSource, /RM: "菜粕"/);
  assert.match(pageSource, /CU: "铜"/);
  assert.match(pageSource, /AL: "铝"/);
  assert.match(pageSource, /IC: "中证500"/);
  assert.match(pageSource, /IF: "沪深300"/);
  assert.doesNotMatch(pageSource, />左腿涨跌</);
  assert.doesNotMatch(pageSource, />右腿涨跌</);
  assert.match(pageSource, /formatLegChange\(option\.leftChangePct\)/);
  assert.match(pageSource, /formatLegChange\(option\.rightChangePct\)/);
  assert.match(pageSource, /option\.percentile\.toFixed/);
  assert.match(pageSource, /signalClass\(option\.signal\)/);
});

test("monthly contract details contain only current values and liquidity", async () => {
  const payload = JSON.parse(await readFile(new URL("../app/data/arbitrage.json", import.meta.url), "utf8"));
  assert.equal(payload.rows.length, 36);
  assert.equal(payload.contractMode, "商品期货持仓量加权(JQ00)；股指及铜铝锌内外盘国内腿使用主力连续(00)；LME使用三个月行情；IM期限套展示当月对下季及隔季；外部股指、估值、纽约联储参考利率与CBOT油粕指标使用各源公布值");
  const trendPairs = payload.rows.filter((row) => row.strategyType === "趋势").map((row) => row.pair).sort();
  assert.deepEqual(trendPairs, ["油/粕比价", "金/银比价"].sort());
  const externalMonitorPairs = payload.rows.filter((row) => row.strategyType === "外盘监控").map((row) => row.pair).sort();
  assert.deepEqual(externalMonitorPairs, ["ERP：标普500", "美元银行融资压力代理", "美盘油粕比", "马盘棕榈油/美盘豆油", "铜内外盘比价", "铝内外盘比价", "锌内外盘比价"].sort());
  assert.equal(payload.rows.filter((row) => row.strategyType === "回归").length, 27);
  assert.deepEqual(payload.rows.slice(0, 3).map((row) => row.pair), ["ERP：沪深300", "ERP：标普500", "美元银行融资压力代理"]);

  const expectedSignal = (percentile) => {
    if (percentile >= 95) return "极度偏高";
    if (percentile >= 85) return "偏高";
    if (percentile <= 5) return "极度偏低";
    if (percentile <= 15) return "偏低";
    return "中性";
  };

  const oilseedMonthPairs = new Set([
    "棕榈油菜油比",
    "油/粕比价",
    "豆油菜油比",
    "豆粕价差",
    "蛋白质价差",
    "豆棕价差",
  ]);
  const filteredMonthPairs = new Set([...oilseedMonthPairs, "螺/矿比价", "焦炭/焦煤比"]);

  for (const row of payload.rows) {
    const isEquityIndex = [row.leftSymbol, row.rightSymbol].some((symbol) => /^(IC|IM|IF)00\.IF$/.test(symbol));
    assert.equal(row.signal, expectedSignal(row.percentile), `${row.pair} signal band`);
    if (row.spotObservation) {
      assert.equal(row.spotObservation.signal, expectedSignal(row.spotObservation.percentile), `${row.pair} spot signal band`);
    }
    const expectedContractCount = ["现货参考", "期限套利", "跨市场套利", "外盘参考"].includes(row.pairType)
      ? 0
      : (filteredMonthPairs.has(row.pair) || isEquityIndex ? null : 4);
    if (expectedContractCount === null) {
      assert.ok(row.contracts.length > 0 && row.contracts.length <= 4, `${row.pair} filtered contract detail count`);
    } else {
      assert.equal(row.contracts.length, expectedContractCount, `${row.pair} contract detail count`);
    }
    for (let index = 1; index < row.contracts.length; index += 1) {
      assert.ok(
        row.contracts[index - 1].expiry < row.contracts[index].expiry,
        `${row.pair} contract months should be displayed from nearest to farthest expiry`,
      );
    }
    for (const contract of row.contracts) {
      assert.equal(contract.signal, expectedSignal(contract.percentile), `${row.pair} ${contract.expiry} signal band`);
      assert.deepEqual(
        Object.keys(contract).sort(),
        [
          "allTime",
          "allTimeRange",
          "change",
          "changeValue",
          "current",
          "deviation",
          "expiry",
          "leftSymbol",
          "leftChangePct",
          "leftVolume",
          "lots",
          "margin",
          "notional",
          "pairedVolume",
          "percentile",
          "fiveYearRange",
          "historyChart",
          "previous",
          "rightSymbol",
          "rightChangePct",
          "rightVolume",
          "signal",
          "sourceStatus",
        ].sort(),
      );
      assert.equal(contract.pairedVolume, Math.min(contract.leftVolume, contract.rightVolume));
      assert.ok(Number.isFinite(contract.leftChangePct), `${row.pair} ${contract.expiry} left-leg daily return`);
      assert.ok(Number.isFinite(contract.rightChangePct), `${row.pair} ${contract.expiry} right-leg daily return`);
      assert.ok(contract.percentile >= 0 && contract.percentile <= 100);
      assert.match(contract.allTimeRange, /^.+ ~ .+$/);
      assert.match(contract.fiveYearRange, /^.+ ~ .+$/);
      assert.equal(contract.sourceStatus, "仅xtdata");
      if (isEquityIndex) {
        assert.equal(contract.historyChart, null, `${row.pair} ${contract.expiry} should not include a same-month history chart`);
        continue;
      }
      assert.ok(contract.historyChart, `${row.pair} ${contract.expiry} should include a same-month history chart`);
      assert.equal(contract.historyChart.month, contract.expiry.slice(-2));
      assert.equal(contract.historyChart.source, "xtdata");
      assert.equal(contract.historyChart.grain, HYBRID_CHART_GRAIN);
      assert.ok(contract.historyChart.series.length >= 1 && contract.historyChart.series.length <= 10);
      assert.equal(new Set(contract.historyChart.series.map((series) => series.expiry)).size, contract.historyChart.series.length);
      for (const series of contract.historyChart.series) {
        assert.equal(series.expiry.slice(-2), contract.expiry.slice(-2));
        assert.ok(series.points.length >= 2, `${row.pair} ${series.expiry} should have enough daily points`);
        assertHybridHistory(series.points, `${row.pair} ${series.expiry}`);
        assert.ok(
          Date.parse(series.points.at(-1).date) - Date.parse(series.points[0].date) <= 400 * 24 * 60 * 60 * 1000,
          `${row.pair} ${series.expiry} should be a concrete contract rather than an ambiguous long series`,
        );
        assert.ok(series.points.every((point, index) => (
          Number.isFinite(point.value) &&
          point.date >= contract.historyChart.startDate &&
          point.date <= contract.historyChart.endDate &&
          (index === 0 || point.date > series.points[index - 1].date)
        )));
      }
      const selectedSeries = contract.historyChart.series.find((series) => series.expiry === contract.expiry);
      assert.ok(selectedSeries, `${row.pair} ${contract.expiry} should be part of its same-month history sample`);
      const selectedCurrent = selectedSeries.points.at(-1).value;
      const allSeasonalPoints = contract.historyChart.series.flatMap((series) => series.points);
      const allTimePercentile = Math.round(
        allSeasonalPoints.filter((point) => point.value <= selectedCurrent).length / allSeasonalPoints.length * 10000,
      ) / 100;
      const fiveYearStart = new Date(`${selectedSeries.points.at(-1).date}T00:00:00Z`);
      fiveYearStart.setUTCFullYear(fiveYearStart.getUTCFullYear() - 5);
      const fiveYearStartDate = fiveYearStart.toISOString().slice(0, 10);
      const fiveYearSeasonalPoints = allSeasonalPoints.filter((point) => point.date >= fiveYearStartDate);
      const fiveYearPercentile = Math.round(
        fiveYearSeasonalPoints.filter((point) => point.value <= selectedCurrent).length / fiveYearSeasonalPoints.length * 10000,
      ) / 100;
      assert.ok(
        Math.abs(Number.parseFloat(contract.allTime) - allTimePercentile) <= 5,
        `${row.pair} ${contract.expiry} all-time percentile should stay consistent with the compact same-month chart`,
      );
      assert.ok(
        Math.abs(contract.percentile - fiveYearPercentile) <= 5,
        `${row.pair} ${contract.expiry} five-year percentile should stay consistent with the compact same-month chart`,
      );
    }
  }

  const imIc = payload.rows.find((row) => row.pair === "IM-IC价差");
  const imIcExpiries = new Set(imIc.contracts.map((contract) => contract.expiry));
  assert.ok(imIcExpiries.size > 0 && imIcExpiries.size <= 4);
  assert.ok(imIc.contracts.every((contract) => /^\d{4}$/.test(contract.expiry)));

  for (const pair of oilseedMonthPairs) {
    const row = payload.rows.find((candidate) => candidate.pair === pair);
    assert.ok(row, `${pair} should be present`);
    assert.ok(row.contracts.length > 0 && row.contracts.length <= 4, `${pair} should have filtered contract details`);
    assert.ok(row.contracts.every((contract) => ["01", "05", "09"].includes(contract.expiry.slice(-2))), `${pair} should only show 1/5/9 contracts`);
  }

  const rebarOreRatio = payload.rows.find((row) => row.pair === "螺/矿比价");
  assert.ok(rebarOreRatio.contracts.length > 0 && rebarOreRatio.contracts.length <= 4);
  assert.ok(rebarOreRatio.contracts.every((contract) => ["01", "05", "09"].includes(contract.expiry.slice(-2))));

  const proteinJanuary = payload.rows
    .find((row) => row.pair === "蛋白质价差")
    .contracts.find((contract) => contract.expiry === "2701");
  assert.ok(proteinJanuary.historyChart.series.length > 5, "2701 should include more than five historical January contracts");
  assert.deepEqual(proteinJanuary.historyChart.series.map((series) => series.expiry).slice(-5), ["2301", "2401", "2501", "2601", "2701"]);
  assert.ok(
    Date.parse(proteinJanuary.historyChart.endDate) - Date.parse(proteinJanuary.historyChart.startDate) >= 3650 * 24 * 60 * 60 * 1000,
    "2701 chart should span at least ten calendar years",
  );
  assert.equal(proteinJanuary.historyChart.title, "蛋白质价差历年1月合约");

  const cokeCoal = payload.rows.find((row) => row.pair === "焦炭/焦煤比");
  assert.ok(cokeCoal, "焦炭/焦煤比 should be present");
  assert.equal(cokeCoal.leftSymbol, "jJQ00.DF");
  assert.equal(cokeCoal.rightSymbol, "jmJQ00.DF");
  assert.equal(cokeCoal.current, (Number(cokeCoal.current)).toFixed(4));
  assert.ok(cokeCoal.contracts.length > 0 && cokeCoal.contracts.length <= 4);
  assert.ok(
    cokeCoal.contracts.every((contract) => ["01", "05", "09"].includes(contract.expiry.slice(-2))),
    "焦炭/焦煤比 should only show weighted and 1/5/9 contract observations",
  );

  const oilMeal = payload.rows.find((row) => row.pair === "油/粕比价");
  assert.ok(oilMeal, "油/粕比价 should be present");
  assert.equal(oilMeal.leftSymbol, "yJQ00.DF");
  assert.equal(oilMeal.rightSymbol, "mJQ00.DF");
  assert.equal(oilMeal.current, (Number(oilMeal.current)).toFixed(4));

  const addedRatios = new Map([
    ["燃料油/沥青比价", ["fuJQ00.SF", "buJQ00.SF"]],
    ["20号胶/BR橡胶比价", ["nrJQ00.INE", "brJQ00.SF"]],
    ["烧碱/玻璃比价", ["SHJQ00.ZF", "FGJQ00.ZF"]],
    ["镍/不锈钢比价", ["niJQ00.SF", "ssJQ00.SF"]],
    ["猪肉/玉米比价", ["lhJQ00.DF", "cJQ00.DF"]],
    ["聚丙烯/甲醇比价", ["ppJQ00.DF", "MAJQ00.ZF"]],
  ]);
  for (const [pair, [leftSymbol, rightSymbol]] of addedRatios) {
    const row = payload.rows.find((item) => item.pair === pair);
    assert.ok(row, `${pair} should be present`);
    assert.match(row.pair, /比价$/);
    assert.equal(row.leftSymbol, leftSymbol);
    assert.equal(row.rightSymbol, rightSymbol);
    assert.equal(row.current, Number(row.current).toFixed(4));
  }

  assert.equal(payload.rows.some((row) => row.pair === "玻璃/聚乙烯比价"), false);
  assert.equal(payload.rows.some((row) => row.pair === "玻璃/聚丙烯比价"), false);
  const glassSoda = payload.rows.find((row) => row.pair === "玻璃/纯碱比价");
  assert.ok(glassSoda);
  assert.equal(glassSoda.leftSymbol, "FGJQ00.ZF");
  assert.equal(glassSoda.rightSymbol, "SAJQ00.ZF");
  assert.equal(glassSoda.current, Number(glassSoda.current).toFixed(4));
  assert.equal(payload.rows.some((row) => row.pair === "纯碱玻璃比"), false);

  const relatedObservations = new Map([
    ["聚丙烯/甲醇比价", ["mto-screen-margin", "MTO盘面利润", "ppJQ00.DF", "MAJQ00.ZF", "聚丙烯 − 3 × 甲醇（未扣加工费等）", "2:3"]],
    ["玻璃/纯碱比价", ["glass-production-profit", "玻璃生产利润", "FGJQ00.ZF", "SAJQ00.ZF", "FG − 0.2 × SA（未扣燃料与其他成本）", "5:1"]],
    ["焦炭/焦煤比", ["coking-profit", "焦化利润", "jJQ00.DF", "jmJQ00.DF", "J − 1.3 × JM（未扣其他成本）", "6:13"]],
  ]);
  for (const [parentPair, [key, label, leftSymbol, rightSymbol, formulaLabel, lots]] of relatedObservations) {
    const parent = payload.rows.find((row) => row.pair === parentPair);
    assert.ok(parent);
    assert.equal(parent.relatedObservations.length, 1);
    const observation = parent.relatedObservations[0];
    assert.equal(observation.key, key);
    assert.equal(observation.label, label);
    assert.equal(observation.leftSymbol, leftSymbol);
    assert.equal(observation.rightSymbol, rightSymbol);
    assert.equal(observation.formulaLabel, formulaLabel);
    assert.equal(observation.lots, lots);
    assert.match(observation.current, /^-?\d+$/);
    assert.ok(observation.historyChart);
    assert.equal(observation.historyChart.title, `${label}加权走势`);
    assert.equal(observation.historyChart.series[0].expiry, "加权");
    assert.ok(observation.historyChart.series[0].points.length >= 300);
  }
  assert.equal(payload.rows.some((row) => row.pair === "玻璃生产利润"), false);
  assert.equal(payload.rows.some((row) => row.pair === "焦化利润"), false);
  assert.equal(payload.rows.some((row) => row.pair === "MTO盘面利润"), false);

  const replacementSpreads = new Map([
    ["塑料-聚丙烯价差", ["lJQ00.DF", "ppJQ00.DF", "塑料 − 聚丙烯", "1:1"]],
    ["PTA盘面加工费", ["TAJQ00.ZF", "PXJQ00.ZF", "PTA − 0.655 × PX（未扣其他成本）", "20:13"]],
  ]);
  for (const [pair, [leftSymbol, rightSymbol, formulaLabel, expectedLots]] of replacementSpreads) {
    const row = payload.rows.find((item) => item.pair === pair);
    assert.ok(row, `${pair} should be present`);
    assert.equal(row.leftSymbol, leftSymbol);
    assert.equal(row.rightSymbol, rightSymbol);
    assert.equal(row.formulaLabel, formulaLabel);
    assert.equal(row.lots, expectedLots);
    assert.ok(row.contracts.every((contract) => contract.lots === expectedLots));
    assert.match(row.current, /^-?\d+$/);
    assert.ok(row.mainHistoryChart, `${pair} should include a weighted-index chart`);
  }

  for (const row of payload.rows.filter((item) => item.pairType === "期货套利")) {
    const isEquityIndex = [row.leftSymbol, row.rightSymbol].some((symbol) => /^(IC|IM|IF)00\.IF$/.test(symbol));
    if (isEquityIndex) {
      assert.equal(row.seriesMode, "main", `${row.pair} should keep the 00 main-continuous default`);
      assert.equal(row.mainContinuousObservation, null);
      assert.ok(row.mainHistoryChart, `${row.pair} should include an expandable main-continuous chart`);
    } else {
      assert.equal(row.seriesMode, "weighted", `${row.pair} should use the JQ00 weighted default`);
      assert.ok(row.mainHistoryChart, `${row.pair} should include an expandable weighted-index chart`);
      assert.equal(row.mainHistoryChart.series[0].expiry, "加权");
      assert.match(row.leftSymbol, /JQ00\./);
      assert.match(row.rightSymbol, /JQ00\./);
      assert.ok(row.mainContinuousObservation, `${row.pair} should retain a main-continuous observation`);
      assert.doesNotMatch(row.mainContinuousObservation.leftSymbol, /JQ00\./);
      assert.doesNotMatch(row.mainContinuousObservation.rightSymbol, /JQ00\./);
    }
  }

  for (const row of payload.rows) {
    assert.match(row.allTimeRange, /^.+ ~ .+$/, `${row.pair} all-time range`);
    assert.match(row.fiveYearRange, /^.+ ~ .+$/, `${row.pair} five-year range`);
  }
});

test("equity-index futures pairs include a pinned spot observation", async () => {
  const payload = JSON.parse(await readFile(new URL("../app/data/arbitrage.json", import.meta.url), "utf8"));
  const expected = new Map([
    ["IC/IF比价", ["中证500/沪深300", "000905.SH", "000300.SH"]],
    ["IM/IF比价", ["中证1000/沪深300", "000852.SH", "000300.SH"]],
    ["IM-IC价差", ["中证1000-中证500", "000852.SH", "000905.SH"]],
  ]);

  for (const [pair, [label, leftSymbol, rightSymbol]] of expected) {
    const row = payload.rows.find((item) => item.pair === pair);
    assert.equal(row.spotObservation.label, label);
    assert.equal(row.spotObservation.leftSymbol, leftSymbol);
    assert.equal(row.spotObservation.rightSymbol, rightSymbol);
    assert.ok(row.spotObservation.percentile >= 0 && row.spotObservation.percentile <= 100);
    for (const [chart, seriesLabel] of [
      [row.spotObservation.historyChart, "现货指数"],
      [row.mainHistoryChart, "主连"],
    ]) {
      assert.ok(chart, `${pair} ${seriesLabel} chart should be present`);
      assert.equal(chart.source, "xtdata");
      assert.equal(chart.grain, HYBRID_CHART_GRAIN);
      assert.equal(chart.series.length, 1);
      assert.equal(chart.series[0].expiry, seriesLabel);
      assert.ok(chart.series[0].points.length >= 180);
      assertHybridHistory(chart.series[0].points, `${pair} ${seriesLabel}`);
      assert.ok(Date.parse(chart.endDate) - Date.parse(chart.startDate) >= 1000 * 24 * 60 * 60 * 1000);
    }
    assert.ok(row.contracts.every((contract) => contract.historyChart === null));
  }
  assert.equal(payload.rows.filter((row) => row.spotObservation !== null).length, expected.size);
});

test("every weighted pair includes an expandable ten-year weighted-index chart", async () => {
  const payload = JSON.parse(await readFile(new URL("../app/data/arbitrage.json", import.meta.url), "utf8"));
  const weightedRows = payload.rows.filter((row) => row.seriesMode === "weighted");

  assert.ok(weightedRows.length > 0);
  for (const row of weightedRows) {
    const chart = row.mainHistoryChart;
    assert.ok(chart, `${row.pair} should include a weighted-index chart`);
    assert.equal(chart.title, `${row.pair}加权走势`);
    assert.equal(chart.source, "xtdata");
    assert.equal(chart.grain, HYBRID_CHART_GRAIN);
    assert.equal(chart.series.length, 1);
    assert.equal(chart.series[0].expiry, "加权");
    assert.equal(chart.series[0].leftSymbol, row.leftSymbol);
    assert.equal(chart.series[0].rightSymbol, row.rightSymbol);
    assert.ok(chart.series[0].points.length >= 120);
    assertHybridHistory(chart.series[0].points, row.pair);
    assert.equal(chart.series[0].points.at(-1).date, payload.dataDate);
    assert.ok(Date.parse(chart.endDate) - Date.parse(chart.startDate) >= 600 * 24 * 60 * 60 * 1000);
    assert.ok(chart.series[0].points.every((point) => point.date <= payload.dataDate));
  }

  const pageSource = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(pageSource, /historyChart: row\.mainHistoryChart/);
  assert.match(pageSource, /historyToggleLabel\(row\.pair, option\.label, isHistoryExpanded\)/);
  assert.match(pageSource, /option\.historyChart &&/);
});

test("spot-reference pairs include expandable xtdata history charts", async () => {
  const payload = JSON.parse(await readFile(new URL("../app/data/arbitrage.json", import.meta.url), "utf8"));
  const expected = new Map([
    ["科创50/上证50", ["000688.SH", "000016.SH"]],
    ["创业板/沪深300", ["399006.SZ", "000300.SH"]],
  ]);

  for (const [pair, [leftSymbol, rightSymbol]] of expected) {
    const row = payload.rows.find((item) => item.pair === pair);
    assert.equal(row.pairType, "现货参考");
    assert.equal(row.contracts.length, 0);
    assert.equal(row.spotObservation, null);
    assert.ok(row.mainHistoryChart, `${pair} should include an expandable spot chart`);
    assert.equal(row.mainHistoryChart.title, `${pair}现货走势`);
    assert.equal(row.mainHistoryChart.source, "xtdata");
    assert.equal(row.mainHistoryChart.grain, HYBRID_CHART_GRAIN);
    assert.equal(row.mainHistoryChart.series.length, 1);
    assert.equal(row.mainHistoryChart.series[0].expiry, "现货");
    assert.equal(row.mainHistoryChart.series[0].leftSymbol, leftSymbol);
    assert.equal(row.mainHistoryChart.series[0].rightSymbol, rightSymbol);
    assert.ok(row.mainHistoryChart.series[0].points.length >= 300);
    assertHybridHistory(row.mainHistoryChart.series[0].points, pair);
    assert.equal(row.mainHistoryChart.series[0].points.at(-1).date, payload.dataDate);
  }
});

test("IM term spread exposes down-quarter and skip-quarter observations without future data", async () => {
  const payload = JSON.parse(await readFile(new URL("../app/data/arbitrage.json", import.meta.url), "utf8"));
  const row = payload.rows.find((item) => item.pair === "IM期限套");

  assert.ok(row);
  assert.equal(row.pairType, "期限套利");
  assert.equal(row.seriesMode, "term");
  assert.equal(row.denominatorSymbol, "000852.SH");
  assert.equal(row.rollTradingDays, undefined);
  assert.equal(row.rollRule, "当月合约正常跟踪至到期，到期后自然切换为次月合约");
  assert.equal(row.formulaLabel, "(IM当月 − IM下季) × 12 / 月差 / 中证1000");
  assert.match(row.leftSymbol, /^IM\d{4}\.IF$/);
  assert.match(row.rightSymbol, /^IM\d{4}\.IF$/);
  assert.ok(row.leftSymbol < row.rightSymbol);
  assert.equal(row.contracts.length, 0);
  assert.equal(row.leftStructure, null);
  assert.equal(row.rightStructure, null);
  assert.equal(row.spotObservation, null);
  assert.ok(Number.isFinite(row.nearPrice));
  assert.ok(Number.isFinite(row.farPrice));
  assert.ok(Number.isFinite(row.spotPrice));
  const expirySerial = (symbol) => {
    const match = symbol.match(/^IM(\d{2})(\d{2})\.IF$/);
    assert.ok(match, `${symbol} should be a concrete IM contract`);
    return Number(match[1]) * 12 + Number(match[2]);
  };
  const expectedMonthGap = expirySerial(row.rightSymbol) - expirySerial(row.leftSymbol);
  assert.equal(row.monthGap, expectedMonthGap);
  const expectedCurrent = (row.nearPrice - row.farPrice) * 12 / row.monthGap / row.spotPrice;
  assert.equal(row.current, `${(expectedCurrent * 100).toFixed(2)}%`);
  assert.match(row.previous, /^-?\d+\.\d{2}%$/);
  assert.match(row.change, /^[+-]\d+\.\d{2}%$/);
  assert.match(row.allTimeRange, /^-?\d+\.\d{2}% ~ -?\d+\.\d{2}%$/);
  assert.match(row.fiveYearRange, /^-?\d+\.\d{2}% ~ -?\d+\.\d{2}%$/);
  assert.deepEqual(row.termObservations.map((item) => [item.key, item.label]), [
    ["term-down", "下季"],
    ["term-skip", "隔季"],
  ]);
  assert.equal(row.termObservations[0].rightSymbol, row.rightSymbol);
  assert.deepEqual(row.mainHistoryChart, row.termObservations[0].historyChart);

  const [down, skip] = row.termObservations;
  assert.equal(expirySerial(skip.rightSymbol) - expirySerial(down.rightSymbol), 3);

  for (const observation of row.termObservations) {
    assert.equal(observation.denominatorSymbol, "000852.SH");
    assert.equal(observation.leftSymbol, row.leftSymbol);
    assert.match(observation.formulaLabel, /^\(IM当月 − IM(下季|隔季)\) × 12 \/ 月差 \/ 中证1000$/);
    assert.equal(observation.monthGap, expirySerial(observation.rightSymbol) - expirySerial(observation.leftSymbol));
    const observationCurrent = (observation.nearPrice - observation.farPrice) * 12 / observation.monthGap / observation.spotPrice;
    assert.equal(observation.current, `${(observationCurrent * 100).toFixed(2)}%`);
    assert.match(observation.previous, /^-?\d+\.\d{2}%$/);
    assert.match(observation.change, /^[+-]\d+\.\d{2}%$/);
    assert.match(observation.allTimeRange, /^-?\d+\.\d{2}% ~ -?\d+\.\d{2}%$/);
    assert.match(observation.fiveYearRange, /^-?\d+\.\d{2}% ~ -?\d+\.\d{2}%$/);
    const chart = observation.historyChart;
    assert.ok(chart);
    assert.equal(chart.title, `IM期限套（当月-${observation.label}）走势`);
    assert.equal(chart.unit, "百分比");
    assert.equal(chart.source, "xtdata");
    assert.equal(chart.grain, HYBRID_CHART_GRAIN);
    assert.equal(chart.series.length, 1);
    assert.equal(chart.series[0].expiry, observation.label);
    assert.ok(chart.series[0].points.length >= 180);
    assertHybridHistory(chart.series[0].points, `IM期限套 ${observation.label}`);
    assert.ok(chart.series[0].points[0].date >= "2022-07-22");
    assert.equal(chart.startDate, chart.series[0].points[0].date);
    assert.equal(chart.series[0].points.at(-1).date, payload.dataDate);
    assert.ok(Math.abs(chart.series[0].points.at(-1).value - observationCurrent) <= 0.0000005);
    assert.ok(chart.series[0].points.every((point, index) => (
      Number.isFinite(point.value)
      && point.date <= payload.dataDate
      && (index === 0 || point.date > chart.series[0].points[index - 1].date)
    )));
  }
});

test("each tradable leg has a valid futures term-structure classification", async () => {
  const payload = JSON.parse(await readFile(new URL("../app/data/arbitrage.json", import.meta.url), "utf8"));
  for (const row of payload.rows) {
    if (row.pairType === "跨市场套利" && row.pair !== "马盘棕榈油/美盘豆油") {
      assert.ok(row.leftStructure);
      assert.ok(["Contango", "Back"].includes(row.leftStructure.state));
      assert.equal(row.rightStructure, null);
      continue;
    }
    if (["现货参考", "期限套利", "外盘参考"].includes(row.pairType) || row.pair === "马盘棕榈油/美盘豆油") {
      assert.equal(row.leftStructure, null);
      assert.equal(row.rightStructure, null);
      continue;
    }
    for (const structure of [row.leftStructure, row.rightStructure]) {
      assert.ok(structure);
      assert.ok(["Contango", "Back"].includes(structure.state));
      assert.ok(structure.contractCount >= 2 && structure.contractCount <= 4);
      assert.ok(structure.nearExpiry < structure.farExpiry);
      assert.equal(structure.state, structure.changePct >= 0 ? "Contango" : "Back");
    }
  }
});

test("xtdata-only integrity validation is internally consistent", async () => {
  const payload = JSON.parse(await readFile(new URL("../app/data/arbitrage.json", import.meta.url), "utf8"));
  const validation = payload.sourceValidation;
  assert.match(payload.source, /xtdata.*用户批准/);
  assert.equal(validation.mode, "xtdata_only");
  assert.equal(validation.summary.total, 75);
  assert.equal(validation.checks.length, validation.summary.total);
  assert.equal(validation.summary.consistent, validation.summary.total);
  assert.equal(validation.summary.review, 0);
  assert.equal(validation.summary.unavailable, 0);
  assert.ok(validation.checks.every((check) => check.date === payload.dataDate));
  assert.ok(validation.checks.every((check) => check.status === "完整"));
  assert.ok(validation.checks.every((check) => check.akMode === "disabled"));
});

test("copper aluminum and zinc cross-market ratios use domestic main-continuous divided directly by LME 3M", async () => {
  const payload = JSON.parse(await readFile(new URL("../app/data/arbitrage.json", import.meta.url), "utf8"));
  const expected = new Map([
    ["铜内外盘比价", ["cu00.SF", "CAD.LME", "CAD"]],
    ["铝内外盘比价", ["al00.SF", "AHD.LME", "AHD"]],
    ["锌内外盘比价", ["zn00.SF", "ZSD.LME", "ZSD"]],
  ]);

  for (const [pair, [domesticSymbol, externalSymbol, lmeSymbol]] of expected) {
    const row = payload.rows.find((item) => item.pair === pair);
    assert.ok(row, `${pair} should be present`);
    assert.equal(row.pairType, "跨市场套利");
    assert.equal(row.seriesMode, "external");
    assert.equal(row.leftSymbol, domesticSymbol);
    assert.match(row.leftSymbol, /00\./);
    assert.doesNotMatch(row.leftSymbol, /JQ00\./);
    assert.equal(row.rightSymbol, externalSymbol);
    assert.equal(row.sourceStatus, "外部补充");
    assert.equal(row.contracts.length, 0);
    assert.equal(row.externalSourceDate, payload.dataDate);
    assert.ok(row.domesticPrice > 0);
    assert.ok(row.lmePriceUsdPerTonne > 0);
    assert.equal(row.usdCnyMid, undefined);
    const expectedRatio = row.domesticPrice / row.lmePriceUsdPerTonne;
    assert.ok(Math.abs(Number(row.current) - expectedRatio) < 0.0001);
    assert.equal(row.formulaLabel, `${domesticSymbol} / ${lmeSymbol}.LME`);
    assert.ok(row.mainHistoryChart);
    assert.match(row.mainHistoryChart.source, /xtdata 00主力连续.*AKShare\/新浪 LME三个月电子盘/);
    assert.equal(row.mainHistoryChart.overlaySeries.label, "美元兑人民币中间价（右轴）");
    assert.equal(row.mainHistoryChart.overlaySeries.symbol, "USDCNY_MID.SAFE");
    assert.match(row.mainHistoryChart.grain, /^更早周频 · 最近20个交易日日线收盘/);
    assert.ok(row.mainHistoryChart.overlaySeries.points.length >= 450);
    assertHybridHistory(row.mainHistoryChart.overlaySeries.points, `${pair} 汇率叠加线`);
    assert.equal(row.mainHistoryChart.overlaySeries.points.at(-1).date, payload.dataDate);
    assert.equal(row.mainHistoryChart.endDate, payload.dataDate);
    assert.ok(row.mainHistoryChart.series[0].points.length >= 300);
    assertHybridHistory(row.mainHistoryChart.series[0].points, row.pair);
  }

  assert.equal(payload.externalSources.length, 15);
  assert.ok(payload.externalSources.every((source) => source.endDate <= new Date().toISOString().slice(0, 10)));
  assert.ok(payload.externalSources.every((source) => ["live", "cache"].includes(source.status)));
  assert.match(payload.externalSourcePolicy, /国内主连÷LME三个月电子盘且不换汇.*风险溢价.*OBFR.*IORB.*IOER.*马盘棕榈油.*美盘油粕比/);
});

test("approved external risk premiums, dollar funding pressure, and cross-market ratios are auditable", async () => {
  const payload = JSON.parse(await readFile(new URL("../app/data/arbitrage.json", import.meta.url), "utf8"));
  const cnRisk = payload.rows.find((row) => row.pair === "ERP：沪深300");
  const usRisk = payload.rows.find((row) => row.pair === "ERP：标普500");
  const dollarFunding = payload.rows.find((row) => row.pair === "美元银行融资压力代理");
  const nasdaqSp = payload.rows.find((row) => row.pair === "纳斯达克/标普500");
  const palmSoy = payload.rows.find((row) => row.pair === "马盘棕榈油/美盘豆油");
  const usOilMeal = payload.rows.find((row) => row.pair === "美盘油粕比");

  for (const row of [cnRisk, usRisk, dollarFunding, nasdaqSp, palmSoy, usOilMeal]) {
    assert.ok(row);
    assert.equal(row.seriesMode, "external");
    assert.equal(row.sourceStatus, "外部补充");
    assert.equal(row.contracts.length, 0);
    assert.ok(row.mainHistoryChart);
    assert.equal(row.mainHistoryChart.endDate, payload.dataDate);
    assert.match(row.mainHistoryChart.grain, /^更早周频 · 最近20个交易日日线收盘/);
    assert.ok(row.mainHistoryChart.series[0].points.length >= 300);
    assertHybridHistory(row.mainHistoryChart.series[0].points, row.pair);
    assert.ok(row.mainHistoryChart.series[0].points.every((point) => point.date <= payload.dataDate));
  }

  assert.equal(cnRisk.current, `${((1 / cnRisk.priceEarningsRatio - cnRisk.bondYieldPct / 100) * 100).toFixed(2)}%`);
  assert.equal(usRisk.current, `${((1 / usRisk.priceEarningsRatio - usRisk.bondYieldPct / 100) * 100).toFixed(2)}%`);
  assert.equal(cnRisk.strategyType, "回归");
  assert.equal(usRisk.strategyType, "外盘监控");
  assert.equal(dollarFunding.current, `${dollarFunding.fundingSpreadBp.toFixed(2)}bp`);
  assert.ok(Math.abs(dollarFunding.fundingSpreadBp - (dollarFunding.obfrPct - dollarFunding.reserveRatePct) * 100) < 0.000001);
  assert.equal(dollarFunding.reserveRateCode, "IORB");
  assert.equal(dollarFunding.formulaLabel, "（OBFR − IORB/IOER）× 100 基点");
  assert.equal(dollarFunding.mainHistoryChart.unit, "基点");
  assert.equal(dollarFunding.mainHistoryChart.startDate, dollarFunding.mainHistoryChart.series[0].points[0].date);
  assert.ok(dollarFunding.mainHistoryChart.startDate >= "2016-08-25");
  assert.ok(dollarFunding.mainHistoryChart.startDate <= "2016-09-05");
  assert.ok(dollarFunding.mainHistoryChart.series[0].points.length >= 500);
  assert.equal(dollarFunding.mainHistoryChart.series[0].expiry, "美元融资压力（左轴）");
  assert.equal(dollarFunding.mainHistoryChart.overlaySeries.label, "标普500指数（右轴）");
  assert.equal(dollarFunding.mainHistoryChart.overlaySeries.symbol, "INX.SINA");
  assert.equal(dollarFunding.mainHistoryChart.overlaySeries.unit, "点位");
  assert.ok(dollarFunding.mainHistoryChart.overlaySeries.points.length >= 500);
  assertHybridHistory(dollarFunding.mainHistoryChart.overlaySeries.points, "美元融资压力图标普500叠加线");
  assert.ok(dollarFunding.mainHistoryChart.overlaySeries.points[0].date >= dollarFunding.mainHistoryChart.startDate);
  assert.ok(dollarFunding.mainHistoryChart.overlaySeries.points.at(-1).date <= dollarFunding.mainHistoryChart.endDate);
  assert.match(dollarFunding.mainHistoryChart.source, /标普500指数：新浪美股指数/);
  assert.match(dollarFunding.mainHistoryChart.grain, /标普500仅作右轴对照/);
  assert.equal(dollarFunding.pairType, "外盘参考");
  assert.equal(dollarFunding.strategyType, "外盘监控");
  assert.match(dollarFunding.interpretation, /美元银行融资压力代理.*不等同于完整离岸美元流动性指数/);
  assert.ok(Math.abs(Number(nasdaqSp.current) - nasdaqSp.leftIndexLevel / nasdaqSp.rightIndexLevel) < 0.0001);
  assert.equal(nasdaqSp.strategyType, "回归");
  assert.equal(nasdaqSp.marketCategory, "股指");
  assert.ok(
    payload.rows.indexOf(nasdaqSp)
      < payload.rows.findIndex((row) => row.strategyType === "回归" && row.marketCategory === "农产品"),
  );
  assert.equal(palmSoy.leftSymbol, "FCPO.SINA");
  assert.equal(palmSoy.rightSymbol, "BO.SINA");
  assert.equal(palmSoy.formulaLabel, "马盘棕榈油报价（马币/公吨）÷ 美盘豆油报价（美分/磅）");
  assert.equal(
    palmSoy.current,
    (palmSoy.palmOilMyrPerMetricTonne / palmSoy.soybeanOilCentsPerLb).toFixed(2),
  );
  assert.equal(palmSoy.soybeanOilUsdPerMetricTonne, undefined);
  assert.equal(palmSoy.soybeanOilMyrPerMetricTonne, undefined);
  assert.equal(palmSoy.fxMyrPerUsd, undefined);
  assert.equal(palmSoy.fxCrossMethod, undefined);
  assert.equal(palmSoy.palmOilCnyPerMetricTonne, undefined);
  assert.equal(palmSoy.soybeanOilCnyPerMetricTonne, undefined);
  assert.equal(cnRisk.mainHistoryChart.unit, "百分比");
  assert.equal(usRisk.mainHistoryChart.unit, "百分比");
  assert.deepEqual(cnRisk.mainHistoryChart.fixedThresholds, [
    { label: "3%", value: 0.03 },
    { label: "6%", value: 0.06 },
  ]);
  assert.equal(usRisk.mainHistoryChart.fixedThresholds, undefined);
  assert.equal(palmSoy.pairType, "跨市场套利");
  assert.equal(palmSoy.marketCategory, "农产品");
  assert.equal(usOilMeal.pairType, "外盘参考");
  assert.equal(usOilMeal.strategyType, "外盘监控");
  assert.equal(usOilMeal.marketCategory, "农产品");
  assert.equal(usOilMeal.leftSymbol, "BO.SINA");
  assert.equal(usOilMeal.rightSymbol, "SM.SINA");
  assert.equal(usOilMeal.formulaLabel, "美豆油（美分/磅）×20 ÷ 美豆粕（美元/短吨）");
  assert.ok(Math.abs(Number(usOilMeal.current) - usOilMeal.soybeanOilCentsPerLb * 20 / usOilMeal.soybeanMealUsdPerShortTon) < 0.0001);
  assert.ok(Math.abs(usOilMeal.soybeanOilUsdPerMetricTonne / usOilMeal.soybeanMealUsdPerMetricTonne - Number(usOilMeal.current)) < 0.0001);
  assert.equal(usOilMeal.mainHistoryChart.series[0].expiry, "外盘");

  const soybeanOil = payload.externalSources.find((source) => source.symbol === "BO.SINA");
  const soybeanMeal = payload.externalSources.find((source) => source.symbol === "SM.SINA");
  const obfr = payload.externalSources.find((source) => source.symbol === "OBFR.NYFED");
  const reserveRate = payload.externalSources.find((source) => source.symbol === "IORB_IOER.FED");
  assert.equal(soybeanOil.quoteUnit, "美分/磅");
  assert.equal(soybeanMeal.quoteUnit, "美元/短吨");
  assert.match(soybeanOil.path, /sina_foreign_futures[\\/]BO\.csv$/);
  assert.match(soybeanMeal.path, /sina_foreign_futures[\\/]SM\.csv$/);
  assert.equal(obfr.provider, "Federal Reserve Bank of New York");
  assert.equal(reserveRate.provider, "Board of Governors of the Federal Reserve System");
  assert.equal(obfr.quoteUnit, "%");
  assert.equal(reserveRate.quoteUnit, "%");
  assert.match(obfr.path, /newyorkfed[\\/]OBFR\.csv$/);
  assert.match(reserveRate.path, /federalreserve[\\/]IORB_IOER\.csv$/);
  assert.equal(reserveRate.startDate, "2008-10-09");
  assert.ok(reserveRate.rows > 6500);
  assert.ok(reserveRate.endDate <= new Date().toISOString().slice(0, 10));
  assert.equal(payload.externalSources.find((source) => source.symbol === "IORB.FED"), undefined);
  assert.equal(payload.externalSources.find((source) => source.symbol === "SOFR.NYFED"), undefined);

  const cnyMyr = payload.externalSources.find((source) => source.symbol === "CNYMYR_MID.SAFE");
  assert.equal(cnyMyr, undefined);
});

test("the six selected chart datasets are present in the requested order", async () => {
  const payload = JSON.parse(await readFile(new URL("../app/data/arbitrage.json", import.meta.url), "utf8"));
  assert.equal(payload.charts.length, 6);
  assert.deepEqual(
    payload.charts.map((chart) => chart.id),
    ["im-ic-spread", "ic-if", "im-if", "rebar-ore", "soy-oil-meal", "copper-aluminum"],
  );
  for (const chart of payload.charts) {
    assert.ok(chart.points.length >= 180, `${chart.pair} should retain hybrid observations for the available five-year window`);
    assert.ok(chart.points.length <= 320, `${chart.pair} should stay within the compact five-year window`);
    assert.equal(chart.startDate, chart.points[0].date);
    assert.equal(chart.endDate, chart.points.at(-1).date);
    assert.ok(chart.points.every((point, index) => Number.isFinite(point.value) && (index === 0 || point.date > chart.points[index - 1].date)));
    assert.equal(chart.grain, `${HYBRID_CHART_GRAIN} · MA基于日频`);
    assertHybridHistory(chart.points, chart.pair);
    for (const key of ["ma5", "ma60", "ma250"]) {
      assert.ok(chart.points.every((point) => point[key] === null || Number.isFinite(point[key])), `${chart.pair} ${key} values should be valid`);
      assert.ok(chart.points.some((point) => Number.isFinite(point[key])), `${chart.pair} should contain ${key}`);
    }
  }
  for (const chart of payload.charts.filter((item) => ["rebar-ore", "soy-oil-meal", "copper-aluminum"].includes(item.id))) {
    assert.match(chart.leftSymbol, /JQ00\./);
    assert.match(chart.rightSymbol, /JQ00\./);
  }
});
