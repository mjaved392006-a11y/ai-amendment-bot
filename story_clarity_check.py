from connection import ask_ai
from utils import parse_json_object, TRANSCRIPT_LIMIT


def check_story_clarity(transcript: str):
    text_part = transcript[:TRANSCRIPT_LIMIT]

    prompt = f"""
You're a senior Koocester editor checking the story structure of this video. The footage is already shot — your job is to work with what's there.

EDITOR SCOPE — you can only suggest:
- Cut or trim sections (e.g. "trim the rambling at 01:20 — it breaks the flow")
- Reorder clips (e.g. "move the price reveal earlier — lead with it")
- Add text overlays, title cards, or captions to fill context gaps
- Add b-roll, graphics, or transitions to bridge jumps
- Tighten pacing by cutting dead air or repeated points

NEVER suggest:
- The host should explain something differently or add more detail
- Re-filming, re-recording, or changing what was said
- The host should have covered a topic they didn't cover
- Anything that requires going back to the shoot

Koocester content doesn't need to be scripted — but it should feel like it goes somewhere:
- Opens with something that sets the scene or grabs you immediately
- Builds through the middle — reveals something, shows something, takes you somewhere
- Lands with a clear close — CTA, key takeaway, or satisfying end

Check only what's actually in the transcript. Don't invent content that isn't there.

Scoring:
5 = strong arc — hook, build, and landing all working together
4 = mostly there — structure is clear even if informal
3 = watchable but loose — meanders a bit (normal for unscripted content that's still followable)
2 = hard to follow — confusing jumps that need editorial intervention
1 = no story — needs heavy restructuring in the edit

Max 3 strengths and 3 improvements. Every improvement must be something an editor can do in post — no production notes.

Return EXACTLY this JSON with no markdown:
{{
  "score": 3,
  "summary": "Direct one-liner on the story structure — is it working?",
  "strengths": [
    "specific thing working in this video"
  ],
  "improvements": [
    "specific edit-room fix — cut, reorder, overlay, or caption — not a filming note"
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
                "score": parsed.get("score", 3),
                "summary": parsed.get("summary", "Could not analyze story clarity reliably."),
                "strengths": parsed.get("strengths", []),
                "improvements": parsed.get("improvements", []),
            }
    except Exception:
        pass

    return {
        "score": 3,
        "summary": "Could not analyze story clarity reliably.",
        "strengths": [],
        "improvements": [],
    }
