"""Natural-language task capture.

Turns an utterance like "I need to finish the homepage by tomorrow, it's urgent"
into structured fields {title, reason, priority, deadline}. Uses the LLM when a
real chat provider is configured; falls back to a heuristic parser (works
offline, no API cost) so voice capture demos before a key is set.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.services.llm import LLMClient

# Leading fillers to strip when deriving a title from speech.
_FILLERS = re.compile(
    r"^\s*(please\s+|can you\s+|could you\s+|i\s+(need|have|want|'?d like)\s+to\s+"
    r"|remind me to\s+|note to self[,:]?\s+|add (a |the )?task(\s+(to|for|:))?\s*"
    r"|create (a |the )?task(\s+(to|for|:))?\s*|new task[,:]?\s*)",
    re.IGNORECASE,
)

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

_PRIORITY_WORDS = [
    (1, re.compile(r"\b(urgent|asap|critical|immediately|right now|top priority)\b", re.I)),
    (2, re.compile(r"\b(important|high priority|high|soon)\b", re.I)),
    (4, re.compile(r"\b(low priority|whenever|someday|sometime|no rush|eventually)\b", re.I)),
]


def _next_weekday(now: datetime, target_idx: int) -> datetime:
    days = (target_idx - now.weekday()) % 7
    days = days or 7  # "on Monday" said on Monday means next Monday
    return (now + timedelta(days=days)).replace(hour=17, minute=0, second=0, microsecond=0)


def parse_deadline(text: str, now: datetime) -> datetime | None:
    t = text.lower()
    eod = lambda d: d.replace(hour=17, minute=0, second=0, microsecond=0)
    if re.search(r"\b(today|tonight|end of day|eod)\b", t):
        return eod(now)
    if re.search(r"\bday after tomorrow\b", t):
        return eod(now + timedelta(days=2))
    if re.search(r"\btomorrow\b", t):
        return eod(now + timedelta(days=1))
    if re.search(r"\bnext week\b", t):
        return eod(now + timedelta(days=7))
    m = re.search(r"\bin (\d+) (day|days|week|weeks)\b", t)
    if m:
        n = int(m.group(1)) * (7 if "week" in m.group(2) else 1)
        return eod(now + timedelta(days=n))
    for i, wd in enumerate(_WEEKDAYS):
        if re.search(rf"\b(by |on |this |next )?{wd}\b", t):
            return _next_weekday(now, i)
    return None


def parse_priority(text: str) -> int:
    for prio, pat in _PRIORITY_WORDS:
        if pat.search(text):
            return prio
    return 3


def clean_title(text: str) -> str:
    title = _FILLERS.sub("", text).strip()
    # Drop trailing time / priority phrases so the title stays tight.
    title = re.sub(
        r"\b(by |on )?(today|tonight|tomorrow|day after tomorrow|next week|"
        r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        "", title, flags=re.I,
    )
    title = re.sub(r"\bin \d+ (day|days|week|weeks)\b", "", title, flags=re.I)
    title = re.sub(r"\b(it'?s |it is |because it'?s )?(urgent|asap|critical|"
                   r"important|high priority|low priority|no rush)\b", "", title, flags=re.I)
    title = re.sub(r"[,\s]+$", "", title).strip(" ,.")
    return (title[:1].upper() + title[1:]) if title else ""


def _heuristic(utterance: str, now: datetime) -> dict:
    return {
        "title": clean_title(utterance),
        "reason": None,
        "priority": parse_priority(utterance),
        "deadline": parse_deadline(utterance, now),
    }


async def extract_fields(llm: LLMClient, utterance: str, now: datetime) -> dict:
    """Extract {title, reason, priority, deadline} from a fresh utterance.

    Uses the LLM for robust parsing when available; otherwise heuristics. Any
    LLM/parse failure falls back to heuristics so capture never hard-fails."""
    if settings.resolved_provider == "stub":
        return _heuristic(utterance, now)
    try:
        system = (
            "Extract a task from the user's message. Return ONLY compact JSON with "
            "keys: title (string), reason (string or null — the WHY, only if stated), "
            "priority (integer 1=critical..4=low, default 3), deadline (ISO 8601 "
            "datetime or null). Resolve relative dates against the given 'now'. No prose."
        )
        user = f"now={now.isoformat()}\nmessage: {utterance}"
        raw = await llm.complete(system, user, reasoning=False)
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(raw)
        deadline = None
        if data.get("deadline"):
            try:
                deadline = datetime.fromisoformat(str(data["deadline"]).replace("Z", "+00:00"))
            except ValueError:
                deadline = None
        title = (data.get("title") or "").strip() or clean_title(utterance)
        prio = data.get("priority")
        prio = prio if isinstance(prio, int) and 1 <= prio <= 4 else parse_priority(utterance)
        return {"title": title, "reason": data.get("reason") or None,
                "priority": prio, "deadline": deadline}
    except Exception:
        return _heuristic(utterance, now)
