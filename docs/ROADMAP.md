# What your assistant can do, and what to add next

Cost key: **Free**: no charge. **Free tier**: free up to a daily or monthly limit.
**Per use**: you pay only when it's used. **Paid**: monthly or one-time fee.
Prices change; check each provider before switching something on.

## Already built

| Hands | What it does | Cost |
|---|---|---|
| Chat assistant (web + phone) | Typing, dictation, hands-free voice conversation, its own name, memory, private chats | Claude usage (capped per day) |
| Voice | Device voices, or a natural voice built into the web app (one-time ~90 MB download) | Free |
| Photos & PDFs | Send a bill, form or screenshot and the assistant reads it | Claude usage |
| Workforce tasks | Chief plans, specialist agents work, a verifier checks, you approve | Claude usage |
| Self-improving workforce | Every night: clone strong agents (clones learn from the checker's feedback and inherit lessons), trial clones on supervised work, promote or retire them, pause then retire weak agents; morning digest | Claude usage (small) |
| Web research | Search and read the web; run code; make spreadsheets and documents | Claude usage (+$0.01 per search) |
| Browser | Sandboxed browser for sites that allow automation | Free |
| Gmail | Send approved email; read and summarise your inbox; save reply drafts | Free |
| Important-email alerts | Phone push (and Telegram) when important mail arrives | Free |
| Google Calendar | See when you're busy, add approved events with invitations | Free |
| Google Drive | Save results as Google Docs, Sheets or files | Free |
| Reminders & repeating jobs | "Remind me at 6", "every Monday summarise my inbox" | Free |
| Telegram | Chat with your assistant from Telegram; alerts arrive there too | Free |
| WhatsApp (your normal app) | The assistant writes the message; your WhatsApp opens with it filled in; you tap Send | Free |
| WhatsApp (business number) | Send approved messages | Free tier (Meta) |
| Slack | Post approved messages | Free |
| GitHub + Vercel | Build a website and publish it at a `*.vercel.app` address | Free tier |
| Pictures | Posters and illustrations (your own Cloudflare account, ~230 a day free); logos, icons and diagrams as SVG | Free tier / Free |
| Cabs, food, shopping, tickets | Agents find options and prepare the link; you confirm and pay in the app | Free |
| Safety | Approvals for anything sent, booked or paid; emergency stop; audit log; encrypted keys | Free |

## Suggested next: free or nearly free

| # | Add | Why it helps | Cost | Effort |
|---|---|---|---|---|
| 1 | **Morning briefing** (preset repeating job) | Each morning: today's calendar, important mail, weather, top news, reminders. In chat, Telegram or push | Free | Small |
| 2 | **Watch & alert** (price, page, stock, train seats) | "Tell me when this phone drops below ₹20,000." The tool exists but isn't switched on yet | Free | Small |
| 3 | **Weather, maps & directions** (Open-Meteo, OpenStreetMap) | Plans trips and commutes without paid map keys | Free | Small |
| 4 | **Expenses from receipts** | Photo or Gmail receipt → a row in your Google Sheet, with a monthly summary | Free | Small |
| 5 | **Google Contacts** | "Email Rahul" finds the right Rahul; birthdays become reminders | Free | Small |
| 6 | **WhatsApp incoming messages** | Alerts when someone important messages your business number; replies drafted for approval | Free tier | Medium |
| 7 | **Outlook / Microsoft 365** mail and calendar | Same as Gmail for people on Outlook | Free | Medium |
| 8 | **Notion** pages and databases | Save notes, plans and research where you already work | Free | Small |
| 9 | **Netlify / Cloudflare Pages** deploy | More free website hosts, custom domains | Free tier | Small |
| 10 | **Android app builds** (Expo EAS) | "Make me an app": an installable Android build | Free tier + Play Console ($25 once) | Medium |
| 11 | **Supabase backend for built apps** | Apps the workforce builds get a real database and login | Free tier | Medium |
| 12 | **Short videos** from pictures + natural voiceover (FFmpeg) | Reels, ads and explainers without paid video AI | Free | Medium |
| 13 | **Natural voice on the phone** (on-device Kokoro) | The same human-like voice on the phone app (332 MB download per language, iOS 17+) | Free | Medium (needs real-phone testing) |
| 14 | **Better speech-to-text on the phone** (on-device Whisper) | More accurate voice input in Indian accents and Hinglish | Free | Medium |
| 15 | **Email newsletters / bulk email** (Brevo) | Send approved campaigns to your list | Free tier (300 a day) | Small |
| 16 | **Payment links** (Razorpay) | Agents prepare a payment link or invoice for you to approve and send | Per use (fee per payment) | Small |
| 17 | **Smart home** (Home Assistant) | "Turn off the AC at 11", "is the door locked?" | Free | Small |
| 18 | **Team / family workspace** | Invite people; shared tasks; one assistant each | Free | Medium |

## Bigger or paid (when you're ready)

| Add | Why | Cost |
|---|---|---|
| **Billing** (Razorpay on web; App Store / Play billing in the apps) | Let people pay for plans, so heavy use isn't on you | Payment fees |
| **AI phone calls** (book a table, follow up a vendor) | The assistant calls on your behalf, with approval | Per minute |
| **SMS** (Exotel, MSG91, Twilio) | Texts to people without WhatsApp or Telegram | Per message |
| **AI video generation** (Veo, Runway, Kling) | Realistic generated video | Per video |
| **Stock trading** (broker API, e.g. Zerodha Kite Connect) | Research and alerts first; orders only with owner approval and compliance review | Broker fees |
| **Flight booking** (Duffel) | Real bookings with approval | Per booking |
| **Social posting** (LinkedIn, Instagram, X) | Approved posts on your accounts | Free to paid; each network reviews apps |
| **iPhone app on the App Store** | Publish built apps for iPhone | Apple Developer $99 a year |
| **Google verification for Gmail reading** | Needed before more than 100 people can connect their inbox | Security assessment fee (yearly) |

## Ideas from Meta's Muse agent (Sept 2026), compared with ours

| Muse has | We have | What to add | Cost |
|---|---|---|---|
| Runs long tasks in the background with sub-agents | ✅ Chief + specialist agents, background worker | — | — |
| Asks before sending or buying | ✅ Approvals, Face ID for money, emergency stop | — | — |
| Name, avatar and communication style | 🟡 Name and voice | **Avatar picture and personality** (friendly / formal / Hinglish, short or detailed) | Free |
| Read-only vs full-action access per app ("Sentinel") | 🟡 Per-service connections | **A read-only / can-act switch on every connection** | Free |
| Goals view and project side-chats | 🟡 Tasks and chats | **Goals** ("find a 2BHK in Pune under ₹25k", "save ₹50k by March") with a plan, progress and check-ins; **Projects** grouping chats, files and tasks | Free |
| Watch the agent's browser live | 🟡 Sandboxed browser, results only | **Live view** of what the agent is doing, with a Stop button | Free |
| Artifacts: documents, trackers, dashboards, web pages | 🟡 Files, Docs, Sheets, websites | **Live trackers and dashboards** (expenses, job applications, habits) that update themselves | Free |
| Its own email address | ❌ | **maya@yourdomain**: forward or CC email to your assistant and it acts on it | Free tier |
| Phone calls to businesses | ❌ | **AI phone calls** with clear disclosure ("I'm Asha's AI assistant") and your approval | Per minute |
| Shopping and travel through partner stores | 🟡 Prepares links | Partner checkouts where official APIs exist (Shopify stores, ONDC in India, Duffel flights) | Per use |
| Realtime video avatar | ❌ | **Talking avatar** in voice mode (lip-synced picture) | Free (simple) to per minute (realistic) |
| Mac app control, smart glasses, a pocket device | ❌ | **"Hey Siri / Hey Google, ask Maya"** shortcuts and home-screen widgets first; a desktop companion that controls your computer later | Free → Medium |

Lessons from Muse's problems:
- Amazon blocked Muse for browsing without saying it was an AI. Ours must always identify itself
  when browsing or calling, and never store passwords or card numbers (it doesn't today).
- Muse's shared chats leaked. If we add sharing, use unguessable links that expire, and let
  people revoke them.

## More ideas

**Easier to use**
- **Share to your assistant from any app** (Android/iPhone share sheet): a screenshot,
  link, PDF or WhatsApp message becomes "do something with this". Free; high value.
- **Proactive nudges**: "Your flight is tomorrow and check-in is open", "Electricity bill due
  Friday", "Rahul's birthday today". Built from your mail, calendar and memory. Free.
- **Meeting notes**: record a meeting and get the transcript, summary and action items as
  tasks and reminders. Speech-to-text runs on the device for free.
- **Hindi and regional-language app screens**, not just voice. Free.
- **Data controls**: export everything, delete everything, and see what it remembers. Free.

**India-first**
- **UPI payment links**: "Pay ₹500 to Ramesh". Opens GPay, PhonePe or Paytm with the
  amount filled in; you confirm. Free; works like the WhatsApp links.
- **Bills and renewals**: due dates read from email and SMS, with reminders before late
  fees (insurance, rent, EMIs). Free.
- **Grocery and pharmacy lists**: list → Blinkit, Zepto, BigBasket or 1mg, ready to order. Free.
- **Trains and flights**: PNR and flight status, itinerary from booking emails into your
  calendar automatically. Free tier.
- **For small shops and freelancers**: GST invoices, payment follow-ups on WhatsApp, a
  simple customer list, and a daily sales summary. Free.

**Life admin**
- **Document reminders**: passport, licence, insurance and PUC expiry (dates only, never the
  documents' numbers). Free.
- **Health**: medicine reminders, doctor appointment links, lab reports summarised in plain
  language (not medical advice). Free.
- **Job search**: tailor your CV per job, track applications, prepare for interviews. Free.
- **Learning**: a tutor for children or language practice in voice mode. Claude usage.
- **Family workspace**: shared grocery lists, a family calendar and chores. Free.

**Workforce power**
- **Skills / templates**: one-tap setups such as "Shop owner", "Student", "Freelancer",
  "Home manager". Free.
- **Usage and cost dashboard** per person (needed for billing). Free.

## Never automatic, by design

Sending, booking, paying, trading and publishing always wait for your approval. Money
actions need the owner, and the emergency stop halts everything at once.
