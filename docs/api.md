# API

Start locally with `uvicorn app.main:app --reload`. FastAPI's interactive OpenAPI UI is at `/docs` and JSON schema at `/openapi.json`.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/health` | Process health |
| GET | `/ready` | SQLite readiness |
| POST | `/api/v1/runs` | Plan and execute a goal |
| GET | `/api/v1/runs/{run_id}` | Read run status |
| GET | `/api/v1/runs/{run_id}/plan` | Read validated plan |
| GET | `/api/v1/runs/{run_id}/events` | Read execution trace |
| GET | `/api/v1/runs/{run_id}/report` | Read JSON report and Markdown |
| POST | `/api/v1/knowledge/documents` | Ingest TXT/Markdown text |
| POST | `/api/v1/knowledge/search` | Search stored chunks |
| GET | `/api/v1/tools` | List registered tool schemas |
| POST | `/api/v1/runs/{run_id}/approve` | Resolve the exact pending approval |
| POST | `/api/v1/runs/{run_id}/cancel` | Cancel a non-terminal run |

Local mode assumes a trusted loopback caller. Approval and cancellation are disabled unless `AGENTFORGE_ADMIN_TOKEN` is configured; then they require `X-Admin-Token`. The service has no user authentication, tenant authorization, rate limiting, or CSRF protection and must not be exposed publicly as-is.

## Examples

```sh
curl -s http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/api/v1/runs \
  -H 'Content-Type: application/json' \
  -d '{"goal":"Calculate 12 * 8"}'
curl -s -X POST http://127.0.0.1:8000/api/v1/knowledge/documents \
  -H 'Content-Type: application/json' \
  -d '{"source_name":"guide.md","content":"Payments require manager approval."}'
curl -s -X POST http://127.0.0.1:8000/api/v1/knowledge/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"payment approval","limit":3}'
```

Run creation is synchronous: the response includes `id`, `goal`, `status`, `created_at`, `updated_at`, and optional `error`. Inspect the plan, events, and report by substituting the returned ID. Search results carry stable chunk/document IDs, a source name, metadata, text, and similarity score.