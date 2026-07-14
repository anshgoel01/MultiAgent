# 🔍 Multi-Agent Research Platform

A multi-agent AI research system that takes a natural language query, coordinates a team of specialized LLM agents to research it (using both an internal document corpus and live web search), critiques its own findings, and produces a structured, cited research report — all streamed live to a React frontend.

Built as a microservices architecture with FastAPI, LangGraph, PostgreSQL + pgvector, Groq (Llama 3.3 70B), and Tavily, fully containerized with Docker Compose.

---

## What This Project Does

You type a research question. Instead of a single AI model answering directly, a coordinated team of AI agents works together:

```
User Query → Gateway → Task Created → Multi-Agent Pipeline Runs → Report Streamed Back
```

| Agent          | Job                                                                                                                               |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| **Planner**    | Breaks the query into 3–5 concrete subtasks                                                                                       |
| **Retriever**  | Searches an internal pgvector document corpus for relevant chunks                                                                 |
| **Web Search** | Searches the live web (via Tavily) for current information                                                                        |
| **Analyst**    | Synthesizes retrieved content into key findings with confidence levels                                                            |
| **Critic**     | Reviews the findings — if too thin, sends the pipeline back to the Retriever for one more pass before proceeding |
| **Writer**     | Produces the final structured report (Executive Summary, Key Findings, Analysis, Conclusion)                                      |

The whole pipeline is orchestrated using **LangGraph**, which manages a shared state object as it flows through each agent — including conditional branching for the Critic's feedback loop.

While the agents work in the background, the frontend receives **live status updates** via Server-Sent Events (SSE), so the user sees progress (`PENDING → RUNNING → DONE`) in real time instead of a blank loading spinner.

---

## Architecture

The backend is split into three independent FastAPI services, each in its own Docker container, communicating over REST:

| Service               | Port | Responsibility                                                                        | Database                            |
| --------------------- | ---- | ------------------------------------------------------------------------------------- | ----------------------------------- |
| `gateway-service`     | 8000 | Entry point — validates requests, rate-limits, routes to other services, handles CORS | None                                |
| `task-service`        | 8001 | Owns task state (`PENDING → RUNNING → DONE/FAILED`), persists final reports           | PostgreSQL                          |
| `agent-orchestrator`  | 8002 | Runs the LangGraph multi-agent pipeline, streams progress via SSE                     | None (uses pgvector via `postgres`) |
| `postgres` (pgvector) | 5432 | Stores task records + a vector-searchable document corpus                             | —                                   |

**Request flow:**

1. Client → `gateway-service` : `POST /research { query }`
2. Gateway → `task-service` : creates a task record, gets back a `task_id`
3. Gateway → `agent-orchestrator` : `POST /run { task_id, query }` (fires as a background task, returns immediately)
4. Orchestrator runs the LangGraph pipeline, periodically patching `task-service` with status updates
5. Client subscribes to `agent-orchestrator`'s `GET /stream/{task_id}` (SSE) to watch live status
6. Once `DONE`, the final report is available via `GET /tasks/{task_id}` and rendered in the UI

---

## Tech Stack

| Layer              | Technology                                          |
| ------------------ | --------------------------------------------------- |
| Agent framework    | LangGraph                                           |
| API services       | FastAPI + Uvicorn                                   |
| Database           | PostgreSQL 16                                       |
| Vector search      | pgvector extension                                  |
| LLM                | Groq API (Llama 3.3 70B)                            |
| Web search         | Tavily API                                          |
| Embeddings         | sentence-transformers (`all-MiniLM-L6-v2`, 384-dim) |
| Containerization   | Docker + Docker Compose                             |
| Inter-service HTTP | httpx                                               |
| Frontend           | React + Vite                                        |

---

## Prerequisites

Before running this project, make sure you have:

