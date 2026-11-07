import asyncio
import os
from gemini_service import GeminiError, call_gemini_api, call_gemini_with_tools
from agent_service import MAX_MESSAGE_LENGTH, PHASE_ACT, PHASE_PROPOSE, PHASE_WRITE, run_agent, should_wake
from collections import deque
import json
import sqlite3
import time
import uuid
from datetime import datetime
import websockets

HOST = os.environ["CHAT_HOST"]
PORT = int(os.environ["CHAT_PORT"])
DB_FILE = os.environ["CHAT_DB_FILE"]
AGENT_MAX_STEPS = int(os.environ["AGENT_MAX_STEPS"])
AGENT_DEBOUNCE_SECONDS = float(os.environ["AGENT_DEBOUNCE_SECONDS"])
AGENT_MAX_RUNS_PER_MINUTE = int(os.environ["AGENT_MAX_RUNS_PER_MINUTE"])

BOT_NAME = "GeminiBot"
AGENT_MODES = ("off", "auto", "manual")
ROOM_TYPES = ("private", "group")

clients = {}  # {username: websocket}
groups = {}   # {group_name: [list_of_member_usernames]}
lock = asyncio.Lock()
agent_pending = {}    # {(owner, room_type, room): งานที่รอหน่วงเวลา}
agent_running = {}    # {(owner, room_type, room): งานที่กำลังเรียก AI}
agent_run_times = {}  # {owner: เวลาที่เริ่มทำงาน ใช้จำกัดจำนวนครั้งต่อนาที}

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
        c.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY)")
        c.execute("""INSERT OR IGNORE INTO users (username)
                     SELECT username FROM group_members
                     UNION SELECT sender FROM private_messages
                     UNION SELECT target FROM private_messages
                     UNION SELECT sender FROM group_messages""")
        c.execute("DELETE FROM users WHERE username IS NULL OR username = '' OR username = 'GeminiBot'")
        columns = {row[1] for row in c.execute("PRAGMA table_info(private_messages)")}
        if "display_sender" not in columns:
            c.execute("ALTER TABLE private_messages ADD COLUMN display_sender TEXT")
        # ชื่อที่แสดงของ AI แยกจาก sender เพื่อไม่ให้กลายเป็นผู้ใช้ในตาราง users ตอนรีสตาร์ต
        columns = {row[1] for row in c.execute("PRAGMA table_info(group_messages)")}
        if "display_sender" not in columns:
            c.execute("ALTER TABLE group_messages ADD COLUMN display_sender TEXT")
        c.execute('''CREATE TABLE IF NOT EXISTS agent_settings (
                        owner TEXT, room_type TEXT, room TEXT, mode TEXT,
                        PRIMARY KEY (owner, room_type, room))''')
        # โหมด plan ถูกรวมเข้ากับ manual ซึ่งต้องให้เจ้าของอนุมัติก่อนส่งเหมือนกัน
        c.execute("UPDATE agent_settings SET mode='manual' WHERE mode='plan'")
        c.execute('''CREATE TABLE IF NOT EXISTS agent_proposals (
                        id TEXT PRIMARY KEY, owner TEXT, room_type TEXT, room TEXT,
                        kind TEXT, payload TEXT, status TEXT, created_at TEXT)''')
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
        c.execute('''SELECT COALESCE(display_sender, sender), target, message, timestamp FROM private_messages
                     WHERE (sender=? AND target=?) OR (sender=? AND target=?)
                     ORDER BY id ASC''', (user1, user2, user2, user1))
        return [{"sender": r[0], "target": r[1], "message": r[2], "timestamp": r[3]} for r in c.fetchall()]

def save_group_msg(group_name, sender, message, ts, display_sender=None):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("INSERT INTO group_messages (group_name, sender, message, timestamp, display_sender) VALUES (?, ?, ?, ?, ?)",
                     (group_name, sender, message, ts, display_sender))
        conn.commit()

def get_group_history(group_name):
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''SELECT COALESCE(display_sender, sender), message, timestamp FROM group_messages
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
    with sqlite3.connect(DB_FILE) as conn:
        user_list = [row[0] for row in conn.execute("SELECT username FROM users ORDER BY username COLLATE NOCASE, username")]
    online_users = list(clients.keys())
    for ws in list(clients.values()):
        await send_json(ws, {"type": "user_list", "users": online_users, "all_users": user_list})

