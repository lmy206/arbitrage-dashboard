import { readFile } from "node:fs/promises";

export async function styleImTermHtml(html) {
  const css = await readFile(new URL("../config/im-term/arbitrage-theme.css", import.meta.url), "utf8");
  const clean = html.replace(/<style id="im-arbitrage-theme">[\s\S]*?<\/style>\s*/g, "");
  if (!clean.includes("</head>")) throw new Error("IM document head is missing");
  return clean.replace("</head>", `<style id="im-arbitrage-theme">${css}</style>\n</head>`);
}
