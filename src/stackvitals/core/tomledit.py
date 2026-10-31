"""Small, checked edits of `.github/stackvitals.toml` for settings changed in the app: a key's line is replaced where it
is (comments and layout stay), a missing key or table is added, None removes a key so its default applies. The result is
parsed again and must hold exactly the asked values; anything else (a layout this can't edit, a value the parser
refuses) raises EditError, so a file is never rewritten blindly."""
import json
import re
import tomllib
from datetime import date

from stackvitals.core import config, schema

MAPS = ("dates", "map", "teams")
_HEADER = re.compile(r"^\s*\[\[?\s*([^\[\]]+?)\s*\]\]?\s*(#.*)?$")


class EditError(ValueError):
    pass


def _render(value, kind: str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        if kind == "dates":
            return date.fromisoformat(value).isoformat()
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_render(x, "list") for x in value) + "]"
    raise EditError(f"{value!r} can't be written as a setting.")


def _depth(line: str) -> int:
    # Brackets opened minus closed on a line, ignoring quoted strings and comments.
    bare = re.sub(r'"(?:[^"\\]|\\.)*"|\'[^\']*\'', "", line).split("#", 1)[0]
    return bare.count("[") - bare.count("]")


def _tables(lines: list[str]) -> list[tuple[str, int, int]]:
    """(name, header line, end line) for each table, skipping lines inside multi-line values."""
    heads, depth = [], 0
    for i, line in enumerate(lines):
        m = _HEADER.match(line) if depth == 0 else None
        if m:
            heads.append((m[1].replace(" ", ""), i))
            continue
        if depth or re.match(r"^\s*[\w\"'.-]+\s*=", line):
            depth = max(depth + _depth(line), 0)
    return [(name, start, heads[k + 1][1] if k + 1 < len(heads) else len(lines)) for k, (name, start) in enumerate(heads)]


def _comment(line: str) -> str:
    # The line's trailing comment (outside quoted strings), kept when its value is replaced.
    bare = re.sub(r'"(?:[^"\\]|\\.)*"|\'[^\']*\'', lambda m: " " * len(m[0]), line)
    at = bare.find("#")
    return line[at:].rstrip() if at >= 0 else ""


def _key_span(lines: list[str], start: int, end: int, leaf: str) -> tuple[int, int] | None:
    pattern = re.compile(rf"^\s*(?:{re.escape(leaf)}|\"{re.escape(leaf)}\"|'{re.escape(leaf)}')\s*=")
    for i in range(start, end):
        if pattern.match(lines[i]):
            j, depth = i, _depth(lines[i])
            while depth > 0 and j + 1 < end:
                j += 1
                depth += _depth(lines[j])
            return i, j + 1
    return None


def _set(lines: list[str], table: str, body: list[str] | None, leaf: str | None) -> list[str]:
    """Put `body` (the new lines) for `leaf` in `table` (leaf None: the whole table's body); body None removes it."""
    found = next(((s, e) for name, s, e in _tables(lines) if name == table), None)
    if found is None:
        if body is None:
            return lines
        gap = [""] if lines and lines[-1].strip() else []
        return lines + gap + [f"[{table}]", *body]
    start, end = found
    if leaf is None:
        tail = end
        while tail > start + 1 and not lines[tail - 1].strip():
            tail -= 1
        return lines[:start + 1] + (body or []) + lines[tail:end] + lines[end:]
    span = _key_span(lines, start + 1, end, leaf)
    if span:
        note = _comment(lines[span[0]]) if body and len(body) == 1 and span[1] - span[0] == 1 else ""
        return lines[:span[0]] + ([f"{body[0]}  {note}"] if note else body or []) + lines[span[1]:]
    if body is None:
        return lines
    last = end
    while last > start + 1 and not lines[last - 1].strip():
        last -= 1
    return lines[:last] + body + lines[last:]


def _expected(setting: schema.Setting, value):
    if value is None:
        return schema.default(setting.key)
    if setting.kind == "int":
        return int(value)
    if setting.kind in ("number", "share", "hours"):
        return float(value)
    return value


def _get(cfg: dict, key: str):
    node = cfg
    for part in key.split("."):
        node = node[part]
    return node


def apply(text: str | None, changes: dict) -> str:
    lines = (text or "").replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    for key, value in changes.items():
        setting = schema.BY_KEY.get(key)
        if setting is None:
            raise EditError(f"{key} is not a setting StackVitals knows.")
        try:
            if setting.kind in MAPS:
                if value is not None and not isinstance(value, dict):
                    raise EditError(f"{key} takes a table of entries.")
                body = None if value is None else [f"{json.dumps(str(k), ensure_ascii=False)} = {_render(v, setting.kind)}"
                                                   for k, v in value.items()]
                lines = _set(lines, key, body, None)
            else:
                table, leaf = key.rsplit(".", 1)
                lines = _set(lines, table, None if value is None else [f"{leaf} = {_render(value, setting.kind)}"], leaf)
        except ValueError as exc:
            raise EditError(f"{key}: {exc}") from None
    out = "\n".join(lines).strip("\n") + "\n"
    try:
        tomllib.loads(out)
    except tomllib.TOMLDecodeError as exc:
        raise EditError(f"this file's layout can't be edited automatically ({exc}); change it by hand.") from None
    cfg, notes = config.parse(out)
    for key, value in changes.items():
        try:
            want = _expected(schema.BY_KEY[key], value)
        except (TypeError, ValueError):
            raise EditError(f"{key} can't be set to {value!r}: it needs a {schema.BY_KEY[key].kind}.") from None
        if _get(cfg, key) != want:
            why = next((n for n in notes if key.rsplit(".", 1)[-1] in n), "the file's layout kept the old value")
            raise EditError(f"{key} can't be set to {value!r}: {why}")
    return out
