from connection import ask_ai_multimodal
import json


def safe_json_parse(result: str, fallback_snippet: str):
    try:
        start = result.find("{")
        end = result.rfind("}") + 1

        if start == -1 or end == 0:
            return [{
                "Type": "Hook",
                "Location": "Opening",
                "Snippet": fallback_snippet[:120],
                "Issue": "Opening hook could not be evaluated reliably.",
                "Suggestion": "Review the first few seconds manually for attention, clarity, and energy.",
                "Severity": "Medium",
            }]

        cleaned = result[start:end]
        data = json.loads(cleaned)

        rows = []
        seen = set()
        allowed_severities = {"Low", "Medium", "High"}

        assessment = data.get("assessment", {}) or {}
        a_snippet = str(assessment.get("snippet", "")).strip() or fallback_snippet[:120]
        a_issue = str(assessment.get("issue", "")).strip() or "Opening hook reviewed."
        a_suggestion = str(assessment.get("suggestion", "")).strip() or "Keep the opening clear, engaging, and easy to follow."
        a_severity = str(assessment.get("severity", "Low")).strip().title()

        if a_severity not in allowed_severities:
            a_severity = "Low"

        rows.append({
            "Type": "Hook",
            "Location": "Opening",
            "Snippet": a_snippet[:120],
            "Issue": a_issue,
            "Suggestion": a_suggestion,
            "Severity": a_severity,
        })
        seen.add((a_snippet.lower(), a_issue.lower()))

        for item in data.get("issues", [])[:1]:  # hard cap — max 1 extra issue
            snippet = str(item.get("snippet", "")).strip()
            issue = str(item.get("issue", "")).strip()
            suggestion = str(item.get("suggestion", "")).strip()
            severity = str(item.get("severity", "Medium")).strip().title()

            if not issue:
                continue
            if severity not in allowed_severities:
                severity = "Medium"
            if not snippet or snippet in {"...", ".", ".."}:
                snippet = fallback_snippet[:120]

            key = (snippet.lower(), issue.lower())
            if key in seen:
                continue
            seen.add(key)

            rows.append({
                "Type": "Hook",
                "Location": "Opening",
                "Snippet": snippet[:120],
                "Issue": issue,
                "Suggestion": suggestion if suggestion else "Strengthen the first few seconds with a clearer or more engaging opening.",
                "Severity": severity,
            })

        return rows

    except Exception:
        return [{
            "Type": "Hook",
            "Location": "Opening",
            "Snippet": fallback_snippet[:120],
            "Issue": "Could not parse hook evaluation output.",
            "Suggestion": "Review the opening manually.",
            "Severity": "Medium",
        }]


def check_hook(transcript: str, frames: list, audio_base64: str):
    opening = transcript[:220]
    images = [f["base64"] for f in frames[:2]] if frames else []

    prompt = f"""
You're a senior Koocester editor doing a no-BS hook check on this video. The footage is already shot — you can only work with what's there.

The hook is the first 3 seconds. If it doesn't stop the scroll, nothing else matters.

Check all three:
1. Does the opening line immediately pull you in? Or does it start slow?
2. Do the opening frames have energy — movement, strong subject, something that makes you look?
3. Is the audio clear and punchy right from the top, or does it start quiet/flat?

EDITOR SCOPE — if the hook isn't working, your suggestions must be edit-room fixes only:
- Trim dead seconds from the start so a stronger moment hits first
- Reorder: pull a more punchy line from later in the video to open with (using a text overlay or cut)
- Add a bold text overlay in the first 2 seconds to inject energy the delivery alone doesn't have
- Cut to a more visually striking frame to open on
- Add a sound effect or music hit to punch up the opening

NEVER suggest:
- The host should deliver the line differently or with more energy
- Re-filming the opening
- The host should have said something different
- Anything that requires going back to the shoot

GROUNDING RULES:
- Only judge what's actually in the transcript opening and the frames provided.
- Don't make up context that isn't there.
- If the caption says one thing and the visual shows something different, flag it with the frame timestamp — don't guess which is right.

Give ONE straight-up verdict on the hook overall. Only add a second issue if there's one specific problem that really needs to be called out separately.

Return ONLY valid JSON:

{{
  "assessment": {{
    "snippet": "exact opening phrase from transcript",
    "issue": "straight verdict — is this hook working or not, and why",
    "suggestion": "specific edit-room fix — trim, reorder, overlay, or SFX — not a host note",
    "severity": "Low | Medium | High"
  }},
  "issues": [
    {{
      "snippet": "exact phrase",
      "issue": "one specific problem worth calling out separately",
      "suggestion": "specific edit-room fix",
      "severity": "Low | Medium | High"
    }}
  ]
}}

Transcript opening:
{opening}
"""

    try:
        result = ask_ai_multimodal(prompt, images)
        if not result:
            return [{
                "Type": "Hook",
                "Location": "Opening",
                "Snippet": opening[:120],
                "Issue": "Hook evaluation returned no result.",
                "Suggestion": "Review the first few seconds manually.",
                "Severity": "Medium",
            }]
        return safe_json_parse(result.strip(), opening)
    except Exception:
        return [{
            "Type": "Hook",
            "Location": "Opening",
            "Snippet": opening[:120],
            "Issue": "Hook checker failed during multimodal analysis.",
            "Suggestion": "Review the opening manually or inspect the multimodal request.",
            "Severity": "Medium",
        }]
