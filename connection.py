import mimetypes
import os
import time

from typing import Any, Dict, List, Optional

import requests

# Load API key from env first (worker-safe), fall back to Streamlit secrets.
# This must NOT call st.secrets at module level — that crashes the worker process.
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
if not OPENAI_API_KEY:
    try:
        import streamlit as _st
        OPENAI_API_KEY = _st.secrets.get("OPENAI_API_KEY", "")  # type: ignore[assignment]
    except Exception:
        pass


# Text-only tasks (grammar, typo, story clarity, summaries) — fast and cheap
OPENAI_MODEL = "gpt-5.2"

# Vision tasks (SOP checks, CTA detection, visual review) — full model for colour/animation accuracy
OPENAI_VISION_MODEL = "gpt-5.2"

OPENAI_AUDIO_MODEL = "gpt-audio"
OPENAI_TRANSCRIBE_MODEL = "whisper-1"
OPENAI_TRANSCRIBE_RESPONSE_FORMAT = ""

RESPONSES_URL = "https://api.openai.com/v1/responses"
CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"


def _headers() -> Dict[str, str]:
    if not OPENAI_API_KEY:
        raise Exception("Missing OPENAI_API_KEY")
    return {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
    }


def _extract_response_text(result: Dict[str, Any]) -> str:
    output_text = result.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    texts: List[str] = []

    for item in result.get("output", []) or []:
        for content in item.get("content", []) or []:
            ctype = content.get("type")
            if ctype in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str):
                    texts.append(text)
                elif isinstance(text, dict):
                    maybe = text.get("value") or text.get("text")
                    if isinstance(maybe, str):
                        texts.append(maybe)

    final_text = "\n".join(t for t in texts if t).strip()
    if not final_text:
        raise Exception(f"OpenAI returned no text content: {str(result)[:1200]}")
    return final_text


def _is_retryable(status_code: int) -> bool:
    """Return True for status codes worth retrying (rate limits, transient server errors)."""
    return status_code in {429, 500, 502, 503, 504}


def _post_responses(
    content: List[Dict[str, Any]],
    model: Optional[str] = None,
    max_retries: int = 3,
    base_delay: float = 2.0,
) -> str:
    payload = {
        "model": model or OPENAI_MODEL,
        "input": [
            {
                "role": "user",
                "content": content,
            }
        ],
    }

    last_exc: Exception = Exception("No attempts made")
    for attempt in range(max_retries):
        try:
            response = requests.post(
                RESPONSES_URL,
                headers={**_headers(), "Content-Type": "application/json"},
                json=payload,
                timeout=600,
            )
            if not response.ok:
                if _is_retryable(response.status_code) and attempt < max_retries - 1:
                    time.sleep(base_delay * (2 ** attempt))
                    continue
                raise Exception(
                    f"OpenAI Responses error {response.status_code}: {response.text[:1200]}"
                )
            return _extract_response_text(response.json())
        except requests.exceptions.Timeout as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))
        except Exception as exc:
            raise exc  # non-retryable errors propagate immediately

    raise last_exc


def ask_ai(prompt: str) -> str:
    return _post_responses([
        {
            "type": "input_text",
            "text": prompt,
        }
    ])


def _image_data_url(image_base64_or_url: str) -> str:
    image = str(image_base64_or_url or "").strip()
    if image.startswith("data:image/"):
        return image
    return f"data:image/jpeg;base64,{image}"


def ask_ai_images(prompt: str, images_base64: list) -> str:
    """Send prompt + images to the configured vision model via Responses API."""
    content: List[Dict[str, Any]] = [
        {
            "type": "input_text",
            "text": prompt,
        }
    ]

    for img in images_base64 or []:
        content.append(
            {
                "type": "input_image",
                "image_url": _image_data_url(img),
            }
        )

    return _post_responses(content, model=OPENAI_VISION_MODEL)


def ask_ai_multimodal(prompt: str, images_base64: Optional[list] = None) -> str:
    """Send prompt + optional images to the configured vision model via Responses API."""
    content: List[Dict[str, Any]] = [
        {
            "type": "input_text",
            "text": prompt,
        }
    ]

    for img in images_base64 or []:
        content.append(
            {
                "type": "input_image",
                "image_url": _image_data_url(img),
            }
        )

    return _post_responses(content, model=OPENAI_VISION_MODEL)


