import { useEffect, useState } from "react";
import { api, type ConfigInfo, type Overview as OverviewT } from "./api";
import { Agent } from "./components/Agent";
import { Overview } from "./components/Overview";
import { Console } from "./components/Console";
import { Findings } from "./components/Findings";
import { Runs } from "./components/Runs";
import { Arsenal } from "./components/Arsenal";
import { Settings } from "./components/Settings";

type Tab = "agent" | "overview" | "console" | "findings" | "runs" | "arsenal" | "settings";

const NAV: { id: Tab; label: string }[] = [
  { id: "agent", label: "Agent" },
  { id: "overview", label: "Overview" },
  { id: "console", label: "Attack console" },
  { id: "findings", label: "Findings" },
  { id: "runs", label: "Run logs" },
  { id: "arsenal", label: "Arsenal" },
  { id: "settings", label: "Settings" },
];

function tabFromHash(): Tab {
  const h = window.location.hash.replace("#", "");
  return (NAV.some((n) => n.id === h) ? h : "agent") as Tab;
}

export function App() {
  const [tab, setTabState] = useState<Tab>(tabFromHash());
  const setTab = (t: Tab) => { setTabState(t); window.location.hash = t; };
  const [cfg, setCfg] = useState<ConfigInfo | null>(null);
  const [ov, setOv] = useState<OverviewT | null>(null);

  const refresh = () => {
    api.config().then(setCfg).catch(() => setCfg(null));
    api.overview().then(setOv).catch(() => setOv(null));
  };
  useEffect(refresh, [tab]);

  const asr = ov?.scorecard?.asr;
  const asrStr = typeof asr === "number" ? `${Math.round(asr * 100)}%` : "—";

  return (
    <div className="app">
      <aside className="rail">
        <div className="brand">
          <span className="mark">◆</span>
          <span className="word">WALL<b>BREAKER</b></span>
        </div>
        {NAV.map((n) => (
          <div
            key={n.id}
            className={`nav-item ${tab === n.id ? "active" : ""}`}
            onClick={() => setTab(n.id)}
          >
            <span className="dot" />
            {n.label}
          </div>
        ))}
        <div className="spacer" />
        <div className="foot">
          break the wall ·<br />
          not the rules of engagement
        </div>
      </aside>

      <div className="main">
        <div className="topbar">
          <div className="title">{NAV.find((n) => n.id === tab)?.label}</div>
          <div className="meta">
            <span>profile <b>{cfg?.profile ?? "—"}</b></span>
            <span>target <b className="accent">{cfg?.target ?? "none"}</b></span>
            <span className="pill">ASR {asrStr}</span>
          </div>
        </div>
        <div className="content">
          {tab === "agent" && <Agent hasTarget={!!cfg?.has_target} />}
          {tab === "overview" && <Overview ov={ov} />}
          {tab === "console" && <Console hasTarget={!!cfg?.has_target} />}
          {tab === "findings" && <Findings />}
          {tab === "runs" && <Runs />}
          {tab === "arsenal" && <Arsenal />}
          {tab === "settings" && <Settings onSaved={refresh} />}
        </div>
      </div>
    </div>
  );
}
