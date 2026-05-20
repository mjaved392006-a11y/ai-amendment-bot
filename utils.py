"""
utils.py
--------
Shared helpers used across all QC checker modules.

Centralises:
  - JSON parsing (was copy-pasted 7+ times with slight variations)
  - Severity validation
  - Standard transcript truncation limit
  - _clean_text (markdown fence stripper)
"""

import json

# ---------------------------------------------------------------------------
# Standard transcript limit used by all text-based checkers.
# Raising this increases coverage on longer videos at the cost of more tokens.
# ---------------------------------------------------------------------------
TRANSCRIPT_LIMIT = 1500


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clean_json_text(text: str) -> str:
    """Strip markdown code fences that some models wrap around JSON output."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:].strip()
    elif text.startswith("```"):
        text = text[3:].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_json_object(result: str) -> dict | None:
    """
    Extract and parse the first JSON *object* from an AI response string.

    Returns the parsed dict, or None on any failure (bad JSON, empty string,
    no object found, etc.).

    Use this for checkers that expect a single structured result dict
    (scores, summaries, overall reviews).
    """
    try:
        cleaned = _clean_json_text(result or "")
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        if start == -1 or end <= start:
            return None
        return json.loads(cleaned[start:end])
    except Exception:
        return None


def validate_severity(s: str, default: str = "Medium") -> str:
    """
    Normalise and validate a severity string.
    Returns one of {"Low", "Medium", "High"}, falling back to `default`.
    """
    normalised = str(s or "").strip().title()
    return normalised if normalised in {"Low", "Medium", "High"} else default
