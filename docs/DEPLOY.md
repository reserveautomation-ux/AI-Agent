# Deploy Workforce OS

This puts the whole system online so the phone app works from anywhere:

```
Phone app / Web app ──► Workforce API ──► Supabase (Postgres + sign-in)
                                            ▲
                          Agent worker ─────┘──► Claude API, websites, Expo push
```

| Piece | Where | Notes |
|---|---|---|
| Database + sign-in | Supabase | Choose the **Mumbai (ap-south-1)** region |
| API | Render web service (Docker) | `apps/api/Dockerfile` |
| Agent worker | Render background worker (Docker) | `apps/worker/Dockerfile`, includes Chromium |
| Web app | Render web service (Node) | `apps/web` (Vercel also works) |
| Phone app | Expo EAS builds | see `apps/mobile/README.md` |

All services are defined in `render.yaml`. The Dockerfiles also run unchanged on
Railway, Fly.io, AWS, Google Cloud or your own server.

Render's background workers and always-on services are paid plans, and the worker
needs about 1–2 GB of memory for its browser. Check current prices on Render and
Anthropic before you start; you can set a per-task budget in the app.

---

## 1. Supabase (database and sign-in)

1. Create a project at supabase.com (region: Mumbai).
2. Apply the database migrations from your computer:
   ```bash
   npx supabase login
   npx supabase link --project-ref <your-project-ref>
   npx supabase db push
   ```
3. **Authentication → Sign In / Providers → Email**: keep Email enabled and turn
   **off** "Allow new users to sign up" so only you (and people you invite) get in.
4. **Authentication → Users → Invite user**: invite your own email. Your workspace,
   owner role and default safety policy are created automatically.
5. **Authentication → Email Templates → Magic Link**: add the 6-digit code for the
   phone app, e.g. `<p>Your code: <strong>{{ .Token }}</strong></p>` (keep the link
   for the web app).
6. **Authentication → URL Configuration**: add your web app URL (step 2 below) to
   the redirect URLs.
7. Collect these values:
   - **Project URL** `https://<ref>.supabase.co`
   - **Publishable (anon) key**: safe in apps; row-level security protects data
   - **Database connection string**: Connect → *Session pooler* (port 5432).
     This is a secret: only the API and worker get it.

## 2. Render (API, worker, web app)

