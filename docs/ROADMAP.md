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
| Web research | Search and read the web; run code; make spreadsheets and documents | Claude usage (+$0.01 per search) |
| Browser | Sandboxed browser for sites that allow automation | Free |
| Gmail | Send approved email; read and summarise your inbox; save reply drafts | Free |
| Important-email alerts | Phone push (and Telegram) when important mail arrives | Free |
| Google Calendar | See when you're busy, add approved events with invitations | Free |
| Google Drive | Save results as Google Docs, Sheets or files | Free |
| Reminders & repeating jobs | "Remind me at 6", "every Monday summarise my inbox" | Free |
| Telegram | Chat with your assistant from Telegram; alerts arrive there too | Free |
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

## Never automatic, by design

Sending, booking, paying, trading and publishing always wait for your approval. Money
actions need the owner, and the emergency stop halts everything at once.
