import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import vinext from "vinext";
import { defineConfig, type Plugin } from "vite";

// macOS Seatbelt blocks FSEvents, so Codex previews need polling for HMR.
const isCodexSeatbeltSandbox = process.env.CODEX_SANDBOX === "seatbelt";

type IntegrityReport = {
  status: string;
  dataDate: string;
  pairCount: number;
  expectedPairCount: number;
  futureDataDetected: boolean;
};

let runningXtdataUpdate: Promise<IntegrityReport> | null = null;

function sendJson(response: import("node:http").ServerResponse, statusCode: number, payload: unknown) {
  response.statusCode = statusCode;
  response.setHeader("Content-Type", "application/json; charset=utf-8");
  response.setHeader("Cache-Control", "no-store");
  response.end(JSON.stringify(payload));
}

function runXtdataUpdate(): Promise<IntegrityReport> {
  const projectRoot = process.cwd();
  const python = process.env.XTQUANT_PYTHON || "D:\\anaconda\\python.exe";
  const script = path.join(projectRoot, "scripts", "update_xtdata.py");
  const sharedRoot = process.env.E_SHARED_DATA_ROOT || "E:\\data";
  const reportPath = path.join(sharedRoot, "reports", "arbitrage_dashboard_integrity.json");

  return new Promise((resolve, reject) => {
    const child = spawn(python, [script], {
      cwd: projectRoot,
      env: { ...process.env, ARBITRAGE_XTDATA_ONLY: "1" },
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let output = "";
    child.stdout.on("data", (chunk) => { output = `${output}${chunk}`.slice(-12000); });
    child.stderr.on("data", (chunk) => { output = `${output}${chunk}`.slice(-12000); });
    child.on("error", reject);
    child.on("close", async (code) => {
      if (code !== 0) {
        reject(new Error(output.trim() || `xtdata 更新退出码 ${code}`));
        return;
      }
      try {
        const report = JSON.parse(await readFile(reportPath, "utf8")) as IntegrityReport;
        if (
          report.status !== "ok" ||
          report.futureDataDetected ||
          report.pairCount !== report.expectedPairCount
        ) {
          throw new Error(`完整性校验未通过：${report.status}`);
        }
        resolve(report);
      } catch (error) {
        reject(error);
      }
    });
  });
}

function localXtdataUpdate(): Plugin {
  return {
    name: "local-xtdata-update",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use("/api/manual-update", async (request, response) => {
        if (request.method !== "POST") {
          sendJson(response, 405, { ok: false, error: "仅支持 POST" });
          return;
        }
        if (runningXtdataUpdate) {
          sendJson(response, 409, { ok: false, error: "数据正在更新，请稍候" });
          return;
        }

        runningXtdataUpdate = runXtdataUpdate();
        try {
          const report = await runningXtdataUpdate;
          sendJson(response, 200, { ok: true, dataDate: report.dataDate });
        } catch (error) {
          const message = error instanceof Error ? error.message : "xtdata 更新失败";
          sendJson(response, 500, { ok: false, error: message.slice(0, 300) });
        } finally {
          runningXtdataUpdate = null;
        }
      });
    },
  };
}

export default defineConfig({
  server: isCodexSeatbeltSandbox
    ? { watch: { useFsEvents: false, usePolling: true } }
    : undefined,
  plugins: [localXtdataUpdate(), vinext()],
});
