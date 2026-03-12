
import os
import subprocess
import tempfile

from faster_whisper import WhisperModel
from hook_check import check_hook
from typo_check import check_typos
from grammar_check import check_grammar
from storytelling_check import check_storytelling
from required_elements_check import check_required_elements

def extract_full_audio(video_path: str) -> str:
    audio_fd, audio_path = tempfile.mkstemp(suffix=".mp3")
    os.close(audio_fd)

    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "libmp3lame",
        audio_path
    ]

    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return audio_path


def transcribe_video(video_path: str) -> str:
    audio_path = extract_full_audio(video_path)

    model = WhisperModel("base", compute_type="int8")

    segments, info = model.transcribe(
        audio_path,
        language="en",
        beam_size=5,
        vad_filter=True
    )

    transcript_parts = []

    for segment in segments:
        text = segment.text.strip()

        if len(text) >= 3:
            transcript_parts.append(text)

    return " ".join(transcript_parts).strip()


def run_video_qc(video_path: str):

    transcript = transcribe_video(video_path)

    print("FULL TRANSCRIPT:")
    print(transcript)

    if not transcript.strip():
        return [{
            "Type": "Video QC",
            "Location": "Video",
            "Snippet": "",
            "Issue": "No transcript generated",
            "Suggestion": "Check whether the video has clear spoken audio.",
            "Severity": "High"
        }]

    rows = []
    print("checking hook...")
    rows.extend(check_hook(transcript))
    print("hook analysed")
    print("detecting typos...")
    rows.extend(check_typos(transcript))
    print("typos detection done")
    print("checking for grammatical errors...")
    rows.extend(check_grammar(transcript))
    print("identified all grammatical errors")
    print("analysing storytelling...")
    rows.extend(check_storytelling(transcript))
    print("analysis successful")
    print("checking required elements...")
    rows.extend(check_required_elements(transcript))
    print("required elements done")
    if not rows:
        rows = [{
            "Type": "Hook",
            "Location": "Opening",
            "Snippet": transcript[:120],
            "Issue": "No hook issue detected",
            "Suggestion": "Opening appears acceptable based on current hook analysis.",
            "Severity": "Low"
        }]

    return rows