import base64
import subprocess
import tempfile
import os
from connection import ask_ai_audio
from utils import parse_json_object


def audio_file_to_base64(audio_path: str) -> str:
    with open(audio_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def safe_json_parse(result: str):
    return parse_json_object(result)


def get_ffmpeg_audio_stats(audio_path: str):
    """
    Uses ffmpeg volumedetect to extract basic loudness stats.
    """
    cmd = [
        "ffmpeg",
        "-i", audio_path,
        "-af", "volumedetect",
        "-f", "null",
        "-",  # output to stdout (discarded) — avoids os.devnull path differences
    ]

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
    except Exception:
        return {"mean_volume": None, "max_volume": None}

    output = result.stderr

    mean_volume = None
    max_volume = None

    for line in output.splitlines():
        line = line.strip()
        if "mean_volume:" in line:
            try:
                mean_volume = float(line.split("mean_volume:")[1].split(" dB")[0].strip())
            except (ValueError, IndexError):
                pass
        if "max_volume:" in line:
            try:
                max_volume = float(line.split("max_volume:")[1].split(" dB")[0].strip())
            except (ValueError, IndexError):
                pass

    return {
        "mean_volume": mean_volume,
        "max_volume": max_volume
    }


def fallback_audio_review(audio_path: str):
    stats = get_ffmpeg_audio_stats(audio_path)

    mean_vol = stats.get("mean_volume")
    max_vol = stats.get("max_volume")

    score = 3
    strengths = []
    issues = []
    suggestions = []

    if mean_vol is not None:
        if mean_vol < -30:
            score = 2
            issues.append("Overall audio level seems quite low.")
            suggestions.append("Increase vocal loudness or overall mix level.")
        elif -24 <= mean_vol <= -12:
            strengths.append("Overall loudness appears reasonably balanced.")
        elif mean_vol > -10:
            score = 2
            issues.append("Overall audio may be too loud or overly compressed.")
            suggestions.append("Reduce loudness slightly and check for harshness.")

    if max_vol is not None:
        if max_vol >= -1:
            issues.append("Audio peaks are very close to clipping.")
            suggestions.append("Lower peak levels slightly to avoid distortion.")
            score = min(score, 2)
        elif max_vol <= -6:
            strengths.append("Peak levels appear controlled.")

    if not strengths and not issues:
        strengths.append("Basic audio signal could be processed.")
        suggestions.append("Review voice clarity and SFX balance manually if needed.")

    summary = "Audio fallback review generated from technical signal checks."
    if issues:
        summary += " Some mix issues may need manual review."
    else:
        summary += " No obvious loudness problem was detected."

    return {
        "score": score,
        "summary": summary,
        "strengths": strengths,
        "issues": issues,
        "suggestions": suggestions,
        "timestamp_notes": []
    }


def check_audio(audio_path: str, transcript: str):
    audio_base64 = audio_file_to_base64(audio_path)

    prompt = f"""
You're a senior Koocester editor doing an audio QC pass on this video.

Koocester audio standard:
- Raw footage audio should be at max — no quiet or muffled delivery
- Fade in and fade out on raw audio should be 0.0 (no fade)
- SFX should be futuristic and premium — from the CapCut library
- Voice needs to sit clearly above music and SFX
- No distracting background noise, hiss, or clipping

What you're checking:
- Is the voice clear and easy to hear throughout? Or does it get buried under music/SFX?
- Is there any obvious clipping, distortion, or dead silence that shouldn't be there?
- Do the SFX feel intentional and polished, or messy and random?
- Any specific moments where the audio clearly drops off, spikes, or cuts weirdly?

SFX NOTE: dings, whooshes, and transition sounds are part of the Koocester style. Don't flag them unless they're actually drowning out the speaker or ruining the experience.

Only flag things that would genuinely affect the viewer. Be specific — if there's a problem, say when and what it is.

Scoring:
5 = polished audio — voice clear, SFX balanced, nothing to fix
4 = good, one small thing to address
3 = acceptable but something needs attention
2 = noticeable problem that will put viewers off
1 = bad audio — fix before uploading

Return EXACT JSON:

{{
  "score": 3,
  "summary": "Straight verdict on the audio quality.",
  "strengths": ["what's working"],
  "issues": ["what's wrong — be specific"],
  "suggestions": ["exactly how to fix it"],
  "timestamp_notes": ["MM:SS - specific moment to check"]
}}

Transcript:
{transcript[:800]}
"""

    try:
        result = ask_ai_audio(prompt, audio_base64)
        parsed = safe_json_parse(result)

        if parsed:
            return {
                "score": parsed.get("score", 3),
                "summary": parsed.get("summary", "Could not analyze audio reliably."),
                "strengths": parsed.get("strengths", []),
                "issues": parsed.get("issues", []),
                "suggestions": parsed.get("suggestions", []),
                "timestamp_notes": parsed.get("timestamp_notes", [])
            }
    except Exception as e:
        # Surface the error in the fallback so it's visible in the report
        fallback = fallback_audio_review(audio_path)
        fallback["summary"] = (
            f"AI audio review failed ({type(e).__name__}: {str(e)[:200]}). "
            f"Falling back to technical signal check. {fallback['summary']}"
        )
        return fallback

    # fallback if AI returned unparseable output
    fallback = fallback_audio_review(audio_path)
    fallback["summary"] = (
        "AI audio review returned unparseable output. "
        f"Falling back to technical signal check. {fallback['summary']}"
    )
    return fallback
   