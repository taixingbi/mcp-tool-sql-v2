import asyncio
import os
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv(override=True)  # .env overrides shell env (e.g. OPENAI_API_KEY from Cursor)

from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from mcp.server.fastmcp import Context, FastMCP

from langchain_openai import ChatOpenAI
from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.agent_toolkits.sql.base import create_sql_agent

# Token usage callback (works for OpenAI-family models)
from langchain_community.callbacks import get_openai_callback

from mcp.server.transport_security import TransportSecuritySettings

mcp = FastMCP(
    "mcp-sql-agent",
    stateless_http=True,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    ),
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"],
)
app.mount("/mcp", mcp.streamable_http_app())

# -------------------------
# Build LangChain SQL Agent
# -------------------------
_AGENT = None

ALLOWED_TABLES = None  # None = all tables
DEFAULT_LIMIT = 10

# In-memory rate limiter: {key: deque of timestamps}
_RATE_LIMIT_STORE: Dict[str, deque] = {}
_RATE_LIMIT_LOCK = asyncio.Lock()

print("DB config:", {"MYSQL_HOST": os.environ.get("MYSQL_HOST"), "MYSQL_PORT": os.environ.get("MYSQL_PORT"), "MYSQL_USER": os.environ.get("MYSQL_USER"), "MYSQL_PASSWORD": os.environ.get("MYSQL_PASSWORD"), "MYSQL_DATABASE": os.environ.get("MYSQL_DATABASE")})

def _mysql_uri() -> str:
    host = os.environ.get("MYSQL_HOST")
    port = int(os.environ.get("MYSQL_PORT"))
    user = os.environ.get("MYSQL_USER")
    pwd = os.environ.get("MYSQL_PASSWORD")
    db = os.environ.get("MYSQL_DATABASE")
    return f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{db}"

def get_llm() -> ChatOpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required")

    return ChatOpenAI(
        model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=float(os.environ.get("OPENAI_TEMPERATURE", "0")),
        api_key=api_key,
    )


def build_sql_system_prompt(db_name: str) -> str:
    return f"""
You are an agent designed to interact with a SQL database.
Given an input question, create a syntactically correct {db_name} query to run,
then look at the results of the query and return the answer. Unless the user
specifies a specific number of examples they wish to obtain, always limit your
query to at most {{top_k}} results.

You can order the results by a relevant column to return the most interesting
examples in the database. Never query for all the columns from a specific table,
only ask for the relevant columns given the question.

You MUST double check your query before executing it. If you get an error while
executing a query, rewrite the query and try again.

DO NOT make any DML statements (INSERT, UPDATE, DELETE, DROP etc.) to the
database.

To start you should ALWAYS look at the tables in the database to see what you
can query. Do NOT skip this step.

Then you should query the schema of the most relevant tables.
""".format(top_k=5)


def get_agent():
    global _AGENT
    if _AGENT is not None:
        return _AGENT

    llm = get_llm()
    db = SQLDatabase.from_uri(_mysql_uri(), include_tables=ALLOWED_TABLES)
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)

    system_prompt = build_sql_system_prompt(db_name=os.environ.get("DB_NAME", "hunter"))

    _AGENT = create_sql_agent(
        llm=llm,
        toolkit=toolkit,
        agent_type="tool-calling",
        system_prompt=system_prompt,
        verbose=False,
        # If you want more observability from the executor, you can set:
        # return_intermediate_steps=True,
    )
    return _AGENT


# -------------
# MCP Tool API
# -------------
class SqlAgentArgs(BaseModel):
    question: str = Field(..., description="Natural language question")
    stream: bool = Field(default=False, description="Stream agent steps and report progress")
    rate_limit: Optional[int] = Field(
        default=None,
        ge=1,
        description="Max requests per minute for this client; if set, enforces rate limiting",
    )


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0


class StreamEvent(BaseModel):
    """Single event from agent stream (when stream=True)."""
    type: str  # "action" | "step" | "finish"
    tool: Optional[str] = None
    message: Optional[str] = None


class SqlAgentResponse(BaseModel):
    ok: bool = True
    request_id: str
    model: str
    latency_ms: int
    version: str

    # ✅ echo inputs for observability
    question: str

    answer: str
    token_usage: Optional[TokenUsage] = None
    error: Optional[str] = None
    # Populated when stream=True
    streamed_events: Optional[List[StreamEvent]] = None


async def _check_rate_limit(key: str, limit: int) -> bool:
    """Return True if under limit, False if over limit."""
    now = time.monotonic()
    window_sec = 60.0
    async with _RATE_LIMIT_LOCK:
        if key not in _RATE_LIMIT_STORE:
            _RATE_LIMIT_STORE[key] = deque()
        q = _RATE_LIMIT_STORE[key]
        while q and now - q[0] > window_sec:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
    return True


