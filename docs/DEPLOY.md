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
3. **Authentication → Sign In / Providers → Email**: keep Email enabled and leave
   **"Allow new users to sign up" on**, so anyone can create an account with just their
   email (each person gets their own private workspace, owner role and safety policy,
   created automatically). Turn it **off** if you want invite-only.
4. Sign in once with your own email (or **Authentication → Users → Invite user**).
5. **Authentication → Rate Limits / SMTP**: Supabase's built-in email sender only sends
   a few emails an hour. Before opening sign-up to the public, set up your own SMTP
   (e.g. Resend, Amazon SES, Brevo) under **Authentication → Emails → SMTP Settings**.
6. **Authentication → Email Templates → Magic Link**: add the 6-digit code for the
   phone app, e.g. `<p>Your code: <strong>{{ .Token }}</strong></p>` (keep the link
   for the web app).
7. **Authentication → URL Configuration**: add your web app URL (step 2 below) to
   the redirect URLs.
8. Collect these values:
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

## 5. Connect Gmail and Google Calendar

One-time setup in Google Cloud (about 10 minutes):

1. Go to **console.cloud.google.com**, create a project (e.g. "Workforce OS").
2. **APIs & Services → Library**: enable the **Gmail API** and the **Google Calendar API**.
3. **Google Auth Platform → Branding / Audience** (the OAuth consent screen):
   - User type **External**, app name "Workforce OS", your email as support contact.
   - **Data access → Add scopes** (nothing else):
     - `openid`, `.../auth/userinfo.email`
     - `.../auth/gmail.send`: *Send email on your behalf*
     - `.../auth/calendar.events.owned`: *create events on calendars you own*
     - `.../auth/calendar.freebusy`: *view your availability* (busy times only)
4. **Publishing status**: while the app is in **Testing**, add your Gmail as a *test
   user*. Google then makes the connection **expire every 7 days** (you'd have to
   reconnect weekly). To avoid that, click **Publish app**. Google shows an
   "unverified app" warning on the sign-in screen (click *Advanced → continue*); that's
   fine for your own use (up to 100 users without Google's verification).
5. **Clients → Create client → Web application**:
   - Authorized redirect URI: `https://<your-api>/connections/google/callback`
     (e.g. `https://workforce-api.onrender.com/connections/google/callback`). One URI
     serves Gmail and Calendar.
   - Copy the **Client ID** and **Client secret**.
6. Make an encryption key (keep it secret; it protects the stored Google tokens):
   `python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`
7. In Render set, on **workforce-api**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
   `GOOGLE_REDIRECT_URI` (the URI from step 5) and `TOKEN_ENCRYPTION_KEY`; on
   **workforce-worker**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and the **same**
   `TOKEN_ENCRYPTION_KEY`.
8. In the app: **Connections** (web menu, or Settings → Open Connections on the phone)
   → **Connect Gmail / Connect Google Calendar**. Sign in with Google and allow what each asks for. Each is a
   separate connection you can disconnect on its own.
9. Check your **time zone** (Settings on the phone, Connections on the web). It defaults
   to India (IST); meetings and "next Friday" use it.

What the app can and can't do:
- **Gmail:** only **send** emails, and only ones you approve. It can't read, search or
  delete your mail.
- **Calendar:** see when you're **busy** (not what your meetings are) and **add events you
  approve** to calendars you own. If an event has guests, Google emails them invitations;
  the approval card says so. Tokens are
stored encrypted; **Disconnect** revokes access at Google and deletes them. You can
also remove access anytime at myaccount.google.com → Security → Third-party connections.

## 6. Other connections (WhatsApp, Telegram, Slack, GitHub, Vercel)

Everyone connects their **own** accounts in **Connections**, only when they need them.
If a task needs a service that isn't connected, it pauses, tells them which one, and
carries on by itself once they connect it. All keys and sign-ins are checked with the
provider first, then stored encrypted with `TOKEN_ENCRYPTION_KEY` (step 5.6), so set
that key on the API and worker even if you skip Google.

**No server setup needed** (each person pastes their own key; the app shows where to
find it):

| Service | What they paste | What agents can do (after approval) |
|---|---|---|
| Telegram | Bot token from @BotFather | Message people who have started a chat with the bot |
| WhatsApp | Meta access token + phone number ID (WhatsApp Business Platform) | Message people who wrote to them in the last 24 hours |
| GitHub | Fine-grained token (Contents + Administration: read/write) | Create a repository and save the website/app files a task made |
| Vercel | Account token | Publish a website a task made, at a `*.vercel.app` address |

**Slack** uses "Sign in with Slack" and needs a one-time Slack app:

1. **api.slack.com/apps → Create New App → From scratch**.
2. **OAuth & Permissions**: redirect URL `https://<your-api>/connections/oauth/callback`;
   bot token scopes `chat:write`, `chat:write.public`, `channels:read`.
3. **Manage Distribution → Activate Public Distribution** if people outside your own
   Slack workspace should be able to connect.
4. On **workforce-api** set `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET` (Basic Information
   → App Credentials) and `OAUTH_REDIRECT_URI` (the URL from step 2).

Services without a public API (Uber, Ola, Rapido, Swiggy, Zomato, Amazon, Flipkart,
BookMyShow, IRCTC) are listed as **Opens their app**: agents find the option and prepare
a link; the person confirms and pays in that app. Services marked **Coming soon**
(Outlook, Notion, Google Drive, Play Store, App Store, brokers, flights) are not
connectable yet.

**Opening the app to the public:** Google allows 100 users on an unverified app; beyond
that, submit the app for Google's verification (Gmail send counts as a *sensitive* scope).
Slack needs public distribution (step 3). Everything else uses each person's own key.

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
| Google says `redirect_uri_mismatch` | `GOOGLE_REDIRECT_URI` must exactly match the URI in the Google client (`…/connections/google/callback`) |
| Meeting at the wrong time | Set your time zone in Settings (phone) / Connections (web) |
| A task says "waiting for you to connect …" | Open Connections, connect that service; the task resumes by itself within a few seconds |
| A service shows "Not set up on server" | Google/Slack: set their client ID/secret and redirect variables; key services: set `TOKEN_ENCRYPTION_KEY` on API and worker |
| Slack says `bad_redirect_uri` | `OAUTH_REDIRECT_URI` must exactly match the Slack app's redirect URL (`…/connections/oauth/callback`) |
| New people can't sign up | Supabase → Email provider → "Allow new users to sign up" on; set up SMTP if codes don't arrive |
| Gmail or Calendar stops working after a week | The Google app is still in *Testing*; publish it (step 5.4) and reconnect |
| Task waiting with "Reconnect Gmail" | Access was revoked or expired: Connections → Reconnect Gmail; the task then continues |
| No push notifications | Real phone + development/store build (not Expo Go), notifications allowed, FCM/APNs credentials set in EAS |
