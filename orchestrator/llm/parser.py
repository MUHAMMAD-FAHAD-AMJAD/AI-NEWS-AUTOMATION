"""
orchestrator/llm/parser.py
----------------------------
LLM response parser — converts labeled text output into SummaryResult.

Uses the EXACT parser logic from 04-MESSAGE-FORMAT.md Section 6.

Algorithm:
  - Split response by newlines
  - For each line: check if it starts with a known FIELD: label
  - If yes: save previous field, start collecting new field
  - If no:  accumulate continuation lines into current field
  - After loop: save last field
  - Join accumulated lines with single space
  - Strip whitespace from all values
  - Validate: HEADLINE and PARAGRAPH_1 must be non-empty → else ValueError
  - point_4: if value is 'N/A' or empty → set to None

SECURITY: ValueError message includes only first 200 chars of response.
          Never log full LLM response content.
"""

import sys
from typing import Optional

from orchestrator.models.summary import SummaryResult


# All valid labeled fields in the expected LLM output format
_FIELDS = [
    "HEADLINE",
    "PARAGRAPH_1",
    "PARAGRAPH_2",
    "PARAGRAPH_3",
    "POINT_1",
    "POINT_2",
    "POINT_3",
    "POINT_4",
    "POINT_5",
    "CONCLUSION",
]

# Values that indicate point_4 has no data → stored as None
_POINT_4_NULL_VALUES = {"n/a", "none", "not available", "scale not yet disclosed",
                        "not disclosed", "unknown", ""}


def parse_llm_response(response_text: str) -> SummaryResult:
    """
    Parse labeled LLM output into SummaryResult.
    Handles minor formatting variations gracefully.

    Args:
        response_text: Raw text output from an LLM API call.

    Returns:
        SummaryResult: Populated with all parsed fields.

    Raises:
        ValueError: If HEADLINE or PARAGRAPH_1 are missing/empty.
                    Message includes only first 200 chars of response.
    """
    # Initialize all fields to empty string
    fields: dict[str, str] = {f: "" for f in _FIELDS}

    current_field: Optional[str] = None
    current_lines: list[str] = []

    for line in response_text.strip().split("\n"):
        stripped = line.strip()
        matched = False

        for field in _FIELDS:
            if stripped.startswith(f"{field}:"):
                # Save the previously accumulated field
                if current_field is not None:
                    fields[current_field] = " ".join(current_lines).strip()

                # Start new field
                current_field = field
                value_part = stripped[len(field) + 1:].strip()
                current_lines = [value_part] if value_part else []
                matched = True
                break

        if not matched and current_field is not None and stripped:
            # Continuation line — accumulate into current field
            current_lines.append(stripped)

    # Save the last field
    if current_field is not None:
        fields[current_field] = " ".join(current_lines).strip()

    # Strip whitespace from all values
    fields = {k: v.strip() for k, v in fields.items()}

    # Validate required fields
    if not fields["HEADLINE"] or not fields["PARAGRAPH_1"]:
        # Only expose first 200 chars in error — never log full response
        raise ValueError(
            f"LLM response missing required fields (HEADLINE or PARAGRAPH_1). "
            f"Response preview: {response_text[:200]!r}"
        )

    # point_4: None if no quantitative data
    point_4_raw = fields["POINT_4"].lower().strip()
    point_4_value: Optional[str] = (
        None if point_4_raw in _POINT_4_NULL_VALUES
        else fields["POINT_4"]
    )

    return SummaryResult(
        headline=fields["HEADLINE"].upper(),
        paragraph_1=fields["PARAGRAPH_1"],
        paragraph_2=fields["PARAGRAPH_2"],
        paragraph_3=fields["PARAGRAPH_3"],
        point_1=fields["POINT_1"],
        point_2=fields["POINT_2"],
        point_3=fields["POINT_3"],
        point_4=point_4_value,
        point_5=fields["POINT_5"],
        conclusion=fields["CONCLUSION"],
    )