async def broadcast_group_list():
    for ws in list(clients.values()):
        await send_json(ws, {"type": "group_list", "groups": groups})

# --- 3. ฟังก์ชันจัดการคำสั่งแต่ละประเภท (Handler Pattern แทน if-elif) ---
async def handle_register(websocket, current_username, msg):
    req_name = msg.get("username", "").strip()
    async with lock:
        if current_username or not req_name or req_name in clients:
            await send_json(websocket, {
                "type": "register_result",
                "success": False,
                "message": "ชื่อนี้กำลังออนไลน์อยู่ กรุณาใช้ชื่ออื่น"
            })
            return current_username

        # ชื่อนี้สงวนไว้ให้ /bot เพื่อกันการปลอมตัว
        if req_name == BOT_NAME:
            await send_json(websocket, {
                "type": "register_result",
                "success": False,
                "message": "ชื่อนี้สงวนไว้สำหรับ AI กรุณาใช้ชื่ออื่น"
            })
            return current_username

        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("INSERT OR IGNORE INTO users (username) VALUES (?)", (req_name,))
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
        await send_agent_restore(req_name)
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

# --- 4. AI Agent ส่วนตัว (โหมด ฉบับร่าง และแผนส่งถึงเจ้าของเท่านั้น) ---
async def post_ai_message(owner, room_type, room, display_name, text):
    """บันทึกและส่งข้อความของ AI โดยเก็บ sender เป็นเจ้าของ และเก็บชื่อที่แสดงแยกไว้"""
    ts = datetime.now().strftime("%H:%M:%S")
    # Agent ส่งในชื่อเจ้าของ: บอก frontend เพื่อไม่ให้สลับห้องเองเหมือนตอนเจ้าของพิมพ์
    from_agent = display_name == owner
    async with lock:
        if room_type == "group":
            save_group_msg(room, owner, text, ts, display_sender=display_name)
            payload = dict(type="group_msg", group_name=room, sender=display_name, message=text, timestamp=ts, agent=from_agent)
            for member in list(groups.get(room, [])):
                if member in clients:
                    await send_json(clients[member], payload)
        else:
            with sqlite3.connect(DB_FILE) as conn:
                conn.execute("INSERT INTO private_messages (sender, target, message, timestamp, display_sender) VALUES (?, ?, ?, ?, ?)",
                             (owner, room, text, ts, display_name))
            for recipient, peer in dict([(owner, room), (room, owner)]).items():
                if recipient in clients:
                    await send_json(clients[recipient], dict(type="private_msg", sender=display_name, target=room,
                        peer=peer, message=text, timestamp=ts, agent=from_agent))

async def send_to_owner(owner, data):
    websocket = clients.get(owner)
    if websocket:
        await send_json(websocket, data)

def agent_room_allowed(owner, room_type, room):
    if room_type not in ROOM_TYPES or not isinstance(room, str) or not room:
        return False
    if room_type == "group":
        return owner in groups.get(room, [])
    if room == owner:
        return False
    with sqlite3.connect(DB_FILE) as conn:
        return conn.execute("SELECT 1 FROM users WHERE username=?", (room,)).fetchone() is not None

def agent_room_history(owner, room_type, room):
    if not agent_room_allowed(owner, room_type, room):
        return []
    if room_type == "group":
        return get_group_history(room)
    return get_private_history(owner, room)

def get_agent_mode(owner, room_type, room):
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute("SELECT mode FROM agent_settings WHERE owner=? AND room_type=? AND room=?",
                           (owner, room_type, room)).fetchone()
    return row[0] if row else "off"

def set_agent_mode(owner, room_type, room, mode):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("INSERT OR REPLACE INTO agent_settings (owner, room_type, room, mode) VALUES (?, ?, ?, ?)",
                     (owner, room_type, room, mode))

async def send_agent_state(owner, room_type, room):
    status = "thinking" if (owner, room_type, room) in agent_running else "idle"
    await send_to_owner(owner, {"type": "agent_state", "room_type": room_type, "room": room,
                                "mode": get_agent_mode(owner, room_type, room), "status": status})

