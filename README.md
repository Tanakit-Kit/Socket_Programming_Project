# WebSocket chat

Python owns messaging, SQLite persistence and Gemini. Next.js provides the browser UI; the previous TCP desktop clients have been retired.

## Setup

Run from the repository root:

```sh
cp .env.template .env
python -m pip install -r requirements.txt
python server.py
```

Set GEMINI_API_KEY in `.env` to enable the bot. Existing SQLite databases are migrated automatically by adding a nullable display_sender column. Back up your database before upgrading. Existing legacy bot rows cannot reliably be assigned to a conversation automatically.

In another terminal:

```sh
conda activate webdev
cd frontend
cp .env.template .env.local
npm ci
npm run dev
```

Set NEXT_PUBLIC_CHAT_WS_URL to the Python server address accessible from the browser. For HTTPS deployments use wss:// with a TLS reverse proxy. Public Next.js settings are embedded at build time; never put API keys in them. Rebuild after changing them.

All deployment and Gemini tuning settings are in the environment templates. UI styles and protocol identifiers remain code constants.

## Fonts

Fonts load once through next/font in the root layout. globals.css maps those CSS variables into Tailwind font-sans and font-mono and applies font-sans globally. Components inherit the font. This preserves Next.js font optimization without repeating imports per page.

## Checks

```sh
python -m unittest discover -s tests
cd frontend
npm run lint
npm run build
```

Private bot replies store the conversation participants separately from the displayed GeminiBot sender. Live replies include a recipient-specific peer field; history uses the same conversation keys. Bot context is scoped to the current conversation and the blocking API call runs in a worker thread.
