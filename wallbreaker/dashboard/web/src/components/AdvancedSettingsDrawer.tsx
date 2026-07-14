import type {
  AdvancedSettings,
  EndpointAdvancedSettings,
  ProfileDetail,
  ProviderRecord,
  RuntimeAdvancedSettings,
  TypicalConfiguration,
} from "../api";
import { ModelChooser } from "./ModelChooser";
import { ProviderChooser } from "./ProviderChooser";

const DEFAULT_ENDPOINT: EndpointAdvancedSettings = {
  protocol: "openai",
  base_url: "",
  model: "",
  api_key_env: "",
  provider: "",
  timeout: 0,
  modality: "text",
  reasoning: false,
  system_mode: "default",
  system_prompt_file: "",
  auth_style: "x-api-key",
};

const DEFAULT_RUNTIME: RuntimeAdvancedSettings = {
  auto: false,
  rounds: 12,
  no_tools: false,
  exit_on_finish: true,
  log: true,
  judge: false,
  resume: "",
};

export const DEFAULT_ADVANCED_SETTINGS: AdvancedSettings = {
  runtime: DEFAULT_RUNTIME,
  attacker: DEFAULT_ENDPOINT,
  target: DEFAULT_ENDPOINT,
  judge: DEFAULT_ENDPOINT,
  art: DEFAULT_ENDPOINT,
};

function clampNumber(value: number, fallback: number, lo: number, hi: number): number {
  if (!Number.isFinite(value)) return fallback;
  return Math.max(lo, Math.min(hi, Math.trunc(value)));
}

function normalizeRuntime(value?: Partial<RuntimeAdvancedSettings> | null): RuntimeAdvancedSettings {
  return {
    auto: !!value?.auto,
    rounds: clampNumber(Number(value?.rounds), DEFAULT_RUNTIME.rounds, 1, 50),
    no_tools: !!value?.no_tools,
    exit_on_finish: value?.exit_on_finish ?? DEFAULT_RUNTIME.exit_on_finish,
    log: value?.log ?? DEFAULT_RUNTIME.log,
    judge: !!value?.judge,
    resume: String(value?.resume || ""),
  };
}

function normalizeEndpoint(value?: Partial<EndpointAdvancedSettings> | null): EndpointAdvancedSettings {
  return {
    protocol: String(value?.protocol || DEFAULT_ENDPOINT.protocol),
    base_url: String(value?.base_url || ""),
    model: String(value?.model || ""),
    api_key_env: String(value?.api_key_env || ""),
    provider: String(value?.provider || ""),
    timeout: clampNumber(Number(value?.timeout), DEFAULT_ENDPOINT.timeout, 0, 600),
    modality: String(value?.modality || DEFAULT_ENDPOINT.modality),
    reasoning: !!value?.reasoning,
    system_mode: String(value?.system_mode || DEFAULT_ENDPOINT.system_mode),
    system_prompt_file: String(value?.system_prompt_file || ""),
    auth_style: String(value?.auth_style || DEFAULT_ENDPOINT.auth_style),
  };
}

export function normalizeAdvancedSettings(value?: Partial<AdvancedSettings> | null): AdvancedSettings {
  return {
    runtime: normalizeRuntime(value?.runtime),
    attacker: normalizeEndpoint(value?.attacker),
    target: normalizeEndpoint(value?.target),
    judge: normalizeEndpoint(value?.judge),
    art: normalizeEndpoint(value?.art),
  };
}

export function mergeAdvancedSettings(
  base: AdvancedSettings,
  patch?: Partial<AdvancedSettings> | null,
): AdvancedSettings {
  if (!patch) return normalizeAdvancedSettings(base);
  return normalizeAdvancedSettings({
    runtime: { ...base.runtime, ...patch.runtime },
    attacker: { ...base.attacker, ...patch.attacker },
    target: { ...base.target, ...patch.target },
    judge: { ...base.judge, ...patch.judge },
    art: { ...base.art, ...patch.art },
  });
}

type EndpointKey = "attacker" | "target" | "judge" | "art";

const ENDPOINTS: { id: EndpointKey; label: string }[] = [
  { id: "attacker", label: "Attacker" },
  { id: "target", label: "Target" },
  { id: "judge", label: "Judge" },
  { id: "art", label: "Art" },
];

