import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import "./App.css";

const STORAGE_KEY = "research_chat_history";
const MAX_SESSIONS = 20;

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

const RUNNING_STAGES = [
  "🔍 Planning subtasks...",
  "📚 Retrieving documents...",
  "🌐 Searching the web...",
  "📊 Analyzing findings...",
  "✍️ Writing report...",
];

const formatReportContent = (content) => {
  if (typeof content !== "string") {
    return content;
  }

  return content.replace(
    /(\(?\bSource:\s*.+?\s+Confidence:\s*(?:HIGH|MED|LOW)\)?)/gi,
    "\n\n> $1",
  );
};

const reportMarkdownComponents = {
  h2: ({ node, ...props }) => <h2 className="report-heading" {...props} />,
  p: ({ node, ...props }) => <p className="report-paragraph" {...props} />,
  ol: ({ node, ...props }) => <ol className="report-list" {...props} />,
  li: ({ node, ...props }) => <li className="report-list-item" {...props} />,
  strong: ({ node, ...props }) => (
    <strong className="report-strong" {...props} />
  ),
  blockquote: ({ node, ...props }) => (
    <blockquote className="report-metadata" {...props} />
  ),
};

const createSession = (messages = [], title = "New chat") => ({
  id: getMessageId(),
  title,
  timestamp: new Date().toISOString(),
  messages,
});

const sortSessions = (sessionList) =>
  [...sessionList].sort(
    (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
  );

const normalizeSessions = (sessionList) =>
  sortSessions(sessionList)
    .map((session) => ({
      ...session,
      title: session.title || "New chat",
      messages: session.messages || [],
    }))
    .slice(0, MAX_SESSIONS);

const loadPersistedState = () => {
  try {
    const storedValue = localStorage.getItem(STORAGE_KEY);
    if (!storedValue) {
      return null;
    }

    const parsed = JSON.parse(storedValue);
    if (!parsed) {
      return null;
    }

    if (Array.isArray(parsed)) {
      const sessions = normalizeSessions(parsed);
      return {
        sessions,
        activeSessionId: sessions.length ? sessions[0].id : null,
      };
    }

    if (typeof parsed === "object") {
      const sessions = normalizeSessions(parsed.sessions || []);
      const activeSessionId =
        parsed.activeSessionId || (sessions[0] && sessions[0].id) || null;
      return { sessions, activeSessionId };
    }

    return null;
  } catch {
    return null;
  }
};

const savePersistedState = (sessions, activeSessionId, messages) => {
  if (!sessions.length) {
    localStorage.removeItem(STORAGE_KEY);
    return;
  }

  const normalized = normalizeSessions(sessions).map((session) => {
    if (session.id === activeSessionId) {
      return { ...session, messages };
    }

    return session;
  });

  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({ sessions: normalized, activeSessionId }),
  );
};

const formatTimestamp = (value) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
};

