# MCP SQL Agent – Test Cases

Examples for calling the `sql_agent` tool via JSON-RPC over HTTP. Use `-N` for no buffering (streaming) and `-sS` for silent + show errors.

Input schema: `data/schema/input_schema.json`
---

### Local (uvicorn on localhost:8000)

**Input:** JSON-RPC `tools/call` request – `question` (natural language), `rate_limit` (optional, max requests/min)
```
curl -N -sS "http://localhost:8000/mcp/" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "sql_agent",
      "arguments": {
        "args": {
          "question": "List 5 job titles in Ventura",
          "rate_limit": 10
        }
      }
    }
  }'
```

**Output:** SSE `event: message` with `result.structuredContent.result` containing `ok`, `answer`, `token_usage`, `error`
```
{
  "event": "message",
  "data": {
    "jsonrpc": "2.0",
    "id": 2,
    "result": {
      "content": [
        {
          "type": "text",
          "text": {
            "ok": true,
            "request_id": "cd3c4209-532a-4050-8f4e-e0a71b1ef632",
            "model": "gpt-4o-mini",
            "latency_ms": 7262,
            "question": "List 5 job titles in Ventura",
            "answer": "Here are 3 job titles in Ventura:\n\n1. Apcd Public Information Specialist\n2. Assistant Chief Probation Officer\n3. Appraiser Trainee\n\n(Note: Only 3 titles were found in the database.)",
            "token_usage": {
              "prompt_tokens": 4453,
              "completion_tokens": 191,
              "total_tokens": 4644,
              "total_cost_usd": 0.00070575
            },
            "error": null
          }
        }
      ],
      "structuredContent": {
        "result": {
          "ok": true,
          "request_id": "cd3c4209-532a-4050-8f4e-e0a71b1ef632",
          "model": "gpt-4o-mini",
          "latency_ms": 7262,
          "question": "List 5 job titles in Ventura",
          "answer": "Here are 3 job titles in Ventura:\n\n1. Apcd Public Information Specialist\n2. Assistant Chief Probation Officer\n3. Appraiser Trainee\n\n(Note: Only 3 titles were found in the database.)",
          "token_usage": {
            "prompt_tokens": 4453,
            "completion_tokens": 191,
            "total_tokens": 4644,
            "total_cost_usd": 0.00070575
          },
          "error": null
        }
      }
    },
    "isError": false
  }
}
```


---

### Fly.io (https://mcp-tool-sql-v2-{env}.fly.dev — env: dev | qa | prod)

**Input:** Same JSON-RPC format, different base URL
```
curl -N -sS "https://mcp-tool-sql-v2-dev.fly.dev/mcp/" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc":"2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "sql_agent",
      "arguments": {
        "args": {
          "question": "List 5 job titles in Ventura",
          "rate_limit": 10
        }
      }
    }
  }'
```

**Output:** Same structure as local
```
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\n  \"ok\": true,\n  \"request_id\": \"a3245938-c4a8-4182-8feb-3fa41e212c55\",\n  \"model\": \"gpt-4o-mini\",\n  \"latency_ms\": 17084,\n  \"question\": \"List 5 job titles in Ventura\",\n  \"answer\": \"Here are 3 job titles in Ventura:\\n\\n1. Appraiser Trainee\\n2. Assistant Chief Probation Officer\\n3. Apcd Public Information Specialist\",\n  \"token_usage\": {\n    \"prompt_tokens\": 4327,\n    \"completion_tokens\": 178,\n    \"total_tokens\": 4505,\n    \"total_cost_usd\": 0.00075585\n  },\n  \"error\": null\n}"
      }
    ],
    "structuredContent": {
      "result": {
        "ok": true,
        "request_id": "a3245938-c4a8-4182-8feb-3fa41e212c55",
        "model": "gpt-4o-mini",
        "latency_ms": 17084,
        "question": "List 5 job titles in Ventura",
        "answer": "Here are 3 job titles in Ventura:\n\n1. Appraiser Trainee\n2. Assistant Chief Probation Officer\n3. Apcd Public Information Specialist",
        "token_usage": {
          "prompt_tokens": 4327,
          "completion_tokens": 178,
          "total_tokens": 4505,
          "total_cost_usd": 0.00075585
        },
        "error": null
      }
    },
    "isError": false
  }
}
```


**Input:** Aggregation query (highest average by jurisdiction)
```
curl -N -sS "https://mcp-tool-sql-v2-dev.fly.dev/mcp/" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc":"2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "sql_agent",
      "arguments": {
        "args": {
          "question": "Which jurisdiction has the highest average amount, and what is that amount?",
          "rate_limit": 3
        }
      }
    }
  }'
```

```
curl -N -sS "https://mcp-tool-sql-v2-qa.fly.dev/mcp/" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc":"2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "sql_agent",
      "arguments": {
        "args": {
          "question": "Which jurisdiction has the highest average amount, and what is that amount?",
          "rate_limit": 3
        }
      }
    }
  }'
```

```
curl -N -sS "https://mcp-tool-sql-v2-prod.fly.dev/mcp/" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc":"2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
      "name": "sql_agent",
      "arguments": {
        "args": {
          "question": "Which jurisdiction has the highest average amount, and what is that amount?",
          "rate_limit": 3
        }
      }
    }
  }'
```