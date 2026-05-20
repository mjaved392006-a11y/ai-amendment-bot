"""
render_check.py

Validates video export settings against Koocester SOP (Slide 26):
  - Resolution : 1920 × 1080  (1080P)
  - Codec      : H.264
  - Format     : MP4
  - FPS        : 30  (29.97 accepted as equivalent)

Pure ffprobe — no API calls, no cost, runs instantly.
Each setting is flagged as a separate QC board row so the editor
knows exactly what to fix before re-exporting.
"""

import json
import subprocess


# ── Severity per setting ──────────────────────────────────────────────────────
#   Resolution / Codec / Format → High  (upload will be rejected or look wrong)
#   FPS                         → Medium (slight mismatch, usually fixable)
_SEVERITY = {
    "Resolution": "High",
    "Codec":      "High",
    "Format":     "High",
    "FPS":        "Medium",
}


def _make_row(setting: str, found: str, issue: str, suggestion: str) -> dict:
    return {
        "Type":       f"Render Settings — {setting}",
        "Location":   "File",
        "Snippet":    found[:120],
        "Issue":      issue,
        "Suggestion": suggestion,
        "Severity":   _SEVERITY.get(setting, "Medium"),
        "Timestamp":  "N/A",
    }


def _probe(video_path: str) -> dict | None:
    """Run ffprobe and return parsed JSON, or None on failure."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,r_frame_rate",
        "-show_entries", "format=format_name",
        "-of", "json",
        video_path,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return json.loads(result.stdout)
    except Exception:
        return None


def check_render_settings(video_path: str) -> list:
    """
    Check the video file's export settings against Koocester SOP.

    Returns a list of QC board rows — one per failing setting.
    Returns an empty list if everything is compliant.
    """
    data = _probe(video_path)

    if data is None:
        return [_make_row(
            "Resolution",
            "unknown",
            "Could not read video metadata — ffprobe failed or file is corrupt.",
            "Verify the file is a valid video. Re-export from CapCut if needed.",
        )]

    streams = data.get("streams", [])
    fmt     = data.get("format", {})

    if not streams:
        return [_make_row(
            "Resolution",
            "no video stream",
            "No video stream found in file.",
            "Re-export the video from CapCut with the correct Koocester settings: 1080P, H.264, MP4, 30fps.",
        )]

    stream = streams[0]
    rows   = []

    # ── 1. Resolution ─────────────────────────────────────────────────────────
    width  = stream.get("width")
    height = stream.get("height")

    if width is not None and height is not None:
        if int(width) != 1920 or int(height) != 1080:
            rows.append(_make_row(
                "Resolution",
                f"{width}×{height}",
                f"Resolution is {width}×{height} — Koocester SOP requires 1920×1080 (1080P).",
                "Re-export at 1080P. In CapCut: tap the export icon → Resolution → 1080P.",
            ))
    else:
        rows.append(_make_row(
            "Resolution",
            "undetectable",
            "Could not detect resolution — metadata may be missing.",
            "Re-export at 1920×1080 (1080P) to be safe.",
        ))

    # ── 2. Codec ──────────────────────────────────────────────────────────────
    codec = (stream.get("codec_name") or "").lower().strip()

    if codec:
        if codec not in ("h264", "avc", "avc1"):
            rows.append(_make_row(
                "Codec",
                codec,
                f"Codec is '{codec}' — Koocester SOP requires H.264.",
                "Re-export with H.264 codec. In CapCut: tap the export icon → Codec → H.264.",
            ))
    else:
        rows.append(_make_row(
            "Codec",
            "undetectable",
            "Could not detect video codec — metadata may be missing.",
            "Re-export with H.264 codec to ensure compatibility.",
        ))

    # ── 3. Format (container) ─────────────────────────────────────────────────
    format_name = (fmt.get("format_name") or "").lower().strip()

    if format_name:
        # ffprobe may return compound names like "mov,mp4,m4a,3gp,4gp,m4b,m4r"
        # Accept anything that includes mp4 or mov (both are fine for Frame.io)
        if "mp4" not in format_name and "mov" not in format_name:
            rows.append(_make_row(
                "Format",
                format_name,
                f"Container format is '{format_name}' — Koocester SOP requires MP4.",
                "Re-export as MP4. In CapCut: tap the export icon → Format → MP4.",
            ))
    else:
        rows.append(_make_row(
            "Format",
            "undetectable",
            "Could not detect container format — metadata may be missing.",
            "Re-export as MP4 to ensure Frame.io compatibility.",
        ))

    # ── 4. Frame Rate ─────────────────────────────────────────────────────────
    r_frame_rate = (stream.get("r_frame_rate") or "").strip()

    if r_frame_rate and "/" in r_frame_rate:
        try:
            num, den = r_frame_rate.split("/")
            fps = float(num) / float(den)
            # 29.97 (30000/1001) is the broadcast-standard near-30 — always accept it
            if not (29.9 <= fps <= 30.1):
                rows.append(_make_row(
                    "FPS",
                    f"{fps:.2f} fps",
                    f"Frame rate is {fps:.2f} fps — Koocester SOP requires 30 fps.",
                    "Re-export at 30 fps. In CapCut: tap the export icon → Frame Rate → 30.",
                ))
        except (ValueError, ZeroDivisionError):
            rows.append(_make_row(
                "FPS",
                r_frame_rate,
                f"Could not parse frame rate '{r_frame_rate}' — verify it is 30 fps.",
                "Re-export at 30 fps to match Koocester SOP.",
            ))
    elif r_frame_rate:
        # Sometimes ffprobe returns a plain number
        try:
            fps = float(r_frame_rate)
            if not (29.9 <= fps <= 30.1):
                rows.append(_make_row(
                    "FPS",
                    f"{fps:.2f} fps",
                    f"Frame rate is {fps:.2f} fps — Koocester SOP requires 30 fps.",
                    "Re-export at 30 fps. In CapCut: tap the export icon → Frame Rate → 30.",
                ))
        except ValueError:
            rows.append(_make_row(
                "FPS",
                r_frame_rate,
                f"Could not parse frame rate '{r_frame_rate}' — verify it is 30 fps.",
                "Re-export at 30 fps to match Koocester SOP.",
            ))
    else:
        # No FPS data at all — low confidence, don't flag as High
        pass

    return rows
