import { useEffect, useState } from "react";
import { api, type AdvancedSettings, type AgentConfig, type RoleAssignments, type Settings as SettingsT, type TypicalConfiguration } from "../api";
import {
  AdvancedSettingsDrawer,
  DEFAULT_ADVANCED_SETTINGS,
  mergeAdvancedSettings,
  normalizeAdvancedSettings,
} from "./AdvancedSettingsDrawer";
import { AgentConfigDrawer, DEFAULT_AGENT_CONFIG, normalizeAgentConfig } from "./AgentConfigDrawer";
import { ModelChooser } from "./ModelChooser";
import { ProviderDiscovery } from "./ProviderDiscovery";
import { ProviderManager } from "./ProviderManager";
import { ProviderChooser } from "./ProviderChooser";

function matchingProfile(settings: SettingsT, endpoint?: { base_url: string; protocol: string } | null): string {
  if (endpoint) {
    const match = Object.entries(settings.profile_details || {}).find(([, profile]) => (
      profile.base_url === endpoint.base_url && profile.protocol === endpoint.protocol
    ));
    if (match) return match[0];
  }
  return settings.default_profile || settings.profiles[0] || "";
}

export function Settings({ onSaved }: { onSaved?: () => void }) {
  const [s, setS] = useState<SettingsT | null>(null);
  const [targetModel, setTargetModel] = useState("");
  const [targetProfile, setTargetProfile] = useState("");
  const [modality, setModality] = useState("auto");
  const [attackerProfile, setAttackerProfile] = useState("");
  const [attackerModel, setAttackerModel] = useState("");
  const [judgeModel, setJudgeModel] = useState("");
  const [judgeProfile, setJudgeProfile] = useState("");
  const [agentConfig, setAgentConfig] = useState<AgentConfig>(DEFAULT_AGENT_CONFIG);
  const [agentStatus, setAgentStatus] = useState("");
  const [advanced, setAdvanced] = useState<AdvancedSettings>(DEFAULT_ADVANCED_SETTINGS);
  const [advancedStatus, setAdvancedStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [roles, setRoles] = useState<RoleAssignments | null>(null);

  function load() {
    api.settings().then((v) => {
      setS(v);
      setTargetModel(v.target?.model ?? "");
      setModality(v.target?.modality ?? "auto");
      setAttackerProfile(v.default_profile ?? "");
      setAttackerModel(v.attacker_model ?? "");
      setJudgeModel(v.judge_model ?? "");
      setAgentConfig(normalizeAgentConfig(v.agent));
      setAdvanced(normalizeAdvancedSettings(v.advanced));
      setTargetProfile(v.target_profile || matchingProfile(v, v.target));
      setJudgeProfile(v.judge_profile || matchingProfile(v, v.advanced?.judge));
    }).catch((e) => setErr((e as Error).message));
    api.roles().then(setRoles).catch(() => setRoles(null));
  }
  useEffect(load, []);

  async function save(body: Record<string, unknown>) {
    setBusy(true); setMsg(""); setErr("");
    try {
      const v = await api.saveSettings(body);
      setS(v);
      setAgentConfig(normalizeAgentConfig(v.agent));
      setAdvanced(normalizeAdvancedSettings(v.advanced));
      setMsg("saved");
      onSaved?.();
      setTimeout(() => setMsg(""), 1800);
      return v;
    } catch (e) {
      setErr((e as Error).message);
      return null;
    } finally {
      setBusy(false);
    }
  }

  async function saveAgentConfig() {
    setAgentStatus("");
    const saved = await save({ agent: agentConfig });
    if (saved) {
      setAgentStatus("saved");
      setTimeout(() => setAgentStatus(""), 1600);
    }
  }

  async function saveAdvanced() {
    setAdvancedStatus("");
    const saved = await save({ advanced });
    if (saved) {
      setAdvancedStatus("saved");
      setTimeout(() => setAdvancedStatus(""), 1600);
    }
  }

  async function applyTypicalConfiguration(preset: TypicalConfiguration) {
    setAdvancedStatus("");
    const nextAdvanced = mergeAdvancedSettings(advanced, preset.advanced);
    const nextAgent = normalizeAgentConfig(preset.agent);
    setAdvanced(nextAdvanced);
    setAgentConfig(nextAgent);
    const saved = await save({
      typical_configuration: preset.id,
      advanced: nextAdvanced,
      agent: nextAgent,
    });
    if (saved) {
      setAdvancedStatus(`${preset.name} saved`);
      setTimeout(() => setAdvancedStatus(""), 1800);
    }
  }

  if (!s) return <div className="empty">{err || "Loading…"}</div>;

  return (
    <div className="grid cols-2 settings-grid">
      <div className="card settings-wide">
        <ProviderManager onChanged={() => { load(); onSaved?.(); }} />
      </div>
      {roles?.research && <div className="card settings-wide">
        <ProviderDiscovery research={roles.research} onChanged={() => { load(); onSaved?.(); }} />
      </div>}
      <div className="card">
        <h3>Target — the model under attack</h3>
        <label className="fld">Provider profile</label>
        <ProviderChooser value={targetProfile} ariaLabel="Target provider" onChange={(next, provider) => { setTargetProfile(next); if (provider) setTargetModel(provider.model); }} />
        <label className="fld">Target model</label>
        <ModelChooser
          profile={targetProfile}
          value={targetModel}
          onChange={setTargetModel}
          disabled={busy}
          placeholder="Choose or paste a target model id"
          ariaLabel="Target model"
        />
        <label className="fld">Modality</label>
        <select value={modality} onChange={(e) => setModality(e.target.value)}>
          <option value="auto">auto-detect from model id</option>
          <option value="text">text</option>
          <option value="image">image</option>
        </select>
        <button className="fire" disabled={busy || !targetModel.trim()}
          onClick={() => save({
            target_profile: targetProfile,
            target_model: targetModel.trim(),
            target_modality: modality,
          })}>
          Set target model
        </button>
        <div className="muted mono" style={{ marginTop: 14, fontSize: 12 }}>
          current: <b className="accent">{s.target?.model ?? "none"}</b>
          {s.target ? ` · ${s.target.modality}` : ""}
        </div>
      </div>

      <div className="card">
        <h3>Attacker brain &amp; judge</h3>
        <label className="fld">Attacker profile (the brain that drives attacks)</label>
        <ProviderChooser value={attackerProfile} ariaLabel="Attacker provider" onChange={(next, provider) => {
          setAttackerProfile(next); if (provider) setAttackerModel(provider.model); void save({ attacker_profile: next });
        }} />
        <label className="fld">Attacker model override (optional)</label>
        <div style={{ display: "flex", gap: 8 }}>
          <ModelChooser
            profile={attackerProfile}
            value={attackerModel}
            onChange={setAttackerModel}
            disabled={busy}
            placeholder="Choose or paste an attacker model id"
            ariaLabel="Attacker model"
          />
          <button className="chip on" style={{ padding: "0 16px" }} disabled={busy || !attackerModel.trim()}
            onClick={() => save({ attacker_model: attackerModel.trim() })}>set</button>
        </div>
        <label className="fld">Judge provider</label>
        <ProviderChooser value={judgeProfile} ariaLabel="Judge provider" onChange={(next, provider) => { setJudgeProfile(next); if (provider) setJudgeModel(provider.model); }} />
        <label className="fld">Judge model</label>
        <div style={{ display: "flex", gap: 8 }}>
          <ModelChooser
            profile={judgeProfile}
            value={judgeModel}
            onChange={setJudgeModel}
            disabled={busy}
            placeholder="Choose or paste a judge model id"
            ariaLabel="Judge model"
          />
          <button className="chip on" style={{ padding: "0 16px" }} disabled={busy || !judgeModel.trim()}
            onClick={() => save({ judge_profile: judgeProfile, judge_model: judgeModel.trim() })}>set</button>
        </div>
        <div className="muted mono" style={{ marginTop: 14, fontSize: 12 }}>
          brain <b className="accent">{s.attacker_model ?? s.default_profile ?? "—"}</b> · judge <b>{s.judge_model ?? "—"}</b>
          {msg && <span style={{ color: "var(--good)", marginLeft: 12 }}>✓ {msg}</span>}
          {err && <span className="err" style={{ marginLeft: 12 }}>{err}</span>}
        </div>
        <AgentConfigDrawer
          value={agentConfig}
          onChange={setAgentConfig}
          disabled={busy}
          onSave={saveAgentConfig}
          saving={busy}
          status={agentStatus}
        />
      </div>

      <div className="card" style={{ gridColumn: "1 / -1" }}>
        <AdvancedSettingsDrawer
          value={advanced}
          presets={s.typical_configurations || []}
          onChange={setAdvanced}
          onSave={saveAdvanced}
          onApplyPreset={applyTypicalConfiguration}
          saving={busy}
          status={advancedStatus}
          profileDetails={s.profile_details || {}}
          defaultProfile={s.default_profile || ""}
        />
      </div>

      <div className="card" style={{ gridColumn: "1 / -1" }}>
        <div className="muted" style={{ fontSize: 12 }}>
          Changes take effect immediately for the next fire / agent run and persist to
          <span className="mono"> .wallbreaker_state.json</span> (so the TUI sees them too). Switching the target to an
          image model auto-sets <span className="mono">modality=image</span>; pick a text model for text jailbreaks.
        </div>
      </div>
    </div>
  );
}
