import socket
import threading
import json

class ChatNetworkClient:
    def __init__(self, server_ip='127.0.0.1', server_port=5000):
        self.server_ip = server_ip
        self.server_port = server_port
        self.sock = None
        self.running = False
        self.on_message_callback = None
        self._buffer = ""

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.server_ip, self.server_port))
        self.running = True

    def send_json(self, data):
        if self.sock:
            msg = json.dumps(data) + "\n"
            self.sock.sendall(msg.encode('utf-8'))

    def register_sync(self, username):
        """ส่งชื่อไปตรวจสอบกับ Server แบบรอผลลัพธ์ทันทีก่อนเปิดหน้าต่างหลัก (R3)"""
        self.send_json({"type": "register", "username": username})
        while "\n" not in self._buffer:
            data = self.sock.recv(4096)
            if not data:
                return {"success": False, "message": "การเชื่อมต่อถูกตัด"}
            self._buffer += data.decode('utf-8')
        line, self._buffer = self._buffer.split("\n", 1)
        return json.loads(line)

    def start_receiving(self, callback):
        """เริ่ม Thread รับข้อมูลจาก Server ตลอดเวลาส่งต่อไปยัง UI"""
        self.on_message_callback = callback
        threading.Thread(target=self._receive_loop, daemon=True).start()

    def _receive_loop(self):
        while self.running:
            try:
                while "\n" in self._buffer:
                    line, self._buffer = self._buffer.split("\n", 1)
                    if line.strip() and self.on_message_callback:
                        self.on_message_callback(json.loads(line))
                data = self.sock.recv(4096)
                if not data:
                    break
                self._buffer += data.decode('utf-8')
            except Exception:
                break

    # --- API สำหรับให้ Frontend เรียกใช้งาน ---
    def send_private_message(self, target, message):
        self.send_json({"type": "private_msg", "target": target, "message": message})

    def request_private_history(self, peer):
        self.send_json({"type": "get_private_history", "peer": peer})

    def create_group(self, group_name):
        self.send_json({"type": "create_group", "group_name": group_name})

    def join_group(self, group_name):
        self.send_json({"type": "join_group", "group_name": group_name})

    def request_group_history(self, group_name):
        self.send_json({"type": "get_group_history", "group_name": group_name})

    def send_group_message(self, group_name, message):
        self.send_json({"type": "group_msg", "group_name": group_name, "message": message})

    def close(self):
        self.running = False
        if self.sock:
            self.sock.close()