export default function App() {
  const getInitialAppState = () => {
    const persisted = loadPersistedState();

    if (persisted && persisted.sessions.length) {
      const selectedSession = persisted.sessions.find(
        (session) => session.id === persisted.activeSessionId,
      );

      return {
        sessions: persisted.sessions,
        activeSessionId:
          persisted.activeSessionId || persisted.sessions[0].id || null,
        messages:
          selectedSession?.messages || persisted.sessions[0].messages || [],
      };
    }

    const initialSession = createSession([], "New chat");
    return {
      sessions: [initialSession],
      activeSessionId: initialSession.id,
      messages: [],
    };
  };

  const initialAppState = getInitialAppState();
  const [query, setQuery] = useState("");
  const [messages, setMessages] = useState(initialAppState.messages);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [eventSource, setEventSource] = useState(null);
  const [sessions, setSessions] = useState(initialAppState.sessions);
  const [activeSessionId, setActiveSessionId] = useState(
    initialAppState.activeSessionId,
  );
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [runningStageIndex, setRunningStageIndex] = useState(0);
  const [copiedMessageId, setCopiedMessageId] = useState(null);
  const copyResetTimeoutRef = useRef(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    savePersistedState(sessions, activeSessionId, messages);
  }, [sessions, activeSessionId, messages]);

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

  useEffect(() => {
    const activeRunningMessage = messages.find(
      (message) => message.role === "assistant" && message.status === "running",
    );

    if (!activeRunningMessage) {
      setRunningStageIndex(0);
      return undefined;
    }

    setRunningStageIndex(0);
    const intervalId = window.setInterval(() => {
      setRunningStageIndex((prev) => (prev + 1) % RUNNING_STAGES.length);
    }, 6000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [messages]);

  useEffect(() => {
    return () => {
      if (copyResetTimeoutRef.current) {
        window.clearTimeout(copyResetTimeoutRef.current);
      }
    };
  }, []);

  const appendMessage = (message) => {
    setMessages((prev) => {
      const nextMessages = [...prev, message];
      setSessions((currentSessions) =>
        sortSessions(
          currentSessions.map((session) =>
            session.id === activeSessionId
              ? { ...session, messages: nextMessages }
              : session,
          ),
        ),
      );
      return nextMessages;
    });
  };

  const createFreshSession = () => {
    const freshSession = createSession([], "New chat");
    setSessions((prev) => sortSessions([freshSession, ...prev]));
    setActiveSessionId(freshSession.id);
    setMessages([]);
    setError("");
    setLoading(false);
    setQuery("");

    if (eventSource) {
      eventSource.close();
      setEventSource(null);
    }
  };

  const selectSession = (sessionId) => {
    const selectedSession = sessions.find(
      (session) => session.id === sessionId,
    );
    if (!selectedSession) {
      return;
    }

    setActiveSessionId(sessionId);
    setMessages(selectedSession.messages || []);
    setError("");
    setLoading(false);
    setQuery("");

    if (eventSource) {
      eventSource.close();
      setEventSource(null);
    }
  };

  async function submitQuery() {
    if (!query.trim() || loading) {
      return;
    }

    setError("");

    const trimmedQuery = query.trim();
    const userMessage = {
      id: getMessageId(),
      role: "user",
      content: trimmedQuery,
    };

    const assistantId = getMessageId();
    const assistantMessage = {
      id: assistantId,
      role: "assistant",
      content: "Researching...",
      status: "running",
    };

    const nextMessages = [...messages, userMessage, assistantMessage];
    setMessages(nextMessages);
    setSessions((currentSessions) =>
      sortSessions(
        currentSessions.map((session) =>
          session.id === activeSessionId
            ? {
                ...session,
                title: trimmedQuery.slice(0, 40),
                timestamp: new Date().toISOString(),
                messages: nextMessages,
              }
            : session,
        ),
      ),
    );
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

      setMessages((prev) => {
        const updatedMessages = prev.map((message) =>
          message.id === assistantId
            ? { ...message, content: newContent, status: newStatus }
            : message,
        );

        setSessions((currentSessions) =>
          sortSessions(
            currentSessions.map((session) =>
              session.id === activeSessionId
                ? { ...session, messages: updatedMessages }
                : session,
            ),
          ),
        );

        return updatedMessages;
      });

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

  const handleCopyMessage = async (messageContent, messageId) => {
    try {
      await navigator.clipboard.writeText(messageContent);
      setCopiedMessageId(messageId);
      if (copyResetTimeoutRef.current) {
        window.clearTimeout(copyResetTimeoutRef.current);
      }
      copyResetTimeoutRef.current = window.setTimeout(() => {
        setCopiedMessageId(null);
      }, 2000);
    } catch {
      setError("Unable to copy report.");
    }
  };

  const exampleQueries = [
    "What are the latest trends in generative AI in 2025?",
    "Compare React vs Vue vs Angular for enterprise applications",
    "What are the key risks and opportunities in India's fintech sector?",
  ];

  return (
    <div className={`app-shell ${isSidebarOpen ? "" : "sidebar-collapsed"}`}>
      <div className="chat-sidebar">
        <div className="sidebar-actions">
          <button className="sidebar-new-chat" onClick={createFreshSession}>
            + New Chat
          </button>
        </div>

        <div className="sidebar-session-list">
          {sessions.map((session) => {
            const isActive = session.id === activeSessionId;
            return (
              <button
                key={session.id}
                className={`sidebar-session-button ${isActive ? "active" : ""}`}
                onClick={() => selectSession(session.id)}
              >
                <div className="session-title">{session.title}</div>
                <div className="session-meta">
                  {formatTimestamp(session.timestamp)}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="main-panel">
        <header className="main-panel-header">
          <div>
            <button
              className="sidebar-toggle"
              onClick={() => setIsSidebarOpen((prev) => !prev)}
              aria-label="Toggle sidebar"
            >
              ☰
            </button>
            <h1>🔍 Concord</h1>
            <p>Ask questions and get live research reports in chat form.</p>
          </div>
        </header>

        <div
          className={`chat-messages ${messages.length === 0 ? "empty" : ""}`}
        >
          {messages.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon" aria-hidden="true">
                🔍
              </div>
              <h2>Concord</h2>
              <p>
                Ask any question and get a structured research report powered by
                AI agents.
              </p>
              <div className="empty-state-examples">
                {exampleQueries.map((exampleQuery) => (
                  <button
                    key={exampleQuery}
                    type="button"
                    className="empty-state-card"
                    onClick={() => setQuery(exampleQuery)}
                  >
                    {exampleQuery}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {messages.map((message) => {
                const isUser = message.role === "user";
                const isAssistant = message.role === "assistant";
                return (
                  <div
                    key={message.id}
                    className={`chat-message-row ${isUser ? "user" : "assistant"}`}
                  >
                    <div
                      className={`chat-bubble ${isUser ? "user" : "assistant"}`}
                    >
                      {isAssistant ? (
                        <div className="assistant-message-body">
                          {message.status === "done" && (
                            <button
                              type="button"
                              className="assistant-copy-button"
                              onClick={() =>
                                handleCopyMessage(message.content, message.id)
                              }
                            >
                              {copiedMessageId === message.id
                                ? "Copied!"
                                : "Copy"}
                            </button>
                          )}
                          {message.status === "running" ? (
                            <div className="assistant-running">
                              <span>
                                {RUNNING_STAGES[runningStageIndex] ||
                                  "🔍 Planning subtasks..."}
                              </span>
                              <span className="typing-dots" aria-hidden="true">
                                <span>•</span>
                                <span>•</span>
                                <span>•</span>
                              </span>
                            </div>
                          ) : message.status === "failed" ? (
                            <div className="assistant-error">
                              {message.content}
                            </div>
                          ) : (
                            <ReactMarkdown
                              className="assistant-markdown"
                              components={reportMarkdownComponents}
                            >
                              {formatReportContent(message.content)}
                            </ReactMarkdown>
                          )}
                        </div>
                      ) : (
                        <div>{message.content}</div>
                      )}
                    </div>
                  </div>
                );
              })}
              <div ref={messagesEndRef} />
            </>
          )}
        </div>

        <div className="composer-card">
          {error && <div className="composer-error">{error}</div>}

          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type your question..."
            rows={1}
            disabled={loading}
            className="composer-input"
          />

          <div className="composer-actions">
            <button
              onClick={submitQuery}
              disabled={loading || !query.trim()}
              className={`composer-button ${loading ? "loading" : ""}`}
            >
              {loading ? "Researching…" : "Run Research"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
