from connection import ask_ai
from utils import parse_json_object, TRANSCRIPT_LIMIT


def check_information_clarity(transcript: str):
    text_part = transcript[:TRANSCRIPT_LIMIT]

    prompt = f"""
You're a senior Koocester editor checking if this video clearly communicates its main point. The footage is already shot — your job is to fix what you can in the edit.

EDITOR SCOPE — you can only suggest:
- Add a text overlay or caption to surface a key fact that gets buried in dialogue (e.g. "put the price as a text overlay at 00:45 — it's mentioned too fast to register")
- Cut a section that muddies the main point or buries the lead
- Reorder clips to front-load the key information
- Add a title card to establish context the viewer is missing
- Tighten a rambling section with a cut so the main idea hits harder

NEVER suggest:
- The host should explain something more clearly or go into more detail
- Re-recording, re-filming, or re-doing any part of the shoot
- The host should have mentioned something they didn't say
- Anything that requires changing the spoken content

Ask yourself: after watching this, does the viewer know what they just learned or why they should care? Does the key info — price, name, fact, takeaway — land clearly? If not, how can the editor fix it with the footage they have?

This is casual SG/MY content — don't penalise informal delivery. Judge whether the MESSAGE lands, not how polished the delivery is. Only call out things that are actually in the transcript.

Scoring:
5 = crystal clear — key info lands with no help from the editor
4 = mostly there — one small overlay or cut would close the gap
3 = followable but the main point needs some editorial support
2 = confusing — key points are buried and the edit needs to do real work
1 = viewer walks away with nothing — heavy restructure needed

Max 3 strengths and 3 improvements. Every improvement must be something the editor can do in post — overlays, cuts, reorders, title cards — no notes about what the host should have said.

Return EXACTLY this JSON with no markdown:
{{
  "score": 3,
  "summary": "One direct line on whether the message lands.",
  "strengths": [
    "what's communicating well — specific to this video"
  ],
  "improvements": [
    "specific edit-room fix — overlay, cut, reorder, or title card — not a filming note"
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
                "summary": parsed.get("summary", "Could not analyze information clarity reliably."),
                "strengths": parsed.get("strengths", []),
                "improvements": parsed.get("improvements", []),
            }
    except Exception:
        pass

    return {
        "score": 3,
        "summary": "Could not analyze information clarity reliably.",
        "strengths": [],
        "improvements": [],
    }
