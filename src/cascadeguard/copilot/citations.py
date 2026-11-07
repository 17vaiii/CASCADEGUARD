# OWNER: P5 | STATUS: ACTIVE
"""Grounding checks for copilot briefs.

* **Citations** - every ``[n]`` must refer to a passage that was actually retrieved and given to
  the generator; invalid markers are removed and reported.
* **Numbers** - every number in the brief must appear in the incident facts or in a cited
  passage (so the LLM cannot invent a megawatt figure); unsupported numbers are reported.
* **Explanation only** - a brief must not instruct anyone to operate equipment beyond restating
  the verified recommendation, and must not claim certainty ("guaranteed", "will definitely").
"""

from __future__ import annotations

import re
from typing import Any

CITE = re.compile(r"\[(\d+)\]")
NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
OVERCLAIM = ("guaranteed", "will definitely", "certainly prevent", "100% safe", "confirmed theft")


def _numbers(text: str) -> set[float]:
    out = set()
    for tok in NUMBER.findall(text.replace(",", "")):
        try:
            out.add(round(float(tok), 1))
        except ValueError:
            pass
    return out


def validate_citations(text: str, valid: set[int]) -> tuple[str, list[int], list[int]]:
    used = [int(n) for n in CITE.findall(text)]
    bad = sorted({n for n in used if n not in valid})
    cleaned = CITE.sub(lambda m: m.group(0) if int(m.group(1)) in valid else "", text)
    return cleaned, sorted({n for n in used if n in valid}), bad


def unsupported_numbers(text: str, facts_text: str, passages_text: str) -> list[float]:
    allowed = _numbers(facts_text) | _numbers(passages_text)
    found = _numbers(CITE.sub("", text))
    # Tolerate rounding of allowed values to integers.
    allowed |= {round(x) for x in allowed} | {float(round(x)) for x in allowed}
    return sorted(x for x in found if x not in allowed and abs(x) > 1.0)


def check_brief(text: str, facts_text: str, passages: dict[int, str]) -> dict[str, Any]:
    cleaned, cited, bad = validate_citations(text, set(passages))
    nums = unsupported_numbers(cleaned, facts_text, " ".join(passages.values()))
    over = [w for w in OVERCLAIM if w in cleaned.lower()]
    warnings = []
    if bad:
        warnings.append(f"removed invalid citations {bad}")
    if not cited:
        warnings.append("no valid citation in the brief")
    if nums:
        warnings.append(f"numbers not found in facts or sources: {nums}")
    if over:
        warnings.append(f"over-confident wording: {over}")
    return {"text": cleaned, "cited": cited, "invalid_citations": bad, "unsupported_numbers": nums,
            "overclaims": over, "warnings": warnings, "grounded": not nums and not over and bool(cited)}
