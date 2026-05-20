import base64
import json  # still used in extract_end_frames manifest write
import os
import subprocess
import tempfile

from connection import ask_ai_images
from utils import parse_json_object


def get_video_duration(video_path: str) -> float:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except:
        return 60.0


def seconds_to_mmss(seconds: float) -> str:
    total = int(seconds)
    mm = total // 60
    ss = total % 60
    return f"{mm:02d}:{ss:02d}"


def file_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def safe_json_parse(result: str):
    return parse_json_object(result)


def _legacy_extract_frames(video_path: str, num_frames: int = 4):
    """Original fixed-percentage extraction kept as a safety-net fallback."""
    duration = get_video_duration(video_path)
    temp_dir = tempfile.mkdtemp(prefix="frames_legacy_")
    ratios = [0.10, 0.35, 0.60, 0.93][:num_frames]
    frames = []

    for i, ratio in enumerate(ratios, start=1):
        ts = duration * ratio
        out_path = os.path.join(temp_dir, f"frame_{i:02d}.jpg")
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(ts),
            "-i", video_path,
            "-frames:v", "1",
            "-vf", "scale='min(1280,iw)':-2",
            "-q:v", "4",
            out_path,
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(out_path):
            frames.append({
                "timestamp": seconds_to_mmss(ts),
                "base64": file_to_base64(out_path),
            })

    return frames


def extract_frames(
    video_path: str,
    num_frames: int = None,
    max_frames: int = 16,
    scene_threshold: float = 0.30,
    min_interval_sec: float = 2.0,
):
    """
    Sample frames covering the ENTIRE video, with scene-change awareness.

    Strategy:
      1. ffmpeg's scene-change detector picks frames where the visual content
         changes significantly (CTAs, b-roll inserts, cuts, end cards).
      2. Interval sampling guarantees coverage of static stretches — the
         interval scales with duration so a 5-minute video doesn't blow up
         the frame count.
      3. The result is capped at `max_frames` to keep API cost predictable.

    Backward-compatible: callers passing `num_frames=4` still work; `num_frames`
    is treated as a soft floor on the cap.
    """
    if num_frames is not None:
        max_frames = max(int(num_frames), max_frames)

    duration = get_video_duration(video_path)
    temp_dir = tempfile.mkdtemp(prefix="frames_")

    # Scale interval so very long videos don't generate hundreds of frames.
    # e.g. 60s video / 16 frames = ~4s interval (clamped to min_interval_sec).
    target_interval = max(min_interval_sec, duration / max(max_frames, 1))

    # Combined ffmpeg select filter — pick a frame if ANY of these are true:
    #   gt(scene, T)                  -> significant visual change
    #   isnan(prev_selected_t)        -> first frame (always include opener)
    #   gte(t - prev_selected_t, I)   -> at least I seconds since last keep
    select_expr = (
        f"select='gt(scene\\,{scene_threshold})"
        f"+isnan(prev_selected_t)"
        f"+gte(t-prev_selected_t\\,{target_interval})',"
        f"scale='min(1280,iw)':-2,"
        f"showinfo"
    )

    out_pattern = os.path.join(temp_dir, "frame_%04d.jpg")

    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vf", select_expr,
        "-vsync", "vfr",
        "-q:v", "4",
        out_pattern,
    ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
        )
    except Exception:
        # If the combined filter fails for any reason, fall back to legacy.
        return _legacy_extract_frames(video_path, num_frames=4)

    # Parse showinfo lines on stderr for the pts_time of each selected frame.
    timestamps = []
    for line in (result.stderr or "").splitlines():
        if "pts_time:" in line:
            try:
                t_str = line.split("pts_time:")[1].split()[0]
                timestamps.append(float(t_str))
            except (ValueError, IndexError):
                pass

    files = sorted(
        f for f in os.listdir(temp_dir)
        if f.startswith("frame_") and f.endswith(".jpg")
    )

    # Belt-and-braces cap: if scene detection produced more than max_frames,
    # evenly downsample so we keep coverage of the full timeline.
    if len(files) > max_frames:
        n = max_frames
        idxs = [int(round(i * (len(files) - 1) / max(n - 1, 1))) for i in range(n)]
        # de-dupe while preserving order
        seen, ordered = set(), []
        for i in idxs:
            if i not in seen:
                ordered.append(i)
                seen.add(i)
        files = [files[i] for i in ordered]
        if len(timestamps) >= max(ordered) + 1:
            timestamps = [timestamps[i] for i in ordered]

    frames = []
    for i, fname in enumerate(files):
        path = os.path.join(temp_dir, fname)
        ts = timestamps[i] if i < len(timestamps) else 0.0
        if not os.path.exists(path):
            continue
        frames.append({
            "timestamp": seconds_to_mmss(ts),
            "base64": file_to_base64(path),
        })

    # Last-resort fallback: if scene detection somehow produced nothing,
    # fall back to the original four-percentage sampler.
    if not frames:
        frames = _legacy_extract_frames(video_path, num_frames=4)

    return frames