1. Push this repository to GitHub (already done if you're reading this there).
2. Render Dashboard → **New → Blueprint** → choose the repository. Render reads
   `render.yaml` and asks for each secret:

| Service | Variable | Value |
|---|---|---|
| workforce-api | `DATABASE_URL` | Supabase session pooler string |
| workforce-api | `SUPABASE_URL` | `https://<ref>.supabase.co` |
| workforce-api | `CORS_ORIGINS` | `["https://workforce-web.onrender.com"]` (your web URL) |
| workforce-worker | `DATABASE_URL` | same as the API |
| workforce-worker | `ANTHROPIC_API_KEY` | from console.anthropic.com |
| workforce-web | `NEXT_PUBLIC_SUPABASE_URL` | `https://<ref>.supabase.co` |
| workforce-web | `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | publishable key |
| workforce-web | `NEXT_PUBLIC_API_URL` | `https://workforce-api.onrender.com` (your API URL) |

3. Deploy. When all three are live, run the check:
   ```bash
   scripts/smoke.sh https://workforce-api.onrender.com https://workforce-web.onrender.com
   ```
4. Optional: add your own domain (e.g. `api.yourdomain.com`) in each service's
   Settings, then update `CORS_ORIGINS`, `NEXT_PUBLIC_API_URL` and the Supabase
   redirect URL to match.

Every push to the branch Render watches redeploys automatically. When the worker
redeploys it hands its current task back, and the new worker resumes it from its
last finished step.

## 3. Phone app

In `apps/mobile/.env`:

```
EXPO_PUBLIC_SUPABASE_URL=https://<ref>.supabase.co
EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<publishable key>
EXPO_PUBLIC_API_URL=https://workforce-api.onrender.com
```

Then build with EAS (`apps/mobile/README.md`). For store builds, set the same three
values as EAS environment variables (`npx eas-cli@latest env:create`) so cloud
builds get them.

## 4. First run

1. Open the web or phone app and sign in with your email.
2. **Workforce → Hire initial workforce**.
3. Give your first instruction, e.g. *"Find 20 well-reviewed vegetarian restaurants in
   Pune with phone numbers, as a spreadsheet"*. Watch it move from planned to
   running to verifying to completed, then open or share the file.
4. On the phone: **Settings → Turn on notifications**, then close the app and give
   another instruction from the web; you should get a push when it finishes.

## 5. Connect Gmail (so approved emails are really sent)

One-time setup in Google Cloud (about 10 minutes):

1. Go to **console.cloud.google.com**, create a project (e.g. "Workforce OS").
2. **APIs & Services → Library**: enable the **Gmail API**.
3. **Google Auth Platform → Branding / Audience** (the OAuth consent screen):
   - User type **External**, app name "Workforce OS", your email as support contact.
   - **Data access → Add scopes**: `openid`, `.../auth/userinfo.email` and
     `.../auth/gmail.send` (*Send email on your behalf*). Nothing else.
4. **Publishing status**: while the app is in **Testing**, add your Gmail as a *test
   user*. Google then makes the connection **expire every 7 days** (you'd have to
   reconnect weekly). To avoid that, click **Publish app**. Google shows an
   "unverified app" warning on the sign-in screen (click *Advanced → continue*); that's
   fine for your own use (up to 100 users without Google's verification).
5. **Clients → Create client → Web application**:
   - Authorized redirect URI: `https://<your-api>/connections/gmail/callback`
     (e.g. `https://workforce-api.onrender.com/connections/gmail/callback`).
   - Copy the **Client ID** and **Client secret**.
6. Make an encryption key (keep it secret; it protects the stored Google tokens):
   `python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`
7. In Render set, on **workforce-api**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
   `GOOGLE_REDIRECT_URI` (the URI from step 5) and `TOKEN_ENCRYPTION_KEY`; on
   **workforce-worker**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and the **same**
   `TOKEN_ENCRYPTION_KEY`.
8. In the app: **Settings → Connect Gmail** (phone) or **Integrations → Connect Gmail**
   (web), sign in with Google and allow *Send email on your behalf*.

What the app can and can't do with Gmail: it can only **send** emails, and only ones you
approve on the Approvals screen. It can't read, search or delete your mail. Tokens are
stored encrypted; **Disconnect** revokes access at Google and deletes them. You can
also remove access anytime at myaccount.google.com → Security → Third-party connections.

## Keeping it safe

- Secrets live only in Render and Supabase settings, never in git or the apps.
- Only the worker holds the Claude key; only the API and worker hold the database string.
- **Settings → Stop all agents** (or the web's *Stop all*) halts every agent at once.
- The default budget is $5 per task (change it in the policy or per task).
- Back up: Supabase → Database → Backups (enable point-in-time recovery on paid plans).

## Troubleshooting

| Symptom | Fix |
|---|---|
| Web shows "Configuration needed" | Set the `NEXT_PUBLIC_*` variables and redeploy the web service |
| Web can sign in but every call fails | `CORS_ORIGINS` must contain the exact web URL (with `https://`, no trailing slash) |
| Tasks stay in *Draft* | Worker not running, or missing `ANTHROPIC_API_KEY`; check the worker logs |
| `prepared statement … does not exist` | Use the session pooler (5432) string |
| Phone app can't connect | `EXPO_PUBLIC_API_URL` must be the public `https://` API URL |
| "Gmail isn't set up on the server" | Set the Google variables and `TOKEN_ENCRYPTION_KEY` on the API and worker, redeploy |
| Google says `redirect_uri_mismatch` | `GOOGLE_REDIRECT_URI` must exactly match the URI in the Google client |
| Gmail stops working after a week | The Google app is still in *Testing*; publish it (step 5.4) and reconnect |
| Approved email says "Reconnect Gmail" | Access was revoked or expired: Settings → Reconnect Gmail, then ask again |
| No push notifications | Real phone + development/store build (not Expo Go), notifications allowed, FCM/APNs credentials set in EAS |
