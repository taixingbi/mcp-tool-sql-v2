# mcp-tool-sql

MCP (Model Context Protocol) server exposing a LangChain SQL agent as a tool. Query your database using natural language.

## Design

```
┌─────────────┐     JSON-RPC      ┌──────────────┐     /mcp/      ┌─────────────────┐
│   Client    │ ────────────────► │   FastAPI    │ ─────────────► │  MCP (FastMCP)   │
│  (curl/IDE) │   tools/call      │   :8000      │   streamable   │  sql_agent tool  │
└─────────────┘                   └──────────────┘      HTTP       └────────┬────────┘
                                                                           │
                                                                           ▼
┌─────────────┐     SQL + results  ┌─────────────────┐     invoke    ┌─────────────────┐
│   MySQL     │ ◄───────────────── │ LangChain SQL   │ ◄─────────────│  ChatOpenAI      │
│ job_descr.  │                    │ Agent (tool-    │   question    │  (gpt-4o-mini)   │
│ salaries    │                    │ calling)        │               └─────────────────┘
└─────────────┘                    └─────────────────┘
```

**Components**
- **FastAPI** – HTTP server, mounts MCP at `/mcp`
- **FastMCP** – MCP server, exposes `sql_agent` tool via JSON-RPC
- **LangChain SQL Agent** – Plans and runs SQL via toolkit (schema inspection, query execution)
- **SQLDatabaseToolkit** – Connects to MySQL (`job_descriptions`, `salaries`), provides tools
- **ChatOpenAI** – LLM for natural language → SQL and answer generation

## Workflow

### Deployment (push to main)
```
git push origin main  →  GitHub Actions  →  flyctl deploy  →  Fly.io
```
Requires `FLY_API_TOKEN` in repo Secrets.

### Request flow
```
Client  →  POST /mcp/ (JSON-RPC tools/call)  →  sql_agent(question, limit)
         →  LangChain agent.invoke  →  LLM plans SQL  →  Execute on MySQL
         →  LLM formats answer  →  SqlAgentResponse (ok, answer, token_usage, error)
```

## Setup

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Create a `.env` file with `OPENAI_API_KEY`, `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`.

## Run

### Local

```bash
uvicorn mcp_server:app --reload --port 8000
```

### Docker

```bash
docker build -t mcp-server .
docker run -p 8000:8000 --env-file .env mcp-server
```

### Fly.io

App naming: `mcp-tool-sql-v2-{env}` where `{env}` is `dev`, `qa`, or `prod`.

```bash
brew install flyctl
fly auth login
fly launch
fly secrets set OPENAI_API_KEY=xxx LANGCHAIN_API_KEY=xxx MYSQL_PASSWORD=xxx MYSQL_HOST=xxx MYSQL_PORT=xxx MYSQL_USER=xxx MYSQL_DATABASE=xxx
flyctl auth token   # Add the token to GitHub → Settings → Secrets and variables → Actions as FLY_API_TOKEN.
fly deploy   # deploys to app in fly.toml; use --app mcp-tool-sql-v2-qa or mcp-tool-sql-v2-prod for other envs
```

Pushes to `main` trigger auto-deploy via GitHub Actions (requires `FLY_API_TOKEN` secret).

## Usage

App URLs: `https://mcp-tool-sql-v2-{env}.fly.dev/mcp/` where `{env}` is `dev`, `qa`, or `prod`.

```bash
curl -N -sS "https://mcp-tool-sql-v2-dev.fly.dev/mcp/" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"sql_agent","arguments":{"args":{"question":"List 5 job titles","limit":5}}}}'
```


## Branch → App mapping

| Branch        | Fly app               |
|---------------|------------------------|
| `feature/*`   | mcp-tool-sql-v2-dev    |
| `qa`          | mcp-tool-sql-v2-qa     |
| `main`        | mcp-tool-sql-v2-prod   |

### Create apps before first deploy

GitHub Actions deploys to these apps by branch. **Create all three apps once** (using the same `fly.toml` config) before pushing, or deploys will fail with "app not found":

```bash
fly apps create mcp-tool-sql-v2-dev
fly apps create mcp-tool-sql-v2-qa
fly apps create mcp-tool-sql-v2-prod
```

Then set secrets on each app (or use `fly secrets set` with `--app mcp-tool-sql-v2-qa` etc.):

```bash
fly secrets set OPENAI_API_KEY=xxx MYSQL_HOST=xxx MYSQL_PORT=xxx MYSQL_USER=xxx MYSQL_PASSWORD=xxx MYSQL_DATABASE=xxx --app mcp-tool-sql-v2-dev
fly secrets set OPENAI_API_KEY=xxx MYSQL_HOST=xxx MYSQL_PORT=xxx MYSQL_USER=xxx MYSQL_PASSWORD=xxx MYSQL_DATABASE=xxx --app mcp-tool-sql-v2-qa
fly secrets set OPENAI_API_KEY=xxx MYSQL_HOST=xxx MYSQL_PORT=xxx MYSQL_USER=xxx MYSQL_PASSWORD=xxx MYSQL_DATABASE=xxx --app mcp-tool-sql-v2-prod
```
