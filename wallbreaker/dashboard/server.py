from __future__ import annotations

import asyncio
import dataclasses
import json
import re
from datetime import datetime
from pathlib import Path

from .. import report as report_mod
from ..presets import list_presets
from ..transforms import TRANSFORMS, apply_chain, list_transforms
from ..session import normalize_inference_records

_VERDICT_RE = re.compile(r"\b(COMPLIED|PARTIAL|REFUSED|EMPTY|BLOCKED_INPUT|BLOCKED_OUTPUT)\b")
_RUN_NAME_RE = re.compile(r"^run-(\d{8})-?(\d{6})\.jsonl$")
_FIRE_TOOLS = {"query_target", "continue_target", "fire", "query_image_target"}
_FINDING_KINDS = {"verdict", "attack_fire"}
_FINDING_LABELS = {"COMPLIED", "PARTIAL"}
_ENDPOINT_PREFIXES = ("attacker", "target", "judge", "art")
_ENDPOINT_FIELDS = (
    "protocol", "base_url", "model", "api_key_env", "provider", "timeout",
    "modality", "reasoning", "system_mode", "system_prompt_file", "auth_style",
    "inference_path", "models_path",
)


TYPICAL_CONFIGURATIONS = [
    {
        "id": "balanced",
        "name": "Balanced",
        "description": "Default dashboard run profile.",
        "agent": {"max_rounds": 8, "max_tokens": 8192},
        "advanced": {
            "runtime": {
                "auto": False, "rounds": 8, "no_tools": False,
                "exit_on_finish": True, "log": True, "judge": True, "resume": "",
            },
        },
    },
    {
        "id": "fast_triage",
        "name": "Fast triage",
        "description": "Short agent runs and lower token budgets.",
        "agent": {"max_rounds": 4, "max_tokens": 4096},
        "advanced": {
            "runtime": {
                "auto": False, "rounds": 4, "no_tools": False,
                "exit_on_finish": True, "log": True, "judge": False, "resume": "",
            },
        },
    },
    {
        "id": "deep_audit",
        "name": "Deep audit",
        "description": "Longer autonomous runs with larger response budgets.",
        "agent": {"max_rounds": 20, "max_tokens": 16000},
        "advanced": {
            "runtime": {
                "auto": True, "rounds": 20, "no_tools": False,
                "exit_on_finish": False, "log": True, "judge": True, "resume": "",
            },
        },
    },
]


def _run_time_from_name(name: str) -> str:
    match = _RUN_NAME_RE.match(name)
    if not match:
        return ""
    try:
        dt = datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")
    except ValueError:
        return ""
    return dt.isoformat(sep=" ", timespec="seconds")


def _models_from_records(records: list[dict]) -> dict:
    for record in records:
        if record.get("kind") != "run_meta":
            continue
        models = record.get("models")
        if isinstance(models, dict):
            return {
                "attacker": str(models.get("attacker") or ""),
                "target": str(models.get("target") or ""),
                "judge": str(models.get("judge") or ""),
                "recorded": True,
            }
    return {"attacker": "", "target": "", "judge": "", "recorded": False}


def _safe_run_path(sessions: Path, name: str) -> Path | None:
    if ".." in name or "/" in name or "\\" in name:
        return None
    path = sessions / name
    return path if path.is_file() else None


def _load_records_with_lines(path: Path) -> tuple[list[dict], list[str], list[int]]:
    records = []
    raw_records = []
    line_numbers = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        raw = line.strip()
        if not raw:
            continue
        raw_records.append(raw)
        line_numbers.append(lineno)
        try:
            records.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            records.append({
                "kind": "parse_error",
                "line": lineno,
                "error": str(exc),
                "raw": raw,
            })
    return records, raw_records, line_numbers


def _text_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(value)


def _dict_value(value) -> dict:
    return value if isinstance(value, dict) else {}


def _list_value(value) -> list:
    return value if isinstance(value, list) else []


def _split_chain(value) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _record_prompt(record: dict) -> str:
    args = _dict_value(record.get("args") or record.get("input"))
    for key in ("payload", "prompt", "request", "text", "objective", "query"):
        value = _text_value(record.get(key)).strip()
        if value:
            return value
    for key in ("payload", "prompt", "request", "text", "objective", "query"):
        value = _text_value(args.get(key)).strip()
        if value:
            return value
    return ""


def _record_response(record: dict) -> str:
    for key in ("response", "content", "result", "answer", "output", "text"):
        value = _text_value(record.get(key)).strip()
        if value:
            return value
    return ""


def _conversation_from_record(record: dict) -> list[dict]:
    for key in ("conversation", "history", "messages"):
        turns = _list_value(record.get(key))
        if not turns:
            continue
        out = []
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            role = str(turn.get("role") or "user")
            content = _text_value(turn.get("content") or turn.get("text"))
            if content:
                out.append({"role": role, "content": content, "source": key})
        if out:
            return out
    return []


def _related_fire_records(records: list[dict], index: int) -> list[dict]:
    start = 0
    for i in range(index - 1, -1, -1):
        if records[i].get("kind") in _FINDING_KINDS:
            start = i + 1
            break
    related = []
    for record in records[start : index + 1]:
        kind = record.get("kind")
        tool = record.get("tool") or record.get("name")
        if kind in ("tool_call", "tool_result") and tool in _FIRE_TOOLS:
            related.append(record)
        elif kind in _FINDING_KINDS:
            related.append(record)
    return related


