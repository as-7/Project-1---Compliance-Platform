import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { API_BASE } from "../api/client";

type ToolEvent = { tool: string; detail?: any };

type Turn =
  | { kind: "user"; text: string }
  | { kind: "assistant"; text: string; citations?: string[]; toolEvents?: ToolEvent[] };

function parseSseBlock(block: string): { event: string; data: string } {
  let event = "message";
  const dataParts: string[] = [];
  for (const raw of block.split("\n")) {
    if (raw.length === 0 || raw.startsWith(":")) continue;
    const colon = raw.indexOf(":");
    const field = colon === -1 ? raw : raw.slice(0, colon);
    let value = colon === -1 ? "" : raw.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") dataParts.push(value);
  }
  return { event, data: dataParts.join("\n") };
}

export default function Chat() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const docId = searchParams.get("docId");
  const docName = searchParams.get("docName");

  function clearDocContext() {
    const next = new URLSearchParams(searchParams);
    next.delete("docId");
    next.delete("docName");
    setSearchParams(next, { replace: true });
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, streaming]);

  async function send() {
    const question = input.trim();
    if (!question || streaming) return;
    setInput("");
    setTurns((t) => [...t, { kind: "user", text: question }, { kind: "assistant", text: "", toolEvents: [] }]);
    setStreaming(true);

    const scopedQuestion = docId
      ? `Restrict retrieval to the document with id "${docId}"` +
        (docName ? ` (name: "${docName}")` : "") +
        `. When calling search_documents, always pass document_id="${docId}".\n\nQuestion: ${question}`
      : question;

    let buffer = "";
    let toolEvents: ToolEvent[] = [];
    try {
      const res = await fetch(`${API_BASE}/api/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ session_id: sessionId, question: scopedQuestion }),
      });
      if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let pending = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        pending += dec.decode(value, { stream: true });
        // SSE event boundary is a blank line. Accept both \n\n and \r\n\r\n.
        let idx;
        while (
          (idx = (() => {
            const a = pending.indexOf("\n\n");
            const b = pending.indexOf("\r\n\r\n");
            if (a === -1) return b;
            if (b === -1) return a;
            return Math.min(a, b);
          })()) !== -1
        ) {
          const sepLen = pending.startsWith("\r\n\r\n", idx) ? 4 : 2;
          const block = pending.slice(0, idx);
          pending = pending.slice(idx + sepLen);
          if (!block) continue;
          const { event: evt, data } = parseSseBlock(block);
          console.log("[chat-sse]", evt, data.slice(0, 200));

          if (evt === "session" && data) {
            try {
              setSessionId(JSON.parse(data).session_id);
            } catch (err) {
              console.warn("chat: bad session payload", err, data);
            }
          } else if (evt === "token") {
            buffer += data;
            setTurns((t) => {
              const next = t.slice();
              const last = next[next.length - 1];
              console.log("[chat-state] token; turns.len=", t.length, "last.kind=", last?.kind, "buffer.len=", buffer.length);
              if (last && last.kind === "assistant") {
                next[next.length - 1] = { ...last, text: buffer, toolEvents };
              }
              return next;
            });
          } else if (evt === "tool_use") {
            try {
              const parsed = JSON.parse(data);
              toolEvents = [...toolEvents, { tool: parsed.tool, detail: parsed.input }];
            } catch (err) {
              console.warn("chat: bad tool_use payload", err, data);
            }
            setTurns((t) => {
              const next = t.slice();
              const last = next[next.length - 1];
              if (last.kind === "assistant") {
                next[next.length - 1] = { ...last, toolEvents };
              }
              return next;
            });
          } else if (evt === "tool_result") {
            // No UI surface yet; keep for future debug.
          } else if (evt === "final") {
            try {
              const parsed = JSON.parse(data);
              const citations: string[] = (parsed.citations ?? []).map(
                (c: any) => c.chunk_id,
              );
              const finalText =
                (buffer && buffer.length >= (parsed.answer?.length ?? 0)
                  ? buffer
                  : parsed.answer) || buffer || parsed.answer || "";
              setTurns((t) => {
                const next = t.slice();
                const last = next[next.length - 1];
                if (last.kind === "assistant") {
                  next[next.length - 1] = {
                    ...last,
                    text: finalText,
                    citations,
                    toolEvents,
                  };
                }
                return next;
              });
            } catch (err) {
              console.warn("chat: bad final payload", err, data);
            }
          } else if (evt === "error") {
            setTurns((t) => {
              const next = t.slice();
              const last = next[next.length - 1];
              if (last.kind === "assistant") {
                next[next.length - 1] = {
                  ...last,
                  text: `(error) ${data}`,
                };
              }
              return next;
            });
          }
        }
      }
    } catch (e: any) {
      setTurns((t) => {
        const next = t.slice();
        const last = next[next.length - 1];
        if (last.kind === "assistant") {
          next[next.length - 1] = { ...last, text: `(error) ${e.message}` };
        }
        return next;
      });
    } finally {
      setStreaming(false);
    }
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-4 h-[calc(100vh-12rem)]">
      <div className="bg-white rounded-lg border border-slate-200 shadow-sm flex flex-col">
        <div className="px-4 py-2 border-b border-slate-100 text-sm text-slate-700 font-medium flex items-center justify-between">
          <span>Q&A — RAG over regulatory corpus + Control Registry</span>
          {docId && (
            <span className="inline-flex items-center gap-2 text-xs bg-emerald-50 text-emerald-800 border border-emerald-200 rounded px-2 py-0.5">
              <span className="font-medium">Document:</span>
              <span className="truncate max-w-[16rem]" title={docName || docId}>
                {docName || docId}
              </span>
              <button
                onClick={clearDocContext}
                className="text-emerald-700 hover:text-emerald-900"
                title="Clear document scope"
              >
                ✕
              </button>
            </span>
          )}
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {turns.map((t, i) => (
            <Bubble key={i} turn={t} />
          ))}
          <div ref={bottomRef} />
        </div>
        <div className="border-t border-slate-100 p-3 flex gap-2">
          <input
            className="flex-1 border border-slate-300 rounded px-3 py-2 text-sm"
            placeholder='Ask a question — e.g. "Are we compliant with access logging?"'
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            disabled={streaming}
          />
          <button
            className="bg-slate-900 text-white text-sm rounded px-4 py-2 disabled:opacity-50"
            onClick={() => void send()}
            disabled={streaming || !input.trim()}
          >
            {streaming ? "Streaming…" : "Send"}
          </button>
        </div>
      </div>

      <aside className="bg-white rounded-lg border border-slate-200 shadow-sm p-4 text-xs text-slate-600">
        <div className="font-medium text-slate-800 mb-2">Try asking</div>
        <ul className="space-y-1.5 list-disc pl-4">
          <li>What does the document say about data retention?</li>
          <li>Summarize HIPAA's requirements for audit logging.</li>
          <li>Are we compliant with multi-factor authentication?</li>
          <li>Which extracted controls are missing org coverage?</li>
        </ul>
        <div className="font-medium text-slate-800 mt-4 mb-2">How it answers</div>
        <p>
          The Q&A agent calls the Document Store MCP for RAG and the Control Registry MCP for
          coverage questions. Citations like <code>[chunk_id: …]</code> come from the corpus;
          <code>[control: …]</code> from your org control registry.
        </p>
      </aside>
    </div>
  );
}

function Bubble({ turn }: { turn: Turn }) {
  if (turn.kind === "user") {
    return (
      <div className="flex justify-end">
        <div className="bg-slate-900 text-white rounded-lg px-3 py-2 max-w-[80%] text-sm">
          {turn.text}
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col items-start max-w-[85%] space-y-1">
      {turn.toolEvents && turn.toolEvents.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {turn.toolEvents.map((te, i) => (
            <span
              key={i}
              className="text-[10px] uppercase tracking-wide bg-slate-100 text-slate-600 rounded px-1.5 py-0.5"
            >
              {te.tool}
            </span>
          ))}
        </div>
      )}
      <div className="bg-slate-100 text-slate-900 rounded-lg px-3 py-2 text-sm whitespace-pre-wrap">
        {turn.text || <span className="text-slate-400">…</span>}
      </div>
      {turn.citations && turn.citations.length > 0 && (
        <div className="text-[11px] text-slate-500">
          citations: {turn.citations.join(", ")}
        </div>
      )}
    </div>
  );
}
