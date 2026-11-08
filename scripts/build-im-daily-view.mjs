import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseArgs } from "node:util";

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const { values } = parseArgs({ options: {
  "project-dir": { type: "string" },
  "sync-template": { type: "boolean", default: false },
} });
const projectDir = values["project-dir"] || path.join(
  process.env.IM_THRESHOLD_VAULT || "D:/思维知识库", "90_Agent指令/scripts/im_threshold_dashboard",
);
const pluginRoot = process.env.DATA_ANALYTICS_PLUGIN_ROOT
  || "C:/Users/71867/.codex/plugins/cache/openai-curated-remote/data-analytics/1.1.0-exp-baseline";
const { buildPrebuiltDataApp } = await import(pathToFileURL(path.join(pluginRoot, "scripts/data-app-build.mjs")));

// The supported read-only runtime disables refresh/schedule/editor controls.
// Authored contract selectors, scenarios, charts and source inspection remain interactive.
const result = await buildPrebuiltDataApp({ projectDir, pluginRoot, separateData: true, staticDemo: true });
const html = await readFile(result.htmlPath);
const htmlText = html.toString("utf8");
const code = [...htmlText.matchAll(/<script src="data:text\/javascript;charset=utf-8;base64,([^"]+)"/g)]
  .map((match) => Buffer.from(match[1], "base64").toString("utf8")).join("\n")
  .replace(/\\u([0-9a-f]{4})/gi, (_match, hex) => String.fromCharCode(parseInt(hex, 16)));
if (!html.includes(Buffer.from('<meta name="data-app-static-demo" content="readonly-v1">'))
    || !/staticDemo:\s*true/.test(code)
    || !code.includes("日度收盘")
    || code.includes("等待最新收盘数据")
    || code.includes("载入最新数据")) {
  throw new Error("IM daily-only view verification failed");
}
if (values["sync-template"]) {
  const manifest = await readFile(result.buildManifestPath);
  await writeFile(path.join(repositoryRoot, "config/im-term/app-template.html"), html);
  await writeFile(path.join(repositoryRoot, "config/im-term/template-manifest.json"), manifest);
}
console.log(JSON.stringify({ mode: "daily-readonly", htmlSha256: result.htmlSha256,
  snapshotSha256: result.snapshotSha256, runtimeSha256: result.runtimeSha256,
  templateSynced: values["sync-template"] }));