def extract_subtitle_frames(video_path: str, interval_sec: float = 2.0) -> list:
    """
    Extract one frame every `interval_sec` seconds across the entire video.
    Designed for dense subtitle/caption OCR — guarantees every subtitle
    visible on screen is captured regardless of scene changes.

    Returns a list of dicts: [{"timestamp": "MM:SS", "base64": "..."}]
    """
    duration = get_video_duration(video_path)
    temp_dir = tempfile.mkdtemp(prefix="subtitle_frames_")

    # Use ffmpeg fps filter: 1 frame every interval_sec seconds
    fps = 1.0 / max(interval_sec, 0.5)
    out_pattern = os.path.join(temp_dir, "frame_%04d.jpg")

    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vf", f"fps={fps}",
        "-q:v", "5",   # slightly lower quality to keep file sizes small
        out_pattern,
    ]

    try:
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=300,
        )
    except Exception:
        return []

    files = sorted(
        f for f in os.listdir(temp_dir)
        if f.startswith("frame_") and f.endswith(".jpg")
    )

    frames = []
    for i, fname in enumerate(files):
        path = os.path.join(temp_dir, fname)
        if not os.path.exists(path):
            continue
        ts = i * interval_sec
        frames.append({
            "timestamp": seconds_to_mmss(ts),
            "base64": file_to_base64(path),
        })

    return frames


def extract_end_frames(video_path: str, duration_sec: float = 10.0) -> list:
    """
    Extract targeted frames from the final part of the video for end-card CTA QC.

    The end card can be very short, so this samples exact positions near the end:
    last 5s, last 3s, last 2s, last 1s, plus a true final-frame attempt.
    It also keeps a debug directory with the JPEGs and manifest so the sampled
    frames can be inspected after a run.
    """
    total = get_video_duration(video_path)
    debug_dir = tempfile.mkdtemp(prefix="end_cta_debug_")

    target_specs = [
        ("last_5s", max(0.0, total - 5.0)),
        ("last_3s", max(0.0, total - 3.0)),
        ("last_2s", max(0.0, total - 2.0)),
        ("last_1s", max(0.0, total - 1.0)),
        ("true_final", max(0.0, total - 0.08)),
    ]

    seen = set()
    frames = []

    for idx, (label, ts) in enumerate(target_specs, start=1):
        rounded_key = round(ts, 2)
        if rounded_key in seen:
            continue
        seen.add(rounded_key)

        path = os.path.join(debug_dir, f"{idx:02d}_{label}_{seconds_to_mmss(ts).replace(':', '-')}.jpg")
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", f"{ts:.3f}",
            "-i", video_path,
            "-frames:v", "1",
            "-vf", "scale='min(1280,iw)':-2",
            "-q:v", "4",
            path,
        ]

        try:
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
            )
        except Exception:
            continue

        if not os.path.exists(path):
            continue

        frames.append({
            "timestamp": seconds_to_mmss(ts),
            "seconds": round(ts, 3),
            "source": label,
            "video_duration": round(total, 3),
            "debug_dir": debug_dir,
            "debug_path": path,
            "base64": file_to_base64(path),
        })

    manifest_path = os.path.join(debug_dir, "manifest.json")
    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "video_path": video_path,
                    "video_duration_seconds": total,
                    "sampled_frames": [
                        {
                            "timestamp": frame.get("timestamp"),
                            "seconds": frame.get("seconds"),
                            "source": frame.get("source"),
                            "debug_path": frame.get("debug_path"),
                        }
                        for frame in frames
                    ],
                },
                f,
                indent=2,
            )
    except Exception:
        pass

    return frames


