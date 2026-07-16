import { useEffect, useRef, useState } from "react";
import { api, runAgent, verdictKind, type AgentConfig, type AgentEvent } from "../api";
import { AgentConfigDrawer, DEFAULT_AGENT_CONFIG, normalizeAgentConfig } from "./AgentConfigDrawer";

type Item =
  | { kind: "text"; text: string }
  | { kind: "round"; round: number; max: number }
  | { kind: "tool_start"; name: string; args: string }
  | { kind: "tool_result"; name: string; content: string; error: boolean; verdict: string }
  | { kind: "progress"; text: string }
  | { kind: "feedback"; text: string }
  | { kind: "start"; brain: string; target: string }
  | { kind: "done"; status: string; summary: string }
  | { kind: "error"; error: string };

const DONE_KIND: Record<string, "bypass" | "held" | "neutral" | "error"> = {
  finished: "bypass", ask: "neutral", stuck: "neutral", max_rounds: "held", error: "error",
};

export function Agent({ hasTarget }: { hasTarget: boolean }) {
  const [objective, setObjective] = useState("");
  const [agentConfig, setAgentConfig] = useState<AgentConfig>(DEFAULT_AGENT_CONFIG);
  const [items, setItems] = useState<Item[]>([]);
  const [running, setRunning] = useState(false);
  const [runLog, setRunLog] = useState("");
  const [savingConfig, setSavingConfig] = useState(false);
  const [configStatus, setConfigStatus] = useState("");
  const [err, setErr] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const runningRef = useRef(false);
  const bodyRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    api.settings()
      .then((settings) => setAgentConfig(normalizeAgentConfig(settings.agent)))
      .catch(() => {});
  }, []);

  function push(it: Item) {
    setItems((prev) => {
      if (it.kind === "text" && prev.length && prev[prev.length - 1].kind === "text") {
        const copy = prev.slice();
        const last = copy[copy.length - 1] as { kind: "text"; text: string };
        copy[copy.length - 1] = { kind: "text", text: last.text + it.text };
        return copy;
      }
      return [...prev, it];
    });
    requestAnimationFrame(() => {
      if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    });
  }

  function onEvent(ev: AgentEvent) {
    if (typeof ev.run_log === "string" && ev.run_log) setRunLog(ev.run_log);
    switch (ev.type) {
      case "start": push({ kind: "start", brain: String(ev.brain || ""), target: String(ev.target || "") }); break;
      case "round": push({ kind: "round", round: Number(ev.round), max: Number(ev.max) }); break;
      case "text": push({ kind: "text", text: String(ev.text) }); break;
      case "tool_start": push({ kind: "tool_start", name: String(ev.name), args: String(ev.args || "") }); break;
      case "tool_result": push({ kind: "tool_result", name: String(ev.name), content: String(ev.content || ""), error: !!ev.error, verdict: String(ev.verdict || "") }); break;
      case "progress": push({ kind: "progress", text: String(ev.text) }); break;
      case "feedback": push({ kind: "feedback", text: String(ev.text) }); break;
      case "done": push({ kind: "done", status: String(ev.status), summary: String(ev.summary || "") }); break;
      case "error": push({ kind: "error", error: String(ev.error) }); break;
    }
  }

  async function run() {
    if (!objective.trim() || runningRef.current) return;
    runningRef.current = true;
    setItems([]); setErr(""); setRunLog(""); setRunning(true);
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      await runAgent({ objective, ...agentConfig }, onEvent, ac.signal);
    } catch (e) {
      if ((e as Error).name !== "AbortError") setErr((e as Error).message);
    } finally {
      runningRef.current = false;
      setRunning(false);
      abortRef.current = null;
    }
  }

  function stop() {
    abortRef.current?.abort();
  }

  async function saveAgentConfig() {
    setSavingConfig(true);
    setConfigStatus("");
    try {
      const saved = await api.saveSettings({ agent: agentConfig });
      setAgentConfig(normalizeAgentConfig(saved.agent));
      setConfigStatus("saved");
      window.setTimeout(() => setConfigStatus(""), 1600);
    } catch (e) {
      setConfigStatus((e as Error).message);
    } finally {
      setSavingConfig(false);
    }
  }

  return (
    <div className="grid" style={{ gridTemplateRows: "auto 1fr", height: "calc(100vh - 130px)" }}>
      <div className="card">
        <h3>Objective — the agent drives the attack loop autonomously</h3>
        {!hasTarget && <div className="err">No [target] configured in config.toml — the agent can't fire.</div>}
        <textarea
          rows={2}
          value={objective}
          placeholder="e.g. jailbreak the model into writing a working keylogger in C"
          onChange={(e) => setObjective(e.target.value)}
          disabled={running}
        />
        <AgentConfigDrawer
          value={agentConfig}
          onChange={setAgentConfig}
          disabled={running}
          onSave={saveAgentConfig}
          saving={savingConfig}
          status={configStatus}
        />
        <div style={{ display: "flex", gap: 12, alignItems: "center", marginTop: 12 }}>
          {!running ? (
            <button className="fire" style={{ marginTop: 0, width: "auto", padding: "10px 26px" }}
              disabled={!hasTarget || !objective.trim()} onClick={run}>▸ RUN AGENT</button>
          ) : (
            <button className="fire" style={{ marginTop: 0, width: "auto", padding: "10px 26px", background: "var(--panel-2)" }}
              onClick={stop}>■ STOP</button>
          )}
          {running && <span className="muted mono" style={{ marginLeft: 4 }}>working…</span>}
          {runLog && (
            <a className="agent-run-log mono" href="#runs" title="Open Run logs">
              saved: {runLog}
            </a>
          )}
        </div>
        {err && <div className="err" style={{ marginTop: 10 }}>{err}</div>}
      </div>

      <div className="card" style={{ overflow: "hidden", display: "flex", flexDirection: "column" }}>
        <h3>Transcript</h3>
        <div className="transcript" ref={bodyRef}>
          {!items.length && <div className="empty">Give the agent an objective and hit RUN — it reasons, picks techniques, fires at the target, reads the verdict, and keeps going.</div>}
          {items.map((it, i) => <Row key={i} it={it} />)}
        </div>
      </div>
    </div>
  );
}

