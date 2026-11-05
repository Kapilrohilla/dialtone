"""Script tokens: ``[[expr:name(:seconds)]]`` expressions and ``{{lead.field}}`` variables."""
import re
from dataclasses import dataclass

BUILTIN_EXPRESSIONS: dict[str, str] = {
    "happy": "say this warmly and cheerfully",
    "laugh": "say this with a light, warm laugh",
    "sad": "say this gently, with sympathy",
    "fear": "say this with a careful, concerned tone",
    "angry": "say this firmly but calmly, never rude",
    "whisper": "say this softly, as if sharing something personal",
    "pause": "pause for about {seconds} seconds before this",
    "excited": "say this with energy and enthusiasm",
}

_TOKEN_RE = re.compile(
    r"\[\[expr:([a-z_]+)(?::(\d+(?:\.\d+)?))?\]\]|\{\{\s*(lead\.[a-z_]+)\s*\}\}"
)


@dataclass(frozen=True)
class TextToken:
    text: str


@dataclass(frozen=True)
class ExprToken:
    name: str
    seconds: float | None = None


@dataclass(frozen=True)
class VarToken:
    path: str


Token = TextToken | ExprToken | VarToken


def parse(body: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    for m in _TOKEN_RE.finditer(body):
        if m.start() > pos:
            tokens.append(TextToken(body[pos:m.start()]))
        if m.group(1) is not None:
            secs = float(m.group(2)) if m.group(2) is not None else None
            tokens.append(ExprToken(m.group(1), secs))
        else:
            tokens.append(VarToken(m.group(3)))
        pos = m.end()
    if pos < len(body):
        tokens.append(TextToken(body[pos:]))
    return tokens


def unknown_expressions(body: str, custom: dict[str, str]) -> list[str]:
    out: list[str] = []
    for t in parse(body):
        if isinstance(t, ExprToken) and t.name not in BUILTIN_EXPRESSIONS \
                and t.name not in custom and t.name not in out:
            out.append(t.name)
    return out


def _hint(t: ExprToken, custom: dict[str, str]) -> str | None:
    if t.name in BUILTIN_EXPRESSIONS:
        seconds = 1.0 if t.seconds is None else t.seconds
        return BUILTIN_EXPRESSIONS[t.name].format(seconds=f"{seconds:g}")
    return custom.get(t.name)


def render_hints(body: str, custom: dict[str, str]) -> str:
    parts: list[str] = []
    for t in parse(body):
        if isinstance(t, TextToken):
            parts.append(t.text)
        elif isinstance(t, VarToken):
            parts.append("{{" + t.path + "}}")
        else:
            hint = _hint(t, custom)
            if hint is not None:
                parts.append(f"({hint})")
    return "".join(parts)


def variables(body: str) -> list[str]:
    out: list[str] = []
    for t in parse(body):
        if isinstance(t, VarToken) and t.path not in out:
            out.append(t.path)
    return out
