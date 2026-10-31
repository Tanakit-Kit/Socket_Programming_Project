"use client";

import { useState, useEffect, useRef, useCallback } from "react";

type Message = {
  sender: string;
  message: string;
  timestamp: string;
};

type Room = {
  id: string;
  name: string;
  type: "private" | "group";
  messages: Message[];
};

type ServerMsg =
  | { type: "register_result"; success: boolean; username?: string; message?: string }
  | { type: "user_list"; users: string[] }
  | { type: "group_list"; groups: Record<string, string[]> }
  | { type: "private_msg"; sender: string; target: string; message: string; timestamp: string }
  | { type: "private_history"; peer: string; history: Array<{ sender: string; message: string; timestamp: string }> }
  | { type: "group_joined"; group_name: string }
  | { type: "group_history"; group_name: string; history: Array<{ sender: string; message: string; timestamp: string }> }
  | { type: "group_msg"; group_name: string; sender: string; message: string; timestamp: string };

export default function Home() {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [username, setUsername] = useState("");
  const [registerOpen, setRegisterOpen] = useState(true);
  const [regName, setRegName] = useState("");
  const [regError, setRegError] = useState("");
  const [onlineUsers, setOnlineUsers] = useState<string[]>([]);
  const [groups, setGroups] = useState<Record<string, string[]>>({});
  const [rooms, setRooms] = useState<Room[]>([]);
  const [activeRoomId, setActiveRoomId] = useState<string | null>(null);
  const [inputText, setInputText] = useState("");
  const [newGroupName, setNewGroupName] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const send = useCallback(
    (data: unknown) => {
      const socket = wsRef.current;
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify(data));
      }
    },
    []
  );

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  const handleMessage = useCallback((msg: ServerMsg) => {
    switch (msg.type) {
      case "register_result":
        if (msg.success) {
          setUsername(msg.username || "");
          setRegisterOpen(false);
          document.title = `Chat Application - ${msg.username}`;
        } else {
          setRegError(msg.message || "Registration failed");
        }
        break;
      case "user_list":
        setOnlineUsers(msg.users);
        break;
      case "group_list":
        setGroups(msg.groups);
        break;
      case "private_msg": {
        const peer = msg.sender === username ? msg.target : msg.sender;
        const roomId = `private:${peer}`;
        setRooms((prev) => {
          const existing = prev.find((r) => r.id === roomId);
          if (existing) {
            return prev.map((r) =>
              r.id === roomId
                ? {
                    ...r,
                    messages: [
                      ...r.messages,
                      { sender: msg.sender, message: msg.message, timestamp: msg.timestamp },
                    ],
                  }
                : r
            );
          }
          return [
            ...prev,
            {
              id: roomId,
              name: `Private Chat กับ ${peer}`,
              type: "private",
              messages: [{ sender: msg.sender, message: msg.message, timestamp: msg.timestamp }],
            },
          ];
        });
        setActiveRoomId(roomId);
        break;
      }
      case "private_history": {
        const peer = msg.peer;
        const roomId = `private:${peer}`;
        setRooms((prev) => {
          const existing = prev.find((r) => r.id === roomId);
          if (existing) {
            return prev.map((r) =>
              r.id === roomId
                ? {
                    ...r,
                    messages: msg.history.map((h) => ({
                      sender: h.sender,
                      message: h.message,
                      timestamp: h.timestamp,
                    })),
                  }
                : r
            );
          }
          return [
            ...prev,
            {
              id: roomId,
              name: `Private Chat กับ ${peer}`,
              type: "private",
              messages: msg.history.map((h) => ({
                sender: h.sender,
                message: h.message,
                timestamp: h.timestamp,
              })),
            },
          ];
        });
        break;
      }
      case "group_joined": {
        const gname = msg.group_name;
        const roomId = `group:${gname}`;
        setRooms((prev) => {
          if (prev.find((r) => r.id === roomId)) return prev;
          return [
            ...prev,
            { id: roomId, name: `Group Chat: ${gname}`, type: "group", messages: [] },
          ];
        });
        setActiveRoomId(roomId);
        break;
      }
      case "group_history": {
        const gname = msg.group_name;
        const roomId = `group:${gname}`;
        setRooms((prev) => {
          const existing = prev.find((r) => r.id === roomId);
          if (existing) {
            return prev.map((r) =>
              r.id === roomId
                ? {
                    ...r,
                    messages: msg.history.map((h) => ({
                      sender: h.sender,
                      message: h.message,
                      timestamp: h.timestamp,
                    })),
                  }
                : r
            );
          }
          return [
            ...prev,
            {
              id: roomId,
              name: `Group Chat: ${gname}`,
              type: "group",
              messages: msg.history.map((h) => ({
                sender: h.sender,
                message: h.message,
                timestamp: h.timestamp,
              })),
            },
          ];
        });
        break;
      }
      case "group_msg": {
        const gname = msg.group_name;
        const roomId = `group:${gname}`;
        setRooms((prev) => {
          const existing = prev.find((r) => r.id === roomId);
          if (existing) {
            return prev.map((r) =>
              r.id === roomId
                ? {
                    ...r,
                    messages: [
                      ...r.messages,
                      { sender: msg.sender, message: msg.message, timestamp: msg.timestamp },
                    ],
                  }
                : r
            );
          }
          return [
            ...prev,
            {
              id: roomId,
              name: `Group Chat: ${gname}`,
              type: "group",
              messages: [{ sender: msg.sender, message: msg.message, timestamp: msg.timestamp }],
            },
          ];
        });
        setActiveRoomId(roomId);
        break;
      }
    }
  }, [username]);

  useEffect(() => {
    const socket = new WebSocket("ws://localhost:5000");
    wsRef.current = socket;
    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as ServerMsg;
        handleMessage(msg);
      } catch {
        // ignore malformed frames
      }
    };
    return () => {
      socket.close();
      wsRef.current = null;
    };
  }, [handleMessage]);

  useEffect(() => {
    scrollToBottom();
  }, [rooms, activeRoomId, scrollToBottom]);

  const handleRegister = (e: React.FormEvent) => {
    e.preventDefault();
    if (!regName.trim()) return;
    setRegError("");
    send({ type: "register", username: regName.trim() });
  };

  const handleSend = () => {
    if (!inputText.trim() || !activeRoomId) return;
    const [kind, target] = activeRoomId.split(":");
    if (kind === "private") {
      send({ type: "private_msg", target, message: inputText.trim() });
    } else {
      send({ type: "group_msg", group_name: target, message: inputText.trim() });
    }
    setInputText("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleSend();
  };

  const openPrivateChat = (peer: string) => {
    const roomId = `private:${peer}`;
    if (!rooms.find((r) => r.id === roomId)) {
      send({ type: "get_private_history", peer });
    }
    setActiveRoomId(roomId);
  };

  const createGroup = () => {
    if (!newGroupName.trim()) return;
    send({ type: "create_group", group_name: newGroupName.trim() });
    setNewGroupName("");
  };

  const joinGroup = (gname: string) => {
    const members = groups[gname] || [];
    if (members.includes(username)) {
      setActiveRoomId(`group:${gname}`);
      send({ type: "get_group_history", group_name: gname });
    } else {
      send({ type: "join_group", group_name: gname });
    }
  };

  const isMember = (gname: string) => {
    return (groups[gname] || []).includes(username);
  };

  const closeTab = (e: React.MouseEvent, roomId: string) => {
    e.stopPropagation();
    setRooms((prev) => prev.filter((r) => r.id !== roomId));
    if (activeRoomId === roomId) {
      setActiveRoomId(rooms.length > 1 ? (rooms.find((r) => r.id !== roomId)?.id || null) : null);
    }
  };

  if (registerOpen) {
    return (
      <div className="flex flex-col flex-1 items-center justify-center bg-green-50 font-sans">
        <div className="w-full max-w-md bg-white rounded-2xl shadow-lg p-8 border border-green-100">
          <div className="flex items-center gap-2 mb-6">
            <span className="text-green-500">▋</span>
            <h1 className="text-2xl font-bold text-green-700">LINE-like Chat</h1>
          </div>
          <p className="text-green-600 text-sm mb-6">Register your name to join the chat</p>
          <form onSubmit={handleRegister} className="space-y-3">
            <input
              type="text"
              placeholder="ตั้งชื่อของคุณ"
              value={regName}
              onChange={(e) => setRegName(e.target.value)}
              className="w-full px-4 py-3 rounded-xl border border-green-200 focus:outline-none focus:ring-2 focus:ring-green-500 text-green-800 placeholder-green-300"
              autoFocus
            />
            {regError && (
              <p className="text-red-500 text-sm">{regError}</p>
            )}
            <button
              type="submit"
              disabled={!regName.trim() || !connected}
              className="w-full py-3 rounded-xl bg-green-500 text-white font-semibold disabled:opacity-50 hover:bg-green-600 transition"
            >
              {connected ? "Join Chat" : "Connecting..."}
            </button>
          </form>
          <p className="mt-4 text-xs text-green-400">
            Server status: {connected ? "Connected" : "Disconnecting"}
          </p>
        </div>
      </div>
    );
  }

  const activeRoom = rooms.find((r) => r.id === activeRoomId);

  return (
    <div className="flex flex-col flex-1 h-screen bg-green-50 font-sans overflow-hidden">
      <header className="h-16 bg-white border-b border-green-100 flex items-center justify-between px-6 shrink-0">
        <div className="flex items-center gap-3">
          <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse"></span>
          <span className="text-green-700 font-semibold">LINE-like Chat</span>
        </div>
        <div className="flex items-center gap-4">
          <span className="text-green-600 text-sm">{username}</span>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <aside className="w-80 bg-white border-r border-green-100 shrink-0 flex flex-col">
          <div className="p-4 border-b border-green-50">
            <h2 className="text-xs font-bold text-green-600 uppercase tracking-wider">Online Clients</h2>
            <div className="mt-2 space-y-1">
              {onlineUsers.map((u) => (
                <div
                  key={u}
                  onClick={() => openPrivateChat(u)}
                  className={`cursor-pointer px-3 py-2 rounded-lg text-sm hover:bg-green-50 ${
                    u === username ? "bg-green-100 font-medium" : "text-green-800"
                  }`}
                >
                  {u}{u === username && " (You)"}
                </div>
              ))}
            </div>
            <button
              className="w-full mt-3 py-2 rounded-lg border border-green-200 text-green-600 text-sm font-medium hover:bg-green-50"
              disabled
            >
              เปิดแชทส่วนตัว (Private Chat)
            </button>
          </div>

          <div className="p-4 flex-1 overflow-y-auto">
            <h2 className="text-xs font-bold text-green-600 uppercase tracking-wider mb-3">Chat Groups</h2>
            <div className="space-y-2 mb-4">
              {Object.entries(groups).map(([gname, members]) => (
                <div
                  key={gname}
                  onClick={() => joinGroup(gname)}
                  className={`cursor-pointer p-3 rounded-xl border text-sm ${
                    isMember(gname)
                      ? "bg-green-50 border-green-200 text-green-800"
                      : "border-green-100 text-green-600 hover:bg-green-50"
                  }`}
                >
                  <div className="flex justify-between items-start">
                    <span className="font-medium">{isMember(gname) ? "✓ " : ""}{gname}</span>
                    <span className="text-[10px] bg-green-100 text-green-600 px-2 py-0.5 rounded">
                      {members.length}
                    </span>
                  </div>
                  <div className="mt-1 text-[11px] text-green-500 truncate">
                    {members.join(", ")}
                  </div>
                </div>
              ))}
            </div>
            <div className="space-y-2">
              <input
                type="text"
                placeholder="ตั้งชื่อกลุ่มแชทใหม่"
                value={newGroupName}
                onChange={(e) => setNewGroupName(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-green-200 focus:outline-none focus:ring-2 focus:ring-green-500 text-sm"
              />
              <button
                onClick={createGroup}
                className="w-full py-2 rounded-lg bg-green-500 text-white text-sm font-semibold hover:bg-green-600 transition disabled:opacity-50"
                disabled={!newGroupName.trim()}
              >
                สร้างกลุ่มใหม่
              </button>
              <button
                className="w-full py-2 rounded-lg border border-green-200 text-green-600 text-sm font-medium hover:bg-green-50 mt-2"
                disabled
              >
                เปิดอ่าน / เข้าร่วมกลุ่ม
              </button>
            </div>
          </div>
        </aside>

        <main className="flex-1 bg-white relative flex flex-col overflow-hidden">
          {rooms.length > 0 && (
            <div className="border-b border-green-100 shrink-0">
              <div className="flex overflow-x-auto pb-1 px-2 gap-1 scrollbar-hide">
                {rooms.map((room) => (
                  <div
                    key={room.id}
                    onClick={() => setActiveRoomId(room.id)}
                    onMouseDown={(e) => e.preventDefault()}
                    className={`flex items-center gap-2 px-4 py-2 rounded-t-xl border-b-2 ${
                      activeRoomId === room.id
                        ? "border-green-500 bg-green-50 text-green-700 font-medium"
                        : "border-transparent bg-white text-green-600 hover:bg-green-50"
                    } cursor-pointer`}
                  >
                    <span className={`text-sm ${room.type === "private" ? "text-green-500" : "text-green-600"}`}>
                      {room.type === "private" ? "👤" : "👥"}
                    </span>
                    <span className="text-sm truncate max-w-[120px]">{room.name}</span>
                    <button
                      onClick={(e) => closeTab(e, room.id)}
                      className="ml-1 opacity-0 group-hover:opacity-100 hover:bg-red-100 text-red-500 rounded-full p-1 transition"
                      title="Close"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="flex-1 overflow-y-auto p-6" ref={scrollRef}>
            {activeRoom ? (
              <div className="space-y-4 max-h-full">
                <div className="flex items-center justify-between mb-2">
                  <h3 className="font-bold text-green-700 text-lg">{activeRoom.name}</h3>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    activeRoom.type === "private" ? "bg-green-100 text-green-700" : "bg-blue-100 text-blue-700"
                  }`}>
                    {activeRoom.type === "private" ? "Private" : "Group"}
                  </span>
                </div>
                <div className="space-y-2 max-h-[calc(100vh-240px)] overflow-y-auto pr-2">
                  {activeRoom.messages.map((m, i) => (
                    <div
                      key={i}
                      className={`flex ${
                        m.sender === username ? "justify-end" : "justify-start"
                      }`}
                    >
                      <div
                        className={`max-w-[75%] px-4 py-2 rounded-2xl text-sm ${
                          m.sender === username
                            ? "bg-green-500 text-white rounded-tr-none shadow-sm"
                            : "bg-white border border-green-100 text-green-800 rounded-tl-none shadow-sm"
                        }`}
                      >
                        <div className="flex items-baseline gap-1">
                          <span className={m.sender === username ? "" : "font-semibold text-green-700"}>
                            {m.sender}
                          </span>
                          {m.timestamp && (
                            <span className="text-[10px] opacity-60 ml-1">{m.timestamp}</span>
                          )}
                        </div>
                        <div className="mt-0.5">{m.message}</div>
                      </div>
                    </div>
                  ))}
                </div>
                {activeRoom.messages.length === 0 && (
                  <div className="text-center py-10 text-green-400 text-sm">
                    No messages yet. Start the conversation!
                  </div>
                )}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center h-full text-green-400">
                <p className="text-sm">Select a chat tab to start messaging</p>
              </div>
            )}
          </div>

          <div className="bg-white border-t border-green-100 p-4 shrink-0">
            <div className="flex gap-2 max-w-xl mx-auto">
              <input
                type="text"
                placeholder="พิมพ์ข้อความ..."
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={!activeRoomId}
                className="flex-1 px-4 py-3 rounded-xl border border-green-200 focus:outline-none focus:ring-2 focus:ring-green-500 text-green-800 disabled:opacity-50 disabled:border-green-100"
              />
              <button
                onClick={handleSend}
                disabled={!inputText.trim() || !activeRoomId}
                className="px-6 py-3 rounded-xl bg-green-500 text-white font-semibold disabled:opacity-50 hover:bg-green-600 transition disabled:hover:bg-green-500"
              >
                Send
              </button>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
