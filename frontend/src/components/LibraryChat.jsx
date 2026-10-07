import { useState } from "react";
import { useNavigate } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { askLibrary } from "../api/library";

function formatTime(s) {
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

export default function LibraryChat() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSend(e) {
    e.preventDefault();
    const message = input.trim();
    if (!message || loading) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", text: message }]);
    setLoading(true);
    try {
      const data = await askLibrary(message);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: data.answer, sources: data.sources || [], calls: data.mcp_calls || [] },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: err.response?.data?.detail || "Sorry, I couldn't search the library right now.", error: true },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="card card-pad" style={{ marginBottom: 24 }}>
      <div style={{ marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 15 }}>Ask the library</h3>
        <p style={{ margin: "4px 0 0", fontSize: 13, color: "var(--color-text-secondary)" }}>
          Describe a topic and the assistant searches every video through the Chroma MCP server.
        </p>
      </div>

      {messages.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12, maxHeight: 420, overflowY: "auto", marginBottom: 12 }}>
          {messages.map((m, i) => (
            <div key={i}>
              <div className={`chat-bubble ${m.role}${m.error ? " error" : ""}`}>
                {m.role === "assistant" ? <ReactMarkdown>{m.text || " "}</ReactMarkdown> : m.text}
              </div>

              {m.sources && m.sources.length > 0 && (
                <div className="search-results-list" style={{ marginTop: 8 }}>
                  {m.sources.map((s) => (
                    <div
                      key={s.video_id}
                      className="search-result-card"
                      onClick={() => navigate(`/watch/${s.video_id}?t=${s.start_time}`)}
                    >
                      <div className="search-result-time">{formatTime(s.start_time)}</div>
                      <div className="search-result-text">
                        <strong>{s.title}</strong> · {s.category}
                        <br />
                        "{s.text}"
                      </div>
                      <div className="search-result-jump">Open →</div>
                    </div>
                  ))}
                </div>
              )}

              {m.calls && m.calls.length > 0 && (
                <p style={{ margin: "6px 0 0", fontSize: 11.5, color: "var(--color-text-muted)" }}>
                  Searched with {m.calls.map((c) => c.tool).join(", ")}
                </p>
              )}
            </div>
          ))}
          {loading && <div className="chat-bubble assistant">Searching...</div>}
        </div>
      )}

      <form onSubmit={handleSend} className="search-bar">
        <input
          className="input"
          placeholder="e.g. Which video explains why AI apps need glue code?"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={loading}
        />
        <button className="btn btn-primary" type="submit" disabled={loading}>Ask</button>
      </form>
    </div>
  );
}