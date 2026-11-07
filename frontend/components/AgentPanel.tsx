"use client";

import { useState } from "react";

export type AgentMode = "off" | "auto" | "manual";

export type AgentRoomState = {
  mode: AgentMode;
  status: "idle" | "thinking";
};

export type AgentProposal = {
  id: string;
  kind: "draft" | "choices";
  text?: string;
  summary?: string;
  options?: string[];
  canGoBack?: boolean;
};

export type AgentDecision = "approve" | "reject" | "revise" | "choose" | "back";

type DecideHandler = (proposalId: string, decision: AgentDecision, details?: { text?: string; option?: number }) => void;

const MODES: Array<{ value: AgentMode; label: string; hint: string }> = [
  { value: "off", label: "Off", hint: "ปิด Agent ในห้องนี้" },
  { value: "auto", label: "Auto", hint: "Agent ตัดสินใจและตอบในชื่อคุณได้เองทันที" },
  { value: "manual", label: "Manual", hint: "Agent เสนอแนวทางให้เลือก แล้วเขียนประโยคให้ตรวจก่อนส่ง" },
];

const SECONDARY_BUTTON =
  "px-3 py-1.5 rounded-lg border border-brand-200 text-heading text-xs font-medium hover:bg-brand-50 transition cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed";
const PRIMARY_BUTTON =
  "px-3 py-1.5 rounded-lg bg-brand-500 text-inverse text-xs font-semibold hover:bg-brand-600 transition cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed";
const TEXT_FIELD =
  "w-full px-3 py-2 rounded-lg border border-brand-200 text-sm text-content-strong placeholder-input-hint focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:opacity-50";

