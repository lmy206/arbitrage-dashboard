import http from "node:http";
import path from "node:path";
import { readFile, stat } from "node:fs/promises";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const publicRoot = path.join(root, "dist", "client");
const args = process.argv.slice(2);
const port = Number(args[args.indexOf("--port") + 1] ?? 3001);
let updating = false;
const types = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".woff": "font/woff", ".woff2": "font/woff2", ".webp": "image/webp" };

function run(command, commandArgs, environment = process.env) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, commandArgs, { cwd: root, env: environment, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
    let output = "";
    const collect = chunk => { output = (output + chunk).slice(-16000); };
    child.stdout.on("data", collect);
    child.stderr.on("data", collect);
    child.on("error", reject);
    child.on("close", code => code === 0 ? resolve() : reject(new Error(`Dashboard update failed (${code}). ${output}`)));
  });
}

function json(response, status, payload) {
  response.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
  response.end(JSON.stringify(payload));
}

const server = http.createServer(async (request, response) => {
  try {
    const url = new URL(request.url, "http://localhost");
    if (url.pathname === "/api/manual-update") {
      if (request.method !== "POST") return json(response, 405, { ok: false, error: "仅支持 POST" });
      const origin = request.headers.origin;
      if (origin && !["localhost", "127.0.0.1", "[::1]"].some(host => origin === `http://${host}:${server.address().port}`)) {
        return json(response, 403, { ok: false, error: "只允许本机看板发起更新" });
      }
      if (updating) return json(response, 409, { ok: false, error: "数据正在更新，请稍候" });
      updating = true;
      try {
        await run(process.env.XTQUANT_PYTHON || "D:\\anaconda\\python.exe", ["-X", "utf8", path.join(root, "scripts/update_xtdata.py")], { ...process.env, ARBITRAGE_XTDATA_ONLY: "1" });
        const report = JSON.parse(await readFile(path.join(process.env.E_SHARED_DATA_ROOT || "E:\\data", "reports/arbitrage_dashboard_integrity.json"), "utf8"));
        if (report.status !== "ok" || report.futureDataDetected || report.pairCount !== report.expectedPairCount) throw new Error("完整性校验未通过");
        await run(process.execPath, [path.join(root, "node_modules/vinext/dist/cli.js"), "build"]);
        await run(process.execPath, [path.join(root, "scripts/export-pages.mjs")]);
        return json(response, 200, { ok: true, dataDate: report.dataDate });
      } catch {
        return json(response, 500, { ok: false, error: "本机更新失败，请检查完整性报告和运行日志" });
      } finally { updating = false; }
    }
    if (!["GET", "HEAD"].includes(request.method)) return json(response, 405, { ok: false });
    const relative = decodeURIComponent(url.pathname).replace(/^\/+/, "") || "index.html";
    let file = path.resolve(publicRoot, relative);
    const within = path.relative(publicRoot, file);
    if (within.startsWith("..") || path.isAbsolute(within)) return json(response, 403, { ok: false });
    let info = await stat(file).catch(() => null);
    if (info?.isDirectory()) { file = path.join(file, "index.html"); info = await stat(file).catch(() => null); }
    if (!info?.isFile()) return json(response, 404, { ok: false });
    response.writeHead(200, { "Content-Type": types[path.extname(file)] || "application/octet-stream", "Cache-Control": "no-store", "Content-Length": info.size });
    response.end(request.method === "HEAD" ? undefined : await readFile(file));
  } catch { if (!response.headersSent) json(response, 500, { ok: false }); else response.end(); }
});

await stat(path.join(publicRoot, "index.html"));
server.listen(port, "127.0.0.1", () => console.log(`Dashboard ready: http://127.0.0.1:${server.address().port}/`));