def extract_dense_cta_frames(video_path: str, max_frames: int = 50) -> list:
    """
    Extract 1 frame per second across the ENTIRE video for mid-CTA detection.
    Catches half-second CTA overlays that scene-change and interval sampling miss.
    Capped at `max_frames` frames (evenly sampled if the video is longer).
    Uses 960px width — smaller than main frames but still sharp enough for CTA text.
    """
    total = get_video_duration(video_path)
    temp_dir = tempfile.mkdtemp(prefix="cta_dense_")
    out_pattern = os.path.join(temp_dir, "frame_%04d.jpg")

    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vf", "fps=1,scale='min(960,iw)':-2",
        "-q:v", "5",
        out_pattern,
    ]

    try:
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=300,
        )
    except Exception:
        return []

    files = sorted(
        f for f in os.listdir(temp_dir)
        if f.startswith("frame_") and f.endswith(".jpg")
    )

    # Evenly downsample if more frames than the cap
    if len(files) > max_frames:
        n = max_frames
        idxs = [int(round(i * (len(files) - 1) / max(n - 1, 1))) for i in range(n)]
        seen_i, ordered = set(), []
        for i in idxs:
            if i not in seen_i:
                ordered.append(i)
                seen_i.add(i)
        files = [files[i] for i in ordered]

    frames = []
    for i, fname in enumerate(files):
        path = os.path.join(temp_dir, fname)
        if not os.path.exists(path):
            continue
        # Approximate timestamp from filename index (1fps = 1s per frame)
        raw_idx = int(fname.replace("frame_", "").replace(".jpg", "")) - 1
        ts = float(raw_idx)
        frames.append({
            "timestamp": seconds_to_mmss(ts),
            "base64": file_to_base64(path),
        })

    return frames

def check_visuals(video_path: str, transcript: str, frames: list | None = None):
    # Reuse pre-extracted frames if provided to avoid running ffmpeg twice.
    if not frames:
        frames = extract_frames(video_path, num_frames=4)

    if not frames:
        return {
            "score": 3,
            "summary": "Could not analyze visuals reliably because no frames were extracted.",
            "strengths": [],
            "issues": [],
            "suggestions": [],
            "frame_timestamps": []
        }

    frames_index = "\n".join(
        f"- Frame {i+1}: t={f.get('timestamp', 'N/A')}"
        for i, f in enumerate(frames)
    )

    prompt = f"""
You're a senior Koocester editor doing a visual QC pass on this video. The footage is already shot — your suggestions must be fixes the editor can apply in post.

What you're checking:
- Is the subject visible and easy to look at? If framing is off, can the editor crop or zoom to fix it?
- Is the exposure readable? If the face is in shadow or the background is blown out, can colour grading or brightness adjustment fix it?
- Are on-screen graphics, title cards, and text overlays readable and correctly placed?
- Is there a CTA at the end? Watermark alone does NOT count.
- Is the watermark visible throughout?

EDITOR SCOPE — suggestions must be post-production fixes only:
- Crop or zoom to fix framing issues
- Colour grade, brightness/contrast adjustment to fix exposure or shadow
- Flag a graphic/overlay that needs repositioning or resizing
- Flag missing or broken CTA/watermark so the editor can add or fix it

NEVER suggest:
- Refilm the shot or change camera angle
- Fix the lighting at the shoot
- The host should move or reposition themselves
- Anything that requires going back to the shoot

KOOCESTER STYLE: single-location talking-head is standard. Don't flag it for staying in one spot — that's intentional. Only flag things that actually affect viewer experience AND that the editor can fix.

CTA CHECK — do this carefully:
- Scan every frame, especially the last few
- Look for: text overlays, follow cards, social handles, branded end-cards
- Watermark-only at the end = missing CTA, flag it as High
- If a real CTA is visible, note the timestamp

Only call out what you can actually see in the frames. Reference timestamps when you flag something.

Frame index (in order):
{frames_index}

Scoring:
5 = everything clean — no post-production visual work needed
4 = solid, one small thing to tighten in the edit
3 = watchable but the editor needs to fix something
2 = real problem that will affect the viewer experience — needs editorial intervention
1 = don't upload this

Return EXACT JSON:

{{
  "score": 3,
  "summary": "One direct line on the overall visual quality.",
  "strengths": ["specific thing working — with timestamp if relevant"],
  "issues": ["specific problem — with timestamp"],
  "suggestions": ["specific post-production fix — crop, grade, reposition overlay, add CTA — not a filming note"]
}}

Transcript context:
{transcript[:800]}
"""

    try:
        result = ask_ai_images(prompt, [f["base64"] for f in frames])
        parsed = safe_json_parse(result)

        if parsed:
            return {
                "score": parsed.get("score", 3),
                "summary": parsed.get("summary", "Could not analyze visuals reliably."),
                "strengths": parsed.get("strengths", []),
                "issues": parsed.get("issues", []),
                "suggestions": parsed.get("suggestions", []),
                "frame_timestamps": [f["timestamp"] for f in frames]
            }
    except Exception as e:
        return {
            "score": 3,
            "summary": f"Could not analyze visuals reliably. Error: {str(e)[:200]}",
            "strengths": [],
            "issues": [],
            "suggestions": [],
            "frame_timestamps": [f["timestamp"] for f in frames]
        }

    return {
        "score": 3,
        "summary": "Could not analyze visuals reliably.",
        "strengths": [],
        "issues": [],
        "suggestions": [],
        "frame_timestamps": [f["timestamp"] for f in frames]
    }