def _conversation_for_finding(records: list[dict], index: int, finding: dict) -> list[dict]:
    explicit = _conversation_from_record(finding)
    if explicit:
        return explicit

    turns = []
    for record in _related_fire_records(records, index):
        kind = record.get("kind")
        tool = str(record.get("tool") or record.get("name") or kind or "")
        if kind == "tool_call":
            args = _dict_value(record.get("args") or record.get("input"))
            for turn in _list_value(args.get("history")):
                if isinstance(turn, dict):
                    content = _text_value(turn.get("content") or turn.get("text"))
                    if content:
                        turns.append({
                            "role": str(turn.get("role") or "user"),
                            "content": content,
                            "source": f"{tool}:history",
                        })
            prompt = _record_prompt(record)
            if prompt:
                turns.append({"role": "user", "content": prompt, "source": tool})
        elif kind == "tool_result":
            response = _record_response(record)
            if response:
                turns.append({"role": "assistant", "content": response, "source": tool})

    if not turns:
        payload = _text_value(finding.get("payload")).strip()
        response = _text_value(finding.get("response")).strip()
        if payload:
            turns.append({"role": "user", "content": payload, "source": "finding"})
        if response:
            turns.append({"role": "assistant", "content": response, "source": "finding"})
    return turns


def _template_for_finding(records: list[dict], index: int, finding: dict) -> dict:
    related = _related_fire_records(records, index)
    args = {}
    source_tool = ""
    for record in reversed(related):
        if record.get("kind") != "tool_call":
            continue
        tool = str(record.get("tool") or record.get("name") or "")
        if tool not in _FIRE_TOOLS:
            continue
        args = _dict_value(record.get("args") or record.get("input"))
        source_tool = tool
        break

    def pick(*keys):
        for source in (finding, args):
            for key in keys:
                value = source.get(key)
                if value not in (None, "", [], {}):
                    return value
        return ""

    transforms = {
        "prompt": _split_chain(pick("transforms", "transform_chain", "obfuscation_chain")),
        "system": _split_chain(pick("system_transforms")),
        "response": _split_chain(pick("response_transforms")),
    }
    return {
        "technique": _text_value(pick("technique") or "manual"),
        "source_tool": source_tool,
        "preset": _text_value(pick("preset")),
        "template": _text_value(pick("template", "prompt_template", "technique_template")),
        "instructions": _text_value(pick("instructions", "system", "persona", "method")),
        "think_seed": _text_value(pick("think_seed")),
        "max_tokens": pick("max_tokens"),
        "transforms": transforms,
        "raw_args": args,
    }


def _judging_for_finding(finding: dict) -> dict:
    from ..judging import IMAGE_JUDGE_SYSTEM, IMAGE_JUDGE_TEMPLATE, JUDGE_SYSTEM, JUDGE_TEMPLATE

    source = _text_value(finding.get("judge_source") or finding.get("source") or "judge")
    is_image = source == "image-judge" or bool(finding.get("image_urls"))
    return {
        "source": source,
        "label": finding.get("label", ""),
        "reason": finding.get("reason", ""),
        "score": finding.get("score"),
        "criteria": IMAGE_JUDGE_SYSTEM if is_image else JUDGE_SYSTEM,
        "template": IMAGE_JUDGE_TEMPLATE if is_image else JUDGE_TEMPLATE,
    }


def _findings_for_run(path: Path) -> list[dict]:
    records, raw_records, line_numbers = _load_records_with_lines(path)
    models = _models_from_records(records)
    run_time = _run_time_from_name(path.name)
    findings = []
    for index, record in enumerate(records):
        label = str(record.get("label", "")).upper()
        if record.get("kind") not in _FINDING_KINDS or label not in _FINDING_LABELS:
            continue
        raw_line = raw_records[index] if index < len(raw_records) else json.dumps(record, ensure_ascii=False)
        line_number = line_numbers[index] if index < len(line_numbers) else index + 1
        finding = dict(record)
        finding.setdefault("label", label)
        finding["id"] = f"{path.name}:{line_number}"
        finding["run"] = path.name
        finding["run_time"] = run_time
        finding["line"] = line_number
        finding["record_index"] = index
        finding["raw"] = raw_line
        finding["models"] = models
        finding["conversation"] = _conversation_for_finding(records, index, record)
        finding["technique_detail"] = _template_for_finding(records, index, record)
        finding["judging"] = _judging_for_finding(record)
        finding["fields"] = record
        findings.append(finding)
    rank = {"COMPLIED": 0, "PARTIAL": 1}
    findings.sort(key=lambda item: (item.get("run", ""), rank.get(item.get("label"), 9), item.get("line", 0)), reverse=True)
    return findings


