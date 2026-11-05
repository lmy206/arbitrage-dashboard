import assert from "node:assert/strict";

const DAY_MS = 24 * 60 * 60 * 1000;

export function assertMembers(actual, expected, label) {
  assert.equal(new Set(actual).size, actual.length, `${label}: duplicate entries`);
  assert.deepEqual([...actual].sort(), [...expected].sort(), `${label}: configured members`);
}

export function snapshotShanghaiDate(updatedAt) {
  assert.match(updatedAt, /^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/);
  const instant = new Date(updatedAt);
  assert.ok(Number.isFinite(instant.getTime()), "snapshot timestamp must be valid");
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(instant);
}

export function assertExternalDates(payload) {
  const snapshotDate = snapshotShanghaiDate(payload.updatedAt);
  assert.ok(payload.dataDate <= snapshotDate, "domestic data cannot be after snapshot day");
  for (const source of payload.externalSources) {
    assert.match(source.startDate, /^\d{4}-\d{2}-\d{2}$/);
    assert.match(source.endDate, /^\d{4}-\d{2}-\d{2}$/);
    assert.ok(source.startDate <= source.endDate && source.endDate <= snapshotDate, `${source.symbol}: source date range`);
    assert.ok(["live", "cache"].includes(source.status), `${source.symbol}: usable source`);
    assert.ok(Number.isInteger(source.rows) && source.rows > 0, `${source.symbol}: observations`);
    assert.ok(Number.isInteger(source.maxLagDays) && source.maxLagDays >= 0, `${source.symbol}: freshness policy`);
    const lag = (Date.parse(payload.dataDate) - Date.parse(source.endDate)) / DAY_MS;
    assert.ok(lag <= source.maxLagDays, `${source.symbol}: source is stale`);
  }
  for (const row of payload.rows.filter((item) => item.seriesMode === "external")) {
    const chart = row.mainHistoryChart;
    assert.ok(row.externalSourceDate <= chart.endDate && chart.endDate <= payload.dataDate, `${row.pair}: no future external observation`);
    const lag = (Date.parse(chart.endDate) - Date.parse(row.externalSourceDate)) / DAY_MS;
    assert.ok(lag >= 0 && lag <= row.externalSourceMaxLagDays, `${row.pair}: external observation freshness`);
  }
}

export function formatRatio(value) {
  return value.toFixed(Math.abs(value) >= 10 ? 2 : 4);
}

export function assertFormattedRatio(current) {
  const value = Number(current);
  assert.ok(Number.isFinite(value), "ratio must be finite");
  // A value just below ten can round to "10.0000" before the precision
  // switches. The original magnitude cannot be recovered from that string.
  if (Math.abs(value) === 10 && /^-?10\.0000$/.test(current)) return;
  assert.equal(current, formatRatio(value));
}

export function assertDisplayedRatio(current, expected) {
  assertFormattedRatio(current);
  assert.ok(Number.isFinite(expected));
  const decimals = current.split(".")[1].length;
  assert.ok(Math.abs(Number(current) - expected) <= 0.5 * 10 ** -decimals + 0.00000051, "displayed ratio must match its underlying value within rounding precision");
}

export function compactPointLimit(startDate, endDate, recentDailyDays = 20) {
  const days = (Date.parse(endDate) - Date.parse(startDate)) / DAY_MS;
  assert.ok(Number.isFinite(days) && days >= 0);
  // A partial week at each edge, plus the uncompressed recent observations.
  return Math.ceil(days / 7) + 2 + recentDailyDays;
}

export function calendarYearsBefore(date, years) {
  const value = new Date(`${date}T00:00:00Z`);
  assert.ok(Number.isFinite(value.getTime()) && Number.isInteger(years));
  const year = value.getUTCFullYear() - years;
  const month = value.getUTCMonth();
  const day = Math.min(value.getUTCDate(), new Date(Date.UTC(year, month + 1, 0)).getUTCDate());
  return new Date(Date.UTC(year, month, day)).toISOString().slice(0, 10);
}

export function assertDailyCalendarCoverage(source) {
  const days = (Date.parse(source.endDate) - Date.parse(source.startDate)) / DAY_MS + 1;
  assert.ok(Number.isInteger(days) && days > 0);
  assert.equal(source.rows, days, `${source.symbol}: complete daily calendar history`);
}
