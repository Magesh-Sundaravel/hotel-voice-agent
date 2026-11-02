"""Deterministic scoring of one agent turn against its expectations."""

import json
import re

from evals.schema import ExpectedToolCall, TurnExpect
from src.agent.llm import ToolCall

_MARKDOWN = re.compile(r"[*#`_\[\]]|(^|\s)-\s")
_MAX_SENTENCES = 2

# Words that mark a language. Words shared by both ("a", "in") are left out.
_STOPWORDS = {
    "it": {
        "abbiamo",
        "e",
        "è",
        "del",
        "della",
        "ha",
        "sono",
        "ecco",
        "prezzi",
        "ci",
        "camere",
        "camera",
        "libere",
        "libera",
        "domani",
        "notte",
        "dalla",
        "alla",
        "quale",
        "di",
        "le",
        "la",
        "il",
        "un",
        "una",
        "che",
        "con",
        "non",
        "posso",
        "puo",
        "può",
        "prezzo",
        "sì",
        "si",
        "buongiorno",
        "buonasera",
        "disponibili",
        "disponibilita",
        "disponibilità",
        "tipologia",
        "interessa",
        "vuole",
        "vorrebbe",
        "dei",
        "delle",
        "gentile",
        "siamo",
        "avete",
        "preferisce",
        "preferite",
    },
    "en": {
        "the",
        "we",
        "you",
        "for",
        "and",
        "is",
        "are",
        "have",
        "would",
        "like",
        "which",
        "room",
        "rooms",
        "your",
        "to",
        "of",
        "any",
        "what",
        "please",
        "may",
        "an",
        "free",
        "available",
        "night",
        "type",
        "with",
        "our",
        "can",
        "do",
    },
}


def _reply_rule_failures(reply: str) -> list[str]:
    """Check the voice rules that apply to every reply."""
    failures: list[str] = []
    if _MARKDOWN.search(reply):
        failures.append("reply contains markdown")
    if re.search(r"\d", reply):
        failures.append("reply contains a digit (say numbers and dates in words)")
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", reply.strip()) if s]
    if len(sentences) > _MAX_SENTENCES:
        failures.append(f"reply has {len(sentences)} sentences (max {_MAX_SENTENCES})")
    return failures


def _detect_language(text: str) -> str | None:
    """Guess "it" or "en" from stopword counts, or None when there is no signal."""
    words = re.findall(r"[\w']+", text.lower())
    counts = {
        lang: sum(w in vocab for w in words) for lang, vocab in _STOPWORDS.items()
    }
    if counts["it"] == counts["en"]:
        return None
    return "it" if counts["it"] > counts["en"] else "en"


def _matches(expected: ExpectedToolCall, made: ToolCall) -> bool:
    """True if the call has the expected name and every listed arg matches."""
    if made.name != expected.name:
        return False
    try:
        args = json.loads(made.arguments)
    except json.JSONDecodeError:
        return False
    return all(str(args.get(key)) == str(value) for key, value in expected.args.items())


def score_turn(
    expect: TurnExpect, language: str, calls: list[ToolCall], reply: str
) -> list[str]:
    """Check one turn and return failure messages (empty means it passed).

    Args:
        expect: What the case expects for this turn.
        language: Language the reply must be in, "it" or "en".
        calls: Tool calls the agent made during the turn, in order.
        reply: The spoken reply.

    Returns:
        A list of human-readable failures.
    """
    failures: list[str] = []
    remaining = iter(calls)
    for expected in expect.tool_calls:
        if not any(_matches(expected, made) for made in remaining):
            failures.append(
                f"expected tool call {expected.name} {expected.args} was not made"
            )
    if expect.must_not_call_tools and calls:
        failures.append(f"expected no tool calls but made: {[c.name for c in calls]}")
    if not reply.strip():
        failures.append("reply is empty")
    failures.extend(_reply_rule_failures(reply))
    detected = _detect_language(reply)
    if detected is not None and detected != language:
        failures.append(f"reply language looks {detected}, expected {language}")
    if expect.exclusive:
        made_names = [c.name for c in calls]
        if made_names != [e.name for e in expect.tool_calls]:
            failures.append(f"exclusive turn made unexpected tool calls: {made_names}")
    return failures
