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
            issue_type = item.get("type", "Hook").strip()
            location = item.get("location", "Opening").strip()
            snippet = item.get("snippet", "").strip()
            issue = item.get("issue", "").strip()
            suggestion = item.get("suggestion", "").strip()
            severity = item.get("severity", "Low").strip()

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
            "Type": "Hook",
            "Location": "Opening",
            "Snippet": fallback_snippet[:120],
            "Issue": "Could not parse AI output",
            "Suggestion": result[:300],
            "Severity": "Medium"
        }]


def check_hook(transcript: str):
    opening = transcript[:220]

    prompt = f"""
You are reviewing the opening hook of a short-form video.

Your task is to decide whether the opening is strong enough to capture attention in the first few seconds.

IMPORTANT:
- Return at most 1 issue.
- Only flag a problem if the hook is clearly weak, generic, boring, or not attention-grabbing.
- The snippet must be an exact phrase copied from the transcript.
- Do NOT use "..." as the snippet.
- Return ONLY JSON.
- Do NOT include text before or after JSON.

Return in this format:
{{
  "issues": [
    {{
      "type": "Hook",
      "location": "Opening",
      "snippet": "exact phrase",
      "issue": "specific hook problem",
      "suggestion": "specific improvement",
      "severity": "Medium"
    }}
  ]
}}

If the hook is strong enough, return:
{{"issues":[]}}

Transcript opening:
{opening}
"""

    result = ask_ai(prompt).strip()
    return safe_json_parse(result, opening)