"""Best-effort parsing of a JSON document that is still being generated."""

import json


def _scan(text: str) -> tuple[list[str], bool, bool, list[tuple[int, str]]]:
    """Return (open brackets, inside a string, dangling backslash, structural cut points outside strings)."""
    stack: list[str] = []
    cuts: list[tuple[int, str]] = []
    in_str = esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
            cuts.append((i, ch))
        elif ch in "}]":
            if stack:
                stack.pop()
        elif ch == ",":
            cuts.append((i, ch))
    return stack, in_str, esc, cuts


def _close(prefix: str) -> str:
    stack, in_str, esc, _ = _scan(prefix)
    if in_str:
        prefix = prefix[:-1] if esc else prefix
        prefix += '"'
    return prefix + "".join("}" if b == "{" else "]" for b in reversed(stack))


def _prune(value):
    """Drop objects that were only just opened (still empty) from arrays."""
    if isinstance(value, dict):
        return {k: _prune(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_prune(v) for v in value if v != {}]
    return value


def parse_partial(text: str) -> dict | None:
    """Parse as much of `text` as is complete. A string cut mid-way is kept as far as it got;
    a half-written key or number is dropped. Returns None if nothing usable exists yet."""
    text = text.strip()
    if not text.startswith("{"):
        return None
    candidates = [text]
    _, _, _, cuts = _scan(text)
    for pos, kind in reversed(cuts):
        candidates.append(text[: pos + 1] if kind in "{[" else text[:pos])
    for i, candidate in enumerate(candidates):
        try:
            value = json.loads(_close(candidate))
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            return None
        return value if i == 0 and _close(text) == text else _prune(value)
    return None
