from connection import ask_ai
from utils import parse_json_object


def extract_glossary(transcript: str) -> list[str]:
    """
    Automatically extract proper nouns, brand names, product names,
    and non-English words from the transcript so checkers don't flag them.
    Works for any video — no hardcoded list needed.
    """
    text_part = transcript[:1200]

    prompt = f"""
You are reading a video transcript and identifying words that should NOT be treated as spelling errors or grammar mistakes.

YOUR TASK:
Extract a list of:
- Brand names (e.g. Koocester, GrabFood, Shopee, Mamee)
- Product names (e.g. Muruking, Twisties, MyKad)
- People's names
- Place names specific to this content
- Non-English words used intentionally (Malay, Indonesian, etc.)
- Channel names or company names
- Any unusual proper nouns that appear intentional

RULES:
- Only include words that are clearly intentional proper nouns
- Do NOT include common English words
- Do NOT include words that are genuinely misspelled
- If unsure, include it (better safe than flagging a real brand)
- Return ONLY valid JSON, no explanation

Return EXACTLY this format:
{{
  "glossary": ["Word1", "Word2", "Word3"]
}}

If nothing found:
{{"glossary": []}}

Transcript:
{text_part}
"""

    try:
        result = ask_ai(prompt).strip()
        data = parse_json_object(result)
        if data:
            glossary = data.get("glossary", [])
            if isinstance(glossary, list):
                return [str(w).strip() for w in glossary if str(w).strip()]
    except Exception:
        pass

    return []