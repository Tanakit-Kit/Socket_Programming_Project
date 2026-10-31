import asyncio
import json
import sqlite3
from datetime import datetime
import websockets

HOST = '0.0.0.0'
PORT = 5000
DB_FILE = "chat_history.db"

clients = {}  # {username: websocket}
groups = {}   # {group_name: [list_of_member_usernames]}
lock = asyncio.Lock()

# --- 1. ส่วนจัดการฐานข้อมูล SQLite ---
def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS private_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sender TEXT, target TEXT, message TEXT, timestamp TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS group_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        group_name TEXT, sender TEXT, message TEXT, timestamp TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS group_members (
                        group_name TEXT, username TEXT,
                        UNIQUE(group_name, username))''')
        conn.commit()

        groups.clear()
        c.execute("SELECT group_name, username FROM group_members")
        for gname, uname in c.fetchall():
            groups.setdefault(gname, []).append(uname)

def save_private_msg(sender, target, message, ts):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("INSERT INTO private_messages (sender, target, message, timestamp) VALUES (?, ?, ?, ?)",
                     (sender, target, message, ts))
        conn.commit()

def get_private_history(user1, user2):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''SELECT sender, target, message, timestamp FROM private_messages
                     WHERE (sender=? AND target=?) OR (sender=? AND target=?)
                     ORDER BY id ASC''', (user1, user2, user2, user1))
        return [{"sender": r[0], "target": r[1], "message": r[2], "timestamp": r[3]} for r in c.fetchall()]

def save_group_msg(group_name, sender, message, ts):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("INSERT INTO group_messages (group_name, sender, message, timestamp) VALUES (?, ?, ?, ?)",
                     (group_name, sender, message, ts))
        conn.commit()

def get_group_history(group_name):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''SELECT sender, message, timestamp FROM group_messages
                     WHERE group_name=? ORDER BY id ASC''', (group_name,))
        return [{"sender": r[0], "message": r[1], "timestamp": r[2]} for r in c.fetchall()]

def add_member_to_db(group_name, username):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("INSERT OR IGNORE INTO group_members (group_name, username) VALUES (?, ?)",
                     (group_name, username))
        conn.commit()

# --- 2. ฟังก์ชันช่วยส่งข้อมูลผ่าน WebSocket ---
async def send_json(websocket, data):
    try:
        await websocket.send(json.dumps(data))
    except Exception:
        pass

async def broadcast_user_list():
    user_list = list(clients.keys())
    for ws in list(clients.values()):
        await send_json(ws, {"type": "user_list", "users": user_list})

async def broadcast_group_list():
    for ws in list(clients.values()):
        await send_json(ws, {"type": "group_list", "groups": groups})

# --- 3. ฟังก์ชันจัดการคำสั่งแต่ละประเภท (Handler Pattern แทน if-elif) ---
async def handle_register(websocket, current_username, msg):
    req_name = msg.get("username", "").strip()
    async with lock:
        if not req_name or req_name in clients:
            await send_json(websocket, {
                "type": "register_result",
                "success": False,
                "message": "ชื่อนี้กำลังออนไลน์อยู่ กรุณาใช้ชื่ออื่น"
            })
            return current_username

        clients[req_name] = websocket
        await send_json(websocket, {
            "type": "register_result",
            "success": True,
            "username": req_name
        })
        await broadcast_user_list()
        await broadcast_group_list()

        for gname, members in groups.items():
            if req_name in members:
                await send_json(websocket, {"type": "group_joined", "group_name": gname})
                history = get_group_history(gname)
                await send_json(websocket, {
                    "type": "group_history",
                    "group_name": gname,
                    "history": history
                })
        return req_name

async def handle_private_msg(websocket, username, msg):
    target = msg.get("target")
    text = msg.get("message")
    ts = datetime.now().strftime("%H:%M:%S")
    async with lock:
        save_private_msg(username, target, text, ts)
        payload = {
            "type": "private_msg",
            "sender": username,
            "target": target,
            "message": text,
            "timestamp": ts
        }
        if target in clients:
            await send_json(clients[target], payload)
        if target != username:
            await send_json(websocket, payload)
    return username

async def handle_get_private_history(websocket, username, msg):
    peer = msg.get("peer")
    async with lock:
        history = get_private_history(username, peer)
        await send_json(websocket, {
            "type": "private_history",
            "peer": peer,
            "history": history
        })
    return username

async def handle_create_group(websocket, username, msg):
    gname = msg.get("group_name", "").strip()
    async with lock:
        if gname and gname not in groups:
            groups[gname] = [username]
            add_member_to_db(gname, username)
            await broadcast_group_list()
            await send_json(websocket, {"type": "group_joined", "group_name": gname})
            await send_json(websocket, {"type": "group_history", "group_name": gname, "history": []})
    return username

async def handle_join_group(websocket, username, msg):
    gname = msg.get("group_name", "").strip()
    async with lock:
        if gname in groups:
            if username not in groups[gname]:
                groups[gname].append(username)
                add_member_to_db(gname, username)
                await broadcast_group_list()
            await send_json(websocket, {"type": "group_joined", "group_name": gname})
            history = get_group_history(gname)
            await send_json(websocket, {
                "type": "group_history",
                "group_name": gname,
                "history": history
            })
    return username

async def handle_get_group_history(websocket, username, msg):
    gname = msg.get("group_name", "").strip()
    async with lock:
        if gname in groups and username in groups[gname]:
            history = get_group_history(gname)
            await send_json(websocket, {
                "type": "group_history",
                "group_name": gname,
                "history": history
            })
    return username

async def handle_group_msg(websocket, username, msg):
    gname = msg.get("group_name")
    text = msg.get("message")
    ts = datetime.now().strftime("%H:%M:%S")
    async with lock:
        if gname in groups and username in groups[gname]:
            save_group_msg(gname, username, text, ts)
            payload = {
                "type": "group_msg",
                "group_name": gname,
                "sender": username,
                "message": text,
                "timestamp": ts
            }
            for member in groups[gname]:
                if member in clients:
                    await send_json(clients[member], payload)
    return username

# ตารางจับคู่คำสั่งแทนการใช้ if-elif-else
ACTION_HANDLERS = {
    "register": handle_register,
    "private_msg": handle_private_msg,
    "get_private_history": handle_get_private_history,
    "create_group": handle_create_group,
    "join_group": handle_join_group,
    "get_group_history": handle_get_group_history,
    "group_msg": handle_group_msg,
}

async def handler(websocket):
    username = None
    try:
        async for message in websocket:
            msg = json.loads(message)
            print(f"[SERVER] Received: {msg}")
            action = msg.get("type")
            handler_fn = ACTION_HANDLERS.get(action)
            if handler_fn:
                username = await handler_fn(websocket, username, msg)
    except Exception as e:
        print(f"[ERROR]: {e}")
    finally:
        async with lock:
            if username and username in clients:
                del clients[username]
                await broadcast_user_list()

async def main():
    init_db()
    async with websockets.serve(handler, HOST, PORT):
        print(f"[SERVER RUNNING] Listening on {HOST}:{PORT} (WebSocket, SQLite DB Enabled)")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
