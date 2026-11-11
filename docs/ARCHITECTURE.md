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
| Workers *(week 2)* | Durable workflows running the agents | `apps/worker` (Temporal) |
| Mobile *(phase 2)* | Native app with push notifications for approvals | `apps/mobile` (Expo) |

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
| **1. Foundation** ✅ | Schema, auth, task API, workforce + lifecycle, audit, kill switch, web app |
| 2. First working agent | Temporal worker; Chief plans with Claude; research agent uses web search; report artifact; verifier |
| 3. Approvals | Approval centre UI, approval-bound execution, notifications |
| 4. Reliability | Failure/restart tests, evaluations feeding the lifecycle, cost tracking, staging deploy |
| 5. Email & calendar | Google OAuth connections |
| 6. Mobile app | Expo app (Android + iOS) with push approvals |
| 7. Software factory | Isolated build runners, web deploy, Play/App Store submission |
| 8. Travel & commerce | Flights via API; rides/food/movies via confirm-in-app links |
| 9. Finance | Market research and alerts, then broker orders after compliance review |

## Review changes from the original blueprint

- **Temporal only** for durable execution (LangGraph dropped; it duplicates checkpointing). Redis deferred.
- Added tables: `policies` (versioned), `tool_definitions`, `task_events`, `llm_calls`,
  `idempotency_key` on `tool_invocations`, full approval binding fields.
- The backend connects as the table owner, so **RLS doesn't protect API queries**:
  every API query scopes by `workspace_id` explicitly. RLS protects anything reachable
  with the public browser key (read-only for members, no writes).
