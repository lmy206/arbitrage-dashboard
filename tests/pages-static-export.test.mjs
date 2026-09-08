import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const clientDirectory = fileURLToPath(new URL("../dist/client/", import.meta.url));

test("Cloudflare Pages output contains a complete static entry document", async () => {
  const html = await readFile(path.join(clientDirectory, "index.html"), "utf8");
  assert.match(html, /<title>套利监测看板<\/title>/i);
  assert.match(html, /<main class="dashboard-shell" data-snapshot-updated-at="\d{4}-\d{2}-\d{2}T/);
  assert.match(html, /36<!-- --> 组/);

  const assetPaths = new Set(
    [...html.matchAll(/(?:src|href)="(\/_next\/[^"?#]+)[^" ]*"/g)].map((match) => match[1]),
  );
  assert.ok(assetPaths.size >= 4, "expected CSS and JavaScript assets in the exported page");
  for (const assetPath of assetPaths) {
    await access(path.join(clientDirectory, assetPath.replace(/^\//, "")));
  }
});