def _finding_run_summaries(sessions: Path) -> list[dict]:
    if not sessions.is_dir():
        return []
    out = []
    for path in sorted(sessions.glob("run-*.jsonl"), reverse=True):
        try:
            records = report_mod._load_records(path)
            findings_count = sum(
                1 for record in records
                if record.get("kind") in _FINDING_KINDS
                and str(record.get("label", "")).upper() in _FINDING_LABELS
            )
            hits = sum(
                1 for record in records
                if str(record.get("label", "")).upper() in _FINDING_LABELS
            )
        except Exception:
            records, findings_count, hits = [], 0, 0
        out.append({
            "name": path.name,
            "time": _run_time_from_name(path.name),
            "models": _models_from_records(records),
            "size": path.stat().st_size,
            "records": len(records),
            "hits": hits,
            "findings": findings_count,
        })
    return out


def _summarize_args(args: dict) -> str:
    if not isinstance(args, dict):
        return str(args)[:300]
    if not args:
        return ""
    parts = []
    for k, v in args.items():
        if k in ("prompt", "request", "text", "payload") and isinstance(v, str):
            parts.append(f"{k}({len(v)} chars): {v[:160]}")
        else:
            vs = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
            parts.append(f"{k}={str(vs)[:120]}")
    return "  ".join(parts)[:600]


def _web_dist(web_dir: str | Path | None) -> Path | None:
    base = Path(web_dir) if web_dir else Path(__file__).resolve().parent / "web"
    dist = base / "dist"
    return dist if dist.is_dir() and (dist / "index.html").is_file() else None


def _config_summary(config) -> dict:
    if config is None:
        return {"has_target": False, "target": None, "profile": None, "judge": None}
    display_config = config
    roles = {}
    try:
        from ..agent_profiles import resolved_config
        display_config, roles = resolved_config(config)
    except Exception:
        pass
    target = getattr(display_config, "target", None)
    judge = getattr(display_config, "judge", None)
    prof = None
    try:
        prof = roles.get("attacker", {}).get("provider", display_config.default_profile)
    except Exception:
        prof = None
    return {
        "has_target": target is not None,
        "target": getattr(target, "model", None) if target else None,
        "target_modality": getattr(target, "modality", "text") if target else None,
        "profile": prof,
        "judge": getattr(judge, "model", None) if judge else None,
    }


def _extract_verdict(text: str) -> str:
    m = _VERDICT_RE.search(text or "")
    return m.group(1) if m else ""


