from connection import ask_ai_images
from utils import parse_json_object, validate_severity


# Title card rules per content type, pulled directly from the Koocester SOP
TITLE_CARD_RULES = {
    "Business & Wealth": """TITLE CARD RULES — Business & Wealth:
- Role text: Times New Roman, italic, white (#FFFFFF)
- Interviewee Full Name: Helvetica, white (#FFFFFF)
- Company Name: Helvetica, white (#FFFFFF), 85% opacity, with a glow effect
These should appear as lower-thirds at specific screen positions.""",

    "Homes": """TITLE CARD RULES — Homes:
- Property Type: Inter font, white (#FFFFFF)
- Price: Inter Black, italic, green (#00FF18) — must have a green glow
- Interviewee Full Name: Helvetica, white (#FFFFFF)
- Role: Times New Roman, italic, white (#FFFFFF)""",

    "Autos": """TITLE CARD RULES — Autos:
- Car Name: Inter font, white (#FFFFFF), slide-up animation in, fade-out animation out
- Car Price: Inter font, green (#00FF18), green glow effect, slide-up in, fade-out out
- Car Masking: white glow stroke, fade-out animation out""",

    "Foodie": """TITLE CARD RULES — Foodie:
- Food/Place Name: Inter font, white (#FFFFFF), slide-up animation in, fade-out out
- Price: Inter font, green (#00FF18), green glow, slide-up in, fade-out out
- Subject masking: white glow stroke, fade-out out""",

    "General": """Check for any title cards or lower-thirds and whether they look professionally formatted and consistent with the Koocester style.""",
}

SUBTITLE_COLOUR_RULES = """SUBTITLE COLOUR RULES (Koocester SOP):
- Interviewer subtitles: WHITE (#FFFFFF), Helvetica font
- Interviewee subtitles: YELLOW (#FFCB00), Helvetica font
- Highlight / key statements: GREEN (#00FF18)
- Negative statements: RED (#EC1D1D)
Wrong subtitle colour = flag it."""


def safe_json_parse(result: str):
    return parse_json_object(result)


def check_sop(transcript: str, frames: list, content_type: str = "General") -> list:
    """
    Check video frames against Koocester brand SOP.
    Returns QC board rows — same format as all other checkers.
    """
    if not frames:
        return []

    all_images = [f["base64"] for f in frames if f.get("base64")]
    if not all_images:
        return []

    title_rules = TITLE_CARD_RULES.get(content_type, TITLE_CARD_RULES["General"])

    frames_index = "\n".join(
        f"- Frame {i+1}: t={f.get('timestamp', 'N/A')}"
        for i, f in enumerate(frames)
    )

    prompt = f"""
You're doing a Koocester brand compliance check on this video. Content type: {content_type}

Check every frame against the six rules below. Be direct — this goes straight to the editor.
Only flag what you can actually see. Don't invent problems.

---

1. WATERMARK
- Must be visible from the very first frame to the very last.
- Fixed position — no movement, no fading, no repositioning.
- Missing at any point, or only partly visible → flag as High.

---

2. CTA (Call to Action)
- The Koocester CTA video from CapCut space must play at the END. Watermark alone does NOT count.
- Look for: "Follow", "Subscribe", social handles, Koocester follow cards, branded end-cards.
- Check the final frames specifically.
- No CTA visible → flag as High.
- CTA present → note the timestamp.

---

3. SUBTITLE COLOURS
{SUBTITLE_COLOUR_RULES}
- Scan every frame for visible subtitle or caption text.
- Interviewer text not white (#FFFFFF) → flag it.
- Interviewee text not yellow (#FFCB00) → flag it.
- Key statement text should be green (#00FF18), negative statements red (#EC1D1D).
- If you can see text but can't confirm colour → note it as "verify manually".

---

4. TITLE CARDS
{title_rules}
- Look for lower-thirds or title card overlays, especially in opening frames.
- Flag if title cards are wrong colour, missing required elements, or wrong font style.
- Flag if a title card is expected for this content type but none is visible.

---

5. KA-CHING ANIMATION (all content types)
The Ka-Ching animation is used for price/value reveals. When you see a price or value highlight on screen, check:
- Line 1: Helvetica font, WHITE text
- Line 2: Inter Black font, GREEN text (#00FF18), with a green glow effect
- Animation: slides up in, fades out
- If a price overlay is visible but the colours or style are clearly wrong → flag it as Medium.
- If no price moment appears in the frames → leave this section empty (it may not apply).

---

6. TEXT ANIMATION STYLE (only flag CLEAR violations)
Koocester subtitle animation rules:
- INTERVIEWER subtitles: Helvetica font, WHITE (#FFFFFF), slide-up animation
- INTERVIEWEE subtitles: Helvetica font, YELLOW (#FFCB00) — option 1 has no animation, option 2 has slide-up for key statements
- Do NOT flag if you're unsure — only flag if you can clearly see the wrong colour or an obviously broken style.
- A subtitle that is clearly white when it should be yellow (or vice versa) = flag as Medium.

---

Frame index (in order):
{frames_index}

For each issue give:
- Which rule is violated (Watermark, CTA, Subtitle Colour, Title Card, Ka-Ching, Text Animation)
- The timestamp of the frame where you saw it (or "Opening" / "End" if approximate)
- Exactly what the editor needs to do to fix it

Return ONLY valid JSON:
{{
  "issues": [
    {{
      "category": "Watermark | CTA | Subtitle Colour | Title Card | Ka-Ching | Text Animation",
      "snippet": "brief description of what you saw or didn't see",
      "issue": "straight-up description of the SOP violation",
      "suggestion": "exactly what the editor needs to fix in CapCut",
      "severity": "High | Medium | Low",
      "timestamp": "MM:SS or Opening or End"
    }}
  ]
}}

If no SOP issues: {{"issues": []}}
"""

    try:
        # Cap at 12 frames to stay within API limits
        result = ask_ai_images(prompt, all_images[:12])
        parsed = safe_json_parse(result)
        if not parsed:
            return []

        rows = []
        seen = set()

        for item in parsed.get("issues", []):
            issue = str(item.get("issue", "")).strip()
            suggestion = str(item.get("suggestion", "")).strip()
            category = str(item.get("category", "SOP")).strip()
            snippet = str(item.get("snippet", "")).strip() or f"Brand check — {category}"
            severity = validate_severity(item.get("severity", "Medium"))
            timestamp = str(item.get("timestamp", "N/A")).strip()

            if not issue:
                continue

            key = (issue.lower(), category.lower())
            if key in seen:
                continue
            seen.add(key)

            rows.append({
                "Type": f"SOP — {category}",
                "Location": "Visual",
                "Snippet": snippet[:120],
                "Issue": issue,
                "Suggestion": suggestion if suggestion else "Fix to match Koocester brand SOP.",
                "Severity": severity,
                "Timestamp": timestamp,
            })

        return rows

    except Exception:
        return []
