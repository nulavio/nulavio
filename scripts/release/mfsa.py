#!/usr/bin/env python3
"""Read Mozilla's security advisories (MFSA) and rate how urgent a Firefox release is.

Mozilla publishes one YAML file per advisory in
github.com/mozilla/foundation-security-advisories (announce/<year>/mfsa<year>-<n>.yml).
This module reads only the small part of YAML those files use (stdlib only, no
YAML library) and fails closed: a file it cannot read raises MfsaFormatError,
and the caller then treats the release as urgent.

    python3 -I scripts/release/mfsa.py FILE...    # what was understood, as JSON

Urgency (docs/architecture/update-policy.md): "urgent" (24-hour target) when the
highest impact is critical or high, a CVE is a sandbox escape, exploitation in
the wild is reported or unclear, exploit code is public, the advisory cannot be
read, or no advisory has appeared yet. "standard" (72 hours) otherwise. The
72-hour deadline applies to every release either way.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import json
import re
import sys
from pathlib import Path

IMPACTS = ("low", "moderate", "high", "critical")
IMPACT_ALIASES = {"medium": "moderate"}  # used in a few 2026 advisories (mfsa2026-63, -86, -94)
NAME_RE = re.compile(r"^mfsa(\d{4})-(\d{1,4})\.yml$")
ID_RE = re.compile(r"^mfsa\d{4}-\d{1,4}$")
CVE_RE = re.compile(r"^CVE-\d{4}-\d{4,}$")
KEY_RE = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.-]*):(?: +(.*))?$")
MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
ANNOUNCED_RE = re.compile(r"^([A-Za-z]+) +(\d{1,2})(?:st|nd|rd|th)?, *(\d{4})$")
ADVISORY_URL = "https://www.mozilla.org/security/advisories/{id}/"

# Exploitation in the wild, judged sentence by sentence. Mozilla's wording varies
# and is sometimes negated ("we are not aware of any attacks in the wild"), so a
# plain search for "in the wild" would be wrong both ways.
ITW_POSITIVE = re.compile(
    r"exploited in (?:other products in )?the wild|being exploited|attacks? in the wild|targeted attacks"
    r"|in-the-wild exploit|exploited in-the-wild",
    re.I,
)
ITW_NEGATIVE = re.compile(
    r"not aware of any|\bnot (?:been |being )?(?:exploited|abused)|\bno (?:known|reports? of)"
    r"|\bnever (?:been )?(?:exploited|abused)",
    re.I,
)
ITW_MENTION = re.compile(r"in[ -]the[ -]wild", re.I)
PUBLIC_EXPLOIT = re.compile(r"exploit code[^.]*\bpublic\b|\bpublic(?:ly)? (?:available )?exploit", re.I)
SANDBOX_ESCAPE = re.compile(r"\bsandbox escape", re.I)
PLATFORM_NOTE = re.compile(r"only affects Firefox (on|for) (\w+)", re.I)
OTHER_PRODUCT = re.compile(r"\b(?:for (?:Android|iOS)|Focus|Klar|Thunderbird)\b")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|<br\s*/?>", re.I)
NO_ADVISORY_GRACE = _dt.timedelta(hours=6)


class MfsaFormatError(ValueError):
    """The advisory does not have the shape this reader understands (fail closed)."""


@dataclasses.dataclass(frozen=True)
class Cve:
    id: str
    title: str
    impact: str
    text: str  # title, description and bug notes: what the detectors read


@dataclasses.dataclass(frozen=True)
class Advisory:
    id: str
    announced: _dt.date
    impact: str
    fixed_in: tuple[str, ...]
    title: str
    description: str
    cves: tuple[Cve, ...]

    @property
    def url(self) -> str:
        return ADVISORY_URL.format(id=self.id)

    def texts(self) -> list[str]:
        return [self.title, self.description, *(cve.text for cve in self.cves)]


@dataclasses.dataclass(frozen=True)
class Classification:
    urgency: str  # "urgent" (24-hour target) or "standard" (72 hours)
    advisory_status: str  # found, none-yet, none, unreadable, unavailable
    reasons: tuple[str, ...]
    itw: str  # yes, no, unclear, unknown
    public_exploit: bool
    sandbox_escape: bool
    emergency: bool  # exploitation in the wild reported
    max_impact: str | None
    platform_notes: tuple[str, ...]


# --- a reader for the YAML subset the advisories use -------------------------


class _Lines:
    def __init__(self, text: str, name: str):
        self.lines = text.splitlines()
        self.i = 0
        self.name = name

    def error(self, message: str, index: int | None = None) -> MfsaFormatError:
        line = (self.i if index is None else index) + 1
        return MfsaFormatError(f"{self.name}:{line}: {message}")

    def next_content(self) -> int | None:
        """Index of the next line that is neither blank nor a comment."""
        while self.i < len(self.lines):
            raw = self.lines[self.i]
            stripped = raw.strip()
            if stripped and "\t" in raw[: len(raw) - len(raw.lstrip())]:
                raise self.error("tab in indentation")
            if stripped and not stripped.startswith("#") and not (self.i == 0 and stripped == "---"):
                return self.i
            self.i += 1
        return None


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_item(stripped: str) -> bool:
    return stripped == "-" or stripped.startswith("- ")


def _strip_comment(text: str) -> str:
    if text.startswith(("'", '"')):
        return text
    match = re.search(r"\s#", text)
    return text[: match.start()].rstrip() if match else text.rstrip()


def _scalar(text: str, reader: _Lines) -> str:
    text = text.strip()
    if text.startswith("'"):
        out, i = [], 1
        while i < len(text):
            if text[i] == "'":
                if text[i + 1 : i + 2] == "'":
                    out.append("'")
                    i += 2
                    continue
                if _strip_comment(text[i + 1 :]).strip():
                    raise reader.error("text after a quoted value")
                return "".join(out)
            out.append(text[i])
            i += 1
        raise reader.error("unterminated quoted value")
    if text.startswith('"'):
        escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/", "'": "'"}
        out, i = [], 1
        while i < len(text):
            char = text[i]
            if char == "\\":
                nxt = text[i + 1 : i + 2]
                if nxt == "u" and re.fullmatch(r"[0-9A-Fa-f]{4}", text[i + 2 : i + 6]):
                    out.append(chr(int(text[i + 2 : i + 6], 16)))
                    i += 6
                    continue
                if nxt not in escapes:
                    raise reader.error("unsupported escape in a quoted value")
                out.append(escapes[nxt])
                i += 2
                continue
            if char == '"':
                if _strip_comment(text[i + 1 :]).strip():
                    raise reader.error("text after a quoted value")
                return "".join(out)
            out.append(char)
            i += 1
        raise reader.error("unterminated quoted value")
    if text[:1] in ("{", "[", "&", "*", "!", "|", ">", "%", "@", "`"):
        raise reader.error(f"unsupported YAML construct {text[:1]!r}")
    return _strip_comment(text)


def _block_scalar(reader: _Lines, parent: int, style: str) -> str:
    if style[1:] not in ("", "-", "+"):
        raise reader.error("unsupported block scalar indicator")
    collected: list[str] = []
    block_indent = None
    while reader.i < len(reader.lines):
        raw = reader.lines[reader.i]
        if not raw.strip():
            collected.append("")
            reader.i += 1
            continue
        indent = _indent(raw)
        if block_indent is None:
            if indent <= parent:
                break
            block_indent = indent
        if indent < block_indent:
            break
        collected.append(raw[block_indent:])
        reader.i += 1
    trailing = 0
    while collected and not collected[-1]:
        collected.pop()
        trailing += 1
    if style[0] == "|":
        body = "\n".join(collected)
    else:
        body, previous_blank = "", False
        for line in collected:
            if not line:
                body += "\n"
                previous_blank = True
                continue
            body += line if (not body or previous_blank) else " " + line
            previous_blank = False
    if style.endswith("-"):
        return body
    if style.endswith("+"):
        return body + "\n" * (trailing + 1)
    return body + "\n" if body else ""


def _continuation(reader: _Lines, indent: int, first: str) -> str:
    """Join a plain or quoted value that continues on more indented lines."""
    parts = [first]
    while True:
        index = reader.next_content()
        if index is None:
            break
        raw = reader.lines[index]
        if _indent(raw) <= indent or KEY_RE.match(raw.strip()) or _is_item(raw.strip()):
            break
        parts.append(raw.strip())
        reader.i = index + 1
    return " ".join(parts)


def _node(reader: _Lines, indent: int):
    index = reader.next_content()
    if index is None:
        return None
    raw = reader.lines[index]
    if _is_item(raw.strip()):
        return _sequence(reader, _indent(raw))
    return _mapping(reader, _indent(raw))


def _mapping(reader: _Lines, indent: int) -> dict:
    result: dict = {}
    while True:
        index = reader.next_content()
        if index is None:
            return result
        raw = reader.lines[index]
        here = _indent(raw)
        if here < indent:
            return result
        if here > indent:
            raise reader.error("unexpected indentation", index)
        match = KEY_RE.match(raw.strip())
        if not match:
            if _is_item(raw.strip()):
                return result
            raise reader.error("expected 'key: value'", index)
        key, rest = match.group(1), _strip_comment(match.group(2) or "")
        if key in result:
            raise reader.error(f"duplicate key {key!r}", index)
        reader.i = index + 1
        if rest[:1] in ("|", ">"):
            result[key] = _block_scalar(reader, indent, rest)
        elif rest:
            result[key] = _scalar(_continuation(reader, indent, rest), reader)
        else:
            following = reader.next_content()
            if following is None:
                result[key] = None
                continue
            nested = reader.lines[following]
            if _indent(nested) > indent or (_indent(nested) == indent and _is_item(nested.strip())):
                result[key] = _node(reader, indent)
            else:
                result[key] = None


def _sequence(reader: _Lines, indent: int) -> list:
    items: list = []
    while True:
        index = reader.next_content()
        if index is None:
            return items
        raw = reader.lines[index]
        here, stripped = _indent(raw), raw.strip()
        if here < indent or (here == indent and not _is_item(stripped)):
            return items
        if here > indent:
            raise reader.error("unexpected indentation", index)
        body = stripped[2:].strip() if stripped != "-" else ""
        if KEY_RE.match(body):
            # "- key: value" starts a mapping whose keys line up two columns in.
            reader.lines[index] = " " * (indent + 2) + body
            reader.i = index
            items.append(_mapping(reader, indent + 2))
        elif body:
            reader.i = index + 1
            items.append(_scalar(_continuation(reader, indent, body), reader))
        else:
            reader.i = index + 1
            items.append(_node(reader, indent + 1))


def load(text: str, name: str = "<advisory>") -> dict:
    """Parse the YAML subset into dicts, lists and strings (no type guessing)."""
    reader = _Lines(text, name)
    data = _node(reader, 0)
    if reader.next_content() is not None:
        raise reader.error("content after the document")
    if not isinstance(data, dict):
        raise MfsaFormatError(f"{name}: the advisory is not a mapping")
    return data


# --- advisories --------------------------------------------------------------


def _month(word: str) -> int | None:
    """'October', 'Oct' and 'Sept' all name a month (abbreviations appear in 2024 advisories)."""
    word = word.lower()
    for number, month in enumerate(MONTHS, 1):
        if word == month or (len(word) >= 3 and month.startswith(word)):
            return number
    return None


def parse_announced(value: str, name: str) -> _dt.date:
    match = ANNOUNCED_RE.match(value.strip())
    month = _month(match.group(1)) if match else None
    if month is None:
        raise MfsaFormatError(f"{name}: unreadable 'announced' date {value!r}")
    try:
        return _dt.date(int(match.group(3)), month, int(match.group(2)))
    except ValueError as exc:
        raise MfsaFormatError(f"{name}: unreadable 'announced' date {value!r}") from exc


def _text(value, field: str, name: str, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise MfsaFormatError(f"{name}: '{field}' is missing or not text")
    return value


def _impact(value, where: str) -> str:
    impact = value.strip().lower() if isinstance(value, str) else None
    impact = IMPACT_ALIASES.get(impact, impact)
    if impact not in IMPACTS:
        raise MfsaFormatError(f"{where}: impact {value!r} is not one of {', '.join(IMPACTS)}")
    return impact


def parse(text: str, name: str) -> Advisory:
    """One advisory file. `name` is its file name (mfsa2026-111.yml)."""
    match = NAME_RE.match(name)
    if not match:
        raise MfsaFormatError(f"{name}: not an advisory file name")
    data = load(text, name)
    fixed_in = data.get("fixed_in")
    if not isinstance(fixed_in, list) or not fixed_in or not all(isinstance(item, str) for item in fixed_in):
        raise MfsaFormatError(f"{name}: 'fixed_in' must be a list of products")
    entries = data.get("advisories")
    if not isinstance(entries, dict) or not entries:
        raise MfsaFormatError(f"{name}: 'advisories' must map CVE ids to entries")
    cves = []
    for cve_id, entry in entries.items():
        if not CVE_RE.match(cve_id) or not isinstance(entry, dict):
            raise MfsaFormatError(f"{name}: unexpected entry {cve_id!r}")
        title = _text(entry.get("title"), f"{cve_id}.title", name)
        description = _text(entry.get("description"), f"{cve_id}.description", name, required=False)
        notes = []
        for bug in entry.get("bugs") or []:
            if isinstance(bug, dict) and isinstance(bug.get("desc"), str):
                notes.append(bug["desc"])
        cves.append(
            Cve(cve_id, title.strip(), _impact(entry.get("impact"), f"{name}: {cve_id}"), " ".join([title, description, *notes]))
        )
    return Advisory(
        id=name.removesuffix(".yml"),
        announced=parse_announced(_text(data.get("announced"), "announced", name), name),
        impact=_impact(data.get("impact"), name),
        fixed_in=tuple(item.strip() for item in fixed_in),
        title=_text(data.get("title"), "title", name).strip(),
        description=_text(data.get("description"), "description", name, required=False),
        cves=tuple(cves),
    )


def sort_key(name: str) -> tuple[int, int]:
    """Numeric order of advisory file names (mfsa2026-99 comes before mfsa2026-100)."""
    match = NAME_RE.match(name)
    if not match:
        raise ValueError(f"not an advisory file name: {name}")
    return int(match.group(1)), int(match.group(2))


def _version_forms(version: str) -> tuple[str, ...]:
    """'158.0' is announced as 'Firefox 158'; dot releases keep their full number."""
    major, _, rest = version.partition(".")
    return (version, major) if rest == "0" else (version,)


def mentions_desktop(text: str, version: str) -> bool:
    """Does `text` name desktop Firefox `version` ("Firefox 158.0.1", or "Firefox 158" for 158.0)?"""
    forms = "|".join(re.escape(form) for form in _version_forms(version))
    return re.search(rf"\bFirefox (?:{forms})(?!\.?\d)", text) is not None


def applies_to(advisory: Advisory, version: str) -> bool:
    """Is this the advisory of desktop Firefox `version`?

    `fixed_in` must list "Firefox <version>" exactly. Android shares that wording
    ("Firefox 158.0.2" in mfsa2026-116, a Firefox for Android release), so a title
    that names another product and not desktop Firefox <version> does not count.
    """
    if not any(product in {f"Firefox {form}" for form in _version_forms(version)} for product in advisory.fixed_in):
        return False
    return mentions_desktop(advisory.title, version) or not OTHER_PRODUCT.search(advisory.title)


def _sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text)
    return [part.strip() for part in SENTENCE_SPLIT.split(flat) if part.strip()]


def itw(text: str) -> str:
    """'yes' when a sentence reports exploitation in the wild, 'unclear' when one mentions it ambiguously, else 'no'."""
    verdicts = set()
    for sentence in _sentences(text):
        if ITW_NEGATIVE.search(sentence) and (ITW_POSITIVE.search(sentence) or ITW_MENTION.search(sentence)):
            verdicts.add("no")
        elif ITW_POSITIVE.search(sentence) and not ITW_NEGATIVE.search(sentence):
            verdicts.add("yes")
        elif ITW_MENTION.search(sentence):
            verdicts.add("unclear")
    if "yes" in verdicts:
        return "yes"
    return "unclear" if "unclear" in verdicts else "no"


def public_exploit(text: str) -> bool:
    return PUBLIC_EXPLOIT.search(re.sub(r"\s+", " ", text)) is not None


def sandbox_escape(text: str) -> bool:
    return SANDBOX_ESCAPE.search(text) is not None


def platform_notes(text: str) -> list[str]:
    """Informational only: never lowers the urgency."""
    return sorted(
        {f"only affects Firefox {m.group(1).lower()} {m.group(2)}" for m in PLATFORM_NOTE.finditer(re.sub(r"\s+", " ", text))}
    )


def classify(
    advisories: list[Advisory],
    *,
    released_by: _dt.datetime | None,
    now: _dt.datetime,
    error: str | None = None,
    unavailable: bool = False,
) -> Classification:
    """Urgency of one Firefox release from its advisories.

    `released_by` is the latest time Mozilla can have published the release
    (None while it is only staged). Without an advisory the release stays
    urgent until 6 hours after that, then it is standard; an advisory that
    appears later raises it again.
    """
    if error is not None or unavailable:
        status = "unavailable" if unavailable else "unreadable"
        why = "advisories could not be fetched" if unavailable else "the advisory could not be read"
        return Classification(
            "urgent", status, (f"{why}: treated as urgent (fail closed)",), "unknown", False, False, False, None, ()
        )
    if not advisories:
        if released_by is None or now - released_by < NO_ADVISORY_GRACE:
            reason = "no advisory yet: treated as urgent until 6 h after Mozilla's release (re-checked each run)"
            return Classification("urgent", "none-yet", (reason,), "unknown", False, False, False, None, ())
        return Classification(
            "standard", "none", ("no advisory 6 h after Mozilla's release",), "no", False, False, False, None, ()
        )
    texts = [text for advisory in advisories for text in advisory.texts()]
    corpus = "\n".join(texts)
    impacts = [advisory.impact for advisory in advisories] + [cve.impact for advisory in advisories for cve in advisory.cves]
    worst = max(impacts, key=IMPACTS.index)
    exploited = itw("\n".join(f"{text}." for text in texts))
    escape = any(sandbox_escape(cve.text) for advisory in advisories for cve in advisory.cves)
    public = public_exploit(corpus)
    reasons = []
    if worst in ("critical", "high"):
        reasons.append(f"impact {worst}")
    if escape:
        reasons.append("sandbox escape")
    if exploited == "yes":
        reasons.append("exploited in the wild (reported by Mozilla)")
    elif exploited == "unclear":
        reasons.append("exploitation in the wild mentioned, wording unclear")
    if public:
        reasons.append("exploit code is public")
    notes = tuple(platform_notes(corpus))
    if reasons:
        return Classification("urgent", "found", tuple(reasons), exploited, public, escape, exploited == "yes", worst, notes)
    return Classification("standard", "found", (f"impact {worst} only",), exploited, public, escape, False, worst, notes)


def summary(advisory: Advisory) -> dict:
    return {"id": advisory.id, "impact": advisory.impact, "title": advisory.title, "url": advisory.url}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args(argv)
    status = 0
    for path in args.files:
        try:
            advisory = parse(path.read_text(encoding="utf-8"), path.name)
        except (OSError, UnicodeDecodeError, MfsaFormatError) as exc:
            print(json.dumps({"file": str(path), "error": str(exc)}))
            status = 1
            continue
        verdict = classify([advisory], released_by=None, now=_dt.datetime.now(_dt.UTC))
        print(json.dumps({**summary(advisory), "fixed_in": advisory.fixed_in, **dataclasses.asdict(verdict)}, default=str))
    return status


if __name__ == "__main__":
    sys.exit(main())
