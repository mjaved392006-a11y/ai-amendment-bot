import re
from spellchecker import SpellChecker


def check_typos(transcript: str):

    spell = SpellChecker()

    rows = []
    seen = set()

    words = re.findall(r"[A-Za-z']+", transcript)

    for word in words:

        lower = word.lower()

        if len(lower) <= 2:
            continue

        if lower in seen:
            continue

        if lower not in spell:

            correction = spell.correction(lower)

            rows.append({
                "Type": "Typos",
                "Location": "Transcript",
                "Snippet": word,
                "Issue": f"Possible spelling mistake: '{word}'",
                "Suggestion": f"Consider changing '{word}' to '{correction}'.",
                "Severity": "Low"
            })

            seen.add(lower)

        if len(rows) >= 5:
            break

    return rows