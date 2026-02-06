"""Tests for mcp_server."""
import asyncio
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Patch load_dotenv and env before importing to avoid .env and missing keys
with patch("dotenv.load_dotenv"), patch.dict(os.environ, {
    "OPENAI_API_KEY": "sk-test",
    "MYSQL_HOST": "localhost",
    "MYSQL_PORT": "3306",
    "MYSQL_USER": "test",
    "MYSQL_PASSWORD": "test",
    "MYSQL_DATABASE": "testdb",
}, clear=False):
    # Suppress print during tests
    with patch("builtins.print"):
        from mcp_server import (
            SqlAgentArgs,
            SqlAgentResponse,
            TokenUsage,
            _dump_model,
            _mysql_uri,
            _RATE_LIMIT_STORE,
            build_sql_system_prompt,
            sql_agent,
        )


class TestSqlAgentArgs:
    """SqlAgentArgs validation."""

    def test_question_required(self):
        args = SqlAgentArgs(question="test")
        assert args.question == "test"

    def test_stream_default_false(self):
        args = SqlAgentArgs(question="test")
        assert args.stream is False

    def test_stream_true(self):
        args = SqlAgentArgs(question="test", stream=True)
        assert args.stream is True

    def test_rate_limit_optional(self):
        args = SqlAgentArgs(question="test")
        assert args.rate_limit is None

    def test_rate_limit_valid(self):
        args = SqlAgentArgs(question="test", rate_limit=10)
        assert args.rate_limit == 10


class TestMysqlUri:
    """_mysql_uri with mocked env."""

    @patch.dict(os.environ, {
        "MYSQL_HOST": "localhost",
        "MYSQL_PORT": "3306",
        "MYSQL_USER": "test",
        "MYSQL_PASSWORD": "test",
        "MYSQL_DATABASE": "testdb",
    }, clear=False)
    def test_mysql_uri_format(self):
        uri = _mysql_uri()
        assert uri == "mysql+pymysql://test:test@localhost:3306/testdb"


class TestBuildSqlSystemPrompt:
    """build_sql_system_prompt."""

    def test_includes_db_name(self):
        prompt = build_sql_system_prompt(db_name="mydb")
        assert "mydb" in prompt

    def test_includes_top_k(self):
        prompt = build_sql_system_prompt(db_name="x")
        assert "5" in prompt  # top_k=5

    def test_no_dml_instruction(self):
        prompt = build_sql_system_prompt(db_name="x")
        assert "INSERT" in prompt or "DML" in prompt
        assert "DO NOT" in prompt or "Never" in prompt


class TestDumpModel:
    """_dump_model for Pydantic v1/v2."""

    def test_dumps_to_dict(self):
        args = SqlAgentArgs(question="q")
        d = _dump_model(args)
        assert isinstance(d, dict)
        assert d["question"] == "q"


class TestSqlAgent:
    """sql_agent tool with mocked agent and callback."""

    @patch("mcp_server.get_openai_callback")
    @patch("mcp_server.get_agent")
    def test_success_returns_ok_response(self, mock_get_agent, mock_callback):
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {"output": "Here are 3 job titles."}

        mock_cb = MagicMock()
        mock_cb.prompt_tokens = 100
        mock_cb.completion_tokens = 50
        mock_cb.total_tokens = 150
        mock_cb.total_cost = 0.001
        mock_callback.return_value.__enter__ = MagicMock(return_value=mock_cb)
        mock_callback.return_value.__exit__ = MagicMock(return_value=False)

        mock_get_agent.return_value = mock_agent

        args = SqlAgentArgs(question="List 5 jobs")
        result = asyncio.run(sql_agent(args))

        assert result["ok"] is True
        assert result["answer"] == "Here are 3 job titles."
        assert result["question"] == "List 5 jobs"
        assert result["error"] is None
        assert "request_id" in result
        assert result["token_usage"]["prompt_tokens"] == 100
        assert result["token_usage"]["completion_tokens"] == 50
        assert "version" in result

    @patch("mcp_server.get_agent")
    def test_exception_returns_error_response(self, mock_get_agent):
        mock_get_agent.side_effect = ValueError("OPENAI_API_KEY is required")

        args = SqlAgentArgs(question="test")
        result = asyncio.run(sql_agent(args))

        assert result["ok"] is False
        assert result["answer"] == ""
        assert "ValueError" in result["error"]
        assert result["token_usage"] is None

    @patch("mcp_server.get_openai_callback")
    @patch("mcp_server.get_agent")
    def test_stream_mode_returns_events(self, mock_get_agent, mock_callback):
        async def mock_astream(*args, **kwargs):
            yield {"actions": [MagicMock(tool="sql_db_list_tables")]}
            yield {"steps": [MagicMock(action=MagicMock(tool="sql_db_list_tables"))]}
            yield {"output": "Tables: job_descriptions, salaries"}

        mock_agent = MagicMock()
        mock_agent.astream = mock_astream

        mock_cb = MagicMock()
        mock_cb.prompt_tokens = 80
        mock_cb.completion_tokens = 40
        mock_cb.total_tokens = 120
        mock_cb.total_cost = 0.0008
        mock_callback.return_value.__enter__ = MagicMock(return_value=mock_cb)
        mock_callback.return_value.__exit__ = MagicMock(return_value=False)

        mock_get_agent.return_value = mock_agent

        args = SqlAgentArgs(question="List tables", stream=True)
        result = asyncio.run(sql_agent(args))

        assert result["ok"] is True
        assert result["answer"] == "Tables: job_descriptions, salaries"
        assert "streamed_events" in result
        assert len(result["streamed_events"]) >= 2
        assert any(e["type"] == "action" for e in result["streamed_events"])
        assert any(e["type"] == "step" for e in result["streamed_events"])

    @patch("mcp_server.get_agent")
    def test_rate_limit_exceeded(self, mock_get_agent):
        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {"output": "ok"}
        mock_get_agent.return_value = mock_agent

        _RATE_LIMIT_STORE.clear()
        args = SqlAgentArgs(question="q1", rate_limit=1)
        r1 = asyncio.run(sql_agent(args))
        assert r1["ok"] is True

        args2 = SqlAgentArgs(question="q2", rate_limit=1)
        r2 = asyncio.run(sql_agent(args2))
        assert r2["ok"] is False
        assert "Rate limit exceeded" in r2["error"]
        assert mock_get_agent.call_count == 1