- **[Docker Desktop](https://www.docker.com/products/docker-desktop/)** installed and running
- **Node.js 18+** and npm (for the frontend)
- A free **[Groq API key](https://console.groq.com)** (for the LLM)
- A free **[Tavily API key](https://tavily.com)** (for web search)
- At least **10–15 GB of free disk space** (Docker images + PyTorch/ML dependencies are sizable)

---

## Setup & Running Locally

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd research-platform
```

### 2. Configure environment variables

Copy the provided template to create your `.env` file in the project root (`research-platform/.env`):

```bash
cp .env.example .env
```

Then fill in your own `GROQ_API_KEY` and `TAVILY_API_KEY`. The full file looks like this:

```env
POSTGRES_USER=admin
POSTGRES_PASSWORD=secret
DATABASE_URL=postgresql://admin:secret@postgres:5432/research_db
TASK_SERVICE_URL=http://task-service:8001
ORCHESTRATOR_URL=http://agent-orchestrator:8002
GROQ_API_KEY=gsk_your_groq_api_key_here
TAVILY_API_KEY=tvly-your-tavily-api-key-here
JWT_SECRET=some_random_string_for_jwt
API_AUTH_TOKEN=demo-token
INTERNAL_AUTH_TOKEN=some_shared_internal_secret
```

> **Important:** `POSTGRES_USER` and `POSTGRES_PASSWORD` are required — without them the `postgres` container fails to initialize and the whole stack won't start. Don't just copy the snippet above by hand; use `.env.example` as the source of truth if the two ever drift.

### 3. Start the backend services

Make sure Docker Desktop is running, then from the project root:

```bash
docker compose up --build
```

This builds and starts all four containers: `postgres`, `task-service`, `agent-orchestrator`, and `gateway-service`. First build can take several minutes (downloading ML dependencies like PyTorch). Wait until you see all four services log `Uvicorn running on http://0.0.0.0:...`.

### 4. Initialize the vector database

In a **new terminal**, run the database initialization script once, to create the `documents` table and load sample content:

```bash
docker compose exec agent-orchestrator python db_init.py
```

You should see confirmation that the `documents` table was created and sample documents were inserted.

### 5. Start the frontend

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

This starts the Vite dev server, typically at `http://localhost:5173`.

## How the Agent Pipeline Works

All agents share a single Python `TypedDict` called `ResearchState`, which LangGraph passes between nodes, merging updates as it goes:

```python
class ResearchState(TypedDict):
    query: str
    task_id: str
    subtasks: list[str]
    retrieved: list[str]
    web_results: list[str]
    findings: list[str]
    critic_retries: int
    report: Optional[str]
    status: str
    error: Optional[str]
```

**Execution graph:**

```
START
  │
  ▼
Planner
  │
  ├──► Retriever ──┐
  │                 ├──► Analyst ──► Critic ──┬──► (insufficient, retries left) ──► back to Retriever
  └──► Web Search ──┘                          │
                                                └──► (sufficient, or retries exhausted) ──► Writer ──► END
```

The Critic/Retriever loop is capped (default: 1 retry) to guarantee the pipeline always terminates, even if the findings never reach a "sufficient" verdict.

---

## Common Issues & Fixes

| Problem | Fix |
|---|---|
| `postgres` container exits immediately / `docker compose up` never reaches "Uvicorn running" | Your `.env` is missing `POSTGRES_USER` / `POSTGRES_PASSWORD`. Use `.env.example` as the source of truth (`cp .env.example .env`) rather than retyping variables by hand. |
| `docker compose up` fails with `read-only file system` | Docker's internal storage is corrupted, usually from low disk space. Free up disk space, restart Docker Desktop / WSL2 (`wsl --shutdown`), or reinstall Docker Desktop. |
| CORS error in browser console | Ensure `CORSMiddleware` is configured in both `gateway-service/main.py` and `agent-orchestrator/main.py` with your frontend's origin (`http://localhost:5173`) allowed. |
| `relation "documents" does not exist` in orchestrator logs | The pgvector table wasn't initialized. Run `docker compose exec agent-orchestrator python db_init.py`. |
| Code changes don't seem to apply | Docker containers run a built image, not your live files. After editing code, rebuild: `docker compose up --build <service-name>`. |
| `404 Not Found` on `/run` or `/stream/{task_id}` | Usually a stale container running an old build. Rebuild with `docker compose up --build agent-orchestrator`. |
| First build is very slow / huge download | `sentence-transformers` pulls in PyTorch, which defaults to a large GPU-enabled build. Add `--extra-index-url https://download.pytorch.org/whl/cpu` above `torch` in `agent-orchestrator/requirements.txt` to force the smaller CPU-only build. |

---

<!-- ## Interview Talking Points

**Why microservices instead of a monolith?**
Each service has a different scaling profile: `task-service` is I/O-bound (database reads/writes), `agent-orchestrator` is CPU/LLM-call heavy, and `gateway-service` is stateless. Separating them means the orchestrator can be scaled independently without touching the others.

**How does agent communication work?**
All agents read from and write to a single shared `ResearchState` object. LangGraph manages state merging across nodes — agents don't call each other directly; the graph definition controls execution order and branching.

**Why LangGraph over a simple prompt chain?**
LangGraph gives explicit control over execution flow — conditional edges, parallel branches, and feedback loops (like the Critic looping back to the Retriever) aren't easily expressible with a linear chain.

**How does the RAG pipeline work?**
Documents are chunked, embedded with `all-MiniLM-L6-v2` (384-dim), and stored in PostgreSQL via the pgvector extension. At query time, the Retriever embeds the subtask and performs a cosine similarity search (`<=>` operator) to pull the top-k most relevant chunks.

**What would you add to make this production-ready?**
Real JWT authentication with refresh tokens, a message queue (e.g. Kafka) for async task handling under concurrent load, observability/tracing (e.g. LangSmith), horizontal scaling of the orchestrator, and a properly curated document corpus instead of sample data.

--- -->

## License

This project was built as a learning/portfolio project. Feel free to fork and adapt it.
