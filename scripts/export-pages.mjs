import { access, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const serverEntry = path.join(projectRoot, "dist", "server", "index.js");
const clientDirectory = path.join(projectRoot, "dist", "client");
const outputPath = path.join(clientDirectory, "index.html");

await access(serverEntry);
const serverModule = await import(`${pathToFileURL(serverEntry).href}?pages-export=${Date.now()}`);
const worker = serverModule.default;
const fetchHandler = typeof worker === "function" ? worker : worker?.fetch?.bind(worker);

if (typeof fetchHandler !== "function") {
  throw new TypeError("vinext server build does not expose a request handler");
}

const response = await fetchHandler(
  new Request("https://arbitrage-dashboard.pages.dev/", {
    headers: { accept: "text/html" },
  }),
  { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
  { waitUntil() {}, passThroughOnException() {} },
);

if (!(response instanceof Response) || response.status !== 200) {
  throw new Error(`static export failed with status ${response?.status ?? "unknown"}`);
}

const html = await response.text();
if (!/<title>套利监测看板<\/title>/i.test(html)) {
  throw new Error("static export did not render the dashboard document");
}

await writeFile(outputPath, html, "utf8");
const written = await readFile(outputPath, "utf8");
if (written.length !== html.length) {
  throw new Error("static export verification failed after writing index.html");
}

console.log(`Cloudflare Pages static entry written: ${outputPath}`);