def _dump_model(m: BaseModel) -> Dict[str, Any]:
    # pydantic v2 -> model_dump; v1 -> dict
    if hasattr(m, "model_dump"):
        return m.model_dump()
    return m.dict()


async def _run_sql_agent_stream(
    agent: Any,
    user_msg: str,
    args: SqlAgentArgs,
    ctx: Optional[Context],
) -> tuple[str, List[StreamEvent], TokenUsage]:
    """Run agent with streaming, optionally reporting progress via Context."""
    events: List[StreamEvent] = []
    step_num = 0

    async def _report(progress: int, message: str) -> None:
        if ctx is not None:
            try:
                await ctx.report_progress(progress, None, message)
            except Exception:
                pass

    answer = ""
    with get_openai_callback() as cb:
        async for chunk in agent.astream(
            {"input": user_msg},
            {"tags": ["mcp-tool-sql", "sql-agent", "langchain-agent", "sql-tool", _get_version()]},
        ):
            if "actions" in chunk:
                for action in chunk.get("actions", []):
                    tool = getattr(action, "tool", None) or (action.get("tool") if isinstance(action, dict) else None)
                    step_num += 1
                    msg = f"Calling tool: {tool}" if tool else "Planning..."
                    events.append(StreamEvent(type="action", tool=str(tool) if tool else None, message=msg))
                    await _report(step_num, msg)
            elif "steps" in chunk:
                for step in chunk.get("steps", []):
                    action = getattr(step, "action", step) if hasattr(step, "action") else step
                    tool = getattr(action, "tool", None) if hasattr(action, "tool") else None
                    step_num += 1
                    msg = f"Completed: {tool}" if tool else "Step completed"
                    events.append(StreamEvent(type="step", tool=str(tool) if tool else None, message=msg))
                    await _report(step_num, msg)
            elif "output" in chunk:
                answer = (chunk.get("output") or "").strip()
                events.append(StreamEvent(type="finish", message="Done"))
                await _report(step_num + 1, "Done")

    token_usage = TokenUsage(
        prompt_tokens=getattr(cb, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(cb, "completion_tokens", 0) or 0,
        total_tokens=getattr(cb, "total_tokens", 0) or 0,
        total_cost_usd=float(getattr(cb, "total_cost", 0.0) or 0.0),
    )
    return answer, events, token_usage


def _get_version() -> str:
    return os.environ.get("APP_VERSION", "v:1.0")


@mcp.tool()
async def sql_agent(args: SqlAgentArgs, ctx: Optional[Context] = None) -> Dict[str, Any]:
    request_id = str(uuid.uuid4())
    model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    version = _get_version()

    start = time.perf_counter()

    if args.rate_limit is not None:
        key = getattr(ctx, "client_id", None) if ctx else None
        key = str(key) if key else "global"
        if not await _check_rate_limit(key, args.rate_limit):
            resp = SqlAgentResponse(
                ok=False,
                request_id=request_id,
                model=model_name,
                latency_ms=int((time.perf_counter() - start) * 1000),
                version=version,
                question=args.question,
                answer="",
                token_usage=None,
                error="Rate limit exceeded",
            )
            return _dump_model(resp)

    try:
        agent = get_agent()
        user_msg = f"{args.question}\n(Use LIMIT <= {DEFAULT_LIMIT}.)"

        if args.stream:
            answer, events, token_usage = await _run_sql_agent_stream(agent, user_msg, args, ctx)
            resp = SqlAgentResponse(
                ok=True,
                request_id=request_id,
                model=model_name,
                latency_ms=int((time.perf_counter() - start) * 1000),
                version=version,
                question=args.question,
                answer=answer,
                token_usage=token_usage,
                streamed_events=events,
            )
        else:
            with get_openai_callback() as cb:
                result = agent.invoke(
                    {"input": user_msg},
                    {"tags": ["mcp-tool-sql", "sql-agent", "langchain-agent", "sql-tool", version]},
                )
            answer = (result.get("output") or "").strip()
            resp = SqlAgentResponse(
                ok=True,
                request_id=request_id,
                model=model_name,
                latency_ms=int((time.perf_counter() - start) * 1000),
                version=version,
                question=args.question,
                answer=answer,
                token_usage=TokenUsage(
                    prompt_tokens=getattr(cb, "prompt_tokens", 0) or 0,
                    completion_tokens=getattr(cb, "completion_tokens", 0) or 0,
                    total_tokens=getattr(cb, "total_tokens", 0) or 0,
                    total_cost_usd=float(getattr(cb, "total_cost", 0.0) or 0.0),
                ),
            )
        return _dump_model(resp)

    except Exception as e:
        latency_ms = int((time.perf_counter() - start) * 1000)
        resp = SqlAgentResponse(
            ok=False,
            request_id=request_id,
            model=model_name,
            latency_ms=latency_ms,
            version=version,
            question=args.question,
            answer="",
            token_usage=None,
            error=f"{type(e).__name__}: {e}",
        )
        return _dump_model(resp)
