import os
import random
import html
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import PlainTextResponse

# Load .env for local testing
load_dotenv()

app = FastAPI()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")



def get_random_snippet() -> str | None:
    # Check both relative to file and project root for Vercel compatibility
    possible_paths = [
        os.path.join(os.path.dirname(__file__), "..", "tech-notes.md"),
        os.path.join(os.getcwd(), "tech-notes.md"),
    ]
    file_path = next((p for p in possible_paths if os.path.exists(p)), None)
    if not file_path:
        return None

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    blocks = [
        block.strip()
        for block in content.split("\n\n")
        if len(block.strip()) > 50 and not block.strip().startswith("```")
    ]

    if not blocks:
        return content[:400] if content.strip() else None
    return random.choice(blocks)


async def summarize_with_groq(client: httpx.AsyncClient, snippet: str) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    prompt = f"""You are an expert daily learning coach.
Excerpt from user's tech notes:
\"\"\"{snippet}\"\"\"

1. Explain this concept in 1-2 sharp, clear sentences.
2. Provide 1 practical real-world or software engineering example.
Keep the total output under 70 words. No intro or conversational filler."""

    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": 150,
    }

    res = await client.post(url, headers=headers, json=payload, timeout=20.0)
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"].strip()


async def send_telegram(client: httpx.AsyncClient, text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    escaped_text = html.escape(text)
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": f"💡 <b>Daily Tech Note Drip</b>\n\n{escaped_text}",
        "parse_mode": "HTML",
    }
    res = await client.post(url, json=payload, timeout=15.0)
    res.raise_for_status()


@app.get("/api/cron", response_class=PlainTextResponse)
@app.get("/", response_class=PlainTextResponse)
async def run_cron():

    # Validate required environment variables
    missing_vars = [
        var for var, val in [
            ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
            ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
            ("GROQ_API_KEY", GROQ_API_KEY),
        ] if not val
    ]
    if missing_vars:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Missing required environment variables: {', '.join(missing_vars)}",
        )

    snippet = get_random_snippet()
    if not snippet:
        raise HTTPException(status_code=404, detail="No valid snippets found in tech-notes.md")

    async with httpx.AsyncClient() as client:
        try:
            summary = await summarize_with_groq(client, snippet)
            await send_telegram(client, summary)
            return "Drip sent successfully!"
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Upstream API failed with status {e.response.status_code}: {e.response.text}",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))