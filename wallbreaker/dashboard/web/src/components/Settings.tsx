import { useEffect, useState } from "react";
import { api, type Settings as SettingsT } from "../api";

export function Settings({ onSaved }: { onSaved?: () => void }) {
  const [s, setS] = useState<SettingsT | null>(null);
  const [targetModel, setTargetModel] = useState("");
  const [targetProfile, setTargetProfile] = useState("");
  const [modality, setModality] = useState("auto");
  const [attackerProfile, setAttackerProfile] = useState("");
  const [attackerModel, setAttackerModel] = useState("");
  const [judgeModel, setJudgeModel] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  function load() {
    api.settings().then((v) => {
      setS(v);
      setTargetModel(v.target?.model ?? "");
      setModality(v.target?.modality ?? "auto");
      setAttackerProfile(v.default_profile ?? "");
      setAttackerModel(v.attacker_model ?? "");
      setJudgeModel(v.judge_model ?? "");
      setTargetProfile("");
    }).catch((e) => setErr((e as Error).message));
  }
  useEffect(load, []);

  async function save(body: Record<string, unknown>) {
    setBusy(true); setMsg(""); setErr("");
    try {
      const v = await api.saveSettings(body);
      setS(v);
      setMsg("saved");
      onSaved?.();
      setTimeout(() => setMsg(""), 1800);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!s) return <div className="empty">{err || "Loading…"}</div>;

  return (
    <div className="grid cols-2" style={{ maxWidth: 920 }}>
      <div className="card">
        <h3>Target — the model under attack</h3>
        <label className="fld">Set target by model id</label>
        <input type="text" value={targetModel} placeholder="e.g. deepseek/deepseek-v4-pro"
          onChange={(e) => setTargetModel(e.target.value)} />
        <label className="fld">Modality</label>
        <select value={modality} onChange={(e) => setModality(e.target.value)}>
          <option value="auto">auto-detect from model id</option>
          <option value="text">text</option>
          <option value="image">image</option>
        </select>
        <button className="fire" disabled={busy || !targetModel.trim()}
          onClick={() => save({ target_model: targetModel.trim(), target_modality: modality })}>
          Set target model
        </button>

        {s.profiles.length > 0 && (
          <>
            <label className="fld">…or use a configured profile as target</label>
            <div style={{ display: "flex", gap: 8 }}>
              <select value={targetProfile} onChange={(e) => setTargetProfile(e.target.value)} style={{ flex: 1 }}>
                <option value="">— pick a profile —</option>
                {s.profiles.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
              <button className="chip on" style={{ padding: "0 16px" }} disabled={busy || !targetProfile}
                onClick={() => save({ target_profile: targetProfile })}>use</button>
            </div>
          </>
        )}
        <div className="muted mono" style={{ marginTop: 14, fontSize: 12 }}>
          current: <b className="accent">{s.target?.model ?? "none"}</b>
          {s.target ? ` · ${s.target.modality}` : ""}
        </div>
      </div>

      <div className="card">
        <h3>Attacker brain &amp; judge</h3>
        <label className="fld">Attacker profile (the brain that drives attacks)</label>
        <select value={attackerProfile} onChange={(e) => { setAttackerProfile(e.target.value); save({ attacker_profile: e.target.value }); }}>
          {s.profiles.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <label className="fld">Attacker model override (optional)</label>
        <div style={{ display: "flex", gap: 8 }}>
          <input type="text" value={attackerModel} placeholder="e.g. glm-5.2" style={{ flex: 1 }}
            onChange={(e) => setAttackerModel(e.target.value)} />
          <button className="chip on" style={{ padding: "0 16px" }} disabled={busy || !attackerModel.trim()}
            onClick={() => save({ attacker_model: attackerModel.trim() })}>set</button>
        </div>
        <label className="fld">Judge model</label>
        <div style={{ display: "flex", gap: 8 }}>
          <input type="text" value={judgeModel} placeholder="e.g. openai/gpt-4o-mini" style={{ flex: 1 }}
            onChange={(e) => setJudgeModel(e.target.value)} />
          <button className="chip on" style={{ padding: "0 16px" }} disabled={busy || !judgeModel.trim()}
            onClick={() => save({ judge_model: judgeModel.trim() })}>set</button>
        </div>
        <div className="muted mono" style={{ marginTop: 14, fontSize: 12 }}>
          brain <b className="accent">{s.attacker_model ?? s.default_profile ?? "—"}</b> · judge <b>{s.judge_model ?? "—"}</b>
          {msg && <span style={{ color: "var(--good)", marginLeft: 12 }}>✓ {msg}</span>}
          {err && <span className="err" style={{ marginLeft: 12 }}>{err}</span>}
        </div>
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
