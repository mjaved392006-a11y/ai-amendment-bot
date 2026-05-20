from connection import ask_ai
from utils import parse_json_object, validate_severity, TRANSCRIPT_LIMIT


def _parse_rows(result: str, fallback_snippet: str) -> list:
    data = parse_json_object(result)
    if data is None:
        return [{
            "Type": "Grammar", "Location": "Transcript",
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
        severity = validate_severity(item.get("severity", "Medium"))

        if not issue:
            continue
        if not snippet or snippet in {"...", ".", ".."}:
            snippet = fallback_snippet[:120]

        key = (snippet.lower(), issue.lower())
        if key in seen:
            continue
        seen.add(key)

        rows.append({
            "Type": "Grammar",
            "Location": "Transcript",
            "Snippet": snippet[:120],
            "Issue": issue,
            "Suggestion": suggestion if suggestion else "Review only if the sentence is genuinely unclear.",
            "Severity": severity,
        })

    return rows


def check_grammar(transcript: str, glossary: list[str] | None = None):
    text_part = transcript[:TRANSCRIPT_LIMIT]

    glossary_note = ""
    if glossary:
        glossary_note = f"""
KNOWN NAMES AND BRANDS — DO NOT FLAG THESE AS GRAMMAR ISSUES:
{", ".join(glossary)}

These are real brand names, product names, or proper nouns used intentionally in this video.
Treat them as correct regardless of how unusual they look.
"""

    prompt = f"""
You're a Koocester editor checking subtitle grammar.

This is spoken SG/MY English — casual grammar is totally fine. The bar is simple: would a viewer reading this subtitle actually misunderstand what's being said?

DON'T flag:
- Casual phrasing ("lah", "mah", "lor", "can or not")
- Missing articles ("I go shop" is fine — it's conversational)
- Informal SG/MY sentence structure that's still clear
- Anything understandable even if not "textbook" English
{glossary_note}
ONLY flag if:
- The sentence is confusing and the viewer won't know what was meant
- The grammar is so broken it looks like a transcription error

Max 2–3 flags. If it's clean, return an empty list — don't go looking for problems that aren't there.

Return ONLY valid JSON:
{{
  "issues": [
    {{
      "type": "Grammar",
      "location": "Transcript",
      "snippet": "exact phrase from transcript",
      "issue": "why this will confuse the viewer",
      "suggestion": "fixed version",
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
            "Type": "Grammar", "Location": "Transcript",
            "Snippet": text_part[:120],
            "Issue": f"Grammar checker failed: {type(exc).__name__}",
            "Suggestion": "Review transcript manually for grammar issues.",
            "Severity": "Low",
        }]
