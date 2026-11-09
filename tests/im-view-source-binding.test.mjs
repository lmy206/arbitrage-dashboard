import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import test from "node:test";
import React from "react";
import * as jsxRuntime from "react/jsx-runtime";
import * as jsxDevRuntime from "react/jsx-dev-runtime";
import { renderToString } from "react-dom/server";

const identity = row => JSON.stringify(row, (_key, value) => value && typeof value === "object" && !Array.isArray(value)
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, value[key]])) : value);

test("compiled IM view renders with original reviewed rows in every scoped source", () => {
  const snapshot = JSON.parse(fs.readFileSync(new URL("../app/data/arbitrage.json", import.meta.url), "utf8")).imTerm;
  const templatePath = process.env.IM_TEMPLATE_UNDER_TEST || new URL("../config/im-term/app-template.html", import.meta.url);
  const html = fs.readFileSync(templatePath, "utf8");
  const scripts = [...html.matchAll(/<script src="data:text\/javascript;charset=utf-8;base64,([^"]+)"/g)]
    .map(match => Buffer.from(match[1], "base64").toString("utf8"));
  const bootstrap = scripts.at(-1);
  const wantedLiteral = /for \(const \[__dataAuthoredKey, __dataAuthoredWanted\] of JSON\.parse\(("(?:\\.|[^"\\])*")\)\)/.exec(bootstrap);
  assert.ok(wantedLiteral, "compiled module export contract must be present");
  const requirements = JSON.parse(JSON.parse(wantedLiteral[1]));
  const checked = [];
  function checkScopes(props) {
    const ids = [...new Set([props.queryId, ...(props.queryIds || [])])];
    for (const id of ids) assert.ok(snapshot.queries[id], `missing reviewed query ${id}`);
    for (const [id, rows] of Object.entries(props.sourceRowsByQuery || {})) {
      assert.ok(ids.includes(id));
      const reviewed = new Set(snapshot.queries[id].rows.map(identity));
      for (const row of rows) assert.ok(reviewed.has(identity(row)), `${props.id}: non-reviewed source row in ${id}`);
    }
    checked.push(props.id);
  }
  const publicApi = {
    useDataApp: () => ({ reviewedRows: id => snapshot.queries[id]?.rows || [] }),
    DataComponent: props => { checkScopes(props); return React.createElement("section", { "data-component": props.id }, props.children); },
    EvidenceChart: props => { checkScopes(props); return React.createElement("section", { "data-component": props.id }, props.title, props.children); },
    ChartTooltip: () => null,
    SectionHeader: props => React.createElement("h2", null, props.title),
  };
  // The compiler validates the whole public namespace, including unused report
  // exports. Leave unused exports null so unexpected authored use still fails.
  for (const [id, names] of requirements) if (id === "@openai/data-app") {
    for (const name of names) if (!Object.hasOwn(publicApi, name)) publicApi[name] = null;
  }
  const common = (exports, defaultExport = exports) => ({ ...exports, default: defaultExport, __esModule: true });
  let mounted;
  const runtime = { apiVersion: 1, staticDemoVersion: 1, publicApi: common(publicApi),
    modules: { react: common(React), "react/jsx-runtime": common(jsxRuntime), "react/jsx-dev-runtime": common(jsxDevRuntime),
      "@openai/data-app": common(publicApi) }, mount: options => { mounted = options; } };
  const context = vm.createContext({ console, JSON, CodexDataAppRuntime: runtime,
    location: { hostname: "test.invalid" },
    document: { getElementById: () => ({ textContent: JSON.stringify(snapshot) }), querySelector: () => null, querySelectorAll: () => [] } });
  vm.runInContext(bootstrap, context, { timeout: 5000 });
  assert.ok(mounted?.createContent, "compiled Data app bootstrap must mount authored content");
  const content = mounted.createContent(snapshot);
  const rendered = renderToString(React.createElement(content.DashboardContent));
  assert.match(rendered, /IM贴水结构/);
  assert.ok(checked.includes("im-spread-position"));
  assert.ok(checked.includes("im-term-down-history"));
  assert.ok(checked.includes("im-term-skip-history"));
});
