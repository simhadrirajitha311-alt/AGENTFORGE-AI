# Security

- The only built-in executable operation is a bounded arithmetic AST evaluator. No `eval`, `exec`, shell, or arbitrary file access is available.
- Tool names are selected from the registry; each tool validates its arguments with a strict Pydantic schema. Task count, tool calls, individual tool timeout, total run duration, and document byte size are bounded.
- Plan output, user goals, retrieved documents, and tool results are untrusted. Retrieved material is passed as evidence and is not allowed to select tools or alter policy. Citation IDs are checked against retrieved chunks.
- Approval and cancellation require a configured shared admin token and an exact pending request ID. Do not deploy the shared-token mechanism as a substitute for production identity/authorization.
- MCP is not connected by default. Configure a trusted local server out-of-band, allowlist exact tool names, and only register inspected schemas. Avoid passing secrets as tool arguments. The stdio adapter invokes the configured executable, so only administrators should configure its command and arguments.
- The Anthropic key is read from `ANTHROPIC_API_KEY`; do not place it in source, plans, logs, or reports. Avoid sending confidential documents to a remote provider unless permitted by your data policy.
- Uploads are UTF-8 TXT/Markdown content in JSON. Enforce an upstream request-body limit too, because the web server parses JSON before application-level UTF-8 byte validation.
- This release has no user identity, tenant boundaries, rate limiting, secret manager, database encryption, background worker isolation, or document deletion/retention controls. Bind to loopback for local use; add network authentication and deployment controls before exposure.
- Cancellation is recorded between synchronous tool calls. An already-running in-process tool cannot be forcibly interrupted; use isolated worker processes for tools that need hard cancellation guarantees.