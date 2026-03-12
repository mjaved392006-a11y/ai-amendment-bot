import requests
API_KEY = "AIzaSyC8QfyRMNra6Nk-5ZiujACMvlTseGL7jEE"


def ask_ai(prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={API_KEY}"
    data = {
        "contents":[

            {
                "parts": [
                    {"text" : prompt}
                ]
            }
        ]
    }
       

    response = requests.post(url, json=data, timeout=600)
    result = response.json()

    if "candidates" not in result:
        raise Exception(f"Gemini error: {result}")

    return result["candidates"][0]["content"]["parts"][0]["text"].strip()
