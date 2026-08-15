import { useRef, useState } from "react";
import * as api from "../services/api.js";
import { REGIONAL_SCOPE, HOUSEHOLD_SCOPE } from "../utils/format.js";

const SUGGESTIONS = [
  "What is my electricity bill?",
  "Will Diwali affect my electricity usage?",
  "What will my consumption look like next month?",
  "Is my consumption too high compared to normal?",
  "How does weather affect my electricity usage?",
  "What is my current consumption right now?",
  "What if I use 250 kWh instead of 350?",
];

function ChatBubble({ role, children }) {
  const isUser = role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? "bg-brand-600 text-white"
            : "border border-panel-edge bg-surface/50 text-slate-200"
        }`}
      >
        {children}
      </div>
    </div>
  );
}

function DataPointCard({ point }) {
  const value = point.value ?? "—";
  const display = point.unit ? `${value} ${point.unit}` : value;
  return (
    <div className="rounded-lg bg-panel px-3 py-2 text-xs">
      <p className="text-[10px] uppercase tracking-wide text-slate-500">{point.label}</p>
      <p className="mt-0.5 font-semibold text-white tabular-nums">{display}</p>
    </div>
  );
}

function ToolChip({ name }) {
  const label = name
    .replace(/^get_/, "")
    .replace(/^calculate_/, "calculate ")
    .replace(/_/g, " ");
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-sky-500/30 bg-sky-500/10 px-2.5 py-0.5 text-[10px] font-medium text-sky-300">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3">
        <path d="M13 2L3 14h7l-1 8 10-12h-7l1-8z" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {label}
    </span>
  );
}

function ScopeBadge({ scope }) {
  const isHousehold = scope === "household";
  const meta = isHousehold ? HOUSEHOLD_SCOPE : REGIONAL_SCOPE;
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
        isHousehold
          ? "border-teal-500/30 bg-teal-500/10 text-teal-300"
          : "border-brand-500/30 bg-brand-500/10 text-brand-300"
      }`}
    >
      {meta.label}
    </span>
  );
}

function AssistantAnswer({ message }) {
  return (
    <div className="space-y-3">
      <p className="whitespace-pre-wrap">{message.answer}</p>
      {message.data_points?.length > 0 && (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {message.data_points.map((p, i) => (
            <DataPointCard key={`${p.label}-${i}`} point={p} />
          ))}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 pt-1">
        {message.tools_used?.length > 0 && (
          <span className="text-[10px] uppercase tracking-wide text-slate-500">Tools used</span>
        )}
        {message.tools_used?.map((t) => (
          <ToolChip key={t} name={t} />
        ))}
        <ScopeBadge scope={message.scope} />
        {message.mode === "mock" && (
          <span className="text-[10px] text-slate-500" title="LLM_PROVIDER=mock demo mode">
            mock LLM
          </span>
        )}
      </div>
    </div>
  );
}

export default function Agent() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const conversationId = useRef(null);
  const bottomRef = useRef(null);

  const send = async (text) => {
    const question = (text ?? input).trim();
    if (!question || loading) return;
    setInput("");
    setError(null);
    setLoading(true);
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    try {
      const data = await api.chatWithAgent(question, conversationId.current);
      conversationId.current = data.conversation_id;
      setMessages((prev) => [...prev, { role: "assistant", ...data }]);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      bottomRef.current?.scrollIntoView?.({ behavior: "smooth" });
    }
  };

  const clear = () => {
    conversationId.current = null;
    setMessages([]);
    setError(null);
    setInput("");
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-white">AI Energy Assistant</h1>
          <p className="text-sm text-slate-400">
            Ask about your household usage, forecasts, bills and savings — answers are always grounded in
            your uploaded data and the deterministic backend engines.
          </p>
        </div>
        {messages.length > 0 && (
          <button
            type="button"
            onClick={clear}
            className="rounded-lg border border-panel-edge bg-panel px-3 py-1.5 text-xs font-medium text-slate-300 hover:bg-panel-edge/60 hover:text-white"
          >
            Clear conversation
          </button>
        )}
      </div>

      <div className="rounded-xl border border-panel-edge bg-surface/20">
        <div className="flex h-[28rem] flex-col">
          <div className="flex-1 space-y-4 overflow-y-auto p-4">
            {messages.length === 0 && !loading && (
              <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
                <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-brand-600/20 text-2xl">
                  ⚡
                </div>
                <div>
                  <p className="text-sm text-slate-300">Ask the AI Energy Assistant a question.</p>
                  <p className="mt-1 text-xs text-slate-500">
                    It only uses your uploaded consumption data and the deterministic backend engines —
                    never invented numbers.
                  </p>
                </div>
                <div className="grid w-full max-w-lg grid-cols-1 gap-2 sm:grid-cols-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => send(s)}
                      className="rounded-lg border border-panel-edge bg-panel px-3 py-2 text-left text-xs text-slate-300 hover:border-brand-500/40 hover:text-white"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m, i) =>
              m.role === "user" ? (
                <ChatBubble key={i} role="user">
                  {m.content}
                </ChatBubble>
              ) : (
                <ChatBubble key={i} role="assistant">
                  <AssistantAnswer message={m} />
                </ChatBubble>
              )
            )}

            {loading && (
              <ChatBubble role="assistant">
                <span className="flex items-center gap-2 text-slate-400">
                  <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-400 border-t-transparent" />
                  Analysing with backend tools…
                </span>
              </ChatBubble>
            )}

            {error && (
              <div className="rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-xs text-rose-200">
                <b>Could not get an answer:</b> {error}
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
            className="flex items-center gap-2 border-t border-panel-edge p-3"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="e.g. What is my electricity bill?"
              disabled={loading}
              aria-label="Ask the AI Energy Assistant"
              className="flex-1 rounded-lg border border-panel-edge bg-surface/50 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-500 focus:border-brand-500/50 disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-semibold text-white hover:bg-brand-500 disabled:opacity-50"
            >
              {loading ? "…" : "Send"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}