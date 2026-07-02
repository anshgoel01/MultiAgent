import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

const getMessageId = () => {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

const formatStatusContent = (status, report) => {
  if (status === "DONE") {
    return report || "No report generated.";
  }

  if (status === "FAILED") {
    return report || "Research failed.";
  }

  if (!status || status === "RUNNING") {
    return "Researching...";
  }

  return `${status}...`;
};

export default function App() {
  const [query, setQuery] = useState("");
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [eventSource, setEventSource] = useState(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    return () => {
      if (eventSource) {
        eventSource.close();
      }
    };
  }, [eventSource]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const appendMessage = (message) => {
    setMessages((prev) => [...prev, message]);
  };

  async function submitQuery() {
    if (!query.trim() || loading) {
      return;
    }

    setError("");

    const userMessage = {
      id: getMessageId(),
      role: "user",
      content: query.trim(),
    };

    const assistantId = getMessageId();
    const assistantMessage = {
      id: assistantId,
      role: "assistant",
      content: "Researching...",
      status: "running",
    };

    appendMessage(userMessage);
    appendMessage(assistantMessage);
    setLoading(true);
    setQuery("");

    if (eventSource) {
      eventSource.close();
    }

    const res = await fetch("http://localhost:8000/research", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer demo-token",
      },
      body: JSON.stringify({ query: userMessage.content }),
    });

    if (!res.ok) {
      setError("Research request failed");
      setLoading(false);
      setMessages((prev) =>
        prev.map((message) =>
          message.id === assistantId
            ? {
                ...message,
                content: "Research request failed.",
                status: "failed",
              }
            : message,
        ),
      );
      return;
    }

    const { task_id } = await res.json();
    connectStream(task_id, assistantId);
  }

  function connectStream(taskId, assistantId) {
    const source = new EventSource(`http://localhost:8002/stream/${taskId}`);

    source.onmessage = (event) => {
      const data = JSON.parse(event.data);
      const newContent = formatStatusContent(data.status, data.report);
      const newStatus =
        data.status === "DONE"
          ? "done"
          : data.status === "FAILED"
            ? "failed"
            : "running";

      setMessages((prev) =>
        prev.map((message) =>
          message.id === assistantId
            ? { ...message, content: newContent, status: newStatus }
            : message,
        ),
      );

      if (data.status === "FAILED") {
        setError(data.report || "Research failed.");
        setLoading(false);
        source.close();
      }

      if (data.status === "DONE") {
        setLoading(false);
        source.close();
      }
    };

    source.onerror = () => {
      setError("Stream disconnected");
      setLoading(false);
      setMessages((prev) =>
        prev.map((message) =>
          message.id === assistantId
            ? { ...message, content: "Stream disconnected.", status: "failed" }
            : message,
        ),
      );
      source.close();
    };

    setEventSource(source);
  }

  const handleKeyDown = (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submitQuery();
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        background: "#0f172a",
        color: "#e2e8f0",
        padding: "20px",
      }}
    >
      <style>{`
        @keyframes blink {
          0%, 100% { opacity: 0.2; }
          50% { opacity: 1; }
        }
      `}</style>

      <div
        style={{
          maxWidth: 900,
          width: "100%",
          margin: "0 auto",
          flex: 1,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <header style={{ marginBottom: 24 }}>
          <h1 style={{ margin: 0, fontSize: 32 }}>🔍 Research Platform</h1>
          <p style={{ marginTop: 8, color: "#94a3b8" }}>
            Ask questions and get live research reports in chat form.
          </p>
        </header>

        <div
          style={{
            flex: 1,
            overflowY: "auto",
            padding: "16px 0",
            display: "flex",
            flexDirection: "column",
            gap: 12,
          }}
        >
          {messages.map((message) => {
            const isUser = message.role === "user";
            const isAssistant = message.role === "assistant";
            return (
              <div
                key={message.id}
                style={{
                  display: "flex",
                  justifyContent: isUser ? "flex-end" : "flex-start",
                }}
              >
                <div
                  style={{
                    maxWidth: "78%",
                    width: "100%",
                    background: isUser ? "#2563eb" : "#1e293b",
                    color: isUser ? "#fff" : "#e2e8f0",
                    borderRadius: 20,
                    padding: "16px 18px",
                    boxShadow: "0 16px 32px rgba(15, 23, 42, 0.08)",
                    position: "relative",
                  }}
                >
                  {isAssistant && message.status === "running" ? (
                    <div
                      style={{ display: "flex", alignItems: "center", gap: 10 }}
                    >
                      <span>{message.content}</span>
                      <span
                        style={{
                          display: "inline-block",
                          width: 18,
                          textAlign: "left",
                        }}
                      >
                        <span style={{ animation: "blink 1s infinite" }}>
                          •
                        </span>
                        <span style={{ animation: "blink 1s infinite 0.2s" }}>
                          •
                        </span>
                        <span style={{ animation: "blink 1s infinite 0.4s" }}>
                          •
                        </span>
                      </span>
                    </div>
                  ) : message.status === "failed" ? (
                    <div style={{ color: "#fecaca" }}>{message.content}</div>
                  ) : isAssistant ? (
                    <ReactMarkdown>{message.content}</ReactMarkdown>
                  ) : (
                    <div>{message.content}</div>
                  )}
                </div>
              </div>
            );
          })}
          <div ref={messagesEndRef} />
        </div>

        <div
          style={{
            marginTop: "auto",
            padding: "16px",
            background: "#020617",
            borderRadius: 24,
            boxShadow: "0 -10px 30px rgba(15, 23, 42, 0.25)",
          }}
        >
          {error && (
            <div style={{ marginBottom: 12, color: "#fecaca" }}>{error}</div>
          )}

          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type your question..."
            rows={1}
            disabled={loading}
            style={{
              width: "100%",
              resize: "none",
              minHeight: 56,
              maxHeight: 180,
              padding: 14,
              borderRadius: 18,
              border: "1px solid #334155",
              background: "#0f172a",
              color: "#e2e8f0",
              fontSize: 16,
              outline: "none",
              lineHeight: 1.6,
            }}
          />

          <div
            style={{
              marginTop: 12,
              display: "flex",
              justifyContent: "flex-end",
            }}
          >
            <button
              onClick={submitQuery}
              disabled={loading || !query.trim()}
              style={{
                padding: "12px 22px",
                borderRadius: 14,
                border: "none",
                background: loading ? "#475569" : "#2563eb",
                color: "#fff",
                cursor: loading ? "not-allowed" : "pointer",
                fontSize: 16,
                fontWeight: 600,
              }}
            >
              {loading ? "Researching…" : "Run Research"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
