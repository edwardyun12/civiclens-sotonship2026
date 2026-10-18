"""Lightweight routing for requests that do not need document retrieval."""

from __future__ import annotations

import re


GREETING_PATTERN = re.compile(
    r"^(?:hello|hi|hey|good morning|good afternoon|good evening)[!.?\s]*$",
    re.IGNORECASE,
)
CAPABILITIES_PATTERN = re.compile(
    r"^(?:what can you do|how can you help(?: me)?|what are your capabilities|help)[!.?\s]*$",
    re.IGNORECASE,
)
WELLBEING_PATTERN = re.compile(
    r"^(?:how are you|how are you doing|how(?:'s| is) it going|are you (?:okay|ok))[!.?\s]*$",
    re.IGNORECASE,
)
THANKS_PATTERN = re.compile(
    r"^(?:thanks|thank you|cheers|great|nice|awesome)[!.?\s]*$",
    re.IGNORECASE,
)
IDENTITY_PATTERN = re.compile(
    r"^(?:who are you|what are you|are you good at what you do)[!.?\s]*$",
    re.IGNORECASE,
)
GOODBYE_PATTERN = re.compile(
    r"^(?:bye|goodbye|see you|see you later)[!.?\s]*$",
    re.IGNORECASE,
)


def direct_response(question: str) -> str | None:
    """Return a deterministic response for simple conversational messages."""
    if GREETING_PATTERN.fullmatch(question.strip()):
        return (
            "Hello! Ask me about Southampton's economy, business sectors, "
            "planning evidence, or local opportunities."
        )
    if WELLBEING_PATTERN.fullmatch(question.strip()):
        return "I'm doing well, thank you. What would you like to explore about Southampton?"
    if THANKS_PATTERN.fullmatch(question.strip()):
        return "You're welcome."
    if IDENTITY_PATTERN.fullmatch(question.strip()):
        return (
            "I'm the Southampton Opportunity Engine, an evidence-based assistant "
            "for exploring local economic, business, and planning information."
        )
    if GOODBYE_PATTERN.fullmatch(question.strip()):
        return "Goodbye!"
    if CAPABILITIES_PATTERN.fullmatch(question.strip()):
        return (
            "I can search the available Southampton evidence to:\n\n"
            "- explain local economic indicators and sector trends;\n"
            "- compare figures, areas, and business conditions;\n"
            "- identify evidence relevant to business and planning questions; and\n"
            "- provide document and page citations for factual claims.\n\n"
            "If the available evidence does not support an answer, I will say that I don't know."
        )
    return None