def _list_arg(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    try:
        items = list(value or [])
    except TypeError:
        items = [value]
    return [str(item).strip() for item in items if str(item).strip()]


def _int_setting(value, default: int, lo: int, hi: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(lo, min(parsed, hi))


def _agent_settings(prefs: dict | None = None) -> dict:
    prefs = prefs or {}
    return {
        "max_rounds": _int_setting(
            prefs.get("agent_max_rounds", prefs.get("rounds")),
            8,
            1,
            50,
        ),
        "max_tokens": _int_setting(
            prefs.get("agent_max_tokens"),
            8192,
            1,
            32000,
        ),
    }


def _bool_setting(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _advanced_settings(config, prefs: dict | None = None) -> dict:
    prefs = prefs or {}
    return {
        "runtime": {
            "auto": _bool_setting(prefs.get("auto"), False),
            "rounds": _int_setting(prefs.get("rounds"), 12, 1, 50),
            "no_tools": _bool_setting(prefs.get("no_tools"), False),
            "exit_on_finish": _bool_setting(prefs.get("exit_on_finish"), True),
            "log": _bool_setting(prefs.get("log"), True),
            "judge": _bool_setting(prefs.get("judge"), False),
            "resume": str(prefs.get("resume", "")),
        },
    }


def _store_advanced_settings(prefs: dict, advanced: dict) -> None:
    runtime = advanced.get("runtime") if isinstance(advanced.get("runtime"), dict) else {}
    if "auto" in runtime:
        prefs["auto"] = _bool_setting(runtime.get("auto"), False)
    if "rounds" in runtime:
        prefs["rounds"] = _int_setting(runtime.get("rounds"), 12, 1, 50)
    if "no_tools" in runtime:
        prefs["no_tools"] = _bool_setting(runtime.get("no_tools"), False)
    if "exit_on_finish" in runtime:
        prefs["exit_on_finish"] = _bool_setting(runtime.get("exit_on_finish"), True)
    if "log" in runtime:
        prefs["log"] = _bool_setting(runtime.get("log"), True)
    if "judge" in runtime:
        prefs["judge"] = _bool_setting(runtime.get("judge"), False)
    if "resume" in runtime:
        prefs["resume"] = str(runtime.get("resume") or "")

def _compose_attack_payload(body: dict) -> dict:
    request = str(body.get("request") or body.get("prompt") or "").strip()
    preset_name = str(body.get("preset") or "").strip()
    transforms = _list_arg(body.get("transforms"))
    system = str(body.get("system") or "")
    try:
        max_tokens = int(body.get("max_tokens", 1024))
    except (TypeError, ValueError) as exc:
        raise ValueError("max_tokens must be an integer") from exc

    raw_payload = body.get("payload")
    if raw_payload is not None:
        payload = str(raw_payload)
        if not payload.strip():
            raise ValueError("'payload' is required")
        return {
            "request": request,
            "prompt": payload,
            "payload": payload,
            "preset": preset_name,
            "transforms": transforms,
            "system": system,
            "max_tokens": max_tokens,
            "source": "payload",
        }

    if not request:
        raise ValueError("'request' is required")

    prompt = request
    if preset_name:
        from ..presets import get_preset

        preset = get_preset(preset_name)
        if preset is None:
            raise ValueError(f"unknown preset {preset_name}")
        prompt = preset.template.replace("{request}", request)

    unknown = [name for name in transforms if name not in TRANSFORMS]
    if unknown:
        raise ValueError(f"unknown transform(s): {', '.join(unknown)}")
    payload = apply_chain(prompt, transforms) if transforms else prompt
    return {
        "request": request,
        "prompt": prompt,
        "payload": payload,
        "preset": preset_name,
        "transforms": transforms,
        "system": system,
        "max_tokens": max_tokens,
        "source": "compose",
    }


def _settings_view(config, prefs: dict | None = None) -> dict:
    agent = _agent_settings(prefs)
    if config is None:
        return {"profiles": [], "default_profile": None, "attacker_model": None,
                "target": None, "judge_model": None, "agent": agent,
                "profile_details": {},
                "advanced": _advanced_settings(None, prefs),
                "typical_configurations": TYPICAL_CONFIGURATIONS}
    display_config = config
    role_view = {}
    try:
        from ..agent_profiles import resolved_config
        display_config, role_view = resolved_config(config)
    except Exception:
        pass
    attacker_model = None
    if config.profiles:
        try:
            attacker_model = display_config.profile().model
        except Exception:
            attacker_model = None
    tgt = getattr(display_config, "target", None)
    target = None
    if tgt is not None:
        target = {
            "model": tgt.model, "modality": getattr(tgt, "modality", "text"),
            "base_url": tgt.base_url, "protocol": tgt.protocol,
            "provider": list(getattr(tgt, "provider", ()) or ()),
        }
    judge = getattr(display_config, "judge", None)
    return {
        "profiles": list(config.profiles.keys()),
        "profile_details": {
            name: {
                "name": name,
                "model": endpoint.model,
                "protocol": endpoint.protocol,
                "base_url": endpoint.base_url,
                "modality": getattr(endpoint, "modality", "text"),
            }
            for name, endpoint in config.profiles.items()
        },
        "default_profile": role_view.get("attacker", {}).get("provider", config.default_profile),
        "attacker_model": attacker_model,
        "target": target,
        "target_profile": role_view.get("target", {}).get("provider"),
        "judge_model": getattr(judge, "model", None) if judge else None,
        "judge_profile": role_view.get("judge", {}).get("provider"),
        "agent": agent,
        "advanced": _advanced_settings(config, prefs),
        "typical_configurations": TYPICAL_CONFIGURATIONS,
    }


def _model_ids(payload) -> list[str]:
    """Normalize OpenAI/Anthropic-compatible model-list response shapes."""
    rows = payload
    if isinstance(payload, dict):
        rows = payload.get("data", payload.get("models", []))
    if not isinstance(rows, list):
        return []
    models = []
    for row in rows:
        model_id = row.get("id") or row.get("name") if isinstance(row, dict) else row
        if model_id and str(model_id).strip():
            models.append(str(model_id).strip())
    return sorted(set(models), key=str.casefold)


async def _discover_profile_models(profile: str, endpoint) -> dict:
    current = str(getattr(endpoint, "model", "") or "").strip()
    fallback = [current] if current else []
    protocol = str(getattr(endpoint, "protocol", "") or "").lower()
    base_url = str(getattr(endpoint, "base_url", "") or "").rstrip("/")
    result = {
        "profile": profile,
        "protocol": protocol,
        "models": fallback,
        "fetched": False,
        "error": "",
    }
    if protocol == "claude-code":
        result["error"] = "This local provider does not expose a model catalog."
        return result
    if not base_url:
        result["error"] = "This profile has no model catalog URL."
        return result

    import httpx

    custom_path = str(getattr(endpoint, "models_path", "") or "")
    if protocol == "anthropic":
        path = custom_path or "/v1/models"
        url = f"{base_url}{path if path.startswith('/') else '/' + path}"
        headers = {
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        key = endpoint.resolved_key()
        if key:
            if getattr(endpoint, "auth_style", "x-api-key") == "bearer":
                headers["Authorization"] = f"Bearer {key}"
            else:
                headers["x-api-key"] = key
    else:
        path = custom_path or "/models"
        url = f"{base_url}{path if path.startswith('/') else '/' + path}"
        headers = {"Content-Type": "application/json"}
        key = endpoint.resolved_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            models = _model_ids(response.json())
    except (httpx.HTTPError, ValueError) as exc:
        result["error"] = f"Model catalog unavailable: {exc}"
        return result

    if current and current not in models:
        models.append(current)
        models.sort(key=str.casefold)
    result["models"] = models
    result["fetched"] = True
    return result


def create_app(config=None, sessions_dir: str | Path = "sessions", web_dir: str | Path | None = None):
    """Build the Wallbreaker dashboard FastAPI app. fastapi is an optional extra
    (`pip install -e '.[dashboard]'`), imported lazily so the package imports without it."""
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles

    sessions = Path(sessions_dir)
    from ..session import RunLog, run_models_meta

    console_runlog = RunLog(directory=str(sessions))
    provider_registry = None
    model_catalog = None
    agent_profile_registry = None
    if config is not None:
        try:
            from ..provider_registry import ProviderRegistry

            provider_registry = ProviderRegistry(config)
            from ..agent_profiles import AgentProfileRegistry
            agent_profile_registry = AgentProfileRegistry(config)
            from ..model_catalog import ModelCatalog, catalog_path_for

            model_catalog = ModelCatalog(catalog_path_for(config))
            for provider_id, endpoint in config.profiles.items():
                model_catalog.upsert(provider_id, endpoint.model, "configured")
            from ..state import load_state, save_state, state_path_for

            state_path = state_path_for(config)
            prefs = load_state(state_path)
            obsolete_keys = {
                "research_profile", "research_model",
                "research_agent_max_rounds", "research_agent_max_tokens",
                "profile", "target_profile", "judge_profile",
                "target_provider", "target_modality",
            }
            obsolete_keys.update(
                f"{prefix}_{field}" for prefix in _ENDPOINT_PREFIXES for field in _ENDPOINT_FIELDS
            )
            if obsolete_keys.intersection(prefs):
                prefs = {key: value for key, value in prefs.items() if key not in obsolete_keys}
                save_state(state_path, prefs)
        except Exception:
            pass
    app = FastAPI(title="Wallbreaker", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _latest():
        return report_mod.latest_run_log(sessions)

    @app.get("/api/health")
    def health():
        return {"ok": True, "name": "wallbreaker", "version": "0.1.0"}

    @app.get("/api/config")
    def config_info():
        return _config_summary(config)

    @app.get("/api/settings")
    def settings_get():
        prefs = {}
        if config is not None:
            try:
                from ..state import load_state, state_path_for

                prefs = load_state(state_path_for(config))
            except Exception:
                prefs = {}
        return _settings_view(config, prefs)

    @app.get("/api/providers")
    def providers_get():
        return provider_registry.list() if provider_registry is not None else []

    @app.get("/api/providers/{name}")
    def provider_get(name: str):
        if provider_registry is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        item = provider_registry.get(name)
        if item is None:
            raise HTTPException(status_code=404, detail=f"unknown provider '{name}'")
        return item

    @app.put("/api/providers/{name}")
    def provider_put(name: str, body: dict):
        if provider_registry is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        try:
            return provider_registry.save(name, body)
        except Exception as exc:
            from ..config import ConfigError

            if isinstance(exc, ConfigError):
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            raise

    @app.delete("/api/providers/{name}")
    def provider_delete(name: str):
        if provider_registry is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        try:
            provider_registry.delete(name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown provider '{name}'") from exc
        except Exception as exc:
            from ..config import ConfigError

            if isinstance(exc, ConfigError):
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            raise
        return {"ok": True}

    @app.post("/api/providers/{name}/test")
    async def provider_test(name: str):
        endpoint = getattr(config, "all_profiles", {}).get(name) if config is not None else None
        if endpoint is None:
            raise HTTPException(status_code=404, detail=f"unknown provider '{name}'")
        result = await _discover_profile_models(name, endpoint)
        if result["fetched"] and model_catalog is not None:
            model_catalog.sync(name, result["models"], "remote")
            result["refreshed_at"] = model_catalog.mark_refreshed(name)
        return {"ok": bool(result["fetched"]), **result}

    def _roles_view() -> dict:
        if agent_profile_registry is None:
            return {}
        return {role: data["active"] for role, data in agent_profile_registry.view()["roles"].items()}

    @app.get("/api/roles")
    def roles_get():
        if config is None:
            return {}
        return _roles_view()

    @app.put("/api/roles/{role}")
    def role_put(role: str, body: dict):
        if config is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        if agent_profile_registry is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        if role not in ("attacker", "target", "judge"):
            raise HTTPException(status_code=404, detail=f"unknown role '{role}'")
        try:
            return agent_profile_registry.activate(role, body)
        except Exception as exc:
            from ..config import ConfigError
            if isinstance(exc, ConfigError):
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            raise

    @app.get("/api/agent-profiles")
    def agent_profiles_get():
        return agent_profile_registry.view() if agent_profile_registry is not None else {"roles": {}}

    @app.put("/api/agent-profiles/{role}/{name}")
    def agent_profile_put(role: str, name: str, body: dict):
        if agent_profile_registry is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        try:
            return dataclasses.asdict(agent_profile_registry.save(role, name, body))
        except Exception as exc:
            from ..config import ConfigError
            if isinstance(exc, ConfigError):
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            raise

    @app.delete("/api/agent-profiles/{role}/{name}")
    def agent_profile_delete(role: str, name: str):
        if agent_profile_registry is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        try:
            agent_profile_registry.delete(role, name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown agent profile") from exc
        except Exception as exc:
            from ..config import ConfigError
            if isinstance(exc, ConfigError):
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            raise
        return {"ok": True}

    @app.get("/api/models")
    async def models_get(profile: str):
        if config is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        endpoint = config.all_profiles.get(profile)
        if endpoint is None:
            raise HTTPException(status_code=404, detail=f"unknown profile '{profile}'")
        refreshed_at = model_catalog.last_refreshed(profile) if model_catalog is not None else ""
        if refreshed_at:
            entries = model_catalog.list(profile)
            return {
                "profile": profile,
                "protocol": endpoint.protocol,
                "models": [entry["model_id"] for entry in entries],
                "entries": entries,
                "fetched": True,
                "cached": True,
                "refreshed_at": refreshed_at,
                "error": "",
            }
        result = await _discover_profile_models(profile, endpoint)
        if model_catalog is not None:
            if result["fetched"]:
                model_catalog.sync(profile, result["models"], "remote")
                result["refreshed_at"] = model_catalog.mark_refreshed(profile)
            entries = model_catalog.list(profile)
            result["entries"] = entries
            result["models"] = [entry["model_id"] for entry in entries]
        return result

    @app.get("/api/providers/{name}/models")
    def provider_models(name: str):
        if config is None or name not in config.all_profiles:
            raise HTTPException(status_code=404, detail=f"unknown provider '{name}'")
        entries = model_catalog.list(name) if model_catalog is not None else []
        return {"provider": name, "models": [item["model_id"] for item in entries], "entries": entries}

    @app.post("/api/providers/{name}/models")
    def provider_model_add(name: str, body: dict):
        if config is None or name not in config.all_profiles:
            raise HTTPException(status_code=404, detail=f"unknown provider '{name}'")
        model_id = str(body.get("model") or "").strip()
        if not model_id:
            raise HTTPException(status_code=400, detail="model is required")
        model_catalog.upsert(name, model_id, "manual")
        return {"provider": name, "model": model_id, "entries": model_catalog.list(name)}

    @app.post("/api/providers/{name}/models/refresh")
    async def provider_models_refresh(name: str):
        endpoint = config.all_profiles.get(name) if config is not None else None
        if endpoint is None:
            raise HTTPException(status_code=404, detail=f"unknown provider '{name}'")
        result = await _discover_profile_models(name, endpoint)
        if result["fetched"]:
            model_catalog.sync(name, result["models"], "remote")
            result["refreshed_at"] = model_catalog.mark_refreshed(name)
        result["entries"] = model_catalog.list(name)
        result["models"] = [item["model_id"] for item in result["entries"]]
        return result

    @app.post("/api/settings")
    def settings_post(body: dict):
        if config is None:
            raise HTTPException(status_code=400, detail="no config loaded")
        from ..state import load_state, save_state, state_path_for

        prefs = load_state(state_path_for(config))

        # Older settings clients submit provider/model pairs here. Persist them
        # through the same canonical Custom assignment used by the header.
        for role, provider_key, model_key in (
            ("attacker", "attacker_profile", "attacker_model"),
            ("target", "target_profile", "target_model"),
            ("judge", "judge_profile", "judge_model"),
        ):
            if provider_key not in body and model_key not in body:
                continue
            try:
                current = agent_profile_registry.view()["roles"][role]["active"]
                provider = str(body.get(provider_key) or current["provider"])
                model = str(body.get(model_key) or current["model"])
                agent_profile_registry.activate(role, {"provider": provider, "model": model})
            except Exception as exc:
                from ..config import ConfigError
                if isinstance(exc, ConfigError):
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                raise
        agent = body.get("agent") if isinstance(body.get("agent"), dict) else body
        if "agent_max_rounds" in agent:
            prefs["agent_max_rounds"] = _int_setting(agent.get("agent_max_rounds"), 8, 1, 50)
        if "max_rounds" in agent:
            prefs["agent_max_rounds"] = _int_setting(agent.get("max_rounds"), 8, 1, 50)
        if "agent_max_tokens" in agent:
            prefs["agent_max_tokens"] = _int_setting(agent.get("agent_max_tokens"), 8192, 1, 32000)
        if "max_tokens" in agent:
            prefs["agent_max_tokens"] = _int_setting(agent.get("max_tokens"), 8192, 1, 32000)
        if isinstance(body.get("advanced"), dict):
            _store_advanced_settings(prefs, body["advanced"])
        if body.get("typical_configuration"):
            preset_id = str(body.get("typical_configuration"))
            preset = next((item for item in TYPICAL_CONFIGURATIONS if item["id"] == preset_id), None)
            if preset is None:
                raise HTTPException(status_code=400, detail=f"unknown configuration '{preset_id}'")
            prefs["agent_max_rounds"] = preset["agent"]["max_rounds"]
            prefs["agent_max_tokens"] = preset["agent"]["max_tokens"]
            _store_advanced_settings(prefs, preset["advanced"])

        save_state(state_path_for(config), prefs)
        return _settings_view(config, prefs)

    @app.get("/api/overview")
    def overview():
        log = _latest()
        scorecard = {}
        findings_count = 0
        if log is not None:
            try:
                scorecard = report_mod.build_scorecard(log)
            except Exception:
                scorecard = {}
            try:
                findings_count = len(_findings_for_run(log))
            except Exception:
                findings_count = 0
        runs = sorted(sessions.glob("run-*.jsonl")) if sessions.is_dir() else []
        return {
            "config": _config_summary(config),
            "scorecard": scorecard,
            "findings_count": findings_count,
            "runs_count": len(runs),
            "latest_run": log.name if log else None,
        }

    @app.get("/api/runs")
    def runs():
        if not sessions.is_dir():
            return []
        out = []
        for p in sorted(sessions.glob("run-*.jsonl"), reverse=True):
            try:
                raw = report_mod._load_records(p)
                records = normalize_inference_records(raw)
                hits = sum(
                    1 for r in records
                    if str(r.get("label", "")).upper() in ("COMPLIED", "PARTIAL")
                )
            except Exception:
                records, hits = [], 0
            out.append({
                "name": p.name,
                "time": _run_time_from_name(p.name),
                "models": _models_from_records(records),
                "size": p.stat().st_size,
                "records": len(records),
                "hits": hits,
            })
        return out

    @app.get("/api/runs/{name}")
    def run_detail(name: str):
        path = _safe_run_path(sessions, name)
        if path is None:
            raise HTTPException(status_code=404, detail="run not found")
        source_records, raw_records, line_numbers = _load_records_with_lines(path)
        records = normalize_inference_records(source_records, line_numbers)
        return {
            "name": name,
            "total": len(records),
            "records": records,
            "raw_records": raw_records,
            "line_numbers": line_numbers,
        }

    @app.get("/api/findings/runs")
    def finding_runs():
        return _finding_run_summaries(sessions)

    @app.get("/api/findings")
    def findings(runs: str | None = None):
        selected = [name.strip() for name in (runs or "").split(",") if name.strip()]
        paths = []
        if selected:
            for name in selected:
                path = _safe_run_path(sessions, name)
                if path is not None:
                    paths.append(path)
        else:
            log = _latest()
            if log is not None:
                paths.append(log)
        out = []
        for path in paths:
            try:
                out.extend(_findings_for_run(path))
            except Exception:
                continue
        out.sort(key=lambda item: (str(item.get("run", "")), int(item.get("line", 0))), reverse=True)
        return out

    @app.get("/api/scorecard")
    def scorecard():
        log = _latest()
        if log is None:
            return {}
        try:
            return report_mod.build_scorecard(log)
        except Exception:
            return {}

    @app.get("/api/presets")
    def presets():
        return [{"name": p.name, "description": p.description} for p in list_presets()]

    @app.get("/api/transforms")
    def transforms():
        return [
            {
                "name": t.name,
                "description": t.description,
                "lossy": t.lossy,
                "reversible": t.reversible,
            }
            for t in list_transforms()
        ]

    @app.get("/api/tools")
    def tools():
        if config is None:
            return []
        try:
            from ..tools import build_registry

            reg = build_registry(config)
            return [{"name": s["name"], "description": s["description"]} for s in reg.specs()]
        except Exception:
            return []

    dashboard_inference_lock = asyncio.Lock()
    agent_active = False

    @app.post("/api/compose")
    def compose(body: dict):
        try:
            return _compose_attack_payload(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/fire")
    async def fire(body: dict):
        if config is None:
            raise HTTPException(status_code=400, detail="no [target] configured in config.toml")
        try:
            composed = _compose_attack_payload(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if dashboard_inference_lock.locked():
            raise HTTPException(status_code=409, detail="another dashboard inference is already in progress")

        args = {
            "prompt": composed["payload"] if composed["source"] == "payload" else composed["prompt"],
            "max_tokens": composed["max_tokens"],
        }
        if composed["source"] != "payload" and composed["transforms"]:
            args["transforms"] = composed["transforms"]
        if composed["system"]:
            args["system"] = composed["system"]

        from ..tools import build_registry
        from ..agent_profiles import resolved_config
        from ..session import inference_logging

        try:
            run_config, role_meta = resolved_config(config)
        except Exception as exc:
            from ..config import ConfigError
            if isinstance(exc, ConfigError):
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            raise
        reg = build_registry(run_config)
        if not console_runlog._started:
            console_runlog.set_run_meta(
                source="dashboard_console",
                models=run_models_meta(run_config, attacker=run_config.profile()),
                agent_roles=role_meta,
            )
        console_runlog.event(
            "console_request",
            request_body=body,
            composed=composed,
            agent_roles=role_meta,
            tool="query_target",
            tool_args=args,
        )
        async with dashboard_inference_lock:
            with inference_logging(console_runlog):
                result = await reg.execute("query_target", args)
        verdict = _extract_verdict(result.content)
        target = run_config.target
        console_runlog.event(
            "attack_fire",
            request=composed["request"],
            prompt=composed["prompt"],
            payload=composed["payload"],
            response=result.content,
            label=verdict,
            technique="console",
            preset=composed["preset"],
            transforms=composed["transforms"],
            system=composed["system"],
            is_error=result.is_error,
            max_tokens=composed["max_tokens"],
            target_model=getattr(target, "model", "") if target else "",
            target_base_url=getattr(target, "base_url", "") if target else "",
            agent_roles=role_meta,
        )
        return {
            **composed,
            "content": result.content,
            "response": result.content,
            "is_error": result.is_error,
            "verdict": verdict,
            "run_log": console_runlog.path.name,
        }

    @app.post("/api/agent/run")
    async def agent_run(body: dict):
        nonlocal agent_active
        from fastapi.responses import StreamingResponse

        if config is None:
            raise HTTPException(status_code=400, detail="no [target] configured in config.toml")
        try:
            from ..agent_profiles import resolved_config
            run_config, role_meta = resolved_config(config)
            brain = run_config.profile()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if brain is None:
            raise HTTPException(status_code=400, detail="no attacker profile configured")
        objective = str(body.get("objective") or "").strip()
        if not objective:
            raise HTTPException(status_code=400, detail="'objective' is required")
        if agent_active:
            raise HTTPException(status_code=409, detail="an agent run is already in progress")
        if dashboard_inference_lock.locked():
            raise HTTPException(status_code=409, detail="another dashboard inference is already in progress")
        prefs = {}
        try:
            from ..state import load_state, state_path_for

            prefs = load_state(state_path_for(config))
        except Exception:
            prefs = {}
        agent_defaults = _agent_settings(prefs)
        max_rounds = _int_setting(body.get("max_rounds"), agent_defaults["max_rounds"], 1, 50)
        max_tokens = _int_setting(body.get("max_tokens"), agent_defaults["max_tokens"], 1, 32000)

        from ..agent.loop import AgentEvents, run_autonomous
        from ..agent.messages import user
        from ..prompts import compose_system
        from ..providers.factory import build_provider
        from ..session import RunLog, run_models_meta
        from ..tools import build_registry

        provider = build_provider(brain)
        registry = build_registry(run_config)
        runlog = RunLog(directory=str(sessions))
        runlog.set_run_meta(
            source="dashboard_agent",
            models=run_models_meta(run_config, attacker=brain),
            agent_roles=role_meta,
            agent={"max_rounds": max_rounds, "max_tokens": max_tokens},
        )
        queue: asyncio.Queue = asyncio.Queue()

        def push(ev) -> None:
            try:
                queue.put_nowait(ev)
            except Exception:
                pass

        def progress(message) -> None:
            text = str(message)
            runlog.event("progress", text=text)
            push({"type": "progress", "text": text})

        def tool_start(tool_id, name, args) -> None:
            runlog.event("tool_call", tool_use_id=tool_id, tool=name, args=args)
            push({"type": "tool_start", "name": name, "args": _summarize_args(args)})

        def tool_result(tool_id, name, content, is_error) -> None:
            runlog.event(
                "tool_result",
                tool_use_id=tool_id,
                tool=name,
                content=content or "",
                error=bool(is_error),
            )
            push({
                "type": "tool_result", "name": name, "content": (content or "")[:6000],
                "error": bool(is_error), "verdict": _extract_verdict(content or ""),
            })

        def round_event(round_number, maximum) -> None:
            runlog.event("agent_round", round=round_number, max_rounds=maximum)
            push({"type": "round", "round": round_number, "max": maximum})

        def error_event(error) -> None:
            text = str(error)
            runlog.event("agent_error", error=text)
            push({"type": "error", "error": text})

        def feedback_event(message) -> None:
            text = str(message)
            runlog.event("operator_feedback", text=text)
            push({"type": "feedback", "text": text})

        def internal_message(role, text, source) -> None:
            runlog.event("history_message", role=role, text=text, source=source)

        def tool_run_event(event) -> None:
            runlog.event("tool_run_event", event=event)
            push({"type": "progress", "text": json.dumps(event, ensure_ascii=False)})

        registry.ctx.progress = progress
        registry.ctx.run_events = tool_run_event
        registry.ctx.record = lambda p, r, lbl, rs, t: runlog.verdict(p, r, lbl, rs, t)

        events = AgentEvents(
            on_text=lambda t: push({"type": "text", "text": t}),
            on_tool_start=tool_start,
            on_tool_result=tool_result,
            on_round=round_event,
            on_error=error_event,
            on_feedback=feedback_event,
            on_internal_message=internal_message,
            on_usage=lambda i, o: push({"type": "usage", "input": i, "output": o}),
        )

        history = [user(objective)]
        runlog.event("objective", text=objective)

        async def runner():
            nonlocal agent_active
            from ..session import inference_logging

            async with dashboard_inference_lock:
                try:
                    with inference_logging(runlog):
                        res = await run_autonomous(
                            provider, registry, history, system=compose_system(brain),
                            events=events, max_rounds=max_rounds, max_tokens=max_tokens,
                        )
                    data = res.data or {}
                    summary = data.get("summary") or data.get("question") or ""
                    runlog.event("agent_done", status=res.status, summary=summary)
                    push({
                        "type": "done", "status": res.status,
                        "summary": summary, "run_log": runlog.path.name,
                    })
                except Exception as exc:  # noqa: BLE001
                    error_event(f"{type(exc).__name__}: {exc}")
                finally:
                    agent_active = False
                    push(None)

        agent_active = True
        task = asyncio.create_task(runner())

        async def gen():
            push({"type": "start", "objective": objective, "brain": getattr(brain, "model", ""),
                  "target": getattr(run_config.target, "model", ""),
                  "max_rounds": max_rounds, "max_tokens": max_tokens,
                  "run_log": runlog.path.name})
            try:
                while True:
                    ev = await queue.get()
                    if ev is None:
                        break
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            finally:
                if not task.done():
                    task.cancel()

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    dist = _web_dist(web_dir)
    if dist is not None:
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="web")
    else:
        @app.get("/")
        def _no_build():
            return {
                "message": "Wallbreaker dashboard API is running, but the web UI is not built.",
                "build": "cd wallbreaker/dashboard/web && npm install && npm run build",
                "api": "/api/overview",
            }

    return app


def serve(host: str = "127.0.0.1", port: int = 8787, config=None, sessions_dir="sessions"):
    import uvicorn

    app = create_app(config=config, sessions_dir=sessions_dir)
    uvicorn.run(app, host=host, port=port)
