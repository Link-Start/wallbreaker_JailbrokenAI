from __future__ import annotations

import dataclasses

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Footer, Input, Static

from ..agent.loop import AgentEvents, run_turn
from ..agent.messages import user
from ..config import Config, Endpoint
from ..prompts import DEFAULT_SYSTEM
from ..providers.factory import build_provider
from ..tools import build_registry
from ..transforms import list_transforms
from . import widgets

HELP_TEXT = """Slash commands:
/help                 show this help
/profile [name]       show or switch the active profile
/target [name]        show target, or set it from a profile name
/model <id>           override the active model id
/transforms           list Parseltongue transforms
/lib [list|update|MODEL]   browse the L1B3RT4S library
/clear                clear the conversation
/save [path]          save the transcript
/quit                 exit

Type anything else to talk to the agent. It has shell, file, parseltongue,
l1b3rt4s, query_target, and http_request tools."""


class RthApp(App):
    CSS = """
    #log { padding: 0 1; }
    #status { height: 1; background: $boost; color: $text; padding: 0 1; }
    #prompt { dock: bottom; }
    """
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear_log", "Clear"),
    ]

    def __init__(self, config: Config, endpoint: Endpoint, system: str) -> None:
        super().__init__()
        self.config = config
        self.endpoint = endpoint
        self.system = system
        self.provider = build_provider(endpoint)
        self.registry = build_registry(config)
        self.history = []
        self.max_tokens = 4096
        self._busy = False
        self._assistant: Static | None = None
        self._buf = ""

    def compose(self) -> ComposeResult:
        yield Static(self._status_text(), id="status")
        yield VerticalScroll(id="log")
        yield Input(placeholder="message, or /help", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        self._log = self.query_one("#log", VerticalScroll)
        self.query_one("#prompt", Input).focus()
        self._mount(widgets.info_panel(
            "rth red-team harness. /help for commands.", title="ready"
        ))

    def _status_text(self) -> str:
        tgt = self.config.target.model if self.config.target else "none"
        return (
            f" profile={self.endpoint.name} | {self.endpoint.protocol} | "
            f"model={self.endpoint.model} | target={tgt}"
        )

    def _refresh_status(self) -> None:
        self.query_one("#status", Static).update(self._status_text())

    def _mount(self, renderable) -> None:
        self._log.mount(Static(renderable))
        self._log.scroll_end(animate=False)

    def _ensure_assistant(self) -> None:
        if self._assistant is None:
            self._buf = ""
            self._assistant = Static(widgets.assistant_panel("", self.endpoint.model))
            self._log.mount(self._assistant)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            self._handle_command(text)
            return
        if self._busy:
            self._mount(widgets.error_panel("Agent is still working; wait for it."))
            return
        self._mount(widgets.user_panel(text))
        self.history.append(user(text))
        self._busy = True
        self.run_worker(self._agent_turn(), exclusive=True, group="agent")

    async def _agent_turn(self) -> None:
        events = AgentEvents(
            on_text=self._on_text,
            on_tool_start=self._on_tool_start,
            on_tool_result=self._on_tool_result,
            on_turn_end=self._on_turn_end,
            on_error=self._on_error,
        )
        try:
            await run_turn(
                self.provider,
                self.registry,
                self.history,
                system=self.system,
                events=events,
                max_tokens=self.max_tokens,
            )
        finally:
            self._assistant = None
            self._busy = False

    def _on_text(self, delta: str) -> None:
        self._ensure_assistant()
        self._buf += delta
        assert self._assistant is not None
        self._assistant.update(widgets.assistant_panel(self._buf, self.endpoint.model))
        self._log.scroll_end(animate=False)

    def _on_turn_end(self, _message) -> None:
        self._assistant = None

    def _on_tool_start(self, _id: str, name: str, args: dict) -> None:
        self._mount(widgets.tool_call_panel(name, args))

    def _on_tool_result(self, _id: str, name: str, content: str, is_error: bool) -> None:
        self._mount(widgets.tool_result_panel(name, content, is_error))

    def _on_error(self, message: str) -> None:
        self._mount(widgets.error_panel(message))

    def action_clear_log(self) -> None:
        self._clear()

    def _clear(self) -> None:
        self.history = []
        self._log.remove_children()
        self._mount(widgets.info_panel("conversation cleared", title="ready"))

    def _handle_command(self, text: str) -> None:
        parts = text.split()
        cmd, rest = parts[0].lower(), parts[1:]
        if cmd in ("/quit", "/exit"):
            self.exit()
        elif cmd == "/help":
            self._mount(widgets.info_panel(HELP_TEXT, title="help"))
        elif cmd == "/clear":
            self._clear()
        elif cmd == "/profile":
            self._cmd_profile(rest)
        elif cmd == "/target":
            self._cmd_target(rest)
        elif cmd == "/model":
            self._cmd_model(rest)
        elif cmd == "/transforms":
            catalog = "\n".join(
                f"{t.name:14} {t.description}" for t in list_transforms()
            )
            self._mount(widgets.info_panel(catalog, title="transforms"))
        elif cmd == "/lib":
            self.run_worker(self._cmd_lib(rest), exclusive=False)
        elif cmd == "/save":
            self._cmd_save(rest)
        else:
            self._mount(widgets.error_panel(f"unknown command: {cmd}"))

    def _cmd_profile(self, rest: list[str]) -> None:
        if not rest:
            names = ", ".join(self.config.profiles)
            self._mount(widgets.info_panel(
                f"active: {self.endpoint.name}\navailable: {names}", title="profile"
            ))
            return
        name = rest[0]
        if name not in self.config.profiles:
            self._mount(widgets.error_panel(f"no profile '{name}'"))
            return
        self.endpoint = self.config.profiles[name]
        self.provider = build_provider(self.endpoint)
        self._refresh_status()
        self._mount(widgets.info_panel(f"switched to {name}", title="profile"))

    def _cmd_target(self, rest: list[str]) -> None:
        if not rest:
            t = self.config.target
            msg = f"{t.model} @ {t.base_url}" if t else "no target configured"
            self._mount(widgets.info_panel(msg, title="target"))
            return
        name = rest[0]
        if name not in self.config.profiles:
            self._mount(widgets.error_panel(f"no profile '{name}'"))
            return
        src = self.config.profiles[name]
        self.config.target = dataclasses.replace(src, name="target")
        self._refresh_status()
        self._mount(widgets.info_panel(f"target set to {name}", title="target"))

    def _cmd_model(self, rest: list[str]) -> None:
        if not rest:
            self._mount(widgets.error_panel("usage: /model <id>"))
            return
        self.endpoint = dataclasses.replace(self.endpoint, model=rest[0])
        self.provider = build_provider(self.endpoint)
        self._refresh_status()
        self._mount(widgets.info_panel(f"model -> {rest[0]}", title="model"))

    async def _cmd_lib(self, rest: list[str]) -> None:
        from ..tools import l1b3rt4s as lib

        action = rest[0] if rest else "list"
        if action == "update":
            out = await self.registry.execute("l1b3rt4s_list", {})
            self._mount(widgets.info_panel(out.content, title="lib"))
        elif action == "list":
            out = await self.registry.execute("l1b3rt4s_list", {})
            self._mount(widgets.info_panel(out.content, title="lib"))
        else:
            out = await self.registry.execute("l1b3rt4s_get", {"model": action})
            self._mount(widgets.info_panel(out.content, title=f"lib:{action}"))

    def _cmd_save(self, rest: list[str]) -> None:
        path = rest[0] if rest else "transcript.md"
        lines = []
        for msg in self.history:
            lines.append(f"## {msg.role}")
            lines.append(msg.text())
            for tu in msg.tool_uses():
                lines.append(f"[tool {tu.name}] {tu.input}")
            lines.append("")
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines))
            self._mount(widgets.info_panel(f"saved to {path}", title="save"))
        except OSError as exc:
            self._mount(widgets.error_panel(str(exc)))


def run_tui(config: Config, args) -> int:
    from ..cli import resolve_endpoint

    endpoint = resolve_endpoint(config, args)
    system = getattr(args, "system", None) or DEFAULT_SYSTEM
    RthApp(config, endpoint, system).run()
    return 0
