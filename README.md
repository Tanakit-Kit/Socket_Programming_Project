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

## AI Agent

Each user has a personal Agent, set per room from the panel above the message box. The mode, drafts and plans are visible only to their owner, and the Agent can only read and post in that room. `/bot` keeps working independently.

| Mode | Starts when | Posting to the room |
|---|---|---|
| Off | Never | Not allowed |
| Auto | Its owner is addressed or asked something, or the owner gives a command | Decides for itself and posts immediately under the owner's name |
| Manual | Same as Auto | Shows a summary and clickable approaches. Choosing one makes the Agent write a draft, which the owner can send, edit or discard |

Agent messages appear under the owner's name with no AI label, so other people cannot tell them apart from messages the owner typed. Advice and summaries the owner asks for stay in the private panel, including in Auto. Choosing an approach always produces a draft. Sending a draft posts exactly that text without another AI call.

The Agent only runs while its owner is online. In group chats, a message wakes it only if it contains the owner's name, a question mark or a common Thai question word. Private messages always wake it. The name `GeminiBot` is reserved.

**Existing `.env` files must add the `AGENT_*` settings from `.env.template`, or the server stops at startup with `KeyError`.**

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
