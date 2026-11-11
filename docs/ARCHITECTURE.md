# Architecture and roadmap

Based on *Autonomous AI Workforce OS — Infrastructure Blueprint v1.0*, with the
review changes listed at the end.

## The idea

You give one instruction. A **Chief AI Executive** plans it, hands parts to
**department heads**, whose **specialist agents** do the work with real tools.
A separate **QA Verifier** checks the result. Anything that spends money, sends
something, or publishes needs your approval first. Work keeps going in the
background when you close the app.

```
You (owner) — type or speak (12 languages incl. Hindi, Marathi, Tamil, Telugu, Bengali)
 └── Chief AI Executive ──── QA Verifier (independent)
      ├── General Task Agent   → anything no department covers (safe tools only)
      ├── Personal Executive   → Email, Calendar, WhatsApp messaging
      ├── Research & BD        → Web research
      ├── Travel & Reservations→ Flights, Rides & tickets
      ├── Shopping, Food       → Orders, Price watch
      ├── Financial Intel      → Market analyst, Order preparation
      ├── Software Factory     → Engineer, Release (web, Play Store, App Store)
      ├── Marketing & Content  → Content writer, Social media
      └── Operations, Data     → Data analyst, Documents, Web forms
```

The command screen lists everything the workforce can do (`capabilities.py`),
with how each is handled: *does it for you*, *asks before sending*, *needs your
approval* or *you confirm in app*. That label is computed from the tools' risk
tiers, so the screen can never promise more than the policy engine allows.

"Do whatever I ask" comes from general-purpose tools rather than a fixed menu:
web search and fetch, a sandboxed browser, sandboxed code execution (data
analysis, charts, Word/Excel/PowerPoint/PDF), and long-term memory. Anything
that sends, spends or publishes goes through the specialist that owns it.

Defined in `packages/core/src/workforce_core/workforce.py`.

## Components

| Layer | What | Where |
|---|---|---|
| Web app | Command center (typing + voice), task board, workforce, integrations, audit; installable on phones | `apps/web` (Next.js) |
| API | Tasks, workforce lifecycle, kill switch, audit; Supabase JWT auth | `apps/api` (FastAPI) |
| Domain core | State machine, policy engine, approvals, tool registry, lifecycle rules | `packages/core` |
| Database | Postgres + Auth via Supabase; RLS; append-only logs | `supabase/migrations` |
| Workers | Plan → do → verify pipeline, agent browser, tool gateway, memory | `apps/worker` |
| Mobile app | Android + iPhone (Expo): voice, tasks, files, workforce, memory, push alerts | `apps/mobile` |

## Safety model

**Risk tiers** (`policy.py`): every tool has one.

| Tier | Examples | Default |
|---|---|---|
| 0 Read | web search, market data | runs automatically |
| 1 Internal write | drafts, reports, memory | runs automatically |
| 2 External commitment | send email, deploy web, prepare booking | needs your approval |
| 3 Financial / high impact | book flight, stock order, store release | needs **owner** approval; can't be loosened |
| 4 Destructive | change credentials, delete prod data | denied; can't be loosened |

The policy engine is plain code. The AI proposes actions; it never decides
whether they are allowed.

**Approvals** bind to the exact action: amount, currency, recipient, item,
account, expiry, task and policy version are hashed. If anything changes, the
approval no longer matches and a new one is needed (`approvals.py`).

**Tasks** follow a state machine enforced in the database. A task can only
reach `completed` from `verifying`. Every status change is logged.

**Audit log, task events and approval events** are append-only, enforced by
database triggers that apply to every role.

**Kill switch** stops everything for the workspace.

## How a task runs (phase 2)

```
instruction ─► Chief plans (Claude, structured output, uses your memories)
            ─► each step: specialist agent tool loop through the Tool Gateway
                 web_search / web_fetch (Claude server tools), browse_page (sandboxed browser),
                 recall / remember, create_report, prepare_booking_link
                 tier ≥2 actions → approval request (exact-action hash), never executed directly
            ─► QA Verifier: automated checks (files exist, CSV rows, duplicates) + independent review
                 fail → one rework round with the verifier's feedback → else failed
            ─► completed, or waiting_for_approval if actions were prepared
            ─► episode memory, agent evaluations (feed clone/suspend/retire)
```

- **Durability:** status and every finished step are saved in Postgres; a lease + heartbeat
  marks which worker is busy; crashed work is picked up by another worker without redoing
  finished steps; retries back off and dead-letter after 5 attempts.
- **Budgets:** each model call is costed (`llm_calls`); a task stops at its budget
  (policy default $5) and waits for you to raise it.
- **Prompt-injection defence:** web content is wrapped as untrusted data; policy is code;
  agent-written memories are never trusted as instructions.
- **Refusal fallback:** model calls opt into Anthropic's server-side fallback, so a
  safety-classifier decline is retried on the recommended fallback model.

## Approval centre

- Every action that sends, books, buys or publishes is prepared by an agent and held as an
  approval bound to its exact details (hash of recipient, amount, item, text, expiry, policy).
