import os
import socket
import threading
import json
import time
from datetime import datetime

from gemini_service import call_gemini_api

HOST = '0.0.0.0'
PORT = 5000

clients = {}  # เก็บ {username: client_socket}
groups = {}   # เก็บ {group_name: [list_of_member_usernames]}
chat_history = []  # เก็บประวัติแชททั้งหมด {sender, target, message, timestamp}
lock = threading.Lock()

# [R2] ฟังก์ชันส่งข้อมูล JSON ผ่าน TCP Socket
def send_json(sock, data):
    try:
        message = json.dumps(data) + "\n"
        sock.sendall(message.encode('utf-8'))
    except Exception:
        pass

# [R4] อัปเดตรายชื่อ Client ทั้งหมดที่ออนไลน์ให้ทุกเครื่องเห็น (รวมชื่อตัวเอง)
def broadcast_user_list():
    user_list = list(clients.keys())
    for sock in list(clients.values()):
        send_json(sock, {"type": "user_list", "users": user_list})

# [R9] อัปเดตรายชื่อกลุ่มทั้งหมดพร้อมรายชื่อสมาชิกในกลุ่มให้ทุกเครื่องเห็น
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

def handle_client(client_socket, addr):
    username = None
    buffer = ""
    try:
        while True:
            # [R2] รับข้อมูลจาก Client ผ่าน Socket
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

                # [R3] ตรวจสอบและลงทะเบียนชื่อ Client ไม่ให้ซ้ำกัน (Unique Name)
                if action == "register":
                    req_name = msg.get("username", "").strip()
                    with lock:
                        if not req_name or req_name in clients:
                            send_json(client_socket, {
                                "type": "register_result",
                                "success": False,
                                "message": "ชื่อนี้ถูกใช้งานแล้ว กรุณาตั้งชื่อใหม่"
                            })
                        else:
                            username = req_name
                            clients[username] = client_socket
                            send_json(client_socket, {
                                "type": "register_result",
                                "success": True,
                                "username": username
                            })
                            broadcast_user_list()
                            broadcast_group_list()

                # [R7] ส่งข้อความแชทส่วนตัว (เห็นเฉพาะผู้ส่งและผู้รับ)
                elif action == "private_msg":
                    target = msg.get("target")
                    text = msg.get("message")
                    with lock:
                        if text and text.strip().startswith("/bot"):
                            question = text.strip()
                            if question.startswith("/bot"):
                                question = question[len("/bot"):].strip()
                            save_to_history(username, target or "", text)
                            # สะท้อนคำถามต้นฉบับกลับให้ผู้ส่งเห็นในแชทเดิม (ไม่ให้แชทหาย)
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
                        elif target in clients:
                            save_to_history(username, target, text)
                            payload = {
                                "type": "private_msg",
                                "sender": username,
                                "target": target,
                                "message": text
                            }
                            # ส่งให้ผู้รับ และส่งกลับให้ผู้ส่งเพื่อแสดงในหน้าต่างแชท
                            send_json(clients[target], payload)
                            if target != username:
                                send_json(client_socket, payload)

                # [R8] สร้างกลุ่มแชทใหม่ โดยเริ่มต้นมีแค่ผู้สร้างเป็นสมาชิกคนเดียว
                elif action == "create_group":
                    gname = msg.get("group_name", "").strip()
                    with lock:
                        if gname and gname not in groups:
                            groups[gname] = [username]
                            broadcast_group_list()
                            send_json(client_socket, {
                                "type": "group_joined",
                                "group_name": gname
                            })

                # [R10] Client กดเลือกเข้าร่วมกลุ่มแชทด้วยตัวเองเท่านั้น
                elif action == "join_group":
                    gname = msg.get("group_name", "").strip()
                    with lock:
                        if gname in groups:
                            if username not in groups[gname]:
                                groups[gname].append(username)
                                broadcast_group_list()
                            send_json(client_socket, {
                                "type": "group_joined",
                                "group_name": gname
                            })

                # [R11] ส่งข้อความเข้ากลุ่มแชท (เห็นเฉพาะสมาชิกที่อยู่ในกลุ่มนั้น)
                elif action == "group_msg":
                    gname = msg.get("group_name")
                    text = msg.get("message")
                    with lock:
                        if gname in groups and username in groups[gname]:
                            if text and text.strip().startswith("/bot"):
                                question = text.strip()
                                if question.startswith("/bot"):
                                    question = question[len("/bot"):].strip()
                                save_to_history(username, gname, text)
                                # สะท้อนคำถามต้นฉบับให้สมาชิกในกลุ่มเห็น (ไม่ให้แชทหาย)
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
                            else:
                                save_to_history(username, gname, text)
                                payload = {
                                    "type": "group_msg",
                                    "group_name": gname,
                                    "sender": username,
                                    "message": text
                                }
                                for member in groups[gname]:
                                    if member in clients:
                                        send_json(clients[member], payload)

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
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen()
    print(f"[SERVER RUNNING] Listening on {HOST}:{PORT}")
    while True:
        client_sock, addr = server_socket.accept()
        threading.Thread(target=handle_client, args=(client_sock, addr), daemon=True).start()

if __name__ == "__main__":
    start_server()