from connection import transcribe_audio_file


def _seconds_to_mmss(value) -> str:
    try:
        total = int(float(value))
    except Exception:
        return "N/A"

    mm = total // 60
    ss = total % 60
    return f"{mm:02d}:{ss:02d}"


def transcribe_audio_with_openai(audio_path: str, hint_words: str = ""):
    parsed = transcribe_audio_file(audio_path, hint_words=hint_words or None) or {}
    if not isinstance(parsed, dict):
        parsed = {"text": str(parsed), "segments": []}

    transcript = str(parsed.get("text", "")).strip()
    raw_segments = parsed.get("segments", []) or []
    raw_words = parsed.get("words", []) or []
    segment_data = []

    if isinstance(raw_segments, list) and raw_segments:
        for seg in raw_segments:
            if not isinstance(seg, dict):
                continue
            text = str(seg.get("text", "")).strip()
            if not text:
                continue
            item = {
                "start": _seconds_to_mmss(seg.get("start")),
                "end": _seconds_to_mmss(seg.get("end")),
                "text": text,
            }
            speaker = seg.get("speaker")
            if speaker:
                item["speaker"] = str(speaker)
            segment_data.append(item)

    elif isinstance(raw_words, list) and raw_words:
        bucket = []
        bucket_start = None
        last_end = None

        for word in raw_words:
            if not isinstance(word, dict):
                continue

            start = word.get("start")
            end = word.get("end")
            text = str(word.get("word", "")).strip()

            if start is None or end is None or not text:
                continue

            if bucket_start is None:
                bucket_start = float(start)

            if bucket and float(end) - float(bucket_start) > 5.0:
                segment_data.append(
                    {
                        "start": _seconds_to_mmss(bucket_start),
                        "end": _seconds_to_mmss(last_end),
                        "text": " ".join(bucket).strip(),
                    }
                )
                bucket = []
                bucket_start = float(start)

            bucket.append(text)
            last_end = float(end)

        if bucket:
            segment_data.append(
                {
                    "start": _seconds_to_mmss(bucket_start),
                    "end": _seconds_to_mmss(last_end),
                    "text": " ".join(bucket).strip(),
                }
            )

    if not transcript and segment_data:
        transcript = " ".join(
            seg["text"] for seg in segment_data if isinstance(seg, dict) and seg.get("text")
        ).strip()

    if not transcript:
        raise Exception("Transcript was empty after parsing OpenAI response.")

    return transcript, segment_data
