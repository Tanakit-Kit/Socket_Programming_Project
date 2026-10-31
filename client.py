import socket
import threading
import json
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox, scrolledtext

SERVER_IP = '127.0.0.1'  # เปลี่ยนเป็น IP ของเครื่อง Server เมื่อรันข้ามเครื่อง
SERVER_PORT = 5000

# [R5 & R6] คลาสสำหรับสร้างห้องแชทแยกแต่ละห้อง พร้อมหน้าต่างแสดงผลและช่องพิมพ์ข้อความ
class ChatRoomFrame(tk.Frame):
    def __init__(self, parent, room_title, send_callback):
        super().__init__(parent)
        self.send_callback = send_callback

        tk.Label(self, text=room_title, font=("Arial", 11, "bold")).pack(pady=3)

        # [R6] Chat Window สำหรับแสดงข้อความที่ส่งและข้อความเข้าใหม่
        self.chat_window = scrolledtext.ScrolledText(self, state='disabled', wrap='word', height=15)
        self.chat_window.pack(fill='both', expand=True, padx=5, pady=5)

        bottom_frame = tk.Frame(self)
        bottom_frame.pack(fill='x', padx=5, pady=5)

        # [R6] Chat Box สำหรับพิมพ์ข้อความและปุ่มกดส่ง
        self.chat_box = tk.Entry(bottom_frame, font=("Arial", 10))
        self.chat_box.pack(side='left', fill='x', expand=True, padx=(0, 5))
        self.chat_box.bind("<Return>", lambda event: self.on_send())

        send_btn = tk.Button(bottom_frame, text="Send", width=8, command=self.on_send)
        send_btn.pack(side='right')

    def on_send(self):
        text = self.chat_box.get().strip()
        if text:
            self.send_callback(text)
            self.chat_box.delete(0, tk.END)

    def append_message(self, sender, message):
        self.chat_window.config(state='normal')
        self.chat_window.insert(tk.END, f"{sender}: {message}\n")
        self.chat_window.yview(tk.END)
        self.chat_window.config(state='disabled')


class ChatClientApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Socket Chat Application")
        self.root.geometry("850x520")

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.connect((SERVER_IP, SERVER_PORT))
        except Exception as e:
            messagebox.showerror("Connection Error", f"เชื่อมต่อ Server ไม่สำเร็จ: {e}")
            self.root.destroy()
            return

        self.username = None
        self.private_rooms = {}  # เก็บห้องแชทส่วนตัว {peer_name: ChatRoomFrame}
        self.group_rooms = {}    # เก็บห้องแชทกลุ่ม {group_name: ChatRoomFrame}
        self.groups_data = {}    # เก็บข้อมูลกลุ่ม {group_name: [members]}

        # [R3] ขอตั้งชื่อผู้ใช้ที่ไม่ซ้ำกันก่อนเข้าใช้งาน
        if not self.register_unique_name():
            self.root.destroy()
            return

        self.root.title(f"Chat Application - ผู้ใช้: {self.username}")
        self.build_gui()

        # เริ่ม Thread รับข้อมูลจาก Server ตลอดเวลา
        threading.Thread(target=self.receive_loop, daemon=True).start()

    # [R2] ส่งข้อมูล JSON ผ่าน Socket
    def send_json(self, data):
        try:
            msg = json.dumps(data) + "\n"
            self.sock.sendall(msg.encode('utf-8'))
        except Exception as e:
            messagebox.showerror("Error", f"การส่งข้อมูลล้มเหลว: {e}")

    # [R3] ฟังก์ชันรับชื่อจากผู้ใช้และตรวจสอบกับ Server จนกว่าจะได้ชื่อที่ไม่ซ้ำ
    def register_unique_name(self):
        buffer = ""
        while True:
            name = simpledialog.askstring("Register Name", "ตั้งชื่อของคุณ (ห้ามซ้ำกับคนอื่น):", parent=self.root)
            if name is None:
                return False
            name = name.strip()
            if not name:
                continue
            self.send_json({"type": "register", "username": name})
            while "\n" not in buffer:
                data = self.sock.recv(4096)
                if not data:
                    return False
                buffer += data.decode('utf-8')
            line, buffer = buffer.split("\n", 1)
            res = json.loads(line)
            if res.get("type") == "register_result":
                if res.get("success"):
                    self.username = res.get("username")
                    self.initial_buffer = buffer
                    return True
                else:
                    messagebox.showwarning("ชื่อซ้ำ", res.get("message"))

    def build_gui(self):
        left_panel = tk.Frame(self.root, width=280)
        left_panel.pack(side='left', fill='y', padx=8, pady=8)

        # [R4] ส่วนแสดงรายชื่อ Client ทั้งหมดที่ออนไลน์ (รวมชื่อตัวเอง)
        tk.Label(left_panel, text="Online Clients (รวมชื่อตัวเอง):", font=("Arial", 10, "bold")).pack(anchor='w')
        self.user_listbox = tk.Listbox(left_panel, height=9)
        self.user_listbox.pack(fill='x', pady=3)
        tk.Button(left_panel, text="แชทส่วนตัว (Private Chat)", command=self.open_selected_private_chat).pack(fill='x', pady=2)

        tk.Frame(left_panel, height=15).pack()

        # [R9] ส่วนแสดงรายชื่อกลุ่มทั้งหมดพร้อมรายชื่อสมาชิก
        tk.Label(left_panel, text="Chat Groups (พร้อมรายชื่อสมาชิก):", font=("Arial", 10, "bold")).pack(anchor='w')
        self.group_listbox = tk.Listbox(left_panel, height=9)
        self.group_listbox.pack(fill='x', pady=3)

        # [R8 & R10] ปุ่มสร้างกลุ่มใหม่ และปุ่มกดเข้าร่วมกลุ่มด้วยตัวเอง
        btn_frame = tk.Frame(left_panel)
        btn_frame.pack(fill='x', pady=2)
        tk.Button(btn_frame, text="สร้างกลุ่มใหม่", command=self.create_group).pack(side='left', expand=True, fill='x', padx=(0, 2))
        tk.Button(btn_frame, text="เข้าร่วมกลุ่ม (Join)", command=self.join_selected_group).pack(side='right', expand=True, fill='x', padx=(2, 0))

        # [R5] พื้นที่แยกห้องแชทแต่ละห้อง (ใช้ Tab แยกแต่ละ Chat Room ออกจากกัน)
        right_panel = tk.Frame(self.root)
        right_panel.pack(side='right', fill='both', expand=True, padx=8, pady=8)
        tk.Label(right_panel, text="Chat Rooms (แยกห้องสนทนาแต่ละห้อง):", font=("Arial", 10, "bold")).pack(anchor='w')
        self.notebook = ttk.Notebook(right_panel)
        self.notebook.pack(fill='both', expand=True, pady=3)

    # [R5 & R7] เปิดหรือสลับไปยังห้องแชทส่วนตัว
    def get_or_create_private_room(self, peer_name, switch_to=False):
        if peer_name not in self.private_rooms:
            def send_priv(text):
                self.send_json({"type": "private_msg", "target": peer_name, "message": text})

            room = ChatRoomFrame(self.notebook, f"Private Chat กับ {peer_name}", send_priv)
            self.notebook.add(room, text=f"ส่วนตัว: {peer_name}")
            self.private_rooms[peer_name] = room
        if switch_to:
            self.notebook.select(self.private_rooms[peer_name])
        return self.private_rooms[peer_name]

    # [R5 & R11] เปิดหรือสลับไปยังห้องแชทกลุ่ม
    def get_or_create_group_room(self, group_name, switch_to=False):
        if group_name not in self.group_rooms:
            def send_grp(text):
                self.send_json({"type": "group_msg", "group_name": group_name, "message": text})

            room = ChatRoomFrame(self.notebook, f"Group Chat: {group_name}", send_grp)
            self.notebook.add(room, text=f"กลุ่ม: {group_name}")
            self.group_rooms[group_name] = room
        if switch_to:
            self.notebook.select(self.group_rooms[group_name])
        return self.group_rooms[group_name]

    def open_selected_private_chat(self):
        sel = self.user_listbox.curselection()
        if not sel:
            messagebox.showinfo("เลือกผู้รับ", "กรุณาคลิกเลือกชื่อเพื่อนในรายการก่อน")
            return
        peer = self.user_listbox.get(sel[0]).replace(" (You)", "")
        self.get_or_create_private_room(peer, switch_to=True)

    # [R8] สร้างกลุ่มใหม่
    def create_group(self):
        gname = simpledialog.askstring("สร้างกลุ่ม", "ตั้งชื่อกลุ่มแชทใหม่:", parent=self.root)
        if gname and gname.strip():
            self.send_json({"type": "create_group", "group_name": gname.strip()})

    # [R10] กดเข้าร่วมกลุ่มด้วยตัวเอง
    def join_selected_group(self):
        sel = self.group_listbox.curselection()
        if not sel:
            messagebox.showinfo("เลือกกลุ่ม", "กรุณาคลิกเลือกกลุ่มที่ต้องการเข้าร่วม")
            return
        item_text = self.group_listbox.get(sel[0])
        gname = item_text.split(" | สมาชิก: ")[0]
        self.send_json({"type": "join_group", "group_name": gname})

    def receive_loop(self):
        buffer = getattr(self, 'initial_buffer', "")
        while True:
            try:
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.strip():
                        msg = json.loads(line)
                        self.root.after(0, self.process_incoming_message, msg)
                data = self.sock.recv(4096)
                if not data:
                    break
                buffer += data.decode('utf-8')
            except Exception:
                break

    def process_incoming_message(self, msg):
        mtype = msg.get("type")

        # [R4] อัปเดตรายชื่อผู้ใช้ออนไลน์บนหน้าจอ
        if mtype == "user_list":
            self.user_listbox.delete(0, tk.END)
            for u in msg.get("users", []):
                label = f"{u} (You)" if u == self.username else u
                self.user_listbox.insert(tk.END, label)

        # [R9] อัปเดตรายชื่อกลุ่มและสมาชิกบนหน้าจอ
        elif mtype == "group_list":
            self.groups_data = msg.get("groups", {})
            self.group_listbox.delete(0, tk.END)
            for gname, members in self.groups_data.items():
                members_str = ", ".join(members)
                self.group_listbox.insert(tk.END, f"{gname} | สมาชิก: [{members_str}]")

        # [R7] แสดงข้อความแชทส่วนตัวในห้องแชทของคู่นั้น
        elif mtype == "private_msg":
            sender = msg.get("sender")
            target = msg.get("target")
            text = msg.get("message")
            peer = target if sender == self.username else sender
            room = self.get_or_create_private_room(peer, switch_to=(sender == self.username))
            room.append_message(sender, text)

        # [R8 & R10] เมื่อสร้างหรือกดเข้าร่วมกลุ่มสำเร็จ ให้เปิดห้องแชทของกลุ่มนั้น
        elif mtype == "group_joined":
            gname = msg.get("group_name")
            self.get_or_create_group_room(gname, switch_to=True)

        # [R11] แสดงข้อความแชทกลุ่มเฉพาะกลุ่มที่ตัวเองเป็นสมาชิก
        elif mtype == "group_msg":
            gname = msg.get("group_name")
            sender = msg.get("sender")
            text = msg.get("message")
            room = self.get_or_create_group_room(gname, switch_to=False)
            room.append_message(sender, text)


if __name__ == "__main__":
    root = tk.Tk()
    app = ChatClientApp(root)
    root.mainloop()