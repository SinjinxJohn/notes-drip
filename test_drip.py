import os
import asyncio
import httpx
from dotenv import load_dotenv
from api.cron import get_random_snippet

load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")


async def test_summary():
    if not GEMINI_API_KEY:
        print("❌ Error: GEMINI_API_KEY is not set.")
        print("Run with: GEMINI_API_KEY=your_key python3 test_drip.py")
        return

    snippet = get_random_snippet()
    if not snippet:
        print("❌ Error: No snippets found in tech-notes.md")
        return

    print("📄 Extracted Snippet from tech-notes.md:")
    print("=" * 60)
    print(snippet)
    print("=" * 60)
    print("\n⏳ Calling Gemini API for summary...\n")

    url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    headers = {
        "Authorization": f"Bearer {GEMINI_API_KEY}",
        "Content-Type": "application/json",
    }

    prompt = f"""You are a Principal Backend & Distributed Systems Architect.
Below is an excerpt from engineering notes on high-scale systems (Order Management System, Spring Boot/JPA, Concurrency, Kafka):
\"\"\"{snippet}\"\"\"

Provide a detailed, high-signal technical lesson with rich explanations:

📌 **Architecture & Core Concept**:
Explain the underlying concept, system design principle, and why this design choice exists in depth (3-4 sentences).

⚙️ **Production Scenario & Deep Dive**:
Walk through a concrete, high-traffic production scenario. Explain what breaks under scale without this pattern (e.g., database row locking, JVM heap memory explosion, Kafka consumer offset lag, race conditions), and detail step-by-step how this solution resolves it (4-6 sentences).

💡 **Key Takeaways & Production Gotchas**:
Provide the exact rules of thumb, edge cases, and architectural mistakes to avoid when implementing this in enterprise code (2-3 sentences).

Rules:
- Be thorough, highly technical, and practical.
- Do not cut the explanation short. Provide complete, insightful sentences.
- Avoid generic intro fluff (no "Welcome to today's lesson"). Jump straight into the breakdown."""

    payload = {
        "model": GEMINI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.4,
        "max_tokens": 4000,
    }

    async with httpx.AsyncClient() as client:
        try:
            res = await client.post(url, headers=headers, json=payload, timeout=25.0)
            res.raise_for_status()
            data = res.json()
            content = data["choices"][0]["message"]["content"].strip()
            print("🚀 Model Output:")
            print("-" * 60)
            print(content)
            print("-" * 60)
        except Exception as e:
            print(f"❌ API Call Failed: {e}")


if __name__ == "__main__":
    asyncio.run(test_summary())
