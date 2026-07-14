import { useEffect, useRef, useState } from "react";
import { api, type RoleAssignments, type RoleChoice } from "../api";
import { ModelChooser } from "./ModelChooser";
import { ProviderChooser } from "./ProviderChooser";

export function RoleChooser({
  role, value, onSaved,
}: {
  role: keyof Pick<RoleAssignments, "attacker" | "target" | "judge">;
  value: RoleChoice;
  onSaved: () => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [provider, setProvider] = useState(value.provider);
  const [model, setModel] = useState(value.model);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { setProvider(value.provider); setModel(value.model); }, [value]);
  useEffect(() => {
    const close = (event: MouseEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const save = async () => {
    if (!provider || !model.trim()) return;
    setBusy(true); setError("");
    try { await api.saveRole(role, { provider, model: model.trim() }); setOpen(false); onSaved(); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  };
  return (
    <div className="role-chooser" ref={root}>
      <button type="button" className="role-chip" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span>{role}</span><b>{value.model || "not set"}</b><small>{value.provider}</small>
      </button>
      {open && <div className="role-menu">
        <label>Provider</label>
        <ProviderChooser value={provider} ariaLabel={`${role} provider`} onChange={(next, item) => { setProvider(next); if (item) setModel(item.model); }} />
        <label>Model</label>
        <ModelChooser profile={provider} value={model} onChange={setModel} ariaLabel={`${role} model`} />
        {error && <div className="err">{error}</div>}
        <button type="button" className="primary-command" disabled={busy || !model.trim()} onClick={() => void save()}>Apply</button>
      </div>}
    </div>
  );
}
