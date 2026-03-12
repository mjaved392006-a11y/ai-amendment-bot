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

            snippet = item.get("snippet", "").strip()
            issue = item.get("issue", "").strip()
            suggestion = item.get("suggestion", "").strip()

            if not issue:
                continue

            if not snippet or snippet in {"...", ".", ".."}:
                snippet = fallback_snippet[:120]

            key = (snippet, issue)
            if key in seen:
                continue
            seen.add(key)

            rows.append({
                "Type": "Storytelling",
                "Location": "Transcript",
                "Snippet": snippet[:120],
                "Issue": issue,
                "Suggestion": suggestion if suggestion else "Improve narrative flow",
                "Severity": "Medium"
            })

        return rows

    except Exception:
        return [{
            "Type": "Storytelling",
            "Location": "Transcript",
            "Snippet": fallback_snippet[:120],
            "Issue": "Could not parse AI output",
            "Suggestion": result[:300],
            "Severity": "Medium"
        }]


def check_storytelling(transcript: str):

    text_part = transcript[:500]

    prompt = f"""
You are reviewing a short-form video transcript.

Your task:
Determine whether the story or explanation flows clearly and is easy for viewers to follow.

Look for:
- sudden topic changes
- confusing explanations
- weak transitions
- incomplete ideas
- abrupt endings

IMPORTANT:
- Only report real storytelling problems.
- Do NOT report grammar or spelling issues.
- Do NOT report hook issues.
- Return only storytelling problems if they exist.

Return ONLY JSON.

Format:
{{
  "issues": [
    {{
      "type": "Storytelling",
      "location": "Transcript",
      "snippet": "exact phrase",
      "issue": "describe the storytelling problem",
      "suggestion": "how the flow could be improved",
      "severity": "Medium"
    }}
  ]
}}

If the story flow is clear, return:

{{"issues":[]}}

Transcript:
{text_part}
"""

    result = ask_ai(prompt).strip()

    return safe_json_parse(result, text_part)