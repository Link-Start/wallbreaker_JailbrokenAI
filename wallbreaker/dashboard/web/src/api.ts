export interface ConfigInfo {
  has_target: boolean;
  target: string | null;
  target_modality?: string;
  profile: string | null;
  judge: string | null;
}

export interface Scorecard {
  asr?: number;
  total?: number;
  hits?: number;
  grade?: string;
  by_technique?: Record<string, { hits: number; total: number }>;
  by_category?: Record<string, { hits: number; total: number }>;
  [k: string]: unknown;
}

export interface Overview {
  config: ConfigInfo;
  scorecard: Scorecard;
  findings_count: number;
  runs_count: number;
  latest_run: string | null;
}

export interface Finding {
  label: string;
  technique?: string;
  payload?: string;
  reason?: string;
  response?: string;
  category?: string;
}

export interface RunSummary {
  name: string;
  size: number;
  records: number;
  hits: number;
}

export interface Preset { name: string; description: string }
export interface Transform { name: string; description: string; lossy: boolean; reversible: boolean }
export interface Tool { name: string; description: string }

export interface FireResult {
  prompt: string;
  content: string;
  is_error: boolean;
  verdict: string;
}

async function j<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const body = await r.json();
      detail = body.detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return r.json() as Promise<T>;
}

export const api = {
  overview: () => j<Overview>("/api/overview"),
  config: () => j<ConfigInfo>("/api/config"),
  findings: () => j<Finding[]>("/api/findings"),
  runs: () => j<RunSummary[]>("/api/runs"),
  run: (name: string) => j<{ name: string; total: number; records: Record<string, unknown>[] }>(`/api/runs/${encodeURIComponent(name)}`),
  presets: () => j<Preset[]>("/api/presets"),
  transforms: () => j<Transform[]>("/api/transforms"),
  tools: () => j<Tool[]>("/api/tools"),
  fire: (body: Record<string, unknown>) =>
    j<FireResult>("/api/fire", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

export interface AgentEvent {
  type: "start" | "round" | "text" | "tool_start" | "tool_result" | "progress" | "feedback" | "usage" | "error" | "done";
  [k: string]: unknown;
}

export async function runAgent(
  body: { objective: string; max_rounds?: number },
  onEvent: (ev: AgentEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const r = await fetch("/api/agent/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!r.ok || !r.body) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const line = frame.startsWith("data:") ? frame.replace(/^data:\s?/, "") : frame;
      if (line) {
        try { onEvent(JSON.parse(line) as AgentEvent); } catch { /* ignore */ }
      }
    }
  }
}

export function verdictKind(label: string | undefined): "bypass" | "partial" | "held" | "neutral" {
  const v = (label || "").toUpperCase();
  if (v === "COMPLIED") return "bypass";
  if (v === "PARTIAL") return "partial";
  if (v === "REFUSED") return "held";
  return "neutral";
}
