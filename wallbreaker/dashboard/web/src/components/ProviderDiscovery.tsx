import { useEffect, useState } from "react";
import { api, discoverProvider, type AgentConfig, type ProviderDraft, type RoleChoice } from "../api";
import { AgentConfigDrawer, normalizeAgentConfig } from "./AgentConfigDrawer";
import { ModelChooser } from "./ModelChooser";
import { ProviderChooser } from "./ProviderChooser";

export function ProviderDiscovery({ research, onChanged }: {
  research: RoleChoice; onChanged: () => void;
}) {
  const [providerName, setProviderName] = useState("");
  const [urls, setUrls] = useState("");
  const [spec, setSpec] = useState("");
  const [notes, setNotes] = useState("");
  const [researchProvider, setResearchProvider] = useState(research.provider);
  const [researchModel, setResearchModel] = useState(research.model);
  const [agentConfig, setAgentConfig] = useState<AgentConfig>(normalizeAgentConfig(research));
  const [events, setEvents] = useState<string[]>([]);
  const [drafts, setDrafts] = useState<ProviderDraft[]>([]);
  const [selected, setSelected] = useState<ProviderDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const loadDrafts = () => api.drafts().then((items) => { setDrafts(items); if (!selected && items[0]) setSelected(items[0]); });
  useEffect(() => { void loadDrafts(); }, []);
  useEffect(() => { setResearchProvider(research.provider); setResearchModel(research.model); setAgentConfig(normalizeAgentConfig(research)); }, [research]);
  const run = async () => {
    if (!providerName.trim()) return;
    setBusy(true); setError(""); setEvents([]);
    try {
      await discoverProvider({
        provider_name: providerName.trim(), docs_urls: urls.split(/\r?\n|,/).map((v) => v.trim()).filter(Boolean),
        spec_text: spec, notes, research_provider: researchProvider, research_model: researchModel,
        max_rounds: agentConfig.max_rounds, max_tokens: agentConfig.max_tokens,
      }, (event) => {
        const kind = String(event.type || "event");
        const detail = String(event.query || event.url || event.name || event.error || event.text || "");
        setEvents((current) => [...current.slice(-20), `${kind}${detail ? ` · ${detail}` : ""}`]);
        if (kind === "done" && event.draft) { setSelected(event.draft as ProviderDraft); loadDrafts(); }
        if (kind === "error") setError(detail);
      });
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  };
  const update = (key: keyof ProviderDraft, value: unknown) => selected && setSelected({ ...selected, [key]: value });
  const saveResearch = async () => { await api.saveRole("research", { provider: researchProvider, model: researchModel, ...agentConfig }); onChanged(); };
  const saveDraft = async () => { if (selected) { const saved = await api.saveDraft(selected.id, selected); setSelected(saved); loadDrafts(); } };
  const apply = async () => { if (selected) { await saveDraft(); await api.applyDraft(selected.id); onChanged(); loadDrafts(); } };
  const discard = async () => { if (selected) { await api.discardDraft(selected.id); setSelected(null); loadDrafts(); } };
  return <details className="settings-drawer discovery-drawer">
    <summary><span><b>Discover provider API</b><small>Research official documentation and prepare a reviewable connection draft</small></span></summary>
    <div className="drawer-body discovery-layout">
      <section className="discovery-inputs">
        <label>Provider name<input value={providerName} onChange={(e) => setProviderName(e.target.value)} placeholder="Provider or service name" /></label>
        <label>Documentation URLs<textarea value={urls} onChange={(e) => setUrls(e.target.value)} placeholder="One URL per line; optional" rows={3} /></label>
        <label>API specification<textarea value={spec} onChange={(e) => setSpec(e.target.value)} placeholder="Paste OpenAPI JSON, YAML, or provider documentation; optional" rows={6} /></label>
        <label>Research notes<textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Known endpoints, compatibility claims, or constraints" rows={3} /></label>
        {!urls.trim() && !spec.trim() && <div className="notice">No source supplied. The research agent will search the web for official documentation.</div>}
        <div className="research-agent-row">
          <label>Research provider<ProviderChooser value={researchProvider} ariaLabel="Research provider" onChange={(next, item) => { setResearchProvider(next); if (item) setResearchModel(item.model); }} /></label>
          <label>Research model<ModelChooser profile={researchProvider} value={researchModel} onChange={setResearchModel} /></label>
        </div>
        <AgentConfigDrawer value={agentConfig} onChange={setAgentConfig} onSave={() => void saveResearch()} saving={busy} status="" />
        <button type="button" className="primary-command" disabled={busy || !providerName.trim()} onClick={() => void run()}>{busy ? "Researching…" : "Research provider"}</button>
        {events.length > 0 && <div className="research-events mono">{events.map((event, index) => <div key={`${event}-${index}`}>{event}</div>)}</div>}
        {error && <div className="err">{error}</div>}
      </section>
      <section className="draft-review">
        <div className="draft-picker"><b>Specification drafts</b><select value={selected?.id || ""} onChange={(e) => setSelected(drafts.find((draft) => draft.id === e.target.value) || null)}><option value="">Select a draft</option>{drafts.map((draft) => <option key={draft.id} value={draft.id}>{draft.provider_name} · {draft.created_at}</option>)}</select></div>
        {!selected ? <div className="empty compact-empty">Completed research drafts appear here for review.</div> : <>
          <div className={`draft-confidence ${selected.supported ? "supported" : "unsupported"}`}>{selected.supported ? `${selected.confidence} confidence · compatible` : "Custom adapter required"}</div>
          <div className="form-grid">
            <label>Name<input value={selected.provider_name} onChange={(e) => update("provider_name", e.target.value)} /></label>
            <label>Protocol<select value={selected.protocol} onChange={(e) => update("protocol", e.target.value)}><option value="openai">OpenAI compatible</option><option value="anthropic">Anthropic compatible</option><option value="claude-code">Claude Code</option><option value="unsupported">Unsupported</option></select></label>
            <label className="wide">Base URL<input value={selected.base_url} onChange={(e) => update("base_url", e.target.value)} /></label>
            <label>Default model<input value={selected.model} onChange={(e) => update("model", e.target.value)} /></label>
            <label>Key environment variable<input value={selected.api_key_env} onChange={(e) => update("api_key_env", e.target.value)} /></label>
            <label>Inference path<input value={selected.inference_path} onChange={(e) => update("inference_path", e.target.value)} /></label>
            <label>Models path<input value={selected.models_path} onChange={(e) => update("models_path", e.target.value)} /></label>
            <label className="wide">Response shape<input value={selected.response_shape} onChange={(e) => update("response_shape", e.target.value)} /></label>
          </div>
          {selected.warnings.length > 0 && <div className="draft-warnings">{selected.warnings.map((warning) => <div key={warning}>{warning}</div>)}</div>}
          <div className="draft-sources"><b>Sources</b>{selected.sources.map((source) => <a href={source} target="_blank" rel="noreferrer" key={source}>{source}</a>)}</div>
          <div className="editor-actions"><button type="button" onClick={() => void discard()}>Discard</button><button type="button" onClick={() => void saveDraft()}>Save edits</button><button type="button" className="primary-command" disabled={!selected.supported} onClick={() => void apply()}>Apply provider</button></div>
        </>}
      </section>
    </div>
  </details>;
}
