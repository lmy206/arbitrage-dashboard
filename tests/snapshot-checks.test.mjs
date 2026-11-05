import assert from "node:assert/strict";
import test from "node:test";
import {
  assertDailyCalendarCoverage, assertDisplayedRatio, assertExternalDates, assertFormattedRatio,
  assertMembers, calendarYearsBefore, compactPointLimit, snapshotShanghaiDate,
} from "./snapshot-checks.mjs";

function externalSnapshot(date) {
  return {
    dataDate: date, updatedAt: `${date}T00:30:00+08:00`,
    externalSources: [{ symbol: "TEST", startDate: date, endDate: date, status: "cache", rows: 1, maxLagDays: 5 }],
    rows: [{ pair: "test", seriesMode: "external", externalSourceDate: date, externalSourceMaxLagDays: 5, mainHistoryChart: { endDate: date } }],
  };
}

test("external dates allow same-day sources across Shanghai midnight and year boundaries", () => {
  for (const date of ["2026-11-05", "2027-01-01", "2028-02-29"]) {
    const payload = externalSnapshot(date);
    assert.doesNotThrow(() => assertExternalDates(payload));
    assert.ok(new Date(payload.updatedAt).toISOString().slice(0, 10) < date);
    assert.equal(snapshotShanghaiDate(payload.updatedAt), date);
  }
});

test("external date checks still reject future observations and stale source or row", () => {
  let payload = externalSnapshot("2027-01-05");
  payload.externalSources[0].endDate = "2027-01-06";
  assert.throws(() => assertExternalDates(payload));
  payload = externalSnapshot("2027-01-05");
  payload.externalSources[0].startDate = payload.externalSources[0].endDate = "2026-12-01";
  assert.throws(() => assertExternalDates(payload), /stale/);
  payload = externalSnapshot("2027-01-05");
  payload.rows[0].externalSourceDate = "2027-01-06";
  assert.throws(() => assertExternalDates(payload), /future/);
  payload.rows[0].externalSourceDate = "2026-12-01";
  assert.throws(() => assertExternalDates(payload), /freshness/);
});

test("source and pair counts follow explicit identities and reject missing or duplicate members", () => {
  assertMembers(["new", "old"], ["old", "new"], "configured");
  assert.throws(() => assertMembers(["old"], ["old", "new"], "missing"));
  assert.throws(() => assertMembers(["old", "old"], ["old", "new"], "duplicate"));
});

test("ratio formatting follows magnitudes on either side of ten", () => {
  for (const current of ["2.9876", "10.25", "-12.50", "9.9999", "10.0000"]) assertFormattedRatio(current);
  assert.throws(() => assertFormattedRatio("10.2500"));
  assert.throws(() => assertFormattedRatio("2.98"));
  assertDisplayedRatio("10.0000", 9.999999);
  assertDisplayedRatio("10.25", 10.254);
  assertDisplayedRatio("2.9876", 2.98755);
  assert.throws(() => assertDisplayedRatio("10.25", 10.26));
});

test("calendar daily counts and compact chart bounds roll with their windows", () => {
  assertDailyCalendarCoverage({ symbol: "FED", startDate: "2028-02-28", endDate: "2028-03-01", rows: 3 });
  assert.throws(() => assertDailyCalendarCoverage({ symbol: "FED", startDate: "2028-02-28", endDate: "2028-03-01", rows: 2 }));
  assert.ok(compactPointLimit("2027-01-01", "2032-01-01") > compactPointLimit("2027-01-01", "2028-01-01"));
  assert.equal(calendarYearsBefore("2028-02-29", 10), "2018-02-28");
  assert.equal(calendarYearsBefore("2027-03-01", 10), "2017-03-01");
});
