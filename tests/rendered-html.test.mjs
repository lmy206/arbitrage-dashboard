import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the arbitrage dashboard", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>套利监测看板<\/title>/i);
  assert.match(html, /每日 20:00 更新/);
  assert.match(html, /IM-IC价差/);
  assert.match(html, /展开IM-IC价差合约月份/);
  assert.match(html, /豆粕价差/);
  assert.match(html, /近3年分位/);
  assert.doesNotMatch(html, /codex-preview|Building your site|react-loading-skeleton/i);
});

test("monthly contract details contain only current values and liquidity", async () => {
  const payload = JSON.parse(await readFile(new URL("../app/data/arbitrage.json", import.meta.url), "utf8"));
  assert.equal(payload.rows.length, 15);

  for (const row of payload.rows) {
    assert.equal(row.contracts.length, 4, `${row.pair} should expose four contract months`);
    for (let index = 1; index < row.contracts.length; index += 1) {
      assert.ok(
        row.contracts[index - 1].pairedVolume >= row.contracts[index].pairedVolume,
        `${row.pair} contract months should be sorted by paired volume`,
      );
    }
    for (const contract of row.contracts) {
      assert.deepEqual(
        Object.keys(contract).sort(),
        ["current", "expiry", "leftSymbol", "leftVolume", "pairedVolume", "rightSymbol", "rightVolume"].sort(),
      );
      assert.equal(contract.pairedVolume, Math.min(contract.leftVolume, contract.rightVolume));
    }
  }

  const imIc = payload.rows.find((row) => row.pair === "IM-IC价差");
  assert.equal(new Set(imIc.contracts.map((contract) => contract.expiry)).size, 4);
  assert.ok(imIc.contracts.every((contract) => /^\d{4}$/.test(contract.expiry)));
});
