# Workforce OS

Your AI workforce: one instruction → a Chief AI Executive delegates to specialist
agents → verified result, with your approval wherever money or commitments are involved.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design, safety model and roadmap.

**Status: phase 1 (foundation).** You can sign in, give instructions by typing
or by voice (stored as durable tasks), see everything the workforce can do,
hire the 28-agent workforce, clone/suspend/retire agents, use the kill switch and
read the audit log. Agents start executing tasks in phase 2.

Voice input uses the browser's built-in speech recognition (Chrome, Edge,
Safari, Android, iPhone). Firefox doesn't support it yet; typing still works there.

```
apps/web        Next.js web app (works on phones; add to home screen)
apps/api        FastAPI backend
packages/core   Shared domain logic (state machine, policy, approvals, workforce, lifecycle)
supabase/       Database migrations
```

## Setup

You need: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22, and a
[Supabase](https://supabase.com) project.

### 1. Supabase

1. Create a project.
2. Apply the migrations: `npx supabase link --project-ref <ref>` then `npx supabase db push`
   (or paste each file in `supabase/migrations/` into the SQL editor, in order).
3. **Authentication → Sign In / Providers**: turn **off** "Allow new users to sign up".
4. **Authentication → Users → Invite user**: invite your own email. Your workspace,
   owner role and default policy are created automatically.
5. **Authentication → URL Configuration**: add `http://localhost:3000` (and later your
   production URL) to the redirect URLs.

### 2. API

```bash
cp apps/api/.env.example apps/api/.env   # fill in DATABASE_URL and SUPABASE_URL
uv sync
cd apps/api && uv run uvicorn --factory workforce_api.main:app_factory --reload --port 8000
```

API docs: http://localhost:8000/docs

### 3. Web

```bash
cd apps/web
cp .env.example .env.local               # fill in Supabase URL + publishable key
npm install
npm run dev
```

Open http://localhost:3000, sign in with the emailed link, then go to
**Workforce → Hire initial workforce**.

## Tests

```bash
export TEST_DATABASE_URL=$(scripts/test-db.sh start)   # local throwaway Postgres
uv run pytest
uv run ruff check . && uv run ruff format --check .
cd apps/web && npm run typecheck && npm run build
```

Database tests run the real migrations, including RLS, the append-only audit log,
the task state machine and the agent clone/retire guards.
