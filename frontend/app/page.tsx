"use client";

import { useState, useEffect, useRef, useCallback } from "react";

type Message = {
  sender: string;
  message: string;
  timestamp: string;
};

type Room = {
  id: string;
  target: string;
  name: string;
  type: "private" | "group";
  messages: Message[];
  unread: number;
};

type ServerMsg =
  | { type: "register_result"; success: boolean; username?: string; message?: string }
  | { type: "user_list"; users: string[] }
  | { type: "group_list"; groups: Record<string, string[]> }
  | { type: "private_msg"; sender: string; target: string; peer?: string; message: string; timestamp: string }
  | { type: "private_history"; peer: string; history: Array<{ sender: string; message: string; timestamp: string }> }
  | { type: "group_joined"; group_name: string }
  | { type: "group_history"; group_name: string; history: Array<{ sender: string; message: string; timestamp: string }> }
  | { type: "group_msg"; group_name: string; sender: string; message: string; timestamp: string };

export default function Home() {
  const wsRef = useRef<WebSocket | null>(null);
  const usernameRef = useRef<string>("");
  const activeRoomIdRef = useRef<string | null>(null);
  const knownPrivateRooms = useRef(new Set<string>());
  const scrollRef = useRef<HTMLDivElement>(null);

  const [serverUrl, setServerUrl] = useState(process.env.NEXT_PUBLIC_CHAT_WS_URL || "");
  const [reconnectTrigger, setReconnectTrigger] = useState(0);
  const [connected, setConnected] = useState(false);
  const [username, setUsername] = useState("");
  const [registerOpen, setRegisterOpen] = useState(true);
  const [regName, setRegName] = useState("");
  const [regError, setRegError] = useState("");
  const [onlineUsers, setOnlineUsers] = useState<string[]>([]);
  const [groups, setGroups] = useState<Record<string, string[]>>({});
  const [rooms, setRooms] = useState<Room[]>([]);
  const [activeRoomId, setActiveRoomId] = useState<string | null>(null);
  const [selectedUser, setSelectedUser] = useState<string | null>(null);
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const [inputText, setInputText] = useState("");
  const [newGroupName, setNewGroupName] = useState("");

  // Sync refs with state so WebSocket message handler always sees current values without re-connecting
  useEffect(() => {
    usernameRef.current = username;
  }, [username]);

  useEffect(() => {
    activeRoomIdRef.current = activeRoomId;
  }, [activeRoomId]);

  const selectRoom = useCallback((roomId: string | null) => {
    activeRoomIdRef.current = roomId;
    setActiveRoomId(roomId);
    if (roomId) {
      setRooms((prev) =>
        prev.map((r) => (r.id === roomId && r.unread > 0 ? { ...r, unread: 0 } : r))
      );
    }
  }, []);

  const sendJson = useCallback((data: Record<string, unknown>) => {
    const socket = wsRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(data));
    }
  }, []);

  // ============================================================================
  // Socket API Calls (Matching Python Backend Protocol R3, R7, R8, R10, R11 + DB History)
  // ============================================================================

  /** R3: ส่งชื่อไปลงทะเบียน (ห้ามซ้ำ) */
  const register_name = useCallback(
    (uname: string) => {
      sendJson({ type: "register", username: uname });
    },
    [sendJson]
  );

  /** R7: ส่งข้อความแชทส่วนตัว */
  const send_private_message = useCallback(
    (target_user: string, message: string) => {
      sendJson({ type: "private_msg", target: target_user, message });
    },
    [sendJson]
  );

  /** R8: สร้างกลุ่มแชทใหม่ (เริ่มต้นมีตัวเองคนเดียว) */
  const create_group = useCallback(
    (group_name: string) => {
      sendJson({ type: "create_group", group_name });
    },
    [sendJson]
  );

  /** R10: กดเข้าร่วมกลุ่มแชทด้วยตัวเอง */
  const join_group = useCallback(
    (group_name: string) => {
      sendJson({ type: "join_group", group_name });
    },
    [sendJson]
  );

  /** R11: ส่งข้อความเข้ากลุ่มแชท */
  const send_group_message = useCallback(
    (group_name: string, message: string) => {
      sendJson({ type: "group_msg", group_name, message });
    },
    [sendJson]
  );

  /** ขอดึงประวัติแชทส่วนตัวกับเพื่อนคนนั้น */
  const request_private_history = useCallback(
    (peer_name: string) => {
      sendJson({ type: "get_private_history", peer: peer_name });
    },
    [sendJson]
  );

  /** ขอดึงประวัติแชทของกลุ่ม */
  const request_group_history = useCallback(
    (group_name: string) => {
      sendJson({ type: "get_group_history", group_name });
    },
    [sendJson]
  );

  // ============================================================================
  // Incoming WebSocket Message Handler
  // ============================================================================

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  const handleMessage = useCallback(
    (msg: ServerMsg) => {
      const currentUser = usernameRef.current;

      switch (msg.type) {
        case "register_result":
          if (msg.success) {
            const registeredName = msg.username || "";
            usernameRef.current = registeredName;
            setUsername(registeredName);
            setRegisterOpen(false);
            setRegError("");
            document.title = `Chat Application - ผู้ใช้: ${registeredName}`;
          } else {
            setRegError(msg.message || "ชื่อนี้กำลังออนไลน์อยู่ กรุณาใช้ชื่ออื่น");
          }
          break;

        case "user_list":
          setOnlineUsers(msg.users);
          break;

        case "group_list":
          setGroups(msg.groups);
          break;

        case "private_msg": {
          const peer = msg.peer ?? (msg.sender === currentUser ? msg.target : msg.sender);
          const roomId = `private:${peer}`;
          if (!knownPrivateRooms.current.has(roomId)) {
            knownPrivateRooms.current.add(roomId);
            request_private_history(peer);
          }
          const isCurrentRoom = activeRoomIdRef.current === roomId;
          const shouldSwitch = msg.sender === currentUser || !activeRoomIdRef.current;

          setRooms((prev) => {
            const existing = prev.find((r) => r.id === roomId);
            if (existing) {
              return prev.map((r) =>
                r.id === roomId
                  ? {
                      ...r,
                      unread: isCurrentRoom || shouldSwitch ? 0 : r.unread + 1,
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
                target: peer,
                name: `Private Chat กับ ${peer}`,
                type: "private",
                unread: isCurrentRoom || shouldSwitch ? 0 : 1,
                messages: [{ sender: msg.sender, message: msg.message, timestamp: msg.timestamp }],
              },
            ];
          });

          if (shouldSwitch) {
            setActiveRoomId(roomId);
          }
          break;
        }

        case "private_history": {
          const peer = msg.peer;
          const roomId = `private:${peer}`;
          const formatted = msg.history.map((h) => ({
            sender: h.sender,
            message: h.message,
            timestamp: h.timestamp,
          }));

          setRooms((prev) => {
            const existing = prev.find((r) => r.id === roomId);
            if (existing) {
              return prev.map((r) =>
                r.id === roomId
                  ? {
                      ...r,
                      messages: formatted,
                    }
                  : r
              );
            }
            return [
              ...prev,
              {
                id: roomId,
                target: peer,
                name: `Private Chat กับ ${peer}`,
                type: "private",
                unread: 0,
                messages: formatted,
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
              {
                id: roomId,
                target: gname,
                name: `Group Chat: ${gname}`,
                type: "group",
                unread: 0,
                messages: [],
              },
            ];
          });
          setActiveRoomId(roomId);
          break;
        }

        case "group_history": {
          const gname = msg.group_name;
          const roomId = `group:${gname}`;
          const formatted = msg.history.map((h) => ({
            sender: h.sender,
            message: h.message,
            timestamp: h.timestamp,
          }));

          setRooms((prev) => {
            const existing = prev.find((r) => r.id === roomId);
            if (existing) {
              return prev.map((r) =>
                r.id === roomId
                  ? {
                      ...r,
                      messages: formatted,
                    }
                  : r
              );
            }
            return [
              ...prev,
              {
                id: roomId,
                target: gname,
                name: `Group Chat: ${gname}`,
                type: "group",
                unread: 0,
                messages: formatted,
              },
            ];
          });
          break;
        }

        case "group_msg": {
          const gname = msg.group_name;
          const roomId = `group:${gname}`;
          const isCurrentRoom = activeRoomIdRef.current === roomId;
          const shouldSwitch = msg.sender === currentUser || !activeRoomIdRef.current;

          setRooms((prev) => {
            const existing = prev.find((r) => r.id === roomId);
            if (existing) {
              return prev.map((r) =>
                r.id === roomId
                  ? {
                      ...r,
                      unread: isCurrentRoom || shouldSwitch ? 0 : r.unread + 1,
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
                target: gname,
                name: `Group Chat: ${gname}`,
                type: "group",
                unread: isCurrentRoom || shouldSwitch ? 0 : 1,
                messages: [{ sender: msg.sender, message: msg.message, timestamp: msg.timestamp }],
              },
            ];
          });

          if (shouldSwitch) {
            setActiveRoomId(roomId);
          }
          break;
        }
      }
    },
    [request_private_history]
  );

  useEffect(() => {
    let socket: WebSocket | null = null;
    try {
      socket = new WebSocket(serverUrl);
      wsRef.current = socket;
      socket.onopen = () => {
        setConnected(true);
        setRegError("");
      };
      socket.onclose = () => {
        setConnected(false);
        setRegisterOpen(true);
        usernameRef.current = "";
        activeRoomIdRef.current = null;
        setUsername("");
        knownPrivateRooms.current.clear();
        setRooms([]);
        setActiveRoomId(null);
        setOnlineUsers([]);
        setGroups({});
        setSelectedUser(null);
        setSelectedGroup(null);
      };
      socket.onerror = () => {
        setConnected(false);
      };
      socket.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data) as ServerMsg;
          handleMessage(msg);
        } catch {
          // ignore malformed JSON frames
        }
      };
    } catch {
      // ignore invalid URL during typing
    }
    return () => {
      if (socket) {
        socket.onclose = null;
        socket.onerror = null;
        socket.onmessage = null;
        socket.close();
      }
      wsRef.current = null;
    };
  }, [handleMessage, serverUrl, reconnectTrigger]);

  const reconnectSocket = useCallback(() => {
    setReconnectTrigger((prev) => prev + 1);
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [rooms, activeRoomId, scrollToBottom]);

  // ============================================================================
  // UI Event Handlers
  // ============================================================================

  const handleRegister = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = regName.trim();
    if (!trimmed) return;
    setRegError("");
    register_name(trimmed);
  };

  const handleSend = () => {
    const text = inputText.trim();
    if (!text || !activeRoomId) return;
    const activeRoom = rooms.find((r) => r.id === activeRoomId);
    if (!activeRoom) return;

    if (activeRoom.type === "private") {
      send_private_message(activeRoom.target, text);
    } else {
      send_group_message(activeRoom.target, text);
    }
    setInputText("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const openPrivateChat = (peer: string) => {
    if (!peer || peer === username || peer === usernameRef.current) return;
    const roomId = `private:${peer}`;
    setRooms((prev) => {
      if (prev.find((r) => r.id === roomId)) {
        return prev.map((r) => (r.id === roomId ? { ...r, unread: 0 } : r));
      }
      return [
        ...prev,
        {
          id: roomId,
          target: peer,
          name: `Private Chat กับ ${peer}`,
          type: "private",
          unread: 0,
          messages: [],
        },
      ];
    });
    request_private_history(peer);
    selectRoom(roomId);
  };

  const handleOpenSelectedPrivateChat = () => {
    if (!selectedUser || selectedUser === username) return;
    openPrivateChat(selectedUser);
  };

  const handleCreateGroup = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const gname = newGroupName.trim();
    if (!gname) return;
    create_group(gname);
    setNewGroupName("");
    setSelectedGroup(gname);
  };

  const openOrJoinGroup = (gname: string) => {
    if (!gname) return;
    const members = groups[gname] || [];
    if (members.includes(username)) {
      const roomId = `group:${gname}`;
      setRooms((prev) => {
        if (prev.find((r) => r.id === roomId)) {
          return prev.map((r) => (r.id === roomId ? { ...r, unread: 0 } : r));
        }
        return [
          ...prev,
          {
            id: roomId,
            target: gname,
            name: `Group Chat: ${gname}`,
            type: "group",
            unread: 0,
            messages: [],
          },
        ];
      });
      selectRoom(roomId);
      request_group_history(gname);
    } else {
      join_group(gname);
    }
  };

  const handleOpenOrJoinSelectedGroup = () => {
    if (!selectedGroup) return;
    openOrJoinGroup(selectedGroup);
  };

  const handleRefreshHistory = () => {
    const activeRoom = rooms.find((r) => r.id === activeRoomId);
    if (!activeRoom) return;
    if (activeRoom.type === "private") {
      request_private_history(activeRoom.target);
    } else {
      request_group_history(activeRoom.target);
    }
  };

  const isMember = (gname: string) => {
    return (groups[gname] || []).includes(username);
  };

  const closeTab = (e: React.MouseEvent, roomId: string) => {
    e.stopPropagation();
    setRooms((prev) => {
      const next = prev.filter((r) => r.id !== roomId);
      if (activeRoomId === roomId) {
        const nextId = next.length > 0 ? next[next.length - 1].id : null;
        activeRoomIdRef.current = nextId;
        setActiveRoomId(nextId);
      }
      return next;
    });
  };

  const handleLogout = () => {
    if (wsRef.current) {
      wsRef.current.close();
    }
    setUsername("");
    usernameRef.current = "";
    setRegisterOpen(true);
    knownPrivateRooms.current.clear();
    setRooms([]);
    selectRoom(null);
    setSelectedUser(null);
    setSelectedGroup(null);
    reconnectSocket();
  };

  // ============================================================================
  // Render Registration Screen (R3)
  // ============================================================================

  if (registerOpen) {
    return (
      <div className="flex flex-col flex-1 min-h-screen items-center justify-center bg-gradient-to-br from-green-50 via-emerald-50 to-teal-50 p-4">
        <div className="w-full max-w-md bg-white rounded-3xl shadow-xl p-8 border border-green-100">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-10 h-10 rounded-2xl bg-green-500 flex items-center justify-center text-inverse font-bold text-xl shadow-sm">
              L
            </div>
            <div>
              <h1 className="text-2xl font-bold text-content">LINE-like Chat</h1>
              <p className="text-xs text-accent">Socket Programming Project</p>
            </div>
          </div>

          <p className="text-heading text-sm mt-4 mb-6 leading-relaxed">
            ตั้งชื่อของคุณเพื่อเข้าใช้งาน (หากใช้ชื่อเดิม ประวัติแชทและกลุ่มเดิมจะถูกดึงกลับมาอัตโนมัติ)
          </p>

          <form onSubmit={handleRegister} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-heading uppercase tracking-wider mb-1.5">
                ชื่อผู้ใช้ (Username)
              </label>
              <input
                type="text"
                placeholder="ตั้งชื่อของคุณ (ห้ามซ้ำกับคนที่ออนไลน์อยู่)..."
                value={regName}
                onChange={(e) => setRegName(e.target.value)}
                className="w-full px-4 py-3 rounded-xl border border-green-200 focus:outline-none focus:ring-2 focus:ring-green-500 text-content-strong placeholder-input-hint transition"
                autoFocus
              />
            </div>

            {regError && (
              <div className="px-4 py-2.5 rounded-xl bg-red-50 border border-red-200 text-error-strong text-sm flex items-center gap-2">
                <span>⚠️</span>
                <span>{regError}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={!regName.trim() || !connected}
              className="w-full py-3.5 rounded-xl bg-green-500 text-inverse font-semibold shadow-sm disabled:opacity-50 hover:bg-green-600 active:scale-[0.99] transition cursor-pointer disabled:cursor-not-allowed"
            >
              {connected ? "เข้าสู่ระบบแชท (Join Chat)" : "กำลังเชื่อมต่อ Server..."}
            </button>
          </form>

          <div className="mt-6 pt-4 border-t border-green-100 flex items-center justify-between text-xs">
            <div className="flex items-center gap-2">
              <span
                className={`w-2.5 h-2.5 rounded-full ${
                  connected ? "bg-green-500 animate-pulse" : "bg-red-400"
                }`}
              />
              <span className={connected ? "text-secondary font-medium" : "text-error font-medium"}>
                {connected ? "Connected to Server" : "Disconnected"}
              </span>
            </div>
            {!connected && (
              <button
                type="button"
                onClick={reconnectSocket}
                className="text-secondary hover:text-content underline font-medium cursor-pointer"
              >
                ลองเชื่อมต่อใหม่
              </button>
            )}
          </div>

          <details className="mt-3 text-xs text-secondary">
            <summary className="cursor-pointer hover:text-content select-none">
              ตั้งค่า WebSocket Server ({serverUrl})
            </summary>
            <div className="mt-2 flex gap-2">
              <input
                type="text"
                value={serverUrl}
                onChange={(e) => setServerUrl(e.target.value)}
                className="flex-1 px-3 py-1.5 rounded-lg border border-green-200 text-content focus:outline-none focus:ring-1 focus:ring-green-500"
                placeholder={process.env.NEXT_PUBLIC_CHAT_WS_URL || "WebSocket server URL"}
              />
              <button
                type="button"
                onClick={reconnectSocket}
                className="px-3 py-1.5 rounded-lg bg-green-100 text-heading font-medium hover:bg-green-200 transition cursor-pointer"
              >
                Connect
              </button>
            </div>
          </details>
        </div>
      </div>
    );
  }

  // ============================================================================
  // Render Main Chat Interface
  // ============================================================================

  const activeRoom = rooms.find((r) => r.id === activeRoomId);

  return (
    <div className="flex flex-col flex-1 h-screen bg-green-50 overflow-hidden">
      {/* Top Header */}
      <header className="h-16 bg-white border-b border-green-100 flex items-center justify-between px-6 shrink-0 shadow-2xs">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-green-500 flex items-center justify-center text-inverse font-bold shadow-2xs">
            L
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-content font-bold">LINE-like Chat</span>
              <span
                className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full font-medium ${
                  connected ? "bg-green-100 text-heading" : "bg-red-100 text-error-strong"
                }`}
              >
                <span
                  className={`w-1.5 h-1.5 rounded-full ${
                    connected ? "bg-green-500 animate-pulse" : "bg-red-500"
                  }`}
                />
                {connected ? "Online" : "Offline"}
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 bg-green-50 border border-green-200 px-3 py-1.5 rounded-xl">
            <span className="text-sm">👤</span>
            <span className="text-content text-sm font-semibold">{username}</span>
          </div>
          <button
            onClick={handleLogout}
            className="text-xs px-3 py-1.5 rounded-lg border border-green-200 text-heading hover:bg-red-50 hover:text-error-strong hover:border-red-200 transition cursor-pointer"
          >
            เปลี่ยนชื่อ / ออกจากระบบ
          </button>
        </div>
      </header>

      {/* Main Content Split */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left Sidebar: Online Clients (R4) & Chat Groups (R8, R9, R10) */}
        <aside className="w-80 bg-white border-r border-green-100 shrink-0 flex flex-col overflow-hidden">
          {/* [R4] Online Clients Section */}
          <div className="p-4 border-b border-green-100 flex flex-col max-h-[45%]">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xs font-bold text-heading uppercase tracking-wider">
                Online Clients ({onlineUsers.length})
              </h2>
              <span className="text-[11px] text-accent">คลิกหรือดับเบิลคลิกเพื่อแชท</span>
            </div>

            <div className="space-y-1 overflow-y-auto flex-1 pr-1">
              {onlineUsers.map((u) => {
                const isMe = u === username;
                const isSelected = !isMe && selectedUser === u;
                const room = rooms.find((r) => r.id === `private:${u}`);
                const unreadCount = room?.unread || 0;

                return (
                  <div
                    key={u}
                    onClick={() => {
                      if (isMe) return;
                      setSelectedUser(u);
                      openPrivateChat(u);
                    }}
                    onDoubleClick={() => {
                      if (isMe) return;
                      openPrivateChat(u);
                    }}
                    className={`group flex items-center justify-between px-3 py-2 rounded-xl text-sm transition border ${
                      isMe
                        ? "bg-green-50/60 border-green-100 text-heading cursor-default"
                        : isSelected
                        ? "bg-green-100/80 border-green-300 text-content-strong font-medium cursor-pointer"
                        : "border-transparent hover:bg-green-50 text-content cursor-pointer"
                    }`}
                  >
                    <div className="flex items-center gap-2 truncate">
                      <span className="w-2 h-2 rounded-full bg-green-500 shrink-0" />
                      <span className="truncate">
                        {u}
                        {isMe && (
                          <span className="ml-1 text-xs text-secondary font-semibold">(You)</span>
                        )}
                      </span>
                    </div>
                    {!isMe && (
                      <div className="flex items-center gap-1.5 shrink-0">
                        {unreadCount > 0 && (
                          <span className="bg-red-500 text-inverse text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                            {unreadCount}
                          </span>
                        )}
                        <span className="text-[11px] text-secondary opacity-0 group-hover:opacity-100 bg-white px-2 py-0.5 rounded-md border border-green-200 transition">
                          แชท
                        </span>
                      </div>
                    )}
                  </div>
                );
              })}
              {onlineUsers.length === 0 && (
                <p className="text-xs text-muted py-3 text-center">ไม่มีผู้ใช้ออนไลน์</p>
              )}
            </div>

            <button
              type="button"
              onClick={handleOpenSelectedPrivateChat}
              disabled={!selectedUser || selectedUser === username}
              className="w-full mt-3 py-2 px-3 truncate rounded-xl border border-green-300 text-heading text-sm font-medium hover:bg-green-50 transition disabled:opacity-40 cursor-pointer disabled:cursor-not-allowed"
            >
              เปิดแชทส่วนตัว {selectedUser && selectedUser !== username ? `กับ ${selectedUser}` : "(Private Chat)"}
            </button>
          </div>

          {/* [R8, R9, R10] Chat Groups Section */}
          <div className="p-4 flex-1 flex flex-col overflow-hidden">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xs font-bold text-heading uppercase tracking-wider">
                Chat Groups ({Object.keys(groups).length})
              </h2>
              <span className="text-[11px] text-accent">เลือกเพื่อเปิดอ่าน/เข้ากลุ่ม</span>
            </div>

            <div className="space-y-2 mb-3 overflow-y-auto flex-1 pr-1">
              {Object.entries(groups).map(([gname, members]) => {
                const member = isMember(gname);
                const isSelected = selectedGroup === gname;
                const room = rooms.find((r) => r.id === `group:${gname}`);
                const unreadCount = room?.unread || 0;

                return (
                  <div
                    key={gname}
                    onClick={() => {
                      setSelectedGroup(gname);
                      if (member) {
                        openOrJoinGroup(gname);
                      }
                    }}
                    onDoubleClick={() => openOrJoinGroup(gname)}
                    className={`cursor-pointer p-3 rounded-xl border text-sm transition ${
                      isSelected
                        ? "bg-green-100/70 border-green-400 text-content-strong shadow-2xs"
                        : member
                        ? "bg-green-50/70 border-green-200 text-content hover:bg-green-50"
                        : "border-green-100 text-heading hover:bg-green-50/50"
                    }`}
                  >
                    <div className="flex justify-between items-center gap-2">
                      <span className="font-semibold truncate">
                        {member ? "✓ " : ""}
                        {gname}
                      </span>
                      <div className="flex items-center gap-1.5 shrink-0">
                        {unreadCount > 0 && (
                          <span className="bg-red-500 text-inverse text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                            {unreadCount}
                          </span>
                        )}
                        <span className="text-[10px] bg-green-100 text-heading px-2 py-0.5 rounded-full font-medium">
                          {members.length} คน
                        </span>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setSelectedGroup(gname);
                            openOrJoinGroup(gname);
                          }}
                          className={`text-[11px] px-2 py-0.5 rounded-md font-medium transition cursor-pointer ${
                            member
                              ? "bg-white border border-green-200 text-heading hover:bg-green-100"
                              : "bg-green-500 text-inverse hover:bg-green-600"
                          }`}
                        >
                          {member ? "เปิดแชท" : "เข้าร่วม"}
                        </button>
                      </div>
                    </div>
                    <div className="mt-1 text-[11px] text-secondary truncate">
                      สมาชิก: [{members.join(", ")}]
                    </div>
                  </div>
                );
              })}
              {Object.keys(groups).length === 0 && (
                <p className="text-xs text-muted py-4 text-center">
                  ยังไม่มีกลุ่มแชท สร้างกลุ่มใหม่ด้านล่างได้เลย!
                </p>
              )}
            </div>

            {/* Create & Join Group Controls */}
            <div className="space-y-2 pt-2 border-t border-green-100 shrink-0">
              <form onSubmit={handleCreateGroup} className="flex w-full gap-1.5">
                <input
                  type="text"
                  placeholder="ตั้งชื่อกลุ่มแชทใหม่..."
                  value={newGroupName}
                  onChange={(e) => setNewGroupName(e.target.value)}
                  className="min-w-0 flex-1 px-3 py-2 rounded-xl border border-green-200 focus:outline-none focus:ring-2 focus:ring-green-500 text-sm text-content-strong placeholder-input-hint"
                />
                <button
                  type="submit"
                  className="px-3 py-2 rounded-xl bg-green-500 text-inverse text-xs font-semibold hover:bg-green-600 transition disabled:opacity-50 shrink-0 whitespace-nowrap cursor-pointer disabled:cursor-not-allowed"
                  disabled={!newGroupName.trim()}
                >
                  สร้างกลุ่มใหม่
                </button>
              </form>

              <button
                type="button"
                onClick={handleOpenOrJoinSelectedGroup}
                disabled={!selectedGroup}
                className="w-full py-2 px-3 truncate rounded-xl border border-green-300 text-heading text-sm font-medium hover:bg-green-50 transition disabled:opacity-40 cursor-pointer disabled:cursor-not-allowed"
              >
                {selectedGroup
                  ? isMember(selectedGroup)
                    ? `เปิดอ่านกลุ่ม "${selectedGroup}"`
                    : `เข้าร่วมกลุ่ม "${selectedGroup}" (Join)`
                  : "เปิดอ่าน / เข้าร่วมกลุ่ม"}
              </button>
            </div>
          </div>
        </aside>

        {/* Right Panel: Chat Rooms & Message Window (R5, R6, R7, R11) */}
        <main className="flex-1 bg-white relative flex flex-col overflow-hidden">
          {/* Room Tabs Bar (R5) */}
          {rooms.length > 0 && (
            <div className="border-b border-green-100 bg-green-50/40 shrink-0">
              <div className="flex overflow-x-auto pt-2 px-3 gap-1.5">
                {rooms.map((room) => {
                  const isActive = activeRoomId === room.id;
                  return (
                    <div
                      key={room.id}
                      onClick={() => selectRoom(room.id)}
                      onMouseDown={(e) => e.preventDefault()}
                      className={`group flex items-center gap-2 px-4 py-2 rounded-t-xl border-b-2 transition cursor-pointer select-none ${
                        isActive
                          ? "border-green-500 bg-white text-content font-semibold shadow-2xs"
                          : "border-transparent bg-green-100/50 text-secondary hover:bg-white/80"
                      }`}
                    >
                      <span className="text-sm">
                        {room.type === "private" ? "👤" : "👥"}
                      </span>
                      <span className="text-sm truncate max-w-[150px]">
                        {room.type === "private" ? `ส่วนตัว: ${room.target}` : `กลุ่ม: ${room.target}`}
                      </span>
                      {room.unread > 0 && (
                        <span className="bg-red-500 text-inverse text-[10px] font-bold px-1.5 py-0.5 rounded-full">
                          {room.unread}
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={(e) => closeTab(e, room.id)}
                        className="ml-1 opacity-60 group-hover:opacity-100 hover:bg-red-100 hover:text-error-strong text-heading rounded-full w-5 h-5 flex items-center justify-center text-xs transition cursor-pointer"
                        title="ปิดแท็บแชทนี้"
                      >
                        ✕
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Active Chat Room Content */}
          {activeRoom ? (
            <>
              {/* Active Room Subheader */}
              <div className="px-6 py-3 border-b border-green-100 bg-white flex items-center justify-between shrink-0">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-bold text-content text-base">{activeRoom.name}</h3>
                    <span
                      className={`text-xs px-2.5 py-0.5 rounded-full font-medium ${
                        activeRoom.type === "private"
                          ? "bg-green-100 text-heading"
                          : "bg-emerald-100 text-group-label"
                      }`}
                    >
                      {activeRoom.type === "private" ? "Private Chat" : "Group Chat"}
                    </span>
                  </div>
                  {activeRoom.type === "group" ? (
                    <p className="text-xs text-accent mt-0.5">
                      สมาชิก ({(groups[activeRoom.target] || []).length}):{" "}
                      {(groups[activeRoom.target] || []).join(", ")}
                    </p>
                  ) : (
                    <p className="text-xs text-accent mt-0.5">
                      สถานะ:{" "}
                      {onlineUsers.includes(activeRoom.target) ? (
                        <span className="text-secondary font-medium">● ออนไลน์</span>
                      ) : (
                        <span className="text-offline">○ ออฟไลน์ (ส่งข้อความทิ้งไว้ได้)</span>
                      )}
                    </p>
                  )}
                </div>

                <button
                  type="button"
                  onClick={handleRefreshHistory}
                  className="text-xs px-3 py-1.5 rounded-lg border border-green-200 text-heading hover:bg-green-50 transition cursor-pointer flex items-center gap-1"
                  title="ดึงประวัติการสนทนาจากฐานข้อมูล"
                >
                  <span>🔄</span>
                  <span>ดึงประวัติแชท</span>
                </button>
              </div>

              {/* Scrollable Messages Area (R6) */}
              <div
                ref={scrollRef}
                className="flex-1 overflow-y-auto p-6 space-y-3 bg-gradient-to-b from-green-50/30 to-green-50/60"
              >
                {activeRoom.messages.map((m, i) => {
                  const isMine = m.sender === username;
                  return (
                    <div
                      key={i}
                      className={`flex flex-col ${isMine ? "items-end" : "items-start"}`}
                    >
                      <div className="flex items-baseline gap-1.5 mb-1 px-1">
                        <span className="text-xs font-semibold text-content">
                          {isMine ? `${m.sender} (You)` : m.sender}
                        </span>
                        {m.timestamp && (
                          <span className="text-[10px] text-accent">{m.timestamp}</span>
                        )}
                      </div>
                      <div
                        className={`max-w-[70%] px-4 py-2.5 rounded-2xl text-sm break-words shadow-2xs ${
                          isMine
                            ? "bg-green-500 text-inverse rounded-tr-xs"
                            : "bg-white border border-green-100 text-content-strong rounded-tl-xs"
                        }`}
                      >
                        {m.message}
                      </div>
                    </div>
                  );
                })}

                {activeRoom.messages.length === 0 && (
                  <div className="text-center py-16 text-muted text-sm">
                    ยังไม่มีข้อความในห้องสนทนานี้ เริ่มพิมพ์ข้อความทักทายได้เลย!
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-muted p-6 bg-green-50/20">
              <div className="w-16 h-16 rounded-3xl bg-green-100 flex items-center justify-center text-3xl mb-3">
                💬
              </div>
              <p className="text-base font-medium text-heading">ยังไม่ได้เลือกห้องสนทนา</p>
              <p className="text-xs text-accent mt-1">
                คลิกเลือกเพื่อนในรายการ Online Clients หรือเลือกกลุ่มใน Chat Groups ทางซ้ายมือเพื่อเริ่มแชท
              </p>
            </div>
          )}

          {/* Bottom Message Input Bar (R6) */}
          <div className="bg-white border-t border-green-100 p-4 shrink-0">
            <div className="flex gap-2 max-w-3xl mx-auto">
              <input
                type="text"
                placeholder={
                  activeRoom
                    ? `พิมพ์ข้อความส่งไปที่ ${activeRoom.name}...`
                    : "เลือกห้องแชทก่อนพิมพ์ข้อความ..."
                }
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={!activeRoomId || !connected}
                className="flex-1 px-4 py-3 rounded-xl border border-green-200 focus:outline-none focus:ring-2 focus:ring-green-500 text-content-strong placeholder-input-hint disabled:opacity-50 disabled:bg-green-50/40"
              />
              <button
                type="button"
                onClick={handleSend}
                disabled={!inputText.trim() || !activeRoomId || !connected}
                className="px-6 py-3 rounded-xl bg-green-500 text-inverse font-semibold disabled:opacity-50 hover:bg-green-600 transition cursor-pointer disabled:cursor-not-allowed"
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