async def send_agent_error(owner, room_type, room, message):
    await send_to_owner(owner, {"type": "agent_error", "room_type": room_type, "room": room, "message": message})

def proposal_message(proposal_id, room_type, room, kind, payload):
    public = {key: value for key, value in payload.items() if key not in ("instruction", "origin")}
    return {"type": "agent_proposal", "proposal_id": proposal_id, "room_type": room_type,
            "room": room, "kind": kind, "can_go_back": "origin" in payload, **public}

async def close_proposal(owner, proposal_id, room_type, room, status):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("UPDATE agent_proposals SET status=? WHERE id=? AND owner=?", (status, proposal_id, owner))
    await send_to_owner(owner, {"type": "agent_proposal_closed", "proposal_id": proposal_id,
                                "room_type": room_type, "room": room, "status": status})

async def close_room_proposals(owner, room_type, room, status):
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute("SELECT id FROM agent_proposals WHERE owner=? AND room_type=? AND room=? AND status='pending'",
                            (owner, room_type, room)).fetchall()
    for (proposal_id,) in rows:
        await close_proposal(owner, proposal_id, room_type, room, status)

async def create_proposal(owner, room_type, room, kind, payload):
    """สร้างรายการรออนุมัติ โดยแทนที่รายการเก่าของห้องนี้"""
    await close_room_proposals(owner, room_type, room, "superseded")
    proposal_id = uuid.uuid4().hex
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""INSERT INTO agent_proposals (id, owner, room_type, room, kind, payload, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
                     (proposal_id, owner, room_type, room, kind, json.dumps(payload), datetime.now().isoformat()))
    await send_to_owner(owner, proposal_message(proposal_id, room_type, room, kind, payload))

async def send_agent_restore(owner):
    """ส่งโหมดและรายการที่ค้างกลับให้เจ้าของตอนเข้าระบบ"""
    with sqlite3.connect(DB_FILE) as conn:
        settings = conn.execute("SELECT room_type, room FROM agent_settings WHERE owner=? AND mode != 'off'", (owner,)).fetchall()
        proposals = conn.execute("SELECT id, room_type, room, kind, payload FROM agent_proposals WHERE owner=? AND status='pending'",
                                 (owner,)).fetchall()
    for room_type, room in settings:
        if agent_room_allowed(owner, room_type, room):
            await send_agent_state(owner, room_type, room)
    for proposal_id, room_type, room, kind, payload in proposals:
        if agent_room_allowed(owner, room_type, room):
            await send_to_owner(owner, proposal_message(proposal_id, room_type, room, kind, json.loads(payload)))

def agent_rate_allowed(owner):
    now = time.monotonic()
    started = agent_run_times.setdefault(owner, deque())
    while started and now - started[0] >= 60:
        started.popleft()
    if len(started) >= AGENT_MAX_RUNS_PER_MINUTE:
        return False
    started.append(now)
    return True

def cancel_agent_tasks(key):
    for tasks in (agent_pending, agent_running):
        task = tasks.pop(key, None)
        if task:
            task.cancel()

def cancel_owner_agents(owner):
    for tasks in (agent_pending, agent_running):
        for key in [key for key in tasks if key[0] == owner]:
            cancel_agent_tasks(key)

def draft_payload(text, origin):
    """origin คือรายการแนวทางเดิม เก็บไว้ให้เจ้าของกลับไปเลือกแนวทางอื่นได้"""
    return {"text": text, "origin": origin} if origin else {"text": text}

async def agent_post(owner, room_type, room, phase, text, origin=None):
    """ด่านควบคุมการส่งข้อความเข้าห้อง: ทุกข้อความของ Agent ต้องผ่านฟังก์ชันนี้"""
    if not agent_room_allowed(owner, room_type, room):
        return {"status": "forbidden", "stop": True}
    mode = get_agent_mode(owner, room_type, room)
    if phase == PHASE_ACT and mode == "auto":
        await post_ai_message(owner, room_type, room, owner, text)
        # จบงานทันทีหลังส่ง เพื่อประหยัดโควตา และไม่ให้รอบถัดไปแจ้ง error ทั้งที่ส่งสำเร็จแล้ว
        return {"status": "posted", "stop": True}
    if phase == PHASE_WRITE:
        await create_proposal(owner, room_type, room, "draft", draft_payload(text, origin))
        return {"status": "draft_created", "stop": True}
    return {"status": "mode_changed", "stop": True}

