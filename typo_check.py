from connection import ask_ai
from utils import parse_json_object, validate_severity, TRANSCRIPT_LIMIT


def _parse_rows(result: str, fallback_snippet: str) -> list:
    data = parse_json_object(result)
    if data is None:
        return [{
            "Type": "Typos", "Location": "Transcript",
            "Snippet": fallback_snippet[:120],
            "Issue": "Could not parse AI output",
            "Suggestion": (result or "")[:300],
            "Severity": "Medium",
        }]

    rows = []
    seen = set()
    for item in data.get("issues", []):
        snippet = str(item.get("snippet", "")).strip()
        issue = str(item.get("issue", "")).strip()
        suggestion = str(item.get("suggestion", "")).strip()
        severity = validate_severity(item.get("severity", "Low"), default="Low")

        if not issue:
            continue
        if not snippet or snippet in {"...", ".", ".."}:
            snippet = fallback_snippet[:120]

        key = (snippet.lower(), issue.lower())
        if key in seen:
            continue
        seen.add(key)

        rows.append({
            "Type": "Typos",
            "Location": "Transcript",
            "Snippet": snippet[:120],
            "Issue": issue,
            "Suggestion": suggestion if suggestion else "Review spelling manually.",
            "Severity": severity,
        })

    return rows


def check_typos(transcript: str, glossary: list[str] | None = None):
    text_part = transcript[:TRANSCRIPT_LIMIT]

    glossary_note = ""
    if glossary:
        glossary_note = f"""
KNOWN NAMES AND BRANDS — DO NOT FLAG THESE AS TYPOS:
{", ".join(glossary)}

These are real brand names, product names, or proper nouns that appear intentionally in this video.
"""

    prompt = f"""
You're a Koocester editor checking subtitles for typos.

Only flag actual spelling mistakes — wrong letters, missing letters, obvious misspellings that would look bad on screen.

Don't flag:
- Grammar issues (that's a separate check)
- Names, brands, or proper nouns unless they're clearly misspelled
- Casual SG/MY English spelling choices
- A correct word used in the wrong context (wrong word but spelled right — not a typo)
{glossary_note}
Snippet must be exact text from the transcript. Return ONLY valid JSON:

{{
  "issues": [
    {{
      "type": "Typos",
      "location": "Transcript",
      "snippet": "exact phrase from transcript",
      "issue": "what's misspelled",
      "suggestion": "correct spelling",
      "severity": "Low"
    }}
  ]
}}

If clean: {{"issues":[]}}

Transcript:
{text_part}
"""

    try:
        result = ask_ai(prompt).strip()
        return _parse_rows(result, text_part)
    except Exception as exc:
        return [{
            "Type": "Typos", "Location": "Transcript",
            "Snippet": text_part[:120],
            "Issue": f"Typo checker failed: {type(exc).__name__}",
            "Suggestion": "Review transcript manually for spelling errors.",
            "Severity": "Low",
        }]
