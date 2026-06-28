"""
orchestrator/llm/parser.py
----------------------------
LLM response parser — converts enterprise intelligence brief output into SummaryResult.

Expected LLM output structure:
    METRIC BRIEF // [CATEGORY]

    THE UPDATE
    [multi-line narrative prose]

    STRATEGIC IMPLICATIONS
    [multi-line narrative prose]

Parsing algorithm:
  1. Scan lines for the "METRIC BRIEF //" prefix → extract category token
  2. Scan for "THE UPDATE" header line → collect all following lines as update_block
     until "STRATEGIC IMPLICATIONS" is encountered or input ends
  3. Scan for "STRATEGIC IMPLICATIONS" header line → collect all following lines
     as strategic_implications until input ends
  4. Strip leading/trailing whitespace from all extracted blocks
  5. Raise ValueError if update_block is empty — triggers LLM fallback chain

SECURITY: ValueError message includes only first 200 chars of response.
          Never log full LLM response content.
"""

import re
from typing import Optional

from orchestrator.models.summary import SummaryResult


# Section header patterns — case-insensitive to handle minor LLM formatting variance
_METRIC_BRIEF_PREFIX = re.compile(r"METRIC\s+BRIEF\s*//\s*(.+)", re.IGNORECASE)
_THE_UPDATE_HEADER   = re.compile(r"^\s*THE\s+UPDATE\s*$", re.IGNORECASE)
_STRAT_IMPL_HEADER   = re.compile(r"^\s*STRATEGIC\s+IMPLICATIONS\s*$", re.IGNORECASE)


def parse_llm_response(response_text: str) -> SummaryResult:
    """
    Parse enterprise intelligence brief LLM output into SummaryResult.

    Extracts category, THE UPDATE block, and STRATEGIC IMPLICATIONS block
    from the structured two-section narrative format.

    Args:
        response_text: Raw text output from an LLM API call.

    Returns:
        SummaryResult: Populated with category, update_block, strategic_implications.

    Raises:
        ValueError: If THE UPDATE block is empty or missing.
                    Message includes only first 200 chars of response.
    """
    category: str = "INTELLIGENCE BRIEF"
    update_lines: list[str] = []
    strat_lines: list[str] = []

    # Parsing state machine
    # States: "seeking_category", "seeking_update", "in_update", "in_strat"
    state = "seeking_category"

    for line in response_text.strip().split("\n"):
        stripped = line.strip()

        # ── Always check for METRIC BRIEF // line ─────────────────────
        metric_match = _METRIC_BRIEF_PREFIX.match(stripped)
        if metric_match:
            raw_category = metric_match.group(1).strip()
            # Clean trailing punctuation or stray characters
            category = raw_category.rstrip(".:;,").strip().upper()
            if state == "seeking_category":
                state = "seeking_update"
            continue

        # ── State: seeking THE UPDATE header ──────────────────────────
        if state in ("seeking_category", "seeking_update"):
            if _THE_UPDATE_HEADER.match(stripped):
                state = "in_update"
            continue

        # ── State: collecting THE UPDATE lines ────────────────────────
        if state == "in_update":
            if _STRAT_IMPL_HEADER.match(stripped):
                state = "in_strat"
                continue
            # Also handle if model wrote "THE UPDATE" again inline — skip it
            if _THE_UPDATE_HEADER.match(stripped):
                continue
            update_lines.append(line)
            continue

        # ── State: collecting STRATEGIC IMPLICATIONS lines ─────────────
        if state == "in_strat":
            # Stop if model appended anything after the section (rare)
            if _METRIC_BRIEF_PREFIX.match(stripped):
                break
            strat_lines.append(line)
            continue

    # ── Assemble blocks ────────────────────────────────────────────────
    update_block = "\n".join(update_lines).strip()
    strategic_implications = "\n".join(strat_lines).strip()

    # ── Validate required field ────────────────────────────────────────
    if not update_block:
        raise ValueError(
            f"LLM response missing required 'THE UPDATE' content. "
            f"Response preview: {response_text[:200]!r}"
        )

    return SummaryResult(
        category=category,
        update_block=update_block,
        strategic_implications=strategic_implications,
    )
