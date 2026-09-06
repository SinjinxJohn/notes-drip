import os
import random
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

app = FastAPI()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

def get_random_snippet():
    # Looks for tech_notes.md in the root directory
    file_path = os.path.join(os.path.dirname(__file__), "..", "tech-notes.md")
    if not os.path.exists(file_path):
        return None

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    lines = [
        line.strip() 
        for line in content.split("\n") 
        if len(line.strip()) > 40 and not line.strip().startswith("```")
    ]
    
    if not lines:
        return content[:400]
    return random.choice(lines)

def summarize_with_groq(snippet):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    prompt = f"""
You are an expert daily learning coach.
Excerpt from user's tech notes:
"{snippet}"

1. Explain this concept in 1-2 sharp, clear sentences.
2. Provide 1 practical real-world or software engineering example.
Keep the total output under 70 words. No intro or conversational filler.
"""
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": 150
    }
    
    res = requests.post(url, headers=headers, json=payload, timeout=20)
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"].strip()

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"💡 *Daily Tech Note Drip*\n\n{text}",
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload, timeout=15)

@app.get("/api/cron", response_class=PlainTextResponse)
def run_cron():
    snippet = get_random_snippet()
    if not snippet:
        raise HTTPException(status_code=404, detail="No notes found in tech_notes.md")

    try:
        summary = summarize_with_groq(snippet)
        send_telegram(summary)
        return "Drip sent successfully!"
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))