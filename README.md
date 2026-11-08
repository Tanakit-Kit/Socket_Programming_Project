# WebSocket chat

Python owns messaging, SQLite persistence and Gemini. Next.js provides the browser UI; the previous TCP desktop clients have been retired.

## Setup

Run from the repository root:

```sh
# with uv
uv run python server.py
# or if you're not using uv
python -m pip install -r requirements.txt
python server.py
```

Set GEMINI_API_KEY in `.env` to enable the bot. Existing SQLite databases are migrated automatically by adding a nullable display_sender column. Back up your database before upgrading. Existing legacy bot rows cannot reliably be assigned to a conversation automatically.

In another terminal:

```sh
cd frontend
# if you are about to host the app
# export the variable HOST_IP=<your ip>
# in the current terminal
npm ci
npm run dev
```

Set NEXT_PUBLIC_CHAT_WS_URL to the Python server address accessible from the browser. For HTTPS deployments use wss:// with a TLS reverse proxy. Public Next.js settings are embedded at build time; never put API keys in them. Rebuild after changing them.

Environment files are optional. The templates document overrides; application defaults work without copying either template. Exported variables take precedence over `.env` values. UI styles and protocol identifiers remain code constants.

## AI Agent

Each user has a personal Agent, set per room from the panel above the message box. The mode, drafts and plans are visible only to their owner, and the Agent can only read and post in that room. `/bot` keeps working independently.

| Mode | Starts when | Posting to the room |
|---|---|---|
| Off | Never | Not allowed |
| Auto | Its owner is addressed or asked something, or the owner gives a command | Decides for itself and posts immediately under the owner's name |
| Manual | Same as Auto | Shows a summary and clickable approaches. Choosing one makes the Agent write a draft, which the owner can send, edit or discard |

Agent messages appear under the owner's name with no AI label, so other people cannot tell them apart from messages the owner typed. Advice and summaries the owner asks for stay in the private panel, including in Auto. Choosing an approach always produces a draft. Sending a draft posts exactly that text without another AI call.

The Agent only runs while its owner is online. In group chats, a message wakes it only if it contains the owner's name, a question mark or a common Thai question word. Private messages always wake it. The name `GeminiBot` is reserved.

All agent settings have defaults; environment overrides are optional.

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

## Optional configuration

For local development, run the backend and frontend without creating `.env` files.
Normal chat works without a Gemini key; Gemini features report that configuration is required.
To enable Gemini, export `GEMINI_API_KEY` or set it in an optional root `.env`.
Python reads the root `.env` when started from the repository root. Next.js reads environment files in `frontend/`.

For LAN hosting, export the host address in the frontend terminal:

```sh
export HOST_IP=<your_ip>
npm run dev -- --hostname 0.0.0.0
```

Next.js derives the WebSocket URL and allowed development origin from `HOST_IP`, defaulting to `localhost`.
Explicit `NEXT_PUBLIC_CHAT_WS_URL` and `DEV_ALLOWED_ORIGINS` overrides take precedence over that derivation.
For production, export the address before `npm run build`; the public WebSocket URL is embedded at build time.
