"use client";

import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

const tabs = [
  { id: "arbitrage", label: "套利看板" },
  { id: "im-term", label: "IM期限套" },
] as const;
type TabId = typeof tabs[number]["id"];
const imUrl = "http://127.0.0.1:8768/?view=1&tab=dashboard";

export default function DashboardTabs({ children }: { children: ReactNode }) {
  const [active, setActive] = useState<TabId>("arbitrage");
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [imVisited, setImVisited] = useState(false);
  const [frameError, setFrameError] = useState(false);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    const local = ["localhost", "127.0.0.1", "::1", "[::1]"].includes(window.location.hostname);
    setFrameUrl(local ? imUrl : "/im-term/?view=1&tab=dashboard");
    const restore = () => {
      const next = new URL(window.location.href).searchParams.get("tab") === "im-term" ? "im-term" : "arbitrage";
      setActive(next);
      if (next === "im-term") setImVisited(true);
    };
    restore();
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);

  function select(next: TabId) {
    setActive(next);
    if (next === "im-term") setImVisited(true);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    window.history.pushState(null, "", url);
  }

  function onKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const target = event.key === "ArrowRight" ? (index + 1) % tabs.length
      : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length
      : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
    if (target == null) return;
    event.preventDefault();
    select(tabs[target].id);
    buttons.current[target]?.focus();
  }

  return <>
    <nav className="dashboard-tabs" role="tablist" aria-label="看板切换">
      {tabs.map((tab, index) => <button key={tab.id} type="button" role="tab"
        id={`dashboard-tab-${tab.id}`} className={`dashboard-tab${active === tab.id ? " active" : ""}`}
        aria-selected={active === tab.id} aria-controls={`dashboard-panel-${tab.id}`}
        tabIndex={active === tab.id ? 0 : -1} ref={element => { buttons.current[index] = element; }}
        onClick={() => select(tab.id)} onKeyDown={event => onKey(event, index)}>{tab.label}</button>)}
    </nav>
    <div id="dashboard-panel-arbitrage" className="dashboard-panel" role="tabpanel"
      aria-labelledby="dashboard-tab-arbitrage" hidden={active !== "arbitrage"}>
      {children}
    </div>
    <section id="dashboard-panel-im-term" className="dashboard-panel im-term-panel" role="tabpanel"
      aria-labelledby="dashboard-tab-im-term" hidden={active !== "im-term"}>
      {frameUrl && <>
        <div className="im-term-actions"><a href={frameUrl} target="_blank" rel="noopener noreferrer">独立打开 IM期限套 ↗</a></div>
        {frameError && <p className="im-term-message" role="alert">IM页面暂时无法载入，请使用上方独立入口重试。</p>}
        {imVisited && <iframe className="im-term-frame" title="IM期限套" src={frameUrl}
          onLoad={() => setFrameError(false)} onError={() => setFrameError(true)} />}
      </>}
      {!frameUrl && <p className="im-term-message" role="status">正在载入IM期限套…</p>}
    </section>
  </>;
}