async def run_agent_task(owner, room_type, room, phase, instruction, triggered, origin=None):
    key = (owner, room_type, room)
    task = asyncio.current_task()
    room_label = f"กลุ่ม {room}" if room_type == "group" else f"แชทส่วนตัวกับ {room}"

    async def post(text):
        return await agent_post(owner, room_type, room, phase, text, origin)

    async def propose(summary, options):
        await create_proposal(owner, room_type, room, "choices",
                              {"summary": summary, "options": options, "instruction": instruction})

    try:
        await send_agent_state(owner, room_type, room)
        result = await run_agent(
            owner=owner, room_label=room_label, phase=phase, instruction=instruction, triggered=triggered,
            read_history=lambda: agent_room_history(owner, room_type, room),
            post_message=post, propose=propose, generate=call_gemini_with_tools,
            max_steps=AGENT_MAX_STEPS,
            context_limit=int(os.environ["GEMINI_CONTEXT_MESSAGES"]),
        )
        if triggered or result.posts or result.proposed:
            return
        # AI ตอบเป็นข้อความเฉย ๆ: แสดงให้เจ้าของเห็นเท่านั้น ไม่ส่งเข้าห้องเอง
        if result.text and phase == PHASE_WRITE:
            await create_proposal(owner, room_type, room, "draft", draft_payload(result.text[:MAX_MESSAGE_LENGTH], origin))
        elif result.text:
            await propose(result.text[:MAX_MESSAGE_LENGTH], [])
        elif result.hit_step_limit:
            await send_agent_error(owner, room_type, room, "Agent ทำงานครบจำนวนรอบที่กำหนดแล้วแต่ยังไม่เสร็จ")
        else:
            await send_agent_error(owner, room_type, room, "Agent ไม่ได้ส่งผลลัพธ์กลับมา")
    except GeminiError as e:
        await send_agent_error(owner, room_type, room, str(e))
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"[AGENT ERROR]: {e}")
        await send_agent_error(owner, room_type, room, "Agent เกิดข้อผิดพลาด กรุณาลองใหม่")
    finally:
        if agent_running.get(key) is task:
            del agent_running[key]
        await send_agent_state(owner, room_type, room)

def start_agent_run(owner, room_type, room, phase, instruction, triggered=False, origin=None):
    key = (owner, room_type, room)
    # ลงทะเบียนก่อนงานเริ่ม เพื่อให้ agent_state แรกเป็น thinking และกันการเริ่มซ้ำ
    agent_running[key] = asyncio.create_task(run_agent_task(owner, room_type, room, phase, instruction, triggered, origin))

def agent_phase(mode):
    """มีแค่ Auto ที่ตอบเข้าห้องเองได้ Manual ต้องให้เจ้าของเลือกแนวทางก่อน"""
    return PHASE_ACT if mode == "auto" else PHASE_PROPOSE

async def debounced_wakeup(owner, room_type, room):
    key = (owner, room_type, room)
    await asyncio.sleep(AGENT_DEBOUNCE_SECONDS)
    while key in agent_running:
        await asyncio.sleep(max(AGENT_DEBOUNCE_SECONDS, 0.05))
    agent_pending.pop(key, None)
    mode = get_agent_mode(owner, room_type, room)
    if owner not in clients or mode not in ("auto", "manual"):
        return
    if not agent_room_allowed(owner, room_type, room):
        return
    if not agent_rate_allowed(owner):
        await send_agent_error(owner, room_type, room, "มีข้อความใหม่ แต่เรียก Agent ถี่เกินไป จึงยังไม่ได้ตอบ")
        return
    start_agent_run(owner, room_type, room, agent_phase(mode),
                    "มีข้อความใหม่ในห้อง กรุณาอ่านแล้วตัดสินใจว่าควรตอบแทนเจ้าของหรือไม่", triggered=True)

