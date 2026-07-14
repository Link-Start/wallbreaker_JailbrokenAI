import { useEffect, useState } from "react";
import { api, type ProviderRecord } from "../api";
import { invalidateModelCatalog, invalidateProviders, loadProviders } from "../dataCache";

const EMPTY = {
  name: "", protocol: "openai", base_url: "", model: "", api_key_env: "",
  api_key: "", auth_style: "bearer", inference_path: "", models_path: "",
  modality: "text", timeout: 120, reasoning: false, enabled: true,
};

export function ProviderManager({ onChanged }: { onChanged: () => void }) {
  const [providers, setProviders] = useState<ProviderRecord[]>([]);
  const [form, setForm] = useState<Record<string, unknown>>(EMPTY);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const load = (force = false) => loadProviders(force).then(setProviders).catch((error) => setStatus((error as Error).message));
  useEffect(() => { void load(); }, []);
  const edit = (provider?: ProviderRecord) => {
    setEditing(true); setStatus("");
    setForm(provider ? { ...provider, api_key: "" } : { ...EMPTY });
  };
  const update = (key: string, value: unknown) => setForm((current) => ({ ...current, [key]: value }));
  const save = async () => {
    const name = String(form.name || "").trim();
    if (!name) return;
    setBusy(true); setStatus("");
    try {
      await api.saveProvider(name, form); invalidateProviders(); invalidateModelCatalog(name);
      setEditing(false); setStatus("Provider saved"); void load(true); onChanged();
    }
    catch (error) { setStatus((error as Error).message); }
    finally { setBusy(false); }
  };
  const act = async (operation: () => Promise<unknown>, message: string) => {
    setBusy(true); setStatus("");
    try { await operation(); invalidateProviders(); invalidateModelCatalog(); setStatus(message); void load(true); onChanged(); }
    catch (error) { setStatus((error as Error).message); }
    finally { setBusy(false); }
  };
  return <details className="settings-drawer" open>
    <summary><span><b>Provider connections</b><small>Configure API-compatible services and credentials</small></span></summary>
    <div className="drawer-body provider-manager">
      <div className="provider-toolbar">
        <button type="button" className="primary-command" onClick={() => edit()}>Add provider</button>
        {status && <span className={status.toLowerCase().includes("saved") || status.toLowerCase().includes("available") ? "ok" : "muted"}>{status}</span>}
      </div>
      <div className="provider-list">
        {providers.map((provider) => <div className="provider-row" key={provider.name}>
          <div><b>{provider.name}</b><small>{provider.protocol} · {provider.base_url || "local CLI"}</small></div>
          <div className="provider-model mono">{provider.model}</div>
          <span className={`status-dot ${provider.enabled ? "live" : ""}`} title={provider.enabled ? "Enabled" : "Disabled"} />
          <div className="row-actions">
            <button type="button" title="Edit provider" onClick={() => edit(provider)}>Edit</button>
            {provider.enabled && <button type="button" title="Test model catalog" disabled={busy} onClick={() => void act(async () => {
              const result = await api.testProvider(provider.name); if (!result.ok) throw new Error(result.error || "Provider unavailable");
            }, "Provider available")}>Test</button>}
            {provider.can_reset && <button type="button" disabled={busy} onClick={() => void act(() => api.resetProvider(provider.name), "Provider reset")}>Reset</button>}
            <button type="button" disabled={busy} onClick={() => void act(() => api.deleteProvider(provider.name), provider.source === "config" ? "Provider disabled" : "Provider removed")}>{provider.source === "config" ? "Disable" : "Remove"}</button>
          </div>
        </div>)}
      </div>
      {editing && <div className="provider-editor">
        <div className="editor-heading"><b>{providers.some((p) => p.name === form.name) ? "Edit provider" : "New provider"}</b><button type="button" aria-label="Close provider editor" title="Close" onClick={() => setEditing(false)}>×</button></div>
        <div className="form-grid">
          <label>Name<input value={String(form.name || "")} onChange={(e) => update("name", e.target.value)} /></label>
          <label>Protocol<select value={String(form.protocol)} onChange={(e) => update("protocol", e.target.value)}><option value="openai">OpenAI compatible</option><option value="anthropic">Anthropic compatible</option><option value="claude-code">Claude Code</option></select></label>
          <label className="wide">Base URL<input value={String(form.base_url || "")} placeholder="https://api.example.com/v1" onChange={(e) => update("base_url", e.target.value)} /></label>
          <label>Default model<input value={String(form.model || "")} onChange={(e) => update("model", e.target.value)} /></label>
          <label>Key environment variable<input value={String(form.api_key_env || "")} placeholder="PROVIDER_API_KEY" onChange={(e) => update("api_key_env", e.target.value)} /></label>
          <label>API key<input type="password" value={String(form.api_key || "")} placeholder={form.has_api_key ? "Stored; enter to replace" : "Stored locally in .env"} onChange={(e) => update("api_key", e.target.value)} /></label>
          <label>Authentication<select value={String(form.auth_style || "bearer")} onChange={(e) => update("auth_style", e.target.value)}><option value="bearer">Bearer token</option><option value="x-api-key">x-api-key</option></select></label>
          <label>Inference path<input value={String(form.inference_path || "")} placeholder="Protocol default" onChange={(e) => update("inference_path", e.target.value)} /></label>
          <label>Models path<input value={String(form.models_path || "")} placeholder="Protocol default" onChange={(e) => update("models_path", e.target.value)} /></label>
        </div>
        <div className="editor-actions"><button type="button" onClick={() => setEditing(false)}>Cancel</button><button type="button" className="primary-command" disabled={busy} onClick={() => void save()}>Save provider</button></div>
      </div>}
    </div>
  </details>;
}
