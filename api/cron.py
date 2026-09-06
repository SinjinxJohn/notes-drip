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
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")



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


async def summarize_with_gemini(client: httpx.AsyncClient, snippet: str) -> str:
    # Google AI Studio OpenAI-compatible endpoint
    url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    headers = {
        "Authorization": f"Bearer {GEMINI_API_KEY}",
        "Content-Type": "application/json",
    }
    prompt = f"""You are an expert technical mentor delivering a daily bite-sized lesson.
Excerpt from user's technical notes:
\"\"\"{snippet}\"\"\"

Provide a high-value, structured breakdown between 100 and 200 words:
1. 🧠 Core Concept: Explain the core architectural or engineering concept clearly and precisely.
2. 🛠 Real-World / Production Example: Give a concrete scenario or codebase example showing why this matters in production.
3. ⚠️ Key Takeaway / Pitfall: One important rule of thumb or mistake to avoid.

Keep the total response between 100 and 200 words. Do not include conversational filler."""

    payload = {
        "model": GEMINI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.5,
        "max_tokens": 600,
    }

    res = await client.post(url, headers=headers, json=payload, timeout=25.0)
    res.raise_for_status()
    data = res.json()
    message = data.get("choices", [{}])[0].get("message", {})
    content = message.get("content") or ""

    if not content.strip():
        # Fallback to direct excerpt if model produced empty output
        content = snippet[:350]

    return content.strip()


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
            ("GEMINI_API_KEY", GEMINI_API_KEY),
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
            summary = await summarize_with_gemini(client, snippet)
            await send_telegram(client, summary)
            return "Drip sent successfully!"
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Upstream API failed with status {e.response.status_code}: {e.response.text}",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))