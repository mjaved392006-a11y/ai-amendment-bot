from connection import ask_ai
from utils import parse_json_object, TRANSCRIPT_LIMIT


def generate_review_summary(transcript: str):
    text_part = transcript[:TRANSCRIPT_LIMIT]

    prompt = f"""
You're the head editor at Koocester giving a straight debrief on this video before it goes to Frame.io. The footage is locked — the editor can only work in post.

Give a 2–3 sentence honest summary — what's working, what's not, and whether it's ready. No fluff. Talk like you're briefing a junior editor, not a producer.

Then call the retention:
- High: hook is strong, pacing holds, content is engaging enough that people will stay
- Medium: watchable, gets the point across
- Low: loses the viewer early or has a structural problem that hurts watch time

Then give 3 specific things the editor needs to act on before uploading. Every suggestion must be something they can do in the edit — cuts, reorders, overlays, captions, title cards, pacing fixes, SFX. No notes about what the host should have said or done differently. Not "explain this better" — the host can't re-record. Instead: "cut the section at [X] — it kills the pacing" or "add a price overlay at [X] — the number is mentioned too fast to register."

Base everything only on the transcript. Don't mention visuals you haven't seen.

Return EXACT JSON:

{{
  "overall_review": "2-3 sentence straight-up verdict — what's working and what the editor needs to fix.",
  "retention": "Medium",
  "suggestions": [
    "Specific edit-room action 1 — cut, reorder, overlay, caption, or pacing fix",
    "Specific edit-room action 2",
    "Specific edit-room action 3"
  ]
}}

Transcript:
{text_part}
"""

    try:
        result = ask_ai(prompt)
        parsed = parse_json_object(result)
        if parsed:
            return {
                "overall_review": parsed.get("overall_review", "Could not generate an overall review reliably."),
                "retention": parsed.get("retention", "Medium"),
                "suggestions": parsed.get("suggestions", []),
            }
    except Exception:
        pass

    return {
        "overall_review": "Could not generate an overall review reliably.",
        "retention": "Medium",
        "suggestions": [],
    }
