import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { assertMembers } from "./snapshot-checks.mjs";

const clientDirectory = fileURLToPath(new URL("../dist/client/", import.meta.url));

test("Cloudflare Pages output contains a complete static entry document", async () => {
  const html = await readFile(path.join(clientDirectory, "index.html"), "utf8");
  assert.match(html, /<title>套利监测看板<\/title>/i);
  assert.match(html, /<main class="dashboard-shell" data-snapshot-updated-at="\d{4}-\d{2}-\d{2}T/);
  const payload = JSON.parse(await readFile(new URL("../app/data/arbitrage.json", import.meta.url), "utf8"));
  const contract = JSON.parse(await readFile(new URL("../config/dashboard-contract.json", import.meta.url), "utf8"));
  assertMembers(payload.rows.map((row) => row.pair), contract.pairs, "static snapshot pairs");
  assert.equal([...html.matchAll(/<tr class="pair-row\b/g)].length, contract.pairs.length);
  assert.ok(html.includes(`data-snapshot-updated-at="${payload.updatedAt}"`));
  assert.match(html, /金\/油比价/);
  assert.doesNotMatch(html, /猪肉\/玉米比价/);
  assert.match(html, /燃料油\/原油比价/);

  const assetPaths = new Set(
    [...html.matchAll(/(?:src|href)="(\/_next\/[^"?#]+)[^" ]*"/g)].map((match) => match[1]),
  );
  assert.ok(assetPaths.size >= 4, "expected CSS and JavaScript assets in the exported page");
  for (const assetPath of assetPaths) {
    await access(path.join(clientDirectory, assetPath.replace(/^\//, "")));
  }
});
