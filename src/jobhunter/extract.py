"""Pull OPT / sponsorship wording out of a JD. Quote the posting; never guess."""

import re

from .text_utils import sentences

NOT_STATED = "Not stated, verify"

# Case-sensitive on purpose: "OPT" the acronym, not the word "opt".
_OPT = re.compile(r"\b(?:STEM[ -]OPT|OPT|CPT|F-?1)\b")
_SPONSOR = re.compile(r"sponsor|work authori[sz]ation|authori[sz]ed to work|\bvisa\b|H-?1B", re.IGNORECASE)


def _clip(sentence: str, limit: int = 220) -> str:
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rstrip() + "…"


def snippets(description: str) -> tuple[str, str]:
    """Return (opt_text, visa_text): first matching sentence of each, or NOT_STATED."""
    opt = visa = ""
    for sentence in sentences(description):
        if not opt and _OPT.search(sentence):
            opt = _clip(sentence)
        if not visa and _SPONSOR.search(sentence):
            visa = _clip(sentence)
        if opt and visa:
            break
    return opt or NOT_STATED, visa or NOT_STATED
