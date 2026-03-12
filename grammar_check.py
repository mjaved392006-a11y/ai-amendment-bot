import json
from connection import ask_ai


def safe_json_parse(result: str, fallback_snippet: str):
    try:
        start = result.find("{")
        end = result.rfind("}") + 1

        if start == -1 or end == 0:
            return []

        result = result[start:end]
        data = json.loads(result)

        rows = []
        seen = set()

        for item in data.get("issues", []):
            issue_type = item.get("type", "Grammar").strip()
            location = item.get("location", "Transcript").strip()
            snippet = item.get("snippet", "").strip()
            issue = item.get("issue", "").strip()
            suggestion = item.get("suggestion", "").strip()
            severity = item.get("severity", "Medium").strip()

            if not issue:
                continue

            if not snippet or snippet in {"...", ".", ".."}:
                snippet = fallback_snippet[:120]

            key = (issue_type, snippet, issue)
            if key in seen:
                continue
            seen.add(key)

            rows.append({
                "Type": issue_type,
                "Location": location,
                "Snippet": snippet[:120],
                "Issue": issue,
                "Suggestion": suggestion if suggestion else "No suggestion returned",
                "Severity": severity
            })

        return rows

    except Exception:
        return [{
            "Type": "Grammar",
            "Location": "Transcript",
            "Snippet": fallback_snippet[:120],
            "Issue": "Could not parse AI output",
            "Suggestion": result[:300],
            "Severity": "Medium"
        }]


def check_grammar(transcript: str):
    text_part = transcript[:300]

    prompt = f"""
You are reviewing a video transcript for grammar only.

Your task:
- identify all clear grammatical mistakes
- do NOT check hook
- do NOT check storytelling
- do NOT check spelling/typos unless it directly affects grammar
- do NOT flag casual spoken English unless it is clearly grammatically wrong in subtitles/captions
- consider context before flagging an issue

IMPORTANT:
- Each issue must point to an exact phrase copied from the transcript.
- Do NOT use "..." as a snippet.
- Do NOT return generic statements.
- Return ONLY JSON.
- Do NOT include text before or after JSON.

Return in this format:
{{
  "issues": [
    {{
      "type": "Grammar",
      "location": "Transcript",
      "snippet": "exact phrase",
      "issue": "specific grammar issue",
      "suggestion": "specific corrected version",
      "severity": "Medium"
    }}
  ]
}}

If there are no grammar issues, return:
{{"issues":[]}}

Transcript:
{text_part}
"""

    result = ask_ai(prompt).strip()
    return safe_json_parse(result, text_part)