def schedule_agents(sender, msg):
    """ปลุก Agent ของคนอื่นในห้องจากข้อความของคน ข้อความของ AI ไม่ผ่านจุดนี้จึงไม่เกิดลูป AI ตอบ AI"""
    text = msg.get("message")
    if not isinstance(text, str) or not text.strip():
        return
    if msg.get("type") == "group_msg":
        room = msg.get("group_name")
        members = groups.get(room, []) if isinstance(room, str) else []
        if sender not in members:
            return
        recipients = [(member, "group", room) for member in members if member != sender]
    else:
        target = msg.get("target")
        if not isinstance(target, str) or target == sender:
            return
        recipients = [(target, "private", sender)]

    for owner, room_type, room in recipients:
        if owner not in clients or get_agent_mode(owner, room_type, room) not in ("auto", "manual"):
            continue
        if not should_wake(owner, room_type, text):
            continue
        key = (owner, room_type, room)
        previous = agent_pending.pop(key, None)
        if previous:
            previous.cancel()
        agent_pending[key] = asyncio.create_task(debounced_wakeup(owner, room_type, room))

async def handle_agent_set_mode(websocket, username, msg):
    room_type, room, mode = msg.get("room_type"), msg.get("room"), msg.get("mode")
    if mode not in AGENT_MODES or not agent_room_allowed(username, room_type, room):
        await send_agent_error(username, room_type, room, "ตั้งค่า Agent ในห้องนี้ไม่ได้")
        return username
    set_agent_mode(username, room_type, room, mode)
    if mode == "off":
        cancel_agent_tasks((username, room_type, room))
        await close_room_proposals(username, room_type, room, "cancelled")
    await send_agent_state(username, room_type, room)
    return username

async def handle_agent_invoke(websocket, username, msg):
    room_type, room, instruction = msg.get("room_type"), msg.get("room"), msg.get("instruction")
    if not agent_room_allowed(username, room_type, room):
        await send_agent_error(username, room_type, room, "ใช้ Agent ในห้องนี้ไม่ได้")
        return username
    if not isinstance(instruction, str) or not instruction.strip():
        await send_agent_error(username, room_type, room, "กรุณาพิมพ์คำสั่งให้ Agent")
        return username
    mode = get_agent_mode(username, room_type, room)
    key = (username, room_type, room)
    if mode == "off":
        await send_agent_error(username, room_type, room, "กรุณาเลือกโหมดของ Agent ก่อน")
    elif key in agent_running:
        await send_agent_error(username, room_type, room, "Agent กำลังทำงานอยู่")
    elif not agent_rate_allowed(username):
        await send_agent_error(username, room_type, room, "เรียก Agent ถี่เกินไป กรุณารอสักครู่")
    else:
        pending = agent_pending.pop(key, None)
        if pending:
            pending.cancel()
        start_agent_run(username, room_type, room, agent_phase(mode), instruction.strip()[:MAX_MESSAGE_LENGTH])
    return username

async def handle_agent_cancel(websocket, username, msg):
    room_type, room = msg.get("room_type"), msg.get("room")
    if room_type in ROOM_TYPES and isinstance(room, str):
        cancel_agent_tasks((username, room_type, room))
        await send_agent_state(username, room_type, room)
    return username

def format_proposal(payload):
    options = "\n".join(f"{i}. {option}" for i, option in enumerate(payload.get("options", []), 1))
    return f"งานจากเจ้าของ: {payload.get('instruction', '')}\nที่เคยเสนอ: {payload.get('summary', '')}\nแนวทางเดิม:\n{options}"

def selected_option(payload, index):
    options = payload.get("options", [])
    if isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(options):
        return options[index]
    return None

