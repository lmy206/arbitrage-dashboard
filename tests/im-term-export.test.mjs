import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = async name => readFile(new URL(`../${name}`, import.meta.url));
const sha = bytes => createHash("sha256").update(bytes).digest("hex");

test("published IM app preserves its verified renderer and binds the reviewed daily snapshot", async () => {
  const manifest = JSON.parse(await read("dist/client/im-term/data-app-build.json"));
  const html = await read("dist/client/im-term/index.html");
  const snapshotBytes = await read(`dist/client/im-term/${manifest.snapshot.path}`);
  const snapshot = JSON.parse(snapshotBytes);
  const payload = JSON.parse(await read("app/data/arbitrage.json"));
  const contract = JSON.parse(await read("config/dashboard-contract.json"));
  assert.equal(sha(html), manifest.html.sha256);
  assert.equal(sha(snapshotBytes), manifest.snapshot.sha256);
  assert.equal(snapshotBytes.length, manifest.snapshot.bytes);
  assert.deepEqual(snapshot, payload.imTerm);
  assert.equal(snapshot.id, contract.imTerm.appId);
  assert.equal(snapshot.buildStatus, "complete");
  assert.equal(snapshot.imMetadata.sourceOnly, contract.imTerm.source);
  assert.equal(snapshot.imMetadata.extremeDisplayMethod, contract.imTerm.extremeDisplayMethod);
  assert.ok(!html.toString().includes('name="data-app-local-thread"'));
  assert.ok(html.toString().includes(`content="${manifest.snapshot.path}"`));
  assert.ok(html.toString().includes('<style id="im-arbitrage-theme">'));
  const skin = (await read("config/im-term/arbitrage-theme.css")).toString();
  assert.match(skin, /color-scheme:\s*light\s*!important/);
  assert.match(skin, /\.dashboard-topbar-actions\s*\{\s*display:\s*none\s*!important/);
  assert.match(skin, /--text:\s*#172033/);
  assert.match(skin, /--control:\s*#ffffff/);
  const stripBinding = value => value.toString()
    .replace(/<style id="im-arbitrage-theme">[\s\S]*?<\/style>\s*/g, "")
    .replace(/<meta name="data-app-local-thread" content="[^"]*">\s*/g, "")
    .replace(/<meta name="data-app-(?:local-snapshot|snapshot-sha256)" content="[^"]*">/g, "");
  assert.equal(stripBinding(html), stripBinding(await read("config/im-term/app-template.html")));
  assert.ok(snapshot.queries.latest.rows.length > 0);
  for (const q of snapshot.queries.latest.rows) {
    assert.equal(q.lowerAnnualRatePct, contract.imTerm.lowerAnnualRatePct);
    assert.equal(q.upperAnnualRatePct, contract.imTerm.upperAnnualRatePct);
    assert.equal(q.extremeScope, "current_pair_lifetime");
    assert.ok(q.extremeStartDate <= q.extremeEndDate && q.extremeEndDate <= q.date);
    assert.ok(q.extremeSamples > 0);
    assert.ok(q.extremeLowAnnualRatePct <= q.extremeHighAnnualRatePct);
    assert.ok(Math.abs(q.lower - q.indexClose * .09 * q.months / 12) < 1e-8);
    assert.ok(Math.abs(q.upper - q.indexClose * .12 * q.months / 12) < 1e-8);
    assert.ok(snapshot.queries.daily.rows.filter(r => r.pair === q.pair).every(r => r.date <= q.date));
  }
  for (const q of Object.values(snapshot.queries)) {
    assert.equal(q.source.provider, "xtdata");
    assert.ok(q.source.files.every(name => !/^[A-Za-z]:[\\/]/.test(name)));
  }
});
