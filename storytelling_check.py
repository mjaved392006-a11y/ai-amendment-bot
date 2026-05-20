import json

from connection import ask_ai, ask_ai_multimodal
from utils import TRANSCRIPT_LIMIT


def safe_json_parse(result: str, fallback_snippet: str):
    try:
        start = result.find("{")
        end = result.rfind("}") + 1

        if start == -1 or end == 0:
            return [{
                "Type": "Storytelling",
                "Location": "Transcript",
                "Snippet": fallback_snippet[:120],
                "Issue": "Storytelling flow could not be evaluated reliably.",
                "Suggestion": "Review whether the narrative is easy to follow from beginning to end.",
                "Severity": "Medium",
            }]

        cleaned = result[start:end]
        data = json.loads(cleaned)

        rows = []
        seen = set()
        allowed_severities = {"Low", "Medium", "High"}

        # ✅ ALWAYS ADD ASSESSMENT ROW
        assessment = data.get("assessment", {}) or {}
        a_snippet = str(assessment.get("snippet", "")).strip() or fallback_snippet[:120]
        a_issue = str(assessment.get("issue", "")).strip() or "Storytelling flow reviewed."
        a_suggestion = str(assessment.get("suggestion", "")).strip() or "Keep the story progression clear and easy to follow."
        a_severity = str(assessment.get("severity", "Low")).strip().title()

        if a_severity not in allowed_severities:
            a_severity = "Low"

        rows.append({
            "Type": "Storytelling",
            "Location": "Transcript",
            "Snippet": a_snippet[:120],
            "Issue": a_issue,
            "Suggestion": a_suggestion,
            "Severity": a_severity,
        })
        seen.add((a_snippet.lower(), a_issue.lower()))

        # ✅ ADD ISSUE ROWS IF ANY
        for item in data.get("issues", []):
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
                "Type": "Storytelling",
                "Location": "Transcript",
                "Snippet": snippet[:120],
                "Issue": issue,
                "Suggestion": suggestion if suggestion else "Improve the flow so the viewer can follow the idea more easily.",
                "Severity": severity,
            })

        return rows

    except Exception:
        return [{
            "Type": "Storytelling",
            "Location": "Transcript",
            "Snippet": fallback_snippet[:120],
            "Issue": "Could not parse storytelling evaluation output.",
            "Suggestion": "Review the narrative flow manually.",
            "Severity": "Medium",
        }]


def check_storytelling(transcript: str, frames: list, audio_base64: str):
    text_part = transcript[:TRANSCRIPT_LIMIT]

    # Cap to 8 frames evenly spread across the timeline — enough for
    # storytelling context without hitting API token limits.
    if frames:
        step = max(1, len(frames) // 8)
        sampled = frames[::step][:8]
    else:
        sampled = []
    images = [f["base64"] for f in sampled if f.get("base64")]

    # Build the index from sampled frames only (not all frames — avoids confusing the model)
    frames_index = "\n".join(
        f"- Frame {i+1}: t={f.get('timestamp', 'N/A')}"
        for i, f in enumerate(sampled)
    ) or "- (no frames provided)"

    prompt = f"""
You're a senior Koocester editor checking if this video's story holds together and flows. The footage is already shot — your job is to fix what you can in the edit.

Koocester content doesn't need to be scripted — but it should feel like it's going somewhere. Check:
- Does it open with something that sets the scene or pulls you in?
- Does the middle build toward something — a reveal, a point, a moment?
- Does it land cleanly at the end, or just... stop?
- Are there any jarring jumps or gaps in flow the editor can smooth over?
- Do the visuals match what's being said? Check the frame timestamps — if something's off, call it out.

EDITOR SCOPE — every suggestion must be an edit-room fix:
- Cut or trim sections that break flow or meander
- Reorder clips to create a cleaner narrative arc
- Add a title card or text overlay to bridge a context gap (e.g. "cut to a location title card here — the viewer doesn't know where we are")
- Add a transition or b-roll to smooth a jarring jump between topics
- Tighten pacing by removing dead air between points

NEVER suggest:
- The host should explain something more clearly or add more context
- Re-filming any section
- The host should have said or shown something different
- Anything requiring changes to the spoken content

GROUNDING RULES:
- Only judge what's actually in the transcript and visible in the frames.
- If captions and visuals don't match at a specific moment, flag it with the timestamp.
- Don't flag it for being casual or conversational — that's the format.
- Don't critique things that aren't actually in the material.

Frame timestamps:
{frames_index}

Always return ONE overall verdict on the story. Add issue rows only if there are real problems — confusing jumps, flow breaks, or visual mismatches that the editor can fix.

Return ONLY valid JSON:

{{
  "assessment": {{
    "snippet": "exact phrase from transcript",
    "issue": "straight verdict — is the story working, and why or why not",
    "suggestion": "specific edit-room fix — cut, reorder, title card, or b-roll — not a host note",
    "severity": "Low | Medium | High"
  }},
  "issues": [
    {{
      "snippet": "exact phrase",
      "issue": "specific problem — confusing jump, flow break, visual mismatch",
      "suggestion": "specific edit-room fix",
      "severity": "Low | Medium | High"
    }}
  ]
}}

Transcript:
{text_part}
"""

    try:
        # Multimodal: pass frames so the AI can detect visual-vs-spoken mismatches.
        if images:
            result = ask_ai_multimodal(prompt, images)
        else:
            result = ask_ai(prompt)

        if not result:
            return [{
                "Type": "Storytelling",
                "Location": "Transcript",
                "Snippet": text_part[:120],
                "Issue": "Storytelling evaluation returned no result.",
                "Suggestion": "Review the flow manually.",
                "Severity": "Medium",
            }]

        return safe_json_parse(result.strip(), text_part)

    except Exception as e:
        return [{
            "Type": "Storytelling",
            "Location": "Transcript",
            "Snippet": text_part[:120],
            "Issue": f"Storytelling checker failed: {type(e).__name__}: {str(e)[:200]}",
            "Suggestion": "Review the narrative flow manually.",
            "Severity": "Medium",
        }]
