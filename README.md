🔍 Multi-Agent Research Platform

A multi-agent AI research system that takes a natural language query, coordinates a team of specialized LLM agents to research it (using both an internal document corpus and live web search), critiques its own findings, and produces a structured, cited research report — all streamed live to a React frontend.

Built as a microservices architecture with FastAPI, LangGraph, PostgreSQL + pgvector, Groq (Llama 3.3 70B), and Tavily, fully containerized with Docker Compose.


What This Project Does

You type a research question. Instead of a single AI model answering directly, a coordinated team of AI agents works together:

User Query → Gateway → Task Created → Multi-Agent Pipeline Runs → Report Streamed Back

AgentJobPlannerBreaks the query into 3–5 concrete subtasksRetrieverSearches an internal pgvector document corpus for relevant chunksWeb SearchSearches the live web (via Tavily) for current informationAnalystSynthesizes retrieved content into key findings with confidence levelsCriticReviews the findings — if too thin, sends the pipeline back to the Retriever for one more pass before proceedingWriterProduces the final structured report (Executive Summary, Key Findings, Analysis, Conclusion)

The whole pipeline is orchestrated using LangGraph, which manages a shared state object as it flows through each agent — including conditional branching for the Critic's feedback loop.

While the agents work in the background, the frontend receives live status updates via Server-Sent Events (SSE), so the user sees progress (PENDING → RUNNING → DONE) in real time instead of a blank loading spinner.


Architecture

The backend is split into three independent FastAPI services, each in its own Docker container, communicating over REST:

ServicePortResponsibilityDatabasegateway-service8000Entry point — validates requests, rate-limits, routes to other services, handles CORSNonetask-service8001Owns task state (PENDING → RUNNING → DONE/FAILED), persists final reportsPostgreSQLagent-orchestrator8002Runs the LangGraph multi-agent pipeline, streams progress via SSENone (uses pgvector via postgres)postgres (pgvector)5432Stores task records + a vector-searchable document corpus—

Request flow:


Client → gateway-service : POST /research { query }
Gateway → task-service : creates a task record, gets back a task_id
Gateway → agent-orchestrator : POST /run { task_id, query } (fires as a background task, returns immediately)
Orchestrator runs the LangGraph pipeline, periodically patching task-service with status updates
Client subscribes to agent-orchestrator's GET /stream/{task_id} (SSE) to watch live status
Once DONE, the final report is available via GET /tasks/{task_id} and rendered in the UI



Tech Stack

LayerTechnologyAgent frameworkLangGraphAPI servicesFastAPI + UvicornDatabasePostgreSQL 16Vector searchpgvector extensionLLMGroq API (Llama 3.3 70B)Web searchTavily APIEmbeddingssentence-transformers (all-MiniLM-L6-v2, 384-dim)ContainerizationDocker + Docker ComposeInter-service HTTPhttpxFrontendReact + Vite


Prerequisites

Before running this project, make sure you have:


Docker Desktop installed and running
Node.js 18+ and npm (for the frontend)
A free Groq API key (for the LLM)
A free Tavily API key (for web search)
At least 10–15 GB of free disk space (Docker images + PyTorch/ML dependencies are sizable)



Setup & Running Locally

1. Clone the repository

bashgit clone <your-repo-url>
cd research-platform

2. Configure environment variables

Copy the provided template to create your .env file in the project root (research-platform/.env):

bashcp .env.example .env

Then fill in your own GROQ_API_KEY and TAVILY_API_KEY. The full file looks like this:

envPOSTGRES_USER=admin
POSTGRES_PASSWORD=secret
DATABASE_URL=postgresql://admin:secret@postgres:5432/research_db
TASK_SERVICE_URL=http://task-service:8001
ORCHESTRATOR_URL=http://agent-orchestrator:8002
GROQ_API_KEY=gsk_your_groq_api_key_here
TAVILY_API_KEY=tvly-your-tavily-api-key-here
JWT_SECRET=some_random_string_for_jwt
API_AUTH_TOKEN=demo-token
INTERNAL_AUTH_TOKEN=some_shared_internal_secret


Important: POSTGRES_USER and POSTGRES_PASSWORD are required — without them the postgres container fails to initialize and the whole stack won't start. Don't just copy the snippet above by hand; use .env.example as the source of truth if the two ever drift.



3. Start the backend services

Make sure Docker Desktop is running, then from the project root:

bashdocker compose up --build

This builds and starts all four containers: postgres, task-service, agent-orchestrator, and gateway-service. First build can take several minutes (downloading ML dependencies like PyTorch). Wait until you see all four services log Uvicorn running on http://0.0.0.0:....

4. Initialize the vector database

In a new terminal, run the database initialization script once, to create the documents table and load sample content:

bashdocker compose exec agent-orchestrator python db_init.py

You should see confirmation that the documents table was created and sample documents were inserted.

5. Start the frontend

In another terminal:

bashcd frontend
npm install
npm run dev

This starts the Vite dev server, typically at http://localhost:5173.

How the Agent Pipeline Works

All agents share a single Python TypedDict called ResearchState, which LangGraph passes between nodes, merging updates as it goes:

pythonclass ResearchState(TypedDict):
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

Execution graph:

START
  │
  ▼
Planner
  │
  ├──► Retriever ──┐
  │                 ├──► Analyst ──► Critic ──┬──► (insufficient, retries left) ──► back to Retriever
  └──► Web Search ──┘                          │
                                                └──► (sufficient, or retries exhausted) ──► Writer ──► END

The Critic/Retriever loop is capped (default: 1 retry) to guarantee the pipeline always terminates, even if the findings never reach a "sufficient" verdict.
