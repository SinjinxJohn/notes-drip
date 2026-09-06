# 💧 Note Drip

An automated, serverless daily learning drip bot that extracts snippets from your technical notes, summarizes them into structured, actionable engineering lessons using **Google Gemini AI**, and delivers them to your **Telegram** every morning via **Vercel Cron**.

---

## 🚀 Features

- **Automated Daily Drips**: Runs on a daily cron schedule () deployed on Vercel Serverless Functions.
- **Smart Note Chunking**: Parses markdown notes () into self-contained conceptual blocks.
- **AI-Powered Technical Breakdown**: Leverages **Google Gemini 2.0 Flash** to format every snippet into:
  1. 🧠 **Core Concept**: Clear, crisp architectural explanation.
  2. 🛠 **Real-World / Production Example**: Concrete engineering scenario.
  3. ⚠️ **Key Takeaway / Pitfall**: Critical mistake or rule of thumb to remember.
- **Telegram HTML Delivery**: Delivers formatted lessons directly to your personal chat or channel.
- **Zero-Server Infrastructure**: Runs completely on the free tiers of Vercel Serverless and Google AI Studio.

---

## 🏗️ Architecture & Workflow

```
                       +-------------------+
                       |    Vercel Cron    |
                       | (Daily 06:00 UTC) |
                       +---------+---------+
                                 |
                                 v
                       +-------------------+
                       |   /api/cron.py    |
                       | (FastAPI / ASGI)  |
                       +---------+---------+
                                 |
         +-----------------------+-----------------------+
         |                                               |
         v                                               v
+-----------------+                             +-----------------+
|  tech-notes.md  |                             |  Google Gemini  |
| (Random Chunk)  | --------> Prompt ---------> | (2.0 Flash API) |
+-----------------+                             +--------+--------+
                                                         |
                                                         v (100-200 Words)
                                                +-----------------+
                                                |  Telegram Bot   |
                                                |  (sendMessage)  |
                                                +-----------------+
```

---

## 📁 Project Structure

```
note-drip/
├── api/
│   └── cron.py          # FastAPI serverless handler & cron endpoint
├── requirements.txt     # Python dependencies (fastapi, httpx, python-dotenv)
├── tech-notes.md        # Curated technical engineering notes
├── vercel.json          # Vercel Cron schedule & file bundling config
├── pyproject.toml       # Project metadata
└── README.md            # Project documentation
```

---

## ⚙️ Environment Variables

Set the following variables in your local `.env` file or **Vercel Project Settings**:

| Variable | Description | Where to Get |
| :--- | :--- | :--- |
| `GEMINI_API_KEY` | Google Gemini API Key | [Google AI Studio](https://aistudio.google.com/apikey) |
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather | [@BotFather](https://t.me/BotFather) on Telegram |
| `TELEGRAM_CHAT_ID` | Your Telegram Chat or Channel ID | [@userinfobot](https://t.me/userinfobot) or via bot update |
| `GEMINI_MODEL` | *(Optional)* Model override | Default: `gemini-2.0-flash` |

---

## 🛠️ Local Development

1. **Clone the repository:**
   ```bash
   git clone https://github.com/<your-username>/note-drip.git
   cd note-drip
   ```

2. **Create a virtual environment & install dependencies:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Create a `.env` file:**
   ```env
   GEMINI_API_KEY=your_gemini_api_key
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token
   TELEGRAM_CHAT_ID=your_telegram_chat_id
   ```

4. **Run the API server locally:**
   ```bash
   uvicorn api.cron:app --reload --port 8000
   ```

5. **Trigger a test drip:**
   Visit `http://localhost:8000/api/cron` in your browser or run:
   ```bash
   curl http://localhost:8000/api/cron
   ```

---

## 🚢 Deploying to Vercel

1. **Push your code to GitHub.**
2. **Import the repository into Vercel.**
3. **Add Environment Variables** in Vercel Dashboard (`Project Settings` > `Environment Variables`):
   - `GEMINI_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
4. **Deploy**:
   - Vercel will automatically configure the serverless function and activate the daily cron job scheduled in `vercel.json`.

---

## 📄 License
MIT License
