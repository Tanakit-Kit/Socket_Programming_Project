import os
import socket
import threading
import json
import time
import sqlite3
from datetime import datetime

from gemini_service import call_gemini_api

HOST = '0.0.0.0'
PORT = 5000
DB_FILE = "chat_history.db"

clients = {}  # เก็บ {username: client_socket}
groups = {}   # เก็บ {group_name: [list_of_member_usernames]}
chat_history = []  # เก็บประวัติแชททั้งหมด {sender, target, message, timestamp}
lock = threading.Lock()

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

# --- 2. ฟังก์ชันช่วยส่งข้อมูลผ่าน Socket (R2) ---
def send_json(sock, data):
    try:
        sock.sendall((json.dumps(data) + "\n").encode('utf-8'))
    except Exception:
        pass

def broadcast_user_list():
    user_list = list(clients.keys())
    for sock in list(clients.values()):
        send_json(sock, {"type": "user_list", "users": user_list})

def broadcast_group_list():
    for sock in list(clients.values()):
        send_json(sock, {"type": "group_list", "groups": groups})

def save_to_history(sender, target, message):
    chat_history.append({
        "sender": sender,
        "target": target,
        "message": message,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })
    if len(chat_history) > 200:
        del chat_history[:-200]

# --- 3. ฟังก์ชันจัดการคำสั่งแต่ละประเภท (Handler Pattern แทน if-elif) ---
def handle_register(client_socket, current_username, msg):
    req_name = msg.get("username", "").strip()
    with lock:
        if not req_name or req_name in clients:
            send_json(client_socket, {
                "type": "register_result",
                "success": False,
                "message": "ชื่อนี้กำลังออนไลน์อยู่ กรุณาใช้ชื่ออื่น"
            })
            return current_username

        clients[req_name] = client_socket
        send_json(client_socket, {
            "type": "register_result",
            "success": True,
            "username": req_name
        })
        broadcast_user_list()
        broadcast_group_list()

        for gname, members in groups.items():
            if req_name in members:
                send_json(client_socket, {"type": "group_joined", "group_name": gname})
                history = get_group_history(gname)
                send_json(client_socket, {
                    "type": "group_history",
                    "group_name": gname,
                    "history": history
                })
        return req_name

def handle_private_msg(client_socket, username, msg):
    target = msg.get("target")
    text = msg.get("message")
    ts = datetime.now().strftime("%H:%M:%S")
    with lock:
        save_private_msg(username, target, text, ts)
        save_to_history(username, target, text)
        payload = {
            "type": "private_msg",
            "sender": username,
            "target": target,
            "message": text,
            "timestamp": ts
        }
        if target in clients:
            send_json(clients[target], payload)
        if target != username:
            send_json(client_socket, payload)
    return username

def handle_get_private_history(client_socket, username, msg):
    peer = msg.get("peer")
    with lock:
        history = get_private_history(username, peer)
        send_json(client_socket, {
            "type": "private_history",
            "peer": peer,
            "history": history
        })
    return username

def handle_create_group(client_socket, username, msg):
    gname = msg.get("group_name", "").strip()
    with lock:
        if gname and gname not in groups:
            groups[gname] = [username]
            add_member_to_db(gname, username)
            broadcast_group_list()
            send_json(client_socket, {"type": "group_joined", "group_name": gname})
            send_json(client_socket, {"type": "group_history", "group_name": gname, "history": []})
    return username

def handle_join_group(client_socket, username, msg):
    gname = msg.get("group_name", "").strip()
    with lock:
        if gname in groups:
            if username not in groups[gname]:
                groups[gname].append(username)
                add_member_to_db(gname, username)
                broadcast_group_list()
            send_json(client_socket, {"type": "group_joined", "group_name": gname})
            history = get_group_history(gname)
            send_json(client_socket, {
                "type": "group_history",
                "group_name": gname,
                "history": history
            })
    return username

def handle_get_group_history(client_socket, username, msg):
    gname = msg.get("group_name", "").strip()
    with lock:
        if gname in groups and username in groups[gname]:
            history = get_group_history(gname)
            send_json(client_socket, {
                "type": "group_history",
                "group_name": gname,
                "history": history
            })
    return username

def handle_group_msg(client_socket, username, msg):
    gname = msg.get("group_name")
    text = msg.get("message")
    ts = datetime.now().strftime("%H:%M:%S")
    with lock:
        save_group_msg(gname, username, text, ts)
        save_to_history(username, gname, text)
        payload = {
            "type": "group_msg",
            "group_name": gname,
            "sender": username,
            "message": text,
            "timestamp": ts
        }
        for member in groups[gname]:
            if member in clients:
                send_json(clients[member], payload)
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

def handle_client(client_socket, addr):
    username = None
    buffer = ""
    try:
        while True:
            data = client_socket.recv(4096)
            if not data:
                break
            buffer += data.decode('utf-8')
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if not line.strip():
                    continue
                msg = json.loads(line)
                action = msg.get("type")
                # ดักจับคำสั่ง /bot ก่อนส่งให้ handler ปกติ
                if action in ("private_msg", "group_msg"):
                    text = msg.get("message", "")
                    if text and text.strip().startswith("/bot"):
                        question = text.strip()
                        if question.startswith("/bot"):
                            question = question[len("/bot"):].strip()
                        if action == "private_msg":
                            target = msg.get("target")
                            save_to_history(username, target or "", text)
                            user_payload = {
                                "type": "private_msg",
                                "sender": username,
                                "target": target,
                                "message": text
                            }
                            send_json(client_socket, user_payload)
                            time.sleep(0.15)
                            reply = call_gemini_api(question, chat_history)
                            bot_payload = {
                                "type": "private_msg",
                                "sender": "GeminiBot",
                                "target": target or "GeminiBot",
                                "message": reply
                            }
                            send_json(client_socket, bot_payload)
                        elif action == "group_msg":
                            gname = msg.get("group_name")
                            if gname in groups and username in groups[gname]:
                                save_to_history(username, gname, text)
                                user_payload = {
                                    "type": "group_msg",
                                    "group_name": gname,
                                    "sender": username,
                                    "message": text
                                }
                                for member in groups[gname]:
                                    if member in clients:
                                        send_json(clients[member], user_payload)
                                time.sleep(0.15)
                                reply = call_gemini_api(question, chat_history)
                                bot_payload = {
                                    "type": "group_msg",
                                    "group_name": gname,
                                    "sender": "GeminiBot",
                                    "message": reply
                                }
                                for member in groups[gname]:
                                    if member in clients:
                                        send_json(clients[member], bot_payload)
                        continue

                handler = ACTION_HANDLERS.get(action)
                if handler:
                    username = handler(client_socket, username, msg)
    except Exception as e:
        print(f"[ERROR] {addr}: {e}")
    finally:
        with lock:
            if username and username in clients:
                del clients[username]
                for gname in list(groups.keys()):
                    if username in groups[gname]:
                        groups[gname].remove(username)
                broadcast_user_list()
                broadcast_group_list()
        client_socket.close()

def start_server():
    init_db()
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen()
    print(f"[SERVER RUNNING] Listening on {HOST}:{PORT} (SQLite DB Enabled)")
    while True:
        client_sock, addr = server_socket.accept()
        threading.Thread(target=handle_client, args=(client_sock, addr), daemon=True).start()

if __name__ == "__main__":
    start_server()