function ProposalCard({
  proposal,
  disabled,
  onDecide,
}: {
  proposal: AgentProposal;
  disabled: boolean;
  onDecide: DecideHandler;
}) {
  const options = proposal.options ?? [];
  const isDraft = proposal.kind === "draft";
  const [messageText, setMessageText] = useState(proposal.text ?? "");
  const [feedback, setFeedback] = useState("");

  const send = () => {
    if (!disabled && messageText.trim()) onDecide(proposal.id, "approve", { text: messageText });
  };
  const revise = () => {
    if (!disabled && feedback.trim()) onDecide(proposal.id, "revise", { text: feedback });
  };

  return (
    // ส่วนเนื้อหาเลื่อนได้ ส่วนปุ่มอยู่นอกพื้นที่เลื่อน ปุ่มจึงไม่ถูกซ่อนเมื่อข้อความยาว
    <div className="mt-2 flex max-h-[38vh] flex-col overflow-hidden rounded-xl border border-brand-300 bg-brand-50/60">
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-3">
        <p className="text-xs font-semibold text-heading mb-1.5">
          {isDraft ? "ประโยคที่ Agent เขียนให้" : "ข้อเสนอจาก Agent"} (เห็นเฉพาะคุณ)
        </p>
        {proposal.summary && (
          <p className="text-sm text-content-strong whitespace-pre-wrap [overflow-wrap:anywhere]">{proposal.summary}</p>
        )}
        {options.length > 0 && (
          <div className="mt-2 space-y-1.5">
            <p className="text-xs font-medium text-heading">กดเลือกแนวทาง แล้ว Agent จะเขียนประโยคให้</p>
            {options.map((option, index) => (
              <button
                key={index}
                type="button"
                disabled={disabled}
                onClick={() => onDecide(proposal.id, "choose", { option: index })}
                className="block w-full cursor-pointer rounded-lg border border-brand-200 bg-surface px-3 py-2 text-left text-sm text-content-strong transition hover:border-brand-400 hover:bg-brand-50 disabled:cursor-wait disabled:opacity-50 [overflow-wrap:anywhere]"
              >
                {option}
              </button>
            ))}
          </div>
        )}
        {isDraft && (
          <textarea
            aria-label="ข้อความที่จะส่ง แก้ไขได้"
            rows={2}
            value={messageText}
            onChange={(e) => setMessageText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            className={`${TEXT_FIELD} resize-y`}
          />
        )}
      </div>

      <div className="shrink-0 border-t border-brand-200 bg-surface p-2">
        <div className="flex flex-wrap items-center justify-end gap-2">
          {!isDraft && (
            <>
              <input
                type="text"
                aria-label="สิ่งที่ต้องการให้ Agent แก้"
                placeholder="ถามต่อ หรือบอกแนวทางที่อยากได้..."
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    revise();
                  }
                }}
                className={`${TEXT_FIELD} !w-auto min-w-40 flex-1 !py-1.5`}
              />
              <button
                type="button"
                className={`${SECONDARY_BUTTON} shrink-0`}
                disabled={disabled || !feedback.trim()}
                onClick={revise}
              >
                ส่งให้ Agent
              </button>
            </>
          )}
          {proposal.canGoBack && (
            <button type="button" className={SECONDARY_BUTTON} disabled={disabled} onClick={() => onDecide(proposal.id, "back")}>
              เลือกแนวทางอื่น
            </button>
          )}
          <button type="button" className={SECONDARY_BUTTON} disabled={disabled} onClick={() => onDecide(proposal.id, "reject")}>
            {isDraft ? "ทิ้ง" : "ปิด"}
          </button>
          {isDraft && (
            <button type="button" className={PRIMARY_BUTTON} disabled={disabled || !messageText.trim()} onClick={send}>
              ส่งเข้าห้อง
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default function AgentPanel({
  state,
  proposal,
  error,
  connected,
  onSetMode,
  onInvoke,
  onCancel,
  onDecide,
  onDismissError,
}: {
  state: AgentRoomState;
  proposal?: AgentProposal;
  error?: string;
  connected: boolean;
  onSetMode: (mode: AgentMode) => void;
  onInvoke: (instruction: string) => void;
  onCancel: () => void;
  onDecide: DecideHandler;
  onDismissError: () => void;
}) {
  const [instruction, setInstruction] = useState("");
  const thinking = state.status === "thinking";
  const activeMode = MODES.find((mode) => mode.value === state.mode) ?? MODES[0];

  const invoke = () => {
    const text = instruction.trim();
    if (!text || thinking || !connected) return;
    onInvoke(text);
    setInstruction("");
  };

  return (
    <div className="bg-surface border-t border-brand-100 px-4 py-2.5 shrink-0">
      <div className="max-w-3xl mx-auto">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <span className="text-xs font-bold text-heading">AI Agent</span>
          <div role="group" aria-label="โหมดของ AI Agent" className="flex rounded-lg border border-brand-200 overflow-hidden">
            {MODES.map((mode) => (
              <button
                key={mode.value}
                type="button"
                title={mode.hint}
                aria-pressed={state.mode === mode.value}
                disabled={!connected}
                onClick={() => onSetMode(mode.value)}
                className={`px-2.5 py-1 text-xs font-medium transition cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${
                  state.mode === mode.value ? "bg-brand-500 text-inverse" : "text-heading hover:bg-brand-50"
                }`}
              >
                {mode.label}
              </button>
            ))}
          </div>
          <span className="text-[11px] text-accent min-w-0" aria-live="polite">
            {thinking ? "Agent กำลังทำงาน..." : activeMode.hint}
          </span>
          {thinking && (
            <button type="button" className={`${SECONDARY_BUTTON} ml-auto`} onClick={onCancel}>
              หยุด
            </button>
          )}
        </div>

        {/* ระหว่างรอตัดสินใจจะซ่อนช่องนี้ไว้ เพื่อให้ยังเห็นแชทและช่องพิมพ์หลัก */}
        {state.mode !== "off" && !proposal && (
          <div className="flex gap-2 mt-2">
            <input
              type="text"
              aria-label="สั่งงาน Agent"
              placeholder="สั่งงาน Agent เช่น ช่วยคิดว่าควรตอบอะไรดี (คนอื่นไม่เห็นคำสั่งนี้)"
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  invoke();
                }
              }}
              disabled={!connected}
              className={`${TEXT_FIELD} min-w-0 flex-1`}
            />
            <button
              type="button"
              className={`${PRIMARY_BUTTON} shrink-0`}
              disabled={!instruction.trim() || thinking || !connected}
              onClick={invoke}
            >
              สั่งงาน
            </button>
          </div>
        )}

        {error && (
          <div role="alert" className="flex items-start justify-between gap-2 mt-2 px-3 py-2 rounded-lg bg-danger-50 border border-danger-200 text-xs text-error-strong">
            <span className="[overflow-wrap:anywhere]">{error}</span>
            <button type="button" aria-label="ปิดข้อความแจ้งเตือน" className="shrink-0 cursor-pointer" onClick={onDismissError}>
              ✕
            </button>
          </div>
        )}

        {proposal && <ProposalCard key={proposal.id} proposal={proposal} disabled={!connected || thinking} onDecide={onDecide} />}
      </div>
    </div>
  );
}
