"""Regular expression search (§728; `ontology` p.130-131; `object-link-types`
p.251).

> "Regular expression (regex) search in the Ontology uses a syntax that is
> similar to typical regular expressions but with some differences" (p.130)

p.130-131 is the whole specification, and this module is it:

* **"Patterns match the full value, not substrings."** `cat` matches `cat`
  and not `concatenate`; `.*cat.*` is how a substring is asked for.
* **"^ and $ anchors are not supported"**, being redundant. Refused with that
  sentence rather than read as literals, since somebody typing `^cat` meant
  an anchor and a literal caret would silently match nothing.
* **The operators**: `.` `?` `+` `*` `{}` `|` `()` `[]` (with ranges, a
  leading `^` negating, and a literal `-` first or escaped), `"…"` for a
  literal phrase, and `\\` escaping one character or naming `\\d \\D \\s \\S
  \\w \\W`. Every other character is itself.
* **"String properties must be indexed for regex search"**, which here is the
  property's *Enable regex queries* render hint (`object-link-types` p.251).
  That check needs the ontology, so it is `object_set_eval`'s; this module
  imports nothing.

**One reading, three dialects.** A pattern is read once into tokens and
written out for Postgres (`~`, an ARE), for OpenSearch (`regexp`, Lucene's
syntax) and for Python (`object_sets.matches`, the reference both stores are
tested against). Writing each store's string by hand from the typed one would
be three parsers of one language, and the first character one of them treated
differently would be a value one store found and the other did not. Lucene's
own optional operators (`#`, `@`, `&`, `<`, `>`, `~`) are not on p.131's list,
so they are written escaped there and match themselves, as everywhere else.

Case matters, as in every one of the three: p.131's own examples are lower
case and never say otherwise.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: Enough for any pattern a person types; a bound on what one filter costs.
MAX_LENGTH = 200

#: p.131's shorthand classes, as plain character sets. The Lucene side cannot
#: be trusted to know the backslash forms, so every dialect is given these.
_CLASSES = {
    "d": ("0-9", False), "D": ("0-9", True),
    "s": (" \t\n\r\f\v", False), "S": (" \t\n\r\f\v", True),
    "w": ("A-Za-z0-9_", False), "W": ("A-Za-z0-9_", True),
}

_OPERATORS = set(".?+*|()")
_LUCENE_RESERVED = set('.?+*|{}[]()"\\#@&<>~')
_QUANTIFIER = re.compile(r"\{(\d{1,4})(,(\d{0,4}))?\}")


@dataclass(frozen=True)
class _Literal:
    char: str


@dataclass(frozen=True)
class _Operator:
    text: str


@dataclass(frozen=True)
class _Set:
    """A bracket expression or a shorthand class: its items as (low, high)
    character pairs - `a-z` is ("a", "z"), `x` is ("x", "x") - and whether it
    is negated."""
    items: tuple[tuple[str, str], ...]
    negated: bool


_Token = _Literal | _Operator | _Set


class RegexError(ValueError):
    """A pattern p.130-131's syntax does not allow."""


def _class_items(spec: str) -> tuple[tuple[str, str], ...]:
    items: list[tuple[str, str]] = []
    i = 0
    while i < len(spec):
        if i + 2 < len(spec) and spec[i + 1] == "-":
            items.append((spec[i], spec[i + 2]))
            i += 3
        else:
            items.append((spec[i], spec[i]))
            i += 1
    return tuple(items)


def _bracket(pattern: str, start: int) -> tuple[_Set, int]:
    """`[…]` from `start` (just past the `[`), and where it ended."""
    i = start
    negated = False
    if i < len(pattern) and pattern[i] == "^":
        negated, i = True, i + 1
    chars: list[str] = []  # literal characters, with ranges marked
    items: list[tuple[str, str]] = []
    first = True
    while True:
        if i >= len(pattern):
            raise RegexError("a [ has no closing ]")
        c = pattern[i]
        if c == "]" and not first:
            break
        if c == "\\":
            if i + 1 >= len(pattern):
                raise RegexError("a \\ ends the pattern with nothing to escape")
            nxt = pattern[i + 1]
            if nxt in _CLASSES:
                spec, inverted = _CLASSES[nxt]
                if inverted:
                    raise RegexError(f"\\{nxt} cannot be used inside [ ]")
                items.extend(_class_items(spec))
            else:
                chars.append(nxt)
                items.append((nxt, nxt))
            i += 2
        elif (c == "-" and not first and i + 1 < len(pattern) and pattern[i + 1] != "]"
              and items and items[-1][0] == items[-1][1]):
            # A range: the previous single character to the next one. A dash
            # first, last or escaped is itself (p.131).
            low = items.pop()[0]
            high = pattern[i + 1]
            if high == "\\":
                if i + 2 >= len(pattern):
                    raise RegexError("a \\ ends the pattern with nothing to escape")
                high = pattern[i + 2]
                i += 1
            if ord(high) < ord(low):
                raise RegexError(f"the range {low}-{high} runs backwards")
            items.append((low, high))
            i += 2
        else:
            items.append((c, c))
            i += 1
        first = False
    if not items:
        raise RegexError("[ ] holds nothing")
    return _Set(tuple(items), negated), i + 1