def _post_chat_completions(
    messages: List[Dict[str, Any]],
    model: str,
    max_retries: int = 3,
    base_delay: float = 2.0,
) -> str:
    payload = {
        "model": model,
        "messages": messages,
    }

    last_exc: Exception = Exception("No attempts made")
    for attempt in range(max_retries):
        try:
            response = requests.post(
                CHAT_COMPLETIONS_URL,
                headers={**_headers(), "Content-Type": "application/json"},
                json=payload,
                timeout=600,
            )
            if not response.ok:
                if _is_retryable(response.status_code) and attempt < max_retries - 1:
                    time.sleep(base_delay * (2 ** attempt))
                    continue
                raise Exception(
                    f"OpenAI Chat Completions error {response.status_code}: {response.text[:1200]}"
                )
            data = response.json()
            try:
                return data["choices"][0]["message"]["content"]
            except (KeyError, IndexError) as exc:
                raise Exception(
                    f"Unexpected chat completions response: {str(data)[:1200]}"
                ) from exc
        except requests.exceptions.Timeout as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))
        except Exception as exc:
            raise exc

    raise last_exc


def ask_ai_audio(prompt: str, audio_base64: str) -> str:
    """Send prompt + MP3 audio to the configured audio model via Chat Completions."""
    return _post_chat_completions(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": audio_base64,
                            "format": "mp3",
                        },
                    },
                ],
            }
        ],
        model=OPENAI_AUDIO_MODEL,
    )


def _audio_mime_type(audio_path: str) -> str:
    guessed, _ = mimetypes.guess_type(audio_path)
    return guessed or "application/octet-stream"


def _transcription_response_format(model: str) -> str:
    model = (model or "").strip()
    requested = (OPENAI_TRANSCRIBE_RESPONSE_FORMAT or "").strip()

    if model == "whisper-1":
        allowed = {"json", "text", "srt", "verbose_json", "vtt"}
        return requested if requested in allowed else "verbose_json"

    if model == "gpt-4o-transcribe-diarize":
        allowed = {"json", "text", "diarized_json"}
        return requested if requested in allowed else "diarized_json"

    if model in {"gpt-4o-transcribe", "gpt-4o-mini-transcribe"}:
        allowed = {"json", "text"}
        return requested if requested in allowed else "json"

    return requested or "json"


def transcribe_audio_file(audio_path: str, hint_words: Optional[str] = None) -> Dict[str, Any]:
    model = OPENAI_TRANSCRIBE_MODEL
    response_format = _transcription_response_format(model)

    with open(audio_path, "rb") as f:
        files = {
            "file": (os.path.basename(audio_path), f, _audio_mime_type(audio_path)),
        }
        base_prompt = (
            "The speaker is using Singaporean or Malaysian accented English. "
            "Transcribe in English only. "
            "Do not translate into Malay. "
            "Preserve natural spoken phrasing and names as accurately as possible."
        )
        whisper_prompt = base_prompt
        if hint_words:
            whisper_prompt += f" Key words in this video: {hint_words}."

        data = {
            "model": model,
            "response_format": response_format,
            "language": "en",
        }

        # gpt-4o-transcribe-diarize does not support prompt. Other supported
        # transcription models can use it to improve local names and phrasing.
        if model != "gpt-4o-transcribe-diarize":
            data["prompt"] = whisper_prompt

        if model == "gpt-4o-transcribe-diarize":
            data["chunking_strategy"] = "auto"

        response = requests.post(
            TRANSCRIPTIONS_URL,
            headers=_headers(),
            files=files,
            data=data,
            timeout=600,
        )

    if not response.ok:
        raise Exception(f"OpenAI transcription error {response.status_code}: {response.text[:1200]}")

    if response_format == "text":
        return {"text": response.text.strip(), "segments": []}

    result = response.json()
    if not isinstance(result, dict):
        raise Exception(f"Unexpected transcription response: {str(result)[:1200]}")
    return result