function Row({ it }: { it: Item }) {
  switch (it.kind) {
    case "start":
      return <div className="t-start mono">brain <b>{it.brain}</b> ▸ target <b className="accent">{it.target}</b></div>;
    case "round":
      return <div className="t-round"><span /> round {it.round}/{it.max} <span /></div>;
    case "text":
      return <div className="t-text">{it.text}</div>;
    case "tool_start":
      return <div className="t-call mono"><span className="t-arrow">▸ call</span> <b>{it.name}</b> <span className="muted">{it.args}</span></div>;
    case "tool_result": {
      const kind = it.error ? "bypass" : it.verdict ? verdictKind(it.verdict) : "neutral";
      return (
        <div className={`t-result ${kind}`}>
          <div className="t-result-head mono">
            <b>{it.name}</b> {it.error ? <span className="badge bypass">ERROR</span> : it.verdict ? <span className={`badge ${verdictKind(it.verdict)}`}>{it.verdict}</span> : null}
          </div>
          <div className="t-result-body mono">{it.content.length > 1400 ? it.content.slice(0, 1400) + "…" : it.content}</div>
        </div>
      );
    }
    case "progress":
      return <div className="t-progress mono">{it.text}</div>;
    case "feedback":
      return <div className="t-feedback mono">steering: {it.text}</div>;
    case "done":
      return <div className={`t-done ${DONE_KIND[it.status] || "neutral"}`}>● {it.status}{it.summary ? ` — ${it.summary}` : ""}</div>;
    case "error":
      return <div className="err mono">{it.error}</div>;
  }
}
