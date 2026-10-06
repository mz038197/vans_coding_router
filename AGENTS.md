# Agent instructions

Read `CONTEXT.md` before changing domain language. Record durable design decisions in `docs/adr/`.

## Agent skills

Skills live in `.agents/skills/` (Matt Pocock's set). Invoke them with `/skill-name` (for example `/grill-with-docs`, `/tdd`, `/ask-matt`).

### Issue tracker

GitHub Issues via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` plus `docs/adr/`. See `docs/agents/domain.md`.

## Cursor Cloud specific instructions

The Cloud Agent image provides `uv` and Node.js 22 on `/usr/local/bin`, plus CPython 3.13 for `uv`. Run Python through `uv run`. The system `python3` may remain 3.12.

Boot copies `config/router.example.yaml` to `~/.vans_coding_router/router.yaml` when that file is missing, then serves `uv run uvicorn app:app --host 0.0.0.0 --port 8000` with `VCR_CONFIG` pointed at that file and `PUBLIC_URL=http://127.0.0.1:8000`. It skips startup when `http://127.0.0.1:8000/health` already responds. The process does not use `--reload`; stop the port 8000 listener before starting another one after code changes.

Dev login in the example config accepts only loopback. Open `http://127.0.0.1:8000/portal`. Portal writes require `Origin: http://127.0.0.1:8000`. The example admin email `mz038197@gmail.com` receives admin, teacher, and student.

`uv run pytest -q` is the test command. Five Postgres repository tests skip unless `TEST_DATABASE_URL` is set. Day-to-day development uses the SQLite file in `~/.vans_coding_router/` and does not start Docker. Portal login, classes, and class sessions do not need upstream API keys. Forwarding chat, image, or speech calls needs `OLLAMA_CLOUD_API_KEY`, `OPENROUTER_API_KEY`, and/or `OPENAI_API_KEY`.