def _tokens(pattern: str) -> list[_Token]:
    out: list[_Token] = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "\\":
            if i + 1 >= len(pattern):
                raise RegexError("a \\ ends the pattern with nothing to escape")
            nxt = pattern[i + 1]
            if nxt in _CLASSES:
                spec, inverted = _CLASSES[nxt]
                out.append(_Set(_class_items(spec), inverted))
            else:
                out.append(_Literal(nxt))
            i += 2
        elif c == '"':
            end = pattern.find('"', i + 1)
            if end < 0:
                raise RegexError('a " has no closing "')
            # A literal phrase, which repeats or groups as one: "ab"+ is ab
            # one or more times, so it is written as a group.
            out.append(_Operator("("))
            out.extend(_Literal(ch) for ch in pattern[i + 1:end])
            out.append(_Operator(")"))
            i = end + 1
        elif c == "[":
            token, i = _bracket(pattern, i + 1)
            out.append(token)
        elif c == "{":
            found = _QUANTIFIER.match(pattern, i)
            if not found:
                raise RegexError("a { must be {n}, {n,} or {n,m}")
            low, comma, high = found.group(1), found.group(2), found.group(3)
            if high and int(high) < int(low):
                raise RegexError(f"{{{low},{high}}} runs backwards")
            out.append(_Operator(f"{{{int(low)}{',' if comma else ''}{int(high) if high else ''}}}"))
            i = found.end()
        elif c in "^$":
            raise RegexError(
                "^ and $ anchors are not supported: a pattern already matches the "
                "whole value (ontology p.130)")
        elif c in _OPERATORS:
            out.append(_Operator(c))
            i += 1
        else:
            out.append(_Literal(c))
            i += 1
    return out


def _escape_python(char: str) -> str:
    return re.escape(char)


def _escape_lucene(char: str) -> str:
    return "\\" + char if char in _LUCENE_RESERVED else char


def _set_text(token: _Set, escape) -> str:
    body = "".join(
        escape(low) if low == high else f"{escape(low)}-{escape(high)}"
        for low, high in token.items
    )
    return f"[{'^' if token.negated else ''}{body}]"


def _write(tokens: list[_Token], dialect: str) -> str:
    def escape_in_set(char: str) -> str:
        if dialect == "lucene":
            return "\\" + char if char in "\\]-^[\"" else char
        return "\\" + char if char in "\\]-^[" else char

    parts: list[str] = []
    for token in tokens:
        if isinstance(token, _Literal):
            parts.append(_escape_lucene(token.char) if dialect == "lucene"
                         else _escape_python(token.char))
        elif isinstance(token, _Operator):
            # `(` stays a group in all three; the two that capture do not
            # matter, since nothing reads a capture.
            parts.append(token.text)
        else:
            parts.append(_set_text(token, escape_in_set))
    return "".join(parts)


@dataclass(frozen=True)
class Pattern:
    """A pattern p.130-131 allows, as typed and as each store asks it."""
    text: str
    python: str
    postgres: str
    lucene: str

    def matches(self, value: str) -> bool:
        return re.fullmatch(self.python, value) is not None


def parse(raw: object) -> Pattern:
    """A pattern read and checked, or a `RegexError` saying what is wrong."""
    if not isinstance(raw, str) or not raw:
        raise RegexError("a regular expression is non-empty text")
    if len(raw) > MAX_LENGTH:
        raise RegexError(f"a regular expression is at most {MAX_LENGTH} characters")
    tokens = _tokens(raw)
    body = _write(tokens, "python")
    try:
        re.compile(body)
    except re.error as exc:
        # Nothing to repeat, an unbalanced bracket: Python's reading of the
        # same tokens, in its words.
        raise RegexError(f"not a pattern: {exc}") from exc
    return Pattern(
        text=raw,
        python=f"(?:{body})",
        # Anchored at both ends: "Patterns match the full value" (p.130).
        postgres=f"^(?:{_write(tokens, 'postgres')})$",
        # Lucene's regexp is anchored already.
        lucene=_write(tokens, "lucene"),
    )
