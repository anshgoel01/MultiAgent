import { useEffect, useState } from "react";

export default function App() {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [report, setReport] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [eventSource, setEventSource] = useState(null);

  useEffect(() => {
    return () => {
      if (eventSource) {
        eventSource.close();
      }
    };
  }, [eventSource]);

  async function submitQuery() {
    setLoading(true);
    setStatus("Submitting...");
    setReport("");
    setError("");

    if (eventSource) {
      eventSource.close();
    }

    const res = await fetch("http://localhost:8000/research", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer demo-token",
      },
      body: JSON.stringify({ query }),
    });

    if (!res.ok) {
      setLoading(false);
      setError("Research request failed");
      setStatus("FAILED");
      return;
    }

    const { task_id } = await res.json();
    connectStream(task_id);
  }

  function connectStream(taskId) {
    const source = new EventSource(`http://localhost:8002/stream/${taskId}`);

    source.onmessage = (event) => {
      const data = JSON.parse(event.data);
      setStatus(data.status);
      if (data.report) {
        setReport(data.report);
      }

      if (data.status === "FAILED") {
        setError(data.report || "Research failed");
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
      source.close();
    };

    setEventSource(source);
  }

  return (
    <div
      style={{
        maxWidth: 800,
        margin: "40px auto",
        fontFamily: "sans-serif",
        padding: "0 20px",
      }}
    >
      <h1>🔍 Research Platform</h1>
      <textarea
        rows={3}
        style={{ width: "100%", padding: 8, fontSize: 16 }}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Enter your research query..."
      />
      <button
        onClick={submitQuery}
        disabled={loading || !query}
        style={{
          marginTop: 8,
          padding: "10px 24px",
          fontSize: 16,
          cursor: "pointer",
        }}
      >
        {loading ? "Researching..." : "Run Research"}
      </button>
      {status && (
        <p>
          <b>Status:</b> {status}
        </p>
      )}
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      {report && (
        <pre
          style={{
            whiteSpace: "pre-wrap",
            background: "#f5f5f5",
            padding: 16,
            borderRadius: 8,
          }}
        >
          {report}
        </pre>
      )}
    </div>
  );
}
