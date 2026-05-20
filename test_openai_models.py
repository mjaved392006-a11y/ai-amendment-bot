import base64
import binascii
import os
import struct
import sys
import tempfile
import wave
import zlib
from pathlib import Path

import connection


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)
    )


def tiny_png_data_url() -> str:
    header = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw_rgb_row = b"\x00\xff\xff\xff"
    png = (
        header
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(raw_rgb_row))
        + _png_chunk(b"IEND", b"")
    )
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _print_result(name: str, ok: bool, message: str):
    status = "PASS" if ok else "FAIL"
    print(f"{status} {name}: {message}")


def _preview(value: str, limit: int = 180) -> str:
    text = " ".join(str(value).split())
    return text[:limit] + ("..." if len(text) > limit else "")


def test_text():
    try:
        result = connection.ask_ai("Reply with exactly: OK")
        _print_result("text", True, f"model={connection.OPENAI_MODEL}; response={_preview(result)}")
    except Exception as exc:
        _print_result("text", False, f"model={connection.OPENAI_MODEL}; error={exc}")


def test_vision():
    try:
        result = connection.ask_ai_images(
            "Reply with exactly: OK",
            [tiny_png_data_url()],
        )
        _print_result("vision", True, f"model={connection.OPENAI_VISION_MODEL}; response={_preview(result)}")
    except Exception as exc:
        _print_result("vision", False, f"model={connection.OPENAI_VISION_MODEL}; error={exc}")


def _audio_path_from_args() -> Path | None:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    env_path = os.getenv("TEST_OPENAI_AUDIO_FILE")
    return Path(env_path) if env_path else None


def _generated_silence_wav() -> Path:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp.close()
    sample_rate = 16000
    duration_seconds = 1
    frames = b"\x00\x00" * sample_rate * duration_seconds
    with wave.open(tmp.name, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)
    return Path(tmp.name)


def test_audio(audio_path: Path | None):
    if not audio_path:
        _print_result(
            "audio",
            True,
            "skipped; set TEST_OPENAI_AUDIO_FILE or pass an MP3 path to test OPENAI_AUDIO_MODEL",
        )
        return
    if not audio_path.exists():
        _print_result("audio", False, f"file not found: {audio_path}")
        return
    if audio_path.suffix.lower() != ".mp3":
        _print_result("audio", True, "skipped; ask_ai_audio currently sends format=mp3, so pass an MP3 file")
        return

    try:
        audio_base64 = base64.b64encode(audio_path.read_bytes()).decode("utf-8")
        result = connection.ask_ai_audio("Reply with a short audio quality verdict.", audio_base64)
        _print_result("audio", True, f"model={connection.OPENAI_AUDIO_MODEL}; response={_preview(result)}")
    except Exception as exc:
        _print_result("audio", False, f"model={connection.OPENAI_AUDIO_MODEL}; error={exc}")


def test_transcription(audio_path: Path | None):
    generated_path = None
    if not audio_path:
        generated_path = _generated_silence_wav()
        audio_path = generated_path
    if not audio_path.exists():
        _print_result("transcription", False, f"file not found: {audio_path}")
        return

    try:
        parsed = connection.transcribe_audio_file(str(audio_path))
        text = str(parsed.get("text", "")).strip() if isinstance(parsed, dict) else ""
        segments = parsed.get("segments", []) if isinstance(parsed, dict) else []
        segment_count = len(segments) if isinstance(segments, list) else 0
        _print_result(
            "transcription",
            True,
            (
                f"model={connection.OPENAI_TRANSCRIBE_MODEL}; "
                f"text_len={len(text)}; segments={segment_count}; preview={_preview(text)}"
            ),
        )
    except Exception as exc:
        _print_result("transcription", False, f"model={connection.OPENAI_TRANSCRIBE_MODEL}; error={exc}")
    finally:
        if generated_path:
            try:
                generated_path.unlink()
            except OSError:
                pass


def main():
    print("Configured OpenAI models:")
    print(f"- OPENAI_MODEL={connection.OPENAI_MODEL}")
    print(f"- OPENAI_VISION_MODEL={connection.OPENAI_VISION_MODEL}")
    print(f"- OPENAI_AUDIO_MODEL={connection.OPENAI_AUDIO_MODEL}")
    print(f"- OPENAI_TRANSCRIBE_MODEL={connection.OPENAI_TRANSCRIBE_MODEL}")
    print("- API key loaded: yes" if connection.OPENAI_API_KEY else "- API key loaded: no")
    print()

    audio_path = _audio_path_from_args()
    test_text()
    test_vision()
    test_audio(audio_path)
    test_transcription(audio_path)


if __name__ == "__main__":
    main()