async def handle_agent_decide(websocket, username, msg):
    proposal_id, decision, text = msg.get("proposal_id"), msg.get("decision"), msg.get("text")
    if not isinstance(proposal_id, str):
        return username
    with sqlite3.connect(DB_FILE) as conn:
        # ตรวจเจ้าของใน query เพื่อให้คนอื่นตัดสินรายการนี้ไม่ได้
        row = conn.execute("SELECT room_type, room, kind, payload FROM agent_proposals WHERE id=? AND owner=? AND status='pending'",
                           (proposal_id, username)).fetchone()
    if not row:
        await send_to_owner(username, {"type": "agent_error", "message": "รายการนี้ถูกปิดไปแล้ว"})
        return username

    room_type, room, kind, raw_payload = row
    payload = json.loads(raw_payload)
    key = (username, room_type, room)
    if decision == "reject":
        await close_proposal(username, proposal_id, room_type, room, "rejected")
        return username
    if not agent_room_allowed(username, room_type, room):
        await close_proposal(username, proposal_id, room_type, room, "forbidden")
        await send_agent_error(username, room_type, room, "คุณไม่ได้อยู่ในห้องนี้แล้ว")
        return username

    typed_text = text.strip() if isinstance(text, str) else ""
    if kind == "draft" and decision == "approve":
        # ส่งเฉพาะข้อความที่เจ้าของเห็น ไม่ให้ AI แต่งใหม่ตอนอนุมัติ
        final_text = typed_text or payload.get("text", "")
        await close_proposal(username, proposal_id, room_type, room, "approved")
        await post_ai_message(username, room_type, room, username, final_text[:MAX_MESSAGE_LENGTH])
    elif kind == "draft" and decision == "back" and "origin" in payload:
        # กลับไปเลือกแนวทางเดิมได้ทันทีโดยไม่เรียก AI และ create_proposal จะปิดฉบับร่างนี้ให้
        await create_proposal(username, room_type, room, "choices", payload["origin"])
    elif kind == "choices" and decision in ("choose", "revise"):
        option = selected_option(payload, msg.get("option"))
        if key in agent_running:
            await send_agent_error(username, room_type, room, "Agent กำลังทำงานอยู่")
        elif decision == "choose" and option is None:
            await send_agent_error(username, room_type, room, "ไม่พบแนวทางที่เลือก")
        elif decision == "revise" and not typed_text:
            await send_agent_error(username, room_type, room, "กรุณาบอกว่าต้องการให้ Agent แก้อย่างไร")
        elif not agent_rate_allowed(username):
            await send_agent_error(username, room_type, room, "เรียก Agent ถี่เกินไป กรุณารอสักครู่")
        elif decision == "choose":
            # ยังไม่ปิดรายการนี้ ถ้า Gemini ล้มเหลวเจ้าของจะกดใหม่ได้ เมื่อได้ฉบับร่าง รายการนี้จะถูกแทนที่เอง
            start_agent_run(username, room_type, room, PHASE_WRITE,
                            f"{format_proposal(payload)}\nแนวทางที่เจ้าของเลือก: {option}\nเขียนประโยคจริงตามแนวทางนี้",
                            origin=payload)
        else:
            await close_proposal(username, proposal_id, room_type, room, "revised")
            start_agent_run(username, room_type, room, PHASE_PROPOSE,
                            f"{format_proposal(payload)}\nเจ้าของขอให้แก้ดังนี้: {typed_text[:MAX_MESSAGE_LENGTH]}")
    else:
        await send_agent_error(username, room_type, room, "คำสั่งนี้ใช้กับรายการนี้ไม่ได้")
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
    "agent_set_mode": handle_agent_set_mode,
    "agent_invoke": handle_agent_invoke,
    "agent_decide": handle_agent_decide,
    "agent_cancel": handle_agent_cancel,
}

async def handle_bot(websocket, username, msg):
    is_group = msg["type"] == "group_msg"
    target = msg.get("group_name") if is_group else msg.get("target")
    if not target or (is_group and username not in groups.get(target, [])):
        return
    await ACTION_HANDLERS[msg["type"]](websocket, username, msg)
    history = get_group_history(target) if is_group else get_private_history(username, target)
    context = [dict(entry, target=target) for entry in history]
    reply = await asyncio.to_thread(call_gemini_api, msg["message"].strip()[4:].strip(), context)
    await post_ai_message(username, "group" if is_group else "private", target, BOT_NAME, reply)

async def handler(websocket):
    username = None
    try:
        async for message in websocket:
            msg = json.loads(message)
            action = msg.get("type")
            handler_fn = ACTION_HANDLERS.get(action)
            if action != "register" and username is None:
                continue
            if action in ("private_msg", "group_msg") and msg.get("message", "").strip().startswith("/bot"):
                await handle_bot(websocket, username, msg)
            elif handler_fn:
                username = await handler_fn(websocket, username, msg)
                if action in ("private_msg", "group_msg"):
                    schedule_agents(username, msg)
    except Exception as e:
        print(f"[ERROR]: {e}")
    finally:
        if username:
            cancel_owner_agents(username)
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
