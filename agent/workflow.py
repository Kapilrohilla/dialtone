"""Pure workflow engine: walks a published workflow graph one path at a time.

No LiveKit imports. Never raises on malformed graphs: a graph without a start
step makes ``start()`` return None and the caller falls back to script-only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

CAPPED_MESSAGE = (
    "The workflow loop limit was reached. Stop following the workflow: record the outcome "
    "UNRESOLVED with reason \"workflow loop limit reached\", then close the call politely."
)


@dataclass(frozen=True)
class Step:
    id: str
    name: str
    type: str
    prompt: str = ""
    field: str | None = None
    knowledge_id: int | None = None
    outcome: str | None = None


@dataclass(frozen=True)
class PathTool:
    name: str
    description: str
    to: str
    takes_value: bool


@dataclass(frozen=True)
class Transition:
    ok: bool
    message: str
    entered: Step | None = None
    capped: bool = False
    captured: tuple[str, str] | None = None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _str(v) -> str:
    return v if isinstance(v, str) else ""


class WorkflowRun:
    def __init__(self, graph, max_visits: int = 3, max_transitions: int = 25):
        self.max_visits = max_visits
        self.max_transitions = max_transitions
        self._steps: dict[str, Step] = {}
        self._out: dict[str, list[dict]] = {}
        self._names: dict[str, str] = {}
        self._edges: list[tuple[str, str, str]] = []  # (from, to, label) in graph order
        self.current: Step | None = None
        self.path: list[str] = []
        self.captured: dict[str, str] = {}
        self.visits: dict[str, int] = {}
        self.transitions = 0
        self._load(graph)

    def _load(self, graph) -> None:
        if not isinstance(graph, dict):
            return
        steps = graph.get("steps")
        paths = graph.get("paths")
        for s in steps if isinstance(steps, list) else []:
            if not isinstance(s, dict) or not isinstance(s.get("id"), str) or s["id"] in self._steps:
                continue
            kid = s.get("knowledge_id")
            self._steps[s["id"]] = Step(
                id=s["id"], name=_str(s.get("name")), type=_str(s.get("type")), prompt=_str(s.get("prompt")),
                field=s.get("field") if isinstance(s.get("field"), str) else None,
                knowledge_id=kid if isinstance(kid, int) and not isinstance(kid, bool) else None,
                outcome=s.get("outcome") if isinstance(s.get("outcome"), str) else None,
            )
        for p in paths if isinstance(paths, list) else []:
            if (not isinstance(p, dict) or not isinstance(p.get("from"), str)
                    or not isinstance(p.get("to"), str)
                    or p["from"] not in self._steps or p["to"] not in self._steps):
                continue
            self._out.setdefault(p["from"], []).append(
                {"to": p["to"], "label": _str(p.get("label"))})
            self._edges.append((p["from"], p["to"], _str(p.get("label"))))
        used: set[str] = set()
        for sid, st in self._steps.items():
            slug = _slug(st.name) or "step_" + (_slug(sid) or "x")
            base = ("go_to_" + slug)[:48].rstrip("_")
            name, n = base, 1
            while name in used:
                n += 1
                suffix = f"_{n}"
                name = base[: 48 - len(suffix)].rstrip("_") + suffix
            used.add(name)
            self._names[sid] = name

    # -- state -----------------------------------------------------------
    def _enter(self, step: Step) -> None:
        self.current = step
        self.visits[step.id] = self.visits.get(step.id, 0) + 1
        self.path.append(step.name)

    def start(self) -> Step | None:
        starts = [s for s in self._steps.values() if s.type == "start"]
        if not starts:
            return None
        self._enter(starts[0])
        return starts[0]

    def to_state(self) -> dict:
        return {
            "current_step_id": self.current.id if self.current else None,
            "visits": dict(self.visits),
            "transitions": self.transitions,
            "captured": dict(self.captured),
            "path": list(self.path),
        }

    @classmethod
    def from_state(cls, graph, state, max_visits: int = 3, max_transitions: int = 25) -> "WorkflowRun":
        run = cls(graph, max_visits, max_transitions)
        if not isinstance(state, dict):
            run.start()
            return run
        sid = state.get("current_step_id")
        cur = run._steps.get(sid) if isinstance(sid, str) else None
        if cur is None:
            run.start()
            return run

        def count(n) -> int:
            return n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else 0

        run.current = cur
        v = state.get("visits")
        run.visits = {k: count(n) for k, n in v.items() if isinstance(k, str)} if isinstance(v, dict) else {}
        run.transitions = count(state.get("transitions"))
        c = state.get("captured")
        run.captured = dict(c) if isinstance(c, dict) and all(
            isinstance(k, str) and isinstance(x, str) for k, x in c.items()) else {}
        p = state.get("path")
        names = [x for x in p if isinstance(x, str)] if isinstance(p, list) else []
        run.path = (names or [cur.name])[-(max_transitions + 1):]
        return run

    # -- tools -----------------------------------------------------------
    def paths_from_current(self) -> list[PathTool]:
        if self.current is None or self.current.type == "end":
            return []
        takes = self.current.type == "collect"
        tools: dict[str, PathTool] = {}
        for p in self._out.get(self.current.id, []):
            name = self._names[p["to"]]
            if name not in tools:
                tools[name] = PathTool(name, p["label"], p["to"], takes)
        return list(tools.values())

    def all_path_tools(self) -> list[PathTool]:
        """Every path tool of the graph, one per target step, in graph order (registered once per call).

        A tool takes a value when any step leading to it is a collect step; the first path's label
        describes it. Paths out of end steps are ignored, as in paths_from_current.
        """
        tools: dict[str, PathTool] = {}
        for src, to, label in self._edges:
            if self._steps[src].type == "end":
                continue
            name = self._names[to]
            takes = self._steps[src].type == "collect"
            if name not in tools:
                tools[name] = PathTool(name, label, to, takes)
            elif takes and not tools[name].takes_value:
                t = tools[name]
                tools[name] = PathTool(t.name, t.description, t.to, True)
        return list(tools.values())

    def take(self, tool_name: str, value: str | None = None) -> Transition:
        cur = self.current
        if cur is None:
            return Transition(False, "That path isn't available from the start of the call.")
        match = next((p for p in self.paths_from_current() if p.name == tool_name), None)
        if match is None:
            return Transition(False, f"That path isn't available from {cur.name}.")
        val = value.strip() if isinstance(value, str) else ""
        if cur.type == "collect" and not val:
            return Transition(False, "Say what the driver answered in `value`.")
        target = self._steps[match.to]
        if (self.visits.get(target.id, 0) + 1 > self.max_visits
                or self.transitions + 1 > self.max_transitions):
            return Transition(False, CAPPED_MESSAGE, None, True)
        captured = None
        if cur.type == "collect" and cur.field:
            self.captured[cur.field] = val
            captured = (cur.field, val)
        self.transitions += 1
        self._enter(target)
        return Transition(True, f"Now at: {target.name}", target, False, captured)


def path_tool_schema(tool: PathTool) -> dict:
    """OpenAI-style function schema for a workflow path tool (livekit raw_schema)."""
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": {
            "type": "object",
            "properties": {"value": {"type": "string", "description": "What the driver answered"}}
            if tool.takes_value
            else {},
            "required": ["value"] if tool.takes_value else [],
        },
    }
