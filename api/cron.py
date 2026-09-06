import os
import random
import requests
from http.server import BaseHTTPRequestHandler

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

def get_random_snippet():
    # Read the markdown file bundled in the project root
    file_path = os.path.join(os.path.dirname(__file__), "..", "tech_notes.md")
    if not os.path.exists(file_path):
        return None

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Filter for meaningful bullet points, sentences, or sections (> 40 chars)
    lines = [
        line.strip() 
        for line in content.split("\n") 
        if len(line.strip()) > 40 and not line.strip().startswith("```")
    ]
    
    if not lines:
        return content[:400]
    return random.choice(lines)

def summarize_with_groq(snippet):
    url = "[https://api.groq.com/openai/v1/chat/completions](https://api.groq.com/openai/v1/chat/completions)"
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
    url = f"[https://api.telegram.org/bot](https://api.telegram.org/bot){TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"💡 *Daily Tech Note Drip*\n\n{text}",
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload, timeout=15)

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        snippet = get_random_snippet()
        if not snippet:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"No notes found")
            return

        try:
            summary = summarize_with_groq(snippet)
            send_telegram(summary)
            
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Drip sent successfully!")
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f"Error: {e}".encode())