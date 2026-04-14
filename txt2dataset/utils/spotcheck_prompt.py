"""Shared spotcheck check-prompt and schema used by all builder backends."""

CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["correct", "fabricated", "debatable"],
        },
        "desc": {"type": "string"},
    },
    "required": ["verdict", "desc"],
}


def build_check_prompt(*, extraction_prompt, context, rows_json, n_rows):
    """Build the spotcheck verification prompt.

    Args:
        extraction_prompt: The original extraction instructions shown to the LLM.
        context: The source document text.
        rows_json: JSON-serialized extracted data rows.
        n_rows: Number of extracted rows.
    """
    return (
        "You are verifying structured data extracted from a source document.\n\n"
        f"## Extraction instructions (for context)\n{extraction_prompt}\n\n"
        f"## Source text\n{context}\n\n"
        f"## Extracted data ({n_rows} row{'s' if n_rows != 1 else ''})\n{rows_json}\n\n"
        "## Verification steps\n"
        "Work through these checks IN ORDER. Stop at the first failure.\n\n"
        "### Step 1 — Completeness\n"
        "Count how many distinct events/items the source text describes, then compare "
        "to the number of extracted rows above. If the text describes N events but "
        "the data contains fewer than N rows, verdict is 'fabricated'. "
        "Do not proceed to field-level checks until row count matches.\n\n"
        "### Step 2 — Date interval fields\n"
        "Date fields use a [start, end] component encoding "
        "(year, month, day, hour, minute, second, timezone). Each component "
        "must reflect what the text actually states — no more, no less:\n"
        "   - Exact date (e.g. 'August 16, 2021'): year=2021/2021, month=8/8, day=16/16.\n"
        "   - Range (e.g. 'the week of May 10, 2021'): day_start=10, day_end=16, "
        "not null or a single value. The interval must capture the range.\n"
        "   - Partial (e.g. 'November 2023'): year and month set, day null — not guessed.\n"
        "   - Vague (e.g. 'late November 2023'): approximate the range (e.g. day 21/30).\n"
        "   - All-null interval components are only correct when the text provides NO "
        "temporal information at all for that date. If any date-like information exists "
        "in the text (year, month, week, season, etc.), the corresponding interval "
        "components MUST be populated — even if a separate *_text field also captures "
        "the original phrasing. A *_text field does NOT substitute for the interval fields.\n"
        "   - Timezone only when explicitly stated in the text.\n\n"
        "### Step 3 — Non-date fields\n"
        "Values must be directly supported by the source text.\n\n"
        "### Step 4 — Omissions\n"
        "If the text clearly states something the extraction "
        "instructions ask for but the extracted data leaves it null/empty, that is an error.\n\n"
        "## Response\n"
        "Return JSON with:\n"
        "- verdict: 'correct', 'fabricated', or 'debatable'\n"
        "- desc: brief explanation citing specific text vs extracted value for any issues\n"
    )