- The owner sees it on the **Approvals** tab (phone and web, with a badge and a push
  notification) and can **Approve**, **Decline**, or **Edit** the wording first. Recipients,
  amounts and items can't be edited there: ask the agent to prepare it again.
- The client sends back the hash it displayed; if the action changed since, or the stored row
  no longer matches its hash, the approval is refused.
- Tier 3 (money / high impact) is owner-only, and on phones needs Face ID or a fingerprint.
- Unanswered approvals expire (default 24 h).
- After the owner decides, a worker re-checks each approval, marks it used *before* running it
  (so it happens at most once), carries it out, and reports the result. If a worker stops
  mid-action, the result is "outcome unknown" and it is never repeated automatically.
- Today, web forms really submit (on the approved site). Email, WhatsApp, calendar, social,
  flights, broker orders and store releases report "not connected yet" until their
  integrations are added (next phase).

## Agent lifecycle: clone the strong, retire the weak

`lifecycle.py` + `/workforce/lifecycle-review`:

1. Agents are judged on measured outcomes (success rate, verifier quality score,
   cost per success, safety violations), and only after a minimum number of
   tasks.
2. **Strong** → a **clone** is created in `sandbox` with the same (never more)
   tools. It takes real work only after it passes its own evaluation
   (`/agents/{id}/promote`).
3. **Weak** → **suspended** (stops getting work). Still weak on the next
   review → **retired**.
4. Any safety violation → suspended immediately.
5. "Delete" means retire. Agents can't be deleted from the database, retired
   agents can't come back, and history is always kept.
6. At most 3 agents per family, so clones can't multiply without limit.
7. The Chief is never auto-cloned or auto-removed.

## Integrations: what is actually possible

See `integrations.py` and the **Integrations** page. Summary:

| Want | How | Status |
|---|---|---|
| Research | Claude web search/fetch | Official API |
| Data analysis, documents, charts | Claude code execution sandbox | Official API |
| Pages needing a real browser, web forms | Sandboxed Playwright browser | Only on sites whose terms allow automation |
| WhatsApp | WhatsApp Business Cloud API | Official API; business number + approved templates |
| Social posts | LinkedIn / X / Instagram APIs | Official API; per-network app approval |
| Google Drive / Sheets | Google APIs (OAuth) | Official API |
| Email, calendar | Gmail / Google Calendar API (OAuth) | Official API |
| Build & deploy websites | GitHub + Vercel APIs | Official API |
| Play Store / App Store | Google Play Publishing API, App Store Connect API + macOS build runner | Official API; store review applies |
| Stocks (India) | Zerodha Kite Connect (or similar broker API) | Official API, paid; SEBI algo rules apply, so research and alerts come first |
| Flights | Duffel | Official API |
| Trains | IRCTC | Authorised partners only |
| Cabs (Uber/Ola/Rapido), food (Swiggy/Zomato), movies (BookMyShow), shopping (Amazon/Flipkart) | No public consumer ordering APIs | Agent prepares, **you confirm in the app** |

Re-check each provider's current terms before enabling it.

## Roadmap

| Phase | Outcome |
|---|---|
| **1. Foundation** ✅ | Schema, auth, task API, workforce + lifecycle, audit, kill switch, web app, voice |
| **1b. Browser & memory** ✅ | Sandboxed browser; workspace + per-agent memory |
| **2. Agents at work** ✅ | Background workers; Chief plans with Claude; specialists use tools; verifier; files; held approvals |
| **3. Approvals** ✅ | Approval centre (phone + web), edit wording then approve, Face ID / fingerprint for money, at-most-once execution, expiry |
| 4. Reliability | Failure/restart tests, evaluations feeding the lifecycle, cost tracking, staging deploy |
| 5. Email & calendar | Google OAuth connections |
| **6. Mobile app** ✅ | Expo app (Android + iOS): native voice, push notifications, share files |
| **6b. Deployment** ✅ | Dockerfiles, Render blueprint, graceful worker restarts, smoke check ([DEPLOY.md](DEPLOY.md)) |
| 7. Software factory | Isolated build runners, web deploy, Play/App Store submission |
| 8. Travel & commerce | Flights via API; rides/food/movies via confirm-in-app links |
| 9. Finance | Market research and alerts, then broker orders after compliance review |

## Review changes from the original blueprint

- **Durable execution in Postgres** instead of Temporal (and no LangGraph or Redis). Workers claim
  tasks with leases (`FOR UPDATE SKIP LOCKED`), checkpoint after every step and resume after
  crashes; that covers the blueprint's reliability requirements with one less service to run.
  Revisit Temporal if long timers/schedules or very high volume make it worthwhile.
- Added tables: `policies` (versioned), `tool_definitions`, `task_events`, `llm_calls`,
  `idempotency_key` on `tool_invocations`, full approval binding fields.
- The backend connects as the table owner, so **RLS doesn't protect API queries**:
  every API query scopes by `workspace_id` explicitly. RLS protects anything reachable
  with the public browser key (read-only for members, no writes).
