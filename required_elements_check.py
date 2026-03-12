def check_required_elements(transcript: str):
    text = transcript.lower()
    rows = []

    cta_keywords = [
        "follow",
        "subscribe",
        "like",
        "comment",
        "share",
        "check the link",
        "link in bio",
        "dm me",
        "message me"
    ]

    length = len(text)

    # middle = middle half of transcript
    middle_start = length // 4
    middle_end = (length * 3) // 4
    middle_text = text[middle_start:middle_end]

    # ending = last 25% of transcript
    ending_text = text[(length * 3) // 4:]

    found_mid_cta = any(keyword in middle_text for keyword in cta_keywords)
    found_ending_cta = any(keyword in ending_text for keyword in cta_keywords)

    if not found_mid_cta:
        rows.append({
            "Type": "Required Elements",
            "Location": "Middle",
            "Snippet": transcript[middle_start:middle_start + 120],
            "Issue": "No clear mid CTA detected",
            "Suggestion": "Add a mid CTA such as 'follow for more' or 'like and share'.",
            "Severity": "Medium"
        })

    if not found_ending_cta:
        rows.append({
            "Type": "Required Elements",
            "Location": "Ending",
            "Snippet": transcript[-120:],
            "Issue": "No clear ending CTA detected",
            "Suggestion": "Add an ending CTA such as 'subscribe for more' or 'check the link in bio'.",
            "Severity": "Medium"
        })

    rows.append({
        "Type": "Required Elements",
        "Location": "Transcript",
        "Snippet": transcript[:120],
        "Issue": "Watermark placement cannot be verified from transcript alone",
        "Suggestion": "Watermark verification requires frame or image analysis.",
        "Severity": "Low"
    })

    return rows