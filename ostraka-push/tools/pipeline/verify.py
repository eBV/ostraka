#!/usr/bin/env python3
"""Ostraka claim verifier.

After the model drafts an answer with [n] citations, every checkable claim
(names, numbers, dates) must be grounded in one of the cited passages.
Unverifiable claims are marked, never silently presented as fact.

Reference implementation; the phone runs the same rules in Kotlin.
"""

import re

# Numbers with units, years, dates, percentages.
_NUMBER_RE = re.compile(
    r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b"      # 1,234 / 1,234.5
    r"|\b\d+\.\d+\b"                          # 3.14
    r"|\b\d+\s?(?:%|percent)\b"               # 42% / 42 percent
    r"|\b(?:1[0-9]\d\d|20[0-3]\d)\b"          # years 1000-2039
    r"|\b\d+\s?(?:m|km|kg|g|cm|mm|mph|km/h|°C|°F|K)\b"  # units
    r"|\b\d{2,}\b",                           # bare integers (900, 42)
    re.IGNORECASE)
# Capitalized multi-word phrases (candidate named entities).
_ENTITY_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b")
_STOP = {"The", "A", "An", "In", "On", "At", "Of", "And", "For", "To",
        "With", "From", "By", "As", "It", "Its", "This", "That", "These",
        "Those", "He", "She", "They", "We", "You", "His", "Her", "Their",
        "About", "Nearly", "Almost", "Over", "Under", "Between", "During",
        "According", "While", "After", "Before", "Such"}


def normalize(s):
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def extract_claims(answer):
    """Return a list of (claim_text, kind) for checkable claims."""
    claims = []
    for m in _NUMBER_RE.finditer(answer):
        claims.append((m.group(0), "number"))
    for m in _ENTITY_RE.finditer(answer):
        ent = m.group(1)
        if ent.split()[0] in _STOP or len(ent) < 3:
            continue
        claims.append((ent, "entity"))
    # de-dupe preserving order
    seen, out = set(), []
    for c, k in claims:
        key = (normalize(c), k)
        if key not in seen:
            seen.add(key)
            out.append((c, k))
    return out


def verify(answer, passages):
    """Check each claim against the cited passages.

    passages: list of passage texts (already resolved from [n] ids).
    Returns (verified, unverified) lists of claim strings.
    """
    normed = [normalize(p) for p in passages]
    verified, unverified = [], []
    for claim, kind in extract_claims(answer):
        n = normalize(claim)
        if kind == "number":
            # numbers must appear near-matching: allow unit variants
            core = re.sub(r"[^\w.]", "", n).replace("percent", "%")
            hit = any(core in re.sub(r"[^\w.]", "", p) for p in normed)
        else:
            hit = any(n in p for p in normed)
        (verified if hit else unverified).append(claim)
    return verified, unverified


def mark_answer(answer, unverified):
    """Append a warning line naming what could not be verified."""
    if not unverified:
        return answer
    names = ", ".join(f'"{u}"' for u in unverified[:5])
    more = f" (+{len(unverified)-5} more)" if len(unverified) > 5 else ""
    return (answer.rstrip() + "\n\n⚠ Could not verify against cited sources: "
            + names + more)


def self_test():
    passage = ("The moai are monolithic human figures carved by the Rapa Nui "
               "people on Easter Island between 1250 and 1500. Nearly half "
               "remain at Rano Raraku, the main quarry.")
    answer = ("The moai [1] are monolithic figures carved by the Rapa Nui "
              "between 1250 and 1500. About 900 statues were completed, "
              "and Napoleon visited the island in 1802.")
    v, u = verify(answer, [passage])
    assert "Rapa Nui" in v and "1250" in v, (v, u)
    assert "Napoleon" in u and "900" in u, (v, u)
    marked = mark_answer(answer, u)
    assert "⚠" in marked and "Napoleon" in marked
    assert mark_answer(answer, []) == answer
    print("VERIFY SELF TEST PASSED")


if __name__ == "__main__":
    self_test()