export function AdvancedSettingsDrawer({
  value,
  presets,
  onChange,
  onSave,
  onApplyPreset,
  saving = false,
  status = "",
  profileDetails,
  defaultProfile,
}: {
  value: AdvancedSettings;
  presets: TypicalConfiguration[];
  onChange: (value: AdvancedSettings) => void;
  onSave: () => void;
  onApplyPreset: (preset: TypicalConfiguration) => void;
  saving?: boolean;
  status?: string;
  profileDetails: Record<string, ProfileDetail>;
  defaultProfile: string;
}) {
  const setRuntime = <K extends keyof RuntimeAdvancedSettings>(key: K, nextValue: RuntimeAdvancedSettings[K]) => {
    onChange(normalizeAdvancedSettings({
      ...value,
      runtime: { ...value.runtime, [key]: nextValue },
    }));
  };

  const setEndpoint = <K extends keyof EndpointAdvancedSettings>(
    endpoint: EndpointKey,
    key: K,
    nextValue: EndpointAdvancedSettings[K],
  ) => {
    onChange(normalizeAdvancedSettings({
      ...value,
      [endpoint]: { ...value[endpoint], [key]: nextValue },
    }));
  };

  return (
    <details className="config-drawer advanced-drawer">
      <summary>
        <span>Advanced settings</span>
        <span className="mono muted">runtime | endpoints | presets</span>
      </summary>
      <div className="config-drawer-body advanced-drawer-body">
        <div className="advanced-presets">
          {presets.map((preset) => (
            <button
              type="button"
              key={preset.id}
              className="preset-btn"
              onClick={() => onApplyPreset(preset)}
              disabled={saving}
            >
              <b>{preset.name}</b>
              <span>{preset.description}</span>
            </button>
          ))}
        </div>

        <div className="advanced-section">
          <h3>Runtime</h3>
          <div className="advanced-grid">
            <NumberField label="Rounds" value={value.runtime.rounds} min={1} max={50} onChange={(next) => setRuntime("rounds", next)} />
            <TextField label="Resume path" value={value.runtime.resume} onChange={(next) => setRuntime("resume", next)} />
            <ToggleField label="Auto" checked={value.runtime.auto} onChange={(next) => setRuntime("auto", next)} />
            <ToggleField label="No tools" checked={value.runtime.no_tools} onChange={(next) => setRuntime("no_tools", next)} />
            <ToggleField label="Log" checked={value.runtime.log} onChange={(next) => setRuntime("log", next)} />
            <ToggleField label="Judge" checked={value.runtime.judge} onChange={(next) => setRuntime("judge", next)} />
            <ToggleField label="Exit on finish" checked={value.runtime.exit_on_finish} onChange={(next) => setRuntime("exit_on_finish", next)} />
          </div>
        </div>

        {ENDPOINTS.map(({ id, label }) => (
          <EndpointSection
            key={id}
            title={label}
            value={value[id]}
            onChange={(key, next) => setEndpoint(id, key, next)}
            onSelectProvider={(provider) => onChange(normalizeAdvancedSettings({
              ...value,
              [id]: {
                ...value[id], protocol: provider.protocol, base_url: provider.base_url,
                model: provider.model, api_key_env: provider.api_key_env,
                auth_style: provider.auth_style, modality: provider.modality,
              },
            }))}
            modelProfile={endpointProfile(value[id], profileDetails, defaultProfile)}
            saving={saving}
          />
        ))}

        <div className="config-drawer-actions">
          <button type="button" className="mini-btn" disabled={saving} onClick={onSave}>
            {saving ? "Saving..." : "Save advanced settings"}
          </button>
          {status && <span className="mono muted">{status}</span>}
        </div>
      </div>
    </details>
  );
}

function endpointProfile(
  endpoint: EndpointAdvancedSettings,
  profiles: Record<string, ProfileDetail>,
  fallback: string,
): string {
  const match = Object.entries(profiles).find(([, profile]) => (
    profile.base_url === endpoint.base_url && profile.protocol === endpoint.protocol
  ));
  return match?.[0] || fallback;
}

function EndpointSection({
  title,
  value,
  onChange,
  onSelectProvider,
  modelProfile,
  saving,
}: {
  title: string;
  value: EndpointAdvancedSettings;
  onChange: <K extends keyof EndpointAdvancedSettings>(key: K, value: EndpointAdvancedSettings[K]) => void;
  onSelectProvider: (provider: ProviderRecord) => void;
  modelProfile: string;
  saving: boolean;
}) {
  return (
    <div className="advanced-section">
      <h3>{title}</h3>
      <div className="advanced-grid">
        <div className="advanced-field">
          <span>Provider</span>
          <ProviderChooser value={modelProfile} ariaLabel={`${title} provider`} disabled={saving} onChange={(_next, provider) => { if (provider) onSelectProvider(provider); }} />
        </div>
        <div className="advanced-field">
          <span>Model</span>
          <ModelChooser
            profile={modelProfile}
            value={value.model}
            onChange={(next) => onChange("model", next)}
            disabled={saving}
            ariaLabel={`${title} model`}
          />
        </div>
        <SelectField
          label="Protocol"
          value={value.protocol}
          options={["openai", "anthropic", "claude-code"]}
          onChange={(next) => onChange("protocol", next)}
        />
        <TextField label="Base URL" value={value.base_url} onChange={(next) => onChange("base_url", next)} />
        <TextField label="API key env" value={value.api_key_env} onChange={(next) => onChange("api_key_env", next)} />
        <TextField label="Provider pins" value={value.provider} onChange={(next) => onChange("provider", next)} />
        <NumberField label="Timeout" value={value.timeout} min={0} max={600} onChange={(next) => onChange("timeout", next)} />
        <SelectField label="Modality" value={value.modality} options={["text", "image", "auto"]} onChange={(next) => onChange("modality", next)} />
        <SelectField label="System mode" value={value.system_mode} options={["default", "merge", "drop"]} onChange={(next) => onChange("system_mode", next)} />
        <SelectField label="Auth style" value={value.auth_style} options={["x-api-key", "bearer"]} onChange={(next) => onChange("auth_style", next)} />
        <TextField label="System prompt file" value={value.system_prompt_file} onChange={(next) => onChange("system_prompt_file", next)} />
        <ToggleField label="Reasoning" checked={value.reasoning} onChange={(next) => onChange("reasoning", next)} />
      </div>
    </div>
  );
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="advanced-field">
      <span>{label}</span>
      <input type="text" value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="advanced-field">
      <span>{label}</span>
      <input
        type="number"
        min={min}
        max={max}
        step={1}
        value={value}
        onChange={(event) => onChange(clampNumber(Number.parseInt(event.target.value || "0", 10), value, min, max))}
      />
    </label>
  );
}

function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="advanced-field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>
  );
}

function ToggleField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="advanced-toggle">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <span>{label}</span>
    </label>
  );
}
