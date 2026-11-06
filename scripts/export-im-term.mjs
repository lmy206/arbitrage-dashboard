import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { styleImTermHtml } from "./im-term-presentation.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const sha = bytes => createHash("sha256").update(bytes).digest("hex");

export async function exportImTerm() {
  const template = await readFile(path.join(root, "config/im-term/app-template.html"));
  const pinned = JSON.parse(await readFile(path.join(root, "config/im-term/template-manifest.json"), "utf8"));
  if (sha(template) !== pinned.html.sha256 || template.length !== pinned.html.bytes) throw new Error("IM compiled template integrity mismatch");
  const payload = JSON.parse(await readFile(path.join(root, "app/data/arbitrage.json"), "utf8"));
  const snapshot = payload.imTerm;
  if (snapshot?.id !== "dashboard:6ba08e54-a81e-4bf5-9baa-cf2d755e55f8" || !snapshot.queries?.latest?.rows?.length) throw new Error("Reviewed IM snapshot is missing");
  const bytes = Buffer.from(JSON.stringify(snapshot));
  const hash = sha(bytes);
  const snapshotPath = `snapshot.${hash}.json`;
  let html = template.toString("utf8");
  // Preserve the pinned renderer and authored UI. Bind this build's immutable
  // reviewed JSON through the runtime's documented separate-data meta fields.
  for (const [name, value] of Object.entries({ "data-app-local-snapshot": snapshotPath, "data-app-snapshot-sha256": hash })) {
    const pattern = new RegExp(`(<meta name="${name}" content=")[^"]+(">)`, "g");
    if ([...html.matchAll(pattern)].length !== 1) throw new Error(`IM bootstrap metadata missing: ${name}`);
    html = html.replace(pattern, (_match, before, after) => before + value + after);
  }
  html = html.replace(/<meta name="data-app-local-thread" content="[^"]*">\s*/g, "");
  html = await styleImTermHtml(html);
  const manifest = { version: 1, kind: "separate-data-v1",
    html: { path: "index.html", sha256: sha(Buffer.from(html)), bytes: Buffer.byteLength(html) },
    snapshot: { path: snapshotPath, sha256: hash, bytes: bytes.length },
    runtimeSha256: pinned.runtimeSha256, sourceSnapshotSha256: hash };
  const directory = path.join(root, "dist/client/im-term");
  await mkdir(directory, { recursive: true });
  await writeFile(path.join(directory, "index.html"), html);
  await writeFile(path.join(directory, snapshotPath), bytes);
  await writeFile(path.join(directory, "data-app-build.json"), JSON.stringify(manifest, null, 2));
  console.log(`IM期限套 exported: ${snapshot.queries.latest.rows[0].date}, ${snapshot.queries.latest.rows.length} contract pairs`);
}
