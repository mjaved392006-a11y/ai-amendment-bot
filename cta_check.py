from connection import ask_ai_images
from utils import parse_json_object, validate_severity

# Max frames sent per API call — keeps cost predictable
_MAX_DENSE_FRAMES_PER_CALL = 30
_MAX_END_FRAMES_PER_CALL = 12


def safe_json_parse(result: str):
    return parse_json_object(result)


def _build_rows(parsed: dict, cta_type: str) -> list:
    """Convert parsed AI output into QC board rows."""
    rows = []
    seen = set()

    for item in (parsed or {}).get("issues", []):
        issue = str(item.get("issue", "")).strip()
        suggestion = str(item.get("suggestion", "")).strip()
        snippet = str(item.get("snippet", "")).strip() or f"CTA check — {cta_type}"
        severity = validate_severity(item.get("severity", "High"), default="High")
        timestamp = str(item.get("timestamp", "N/A")).strip()

        if not issue:
            continue

        key = (issue.lower(), cta_type.lower())
        if key in seen:
            continue
        seen.add(key)

        rows.append({
            "Type": f"CTA — {cta_type}",
            "Location": "Visual",
            "Snippet": snippet[:120],
            "Issue": issue,
            "Suggestion": suggestion if suggestion else "Add the Koocester CTA from CapCut space.",
            "Severity": severity,
            "Timestamp": timestamp,
        })

    return rows


def _check_end_cta(end_frames: list) -> list:
    """
    Dedicated end-CTA pass using targeted frames from the final seconds.
    """
    if not end_frames:
        return [{
            "Type": "CTA — End",
            "Location": "Visual",
            "Snippet": "End of video",
            "Issue": "Could not extract end frames — CTA presence unverified.",
            "Suggestion": "Make sure the Koocester CTA video from CapCut space is applied at the end.",
            "Severity": "High",
            "Timestamp": "End",
        }]

    images = [f["base64"] for f in end_frames[:_MAX_END_FRAMES_PER_CALL] if f.get("base64")]
    frames_index = "\n".join(
        (
            f"- Frame {i+1}: t={f.get('timestamp', 'N/A')} "
            f"source={f.get('source', 'end')} "
            f"debug={f.get('debug_path', '')}"
        )
        for i, f in enumerate(end_frames[:_MAX_END_FRAMES_PER_CALL])
    )
    duration = end_frames[0].get("video_duration", "unknown") if end_frames else "unknown"

    prompt = f"""
You're a senior Koocester editor checking if the end CTA is properly applied.

These frames are targeted samples from the final part of the video.
Video duration: {duration}s.
The source labels mean:
- last_5s = frame around 5 seconds before the end
- last_3s = frame around 3 seconds before the end
- last_2s = frame around 2 seconds before the end
- last_1s = frame around 1 second before the end
- true_final = closest frame we could extract to the actual final frame

Koocester SOP: every video must end with the CTA video from CapCut space. The watermark alone does NOT count as a CTA.

What counts as a CTA:
- Koocester branded end card / CTA clip
- "Follow us"
- "Follow for more" text overlay
- Explicit CTA text
- Social handle callout (@koocester or similar)
- Branded follow animation or end screen
- Koocester logo/page name used as a closing graphic
- "Watch more"
- "Contact us"
- "DM us"
- Any closing graphic or branded ending screen

What does NOT count:
- The watermark logo sitting in the corner
- A blank frame
- The subject still talking

Frame index:
{frames_index}

Answer straight:
- Is the Koocester CTA card / end screen clearly visible in these final frames?
- If YES: note the timestamp it appears
- If NO: say whether:
  1. no CTA/end-card exists in the sampled final frames, OR
  2. the sampled frames may not include the real ending/end-card

Use option 2 only if the true_final frame still looks like regular footage or the samples appear not to reach the actual closing screen.
Do not mark a CTA as missing if any final frame shows Follow us, a social handle, Watch more, Contact us, DM us, a Koocester page/name card, or any branded closing graphic.

Return ONLY valid JSON:
{{
  "issues": [
    {{
      "snippet": "brief description of what's visible in the final frames",
      "issue": "CTA present, missing, or sampling may not include real ending - straight answer",
      "suggestion": "what the editor needs to do, or which debug frames to verify",
      "severity": "High | Medium | Low",
      "timestamp": "MM:SS when CTA appears, or End if missing"
    }}
  ]
}}

If the CTA is clearly present and correct: {{"issues": []}}
"""

    try:
        result = ask_ai_images(prompt, images)
        parsed = safe_json_parse(result)
        if parsed is None:
            return []
        return _build_rows(parsed, "End")
    except Exception:
        return [{
            "Type": "CTA — End",
            "Location": "Visual",
            "Snippet": "End of video",
            "Issue": "End CTA check failed — verify manually.",
            "Suggestion": "Check the final seconds — Koocester CTA from CapCut space must be applied.",
            "Severity": "High",
            "Timestamp": "End",
        }]


