import tkinter as tk
from tkinter import ttk, simpledialog, messagebox, scrolledtext
from client_network import ChatNetworkClient

SERVER_IP = '127.0.0.1'  # เปลี่ยนเป็น IP เครื่อง Server เมื่อรันข้ามเครื่อง
SERVER_PORT = 5000

# [R5 & R6] คลาสหน้าต่างห้องแชทแยกแต่ละห้อง พร้อมฟังก์ชัน clear_messages()
class ChatRoomFrame(tk.Frame):
    def __init__(self, parent, room_title, send_callback):
        super().__init__(parent)
        self.send_callback = send_callback

        tk.Label(self, text=room_title, font=("Arial", 11, "bold")).pack(pady=3)

        self.chat_window = scrolledtext.ScrolledText(self, state='disabled', wrap='word', height=15)
        self.chat_window.pack(fill='both', expand=True, padx=5, pady=5)

        bottom_frame = tk.Frame(self)
        bottom_frame.pack(fill='x', padx=5, pady=5)

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

    def clear_messages(self):
        """ล้างข้อความในหน้าต่างแชทก่อนวาดประวัติแชทใหม่"""
        self.chat_window.config(state='normal')
        self.chat_window.delete('1.0', tk.END)
        self.chat_window.config(state='disabled')

    def append_message(self, sender, message):
        self.chat_window.config(state='normal')
        self.chat_window.insert(tk.END, f"{sender}: {message}\n")
        self.chat_window.yview(tk.END)
        self.chat_window.config(state='disabled')


class ChatClientGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Socket Chat Application")
        self.root.geometry("880x540")

        self.network = ChatNetworkClient(SERVER_IP, SERVER_PORT)
        try:
            self.network.connect()
        except Exception as e:
            messagebox.showerror("Connection Error", f"เชื่อมต่อ Server ไม่สำเร็จ: {e}")
            self.root.destroy()
            return

        self.username = None
        self.private_rooms = {}
        self.group_rooms = {}
        self.groups_data = {}

        if not self.prompt_unique_name():
            self.network.close()
            self.root.destroy()
            return

        self.root.title(f"Chat Application - ผู้ใช้: {self.username}")
        self.build_gui()

        # เริ่มรับข้อมูลจากโมดูล Network
        self.network.start_receiving(lambda msg: self.root.after(0, self.handle_incoming_message, msg))

    def prompt_unique_name(self):
        while True:
            name = simpledialog.askstring("Register Name", "ตั้งชื่อของคุณ (หากใช้ชื่อเดิม ประวัติแชทและกลุ่มเดิมจะกลับมา):", parent=self.root)
            if name is None:
                return False
            name = name.strip()
            if not name:
                continue
            res = self.network.register_sync(name)
            if res.get("success"):
                self.username = res.get("username")
                return True
            else:
                messagebox.showwarning("ชื่อซ้ำ", res.get("message"))

    def build_gui(self):
        left_panel = tk.Frame(self.root, width=300)
        left_panel.pack(side='left', fill='y', padx=8, pady=8)

        # [R4] รายชื่อผู้ใช้ออนไลน์ (ดับเบิลคลิกเพื่อเปิดแชทได้ทันที)
        tk.Label(left_panel, text="Online Clients (ดับเบิลคลิกเพื่อแชท):", font=("Arial", 10, "bold")).pack(anchor='w')
        self.user_listbox = tk.Listbox(left_panel, height=9)
        self.user_listbox.pack(fill='x', pady=3)
        self.user_listbox.bind("<Double-Button-1>", lambda e: self.open_selected_private_chat())
        tk.Button(left_panel, text="เปิดแชทส่วนตัว (Private Chat)", command=self.open_selected_private_chat).pack(fill='x', pady=2)

        tk.Frame(left_panel, height=12).pack()

        # [R9] รายชื่อกลุ่มพร้อมสมาชิก (ดับเบิลคลิกเพื่อเปิดอ่านหรือเข้าร่วม)
        tk.Label(left_panel, text="Chat Groups (ดับเบิลคลิกเพื่อเปิดอ่าน/เข้ากลุ่ม):", font=("Arial", 10, "bold")).pack(anchor='w')
        self.group_listbox = tk.Listbox(left_panel, height=9)
        self.group_listbox.pack(fill='x', pady=3)
        self.group_listbox.bind("<Double-Button-1>", lambda e: self.open_or_join_selected_group())

        btn_frame = tk.Frame(left_panel)
        btn_frame.pack(fill='x', pady=2)
        tk.Button(btn_frame, text="สร้างกลุ่มใหม่", command=self.create_group).pack(side='left', expand=True, fill='x', padx=(0, 2))
        tk.Button(btn_frame, text="เปิดอ่าน / เข้าร่วมกลุ่ม", command=self.open_or_join_selected_group).pack(side='right', expand=True, fill='x', padx=(2, 0))

        # [R5] แท็บแยกห้องแชท
        right_panel = tk.Frame(self.root)
        right_panel.pack(side='right', fill='both', expand=True, padx=8, pady=8)
        tk.Label(right_panel, text="Chat Rooms (แยกห้องสนทนาแต่ละห้อง):", font=("Arial", 10, "bold")).pack(anchor='w')
        self.notebook = ttk.Notebook(right_panel)
        self.notebook.pack(fill='both', expand=True, pady=3)

    def get_or_create_private_room(self, peer_name, switch_to=False):
        if peer_name not in self.private_rooms:
            room = ChatRoomFrame(
                self.notebook,
                f"Private Chat กับ {peer_name}",
                lambda text: self.network.send_private_message(peer_name, text)
            )
            self.notebook.add(room, text=f"ส่วนตัว: {peer_name}")
            self.private_rooms[peer_name] = room
            self.network.request_private_history(peer_name)
        if switch_to:
            self.notebook.select(self.private_rooms[peer_name])
        return self.private_rooms[peer_name]

    def get_or_create_group_room(self, group_name, switch_to=False):
        if group_name not in self.group_rooms:
            room = ChatRoomFrame(
                self.notebook,
                f"Group Chat: {group_name}",
                lambda text: self.network.send_group_message(group_name, text)
            )
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

    def create_group(self):
        gname = simpledialog.askstring("สร้างกลุ่ม", "ตั้งชื่อกลุ่มแชทใหม่:", parent=self.root)
        if gname and gname.strip():
            self.network.create_group(gname.strip())

    def open_or_join_selected_group(self):
        """หากอยู่ในกลุ่มแล้วจะสลับไปเปิดอ่านห้องแชททันที หากยังไม่อยู่จะส่งคำขอเข้าร่วมกลุ่ม (R10)"""
        sel = self.group_listbox.curselection()
        if not sel:
            messagebox.showinfo("เลือกกลุ่ม", "กรุณาคลิกเลือกกลุ่มที่ต้องการ")
            return
        item_text = self.group_listbox.get(sel[0])
        gname = item_text.split(" | สมาชิก: ")[0].replace("✓ ", "")
        members = self.groups_data.get(gname, [])

        if self.username in members:
            # เป็นสมาชิกอยู่แล้ว เปิดแท็บห้องแชทและดึงประวัติล่าสุดมาแสดงได้เลยโดยไม่ต้อง Join ใหม่
            self.get_or_create_group_room(gname, switch_to=True)
            self.network.request_group_history(gname)
        else:
            # ยังไม่ได้เป็นสมาชิก ส่งคำขอ Join Group
            self.network.join_group(gname)

    def handle_incoming_message(self, msg):
        mtype = msg.get("type")

        if mtype == "user_list":
            self.user_listbox.delete(0, tk.END)
            for u in msg.get("users", []):
                label = f"{u} (You)" if u == self.username else u
                self.user_listbox.insert(tk.END, label)

        elif mtype == "group_list":
            self.groups_data = msg.get("groups", {})
            self.group_listbox.delete(0, tk.END)
            for gname, members in self.groups_data.items():
                members_str = ", ".join(members)
                prefix = "✓ " if self.username in members else ""
                self.group_listbox.insert(tk.END, f"{prefix}{gname} | สมาชิก: [{members_str}]")

        elif mtype == "private_msg":
            sender = msg.get("sender")
            target = msg.get("target")
            text = msg.get("message")
            ts = msg.get("timestamp", "")
            peer = target if sender == self.username else sender
            room = self.get_or_create_private_room(peer, switch_to=(sender == self.username))
            room.append_message(f"[{ts}] {sender}" if ts else sender, text)

        elif mtype == "private_history":
            peer = msg.get("peer")
            room = self.get_or_create_private_room(peer, switch_to=False)
            room.clear_messages()
            for item in msg.get("history", []):
                ts = item.get("timestamp", "")
                sender = item.get("sender")
                text = item.get("message")
                room.append_message(f"[{ts}] {sender}" if ts else sender, text)

        elif mtype == "group_joined":
            gname = msg.get("group_name")
            self.get_or_create_group_room(gname, switch_to=True)

        elif mtype == "group_history":
            gname = msg.get("group_name")
            room = self.get_or_create_group_room(gname, switch_to=False)
            room.clear_messages()
            for item in msg.get("history", []):
                ts = item.get("timestamp", "")
                sender = item.get("sender")
                text = item.get("message")
                room.append_message(f"[{ts}] {sender}" if ts else sender, text)

        elif mtype == "group_msg":
            gname = msg.get("group_name")
            sender = msg.get("sender")
            text = msg.get("message")
            ts = msg.get("timestamp", "")
            room = self.get_or_create_group_room(gname, switch_to=False)
            room.append_message(f"[{ts}] {sender}" if ts else sender, text)


if __name__ == "__main__":
    root = tk.Tk()
    app = ChatClientGUI(root)
    root.mainloop()