def _check_mid_cta(dense_frames: list) -> list:
    """
    Mid-video CTA pass using 1fps dense scan across the whole video.
    Catches half-second CTA overlays that scene-change sampling misses.
    Sent in batches of 30 frames so nothing exceeds API limits.
    """
    if not dense_frames:
        return []

    # Split into batches of 30 frames each
    batch_size = _MAX_DENSE_FRAMES_PER_CALL
    batches = [
        dense_frames[i: i + batch_size]
        for i in range(0, len(dense_frames), batch_size)
    ]

    all_rows = []

    for batch_idx, batch in enumerate(batches):
        images = [f["base64"] for f in batch if f.get("base64")]
        if not images:
            continue

        frames_index = "\n".join(
            f"- Frame {i+1}: t={f.get('timestamp', 'N/A')}"
            for i, f in enumerate(batch)
        )

        # Label the time range this batch covers
        first_ts = batch[0].get("timestamp", "?")
        last_ts = batch[-1].get("timestamp", "?")

        prompt = f"""
You're a senior Koocester editor scanning for mid-video CTA overlays.

These frames cover {first_ts} → {last_ts} at 1 frame per second — every second is represented, so even a half-second CTA flash will appear in at least one frame.

Koocester mid-video CTAs look like:
- Text overlay ("Follow for more", "Check the link", "@handle")
- Ka-Ching animation (price/value reveal with Helvetica + Inter Black)
- Branded graphic insert or animated text card
- Any overlay that appears for a moment and then disappears

NOT a mid-CTA:
- The persistent watermark in the corner
- Subtitle text
- Title cards (those are intro elements, not CTAs)

Frame index ({first_ts} → {last_ts}):
{frames_index}

Scan every frame carefully. If you spot a CTA overlay — even briefly:
- Note the timestamp it appears
- Confirm whether it's readable and correctly placed

If no mid-video CTA appears in this section, return an empty issues list — the mid-CTA may be in a different part of the video or may not be required for this video type.

Only flag it if the overlay is present but broken (wrong position, unreadable, cut off).

Return ONLY valid JSON:
{{
  "issues": [
    {{
      "snippet": "description of what's visible at that moment",
      "issue": "what's wrong with the CTA overlay",
      "suggestion": "how to fix it",
      "severity": "High | Medium | Low",
      "timestamp": "MM:SS"
    }}
  ]
}}

If no CTA issues in this batch: {{"issues": []}}
"""

        try:
            result = ask_ai_images(prompt, images)
            parsed = safe_json_parse(result)
            if parsed:
                all_rows.extend(_build_rows(parsed, "Mid-video"))
        except Exception:
            continue  # Skip failed batch, don't block other results

    return all_rows


def check_cta(transcript: str, dense_frames: list, end_frames: list) -> list:
    """
    Full CTA check — runs end-CTA and mid-video CTA detection.
    End frames: 1fps last 10 seconds — catches static end cards.
    Dense frames: 1fps whole video — catches brief mid-video overlays.
    Returns QC board rows.
    """
    rows = []

    # End CTA is the critical one — always run it
    rows.extend(_check_end_cta(end_frames))

    # Mid-video CTA — run if we have dense frames
    if dense_frames:
        rows.extend(_check_mid_cta(dense_frames))

    return rows
