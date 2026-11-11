export const ACTION_LABEL: Record<string, string> = {
  send_email: 'Send email',
  send_whatsapp: 'Send WhatsApp',
  calendar_create_event: 'Create calendar event',
  post_social: 'Publish post',
  deploy_web: 'Deploy website',
  book_flight: 'Book flight',
  place_stock_order: 'Place stock order',
  play_store_release: 'Release on Play Store',
  app_store_submit: 'Submit to App Store',
  browser_submit_form: 'Submit web form',
};

export const FIELD_LABEL: Record<string, string> = {
  to: 'To',
  subject: 'Subject',
  body: 'Message',
  message: 'Message',
  text: 'Text',
  network: 'Network',
  title: 'Title',
  start: 'Starts',
  end: 'Ends',
  symbol: 'Stock',
  side: 'Buy/Sell',
  quantity: 'Quantity',
  order_type: 'Order type',
  amount: 'Amount',
  currency: 'Currency',
  url: 'Website',
  fields: 'Form details',
  attendees: 'Invites',
  location: 'Location',
  description: 'Notes',
  duration_minutes: 'Duration (minutes)',
  timezone: 'Time zone',
  offer_id: 'Offer',
};

export function fieldLabel(key: string): string {
  return FIELD_LABEL[key] ?? key.replaceAll('_', ' ');
}

const WHEN_FIELDS = new Set(['start', 'end']);

export function fieldValue(v: unknown, key?: string): string {
  if (typeof v === 'string' && key && WHEN_FIELDS.has(key)) {
    const d = new Date(v);
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleString('en-IN', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
    }
  }
  if (typeof v === 'string') return v;
  if (v && typeof v === 'object') {
    return Object.entries(v as Record<string, unknown>)
      .map(([k, val]) => `${k}: ${String(val)}`)
      .join('\n');
  }
  return String(v);
}

export function expiresIn(iso: string): string {
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return 'expired';
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  return h >= 1 ? `${h}h ${m}m left` : `${m}m left`;
}

export function formatMoney(amount: string, currency: string | null): string {
  const n = Number(amount);
  if (!Number.isFinite(n)) return `${amount} ${currency ?? ''}`.trim();
  try {
    return currency
      ? new Intl.NumberFormat('en-IN', { style: 'currency', currency }).format(n)
      : new Intl.NumberFormat('en-IN').format(n);
  } catch {
    return `${n.toLocaleString('en-IN')} ${currency ?? ''}`.trim();
  }
}

/** Payload fields to list (amount/currency are shown separately, large). */
const FIELD_ORDER = ['title', 'to', 'subject', 'start', 'end', 'duration_minutes', 'timezone', 'location', 'attendees', 'network', 'message', 'text', 'body', 'description'];

export function detailEntries(payload: Record<string, unknown>, hasAmount: boolean): [string, unknown][] {
  const rank = (k: string) => (FIELD_ORDER.includes(k) ? FIELD_ORDER.indexOf(k) : FIELD_ORDER.length);
  return Object.entries(payload)
    .filter(([k]) => !(hasAmount && (k === 'amount' || k === 'currency')))
    .sort(([a], [b]) => rank(a) - rank(b));
}

/** Text fields the owner may reword before approving (matches the API). */
export const EDITABLE_FIELDS = new Set(['subject', 'body', 'message', 'text', 'title', 'caption', 'description']);

/** Badge for a decided approval, honest about whether the action actually happened. */
export function decidedBadge(status: string, execution: string | null): [string, 'ok' | 'warn' | 'info' | 'muted' | 'bad'] {
  if (status === 'rejected') return ['Declined', 'muted'];
  if (status === 'expired') return ['Expired', 'bad'];
  if (status === 'invalidated') return ['Cancelled (changed)', 'bad'];
  if (status === 'approved') return ['Approved · running', 'info'];
  return execution === 'succeeded' ? ['Approved · done', 'ok'] : ['Approved · not done', 'warn'];
}

/** Which connected service an approved action needs. */
export const ACTION_SERVICE: Record<string, { provider: string; name: string }> = {
  send_email: { provider: 'gmail', name: 'Gmail' },
  calendar_create_event: { provider: 'google_calendar', name: 'Google Calendar' },
};

export const TIMEZONES: { zone: string; label: string }[] = [
  { zone: 'Asia/Kolkata', label: 'India (IST)' },
  { zone: 'Asia/Dubai', label: 'Dubai (GST)' },
  { zone: 'Asia/Singapore', label: 'Singapore' },
  { zone: 'Europe/London', label: 'London' },
  { zone: 'Europe/Berlin', label: 'Berlin / Paris' },
  { zone: 'America/New_York', label: 'New York' },
  { zone: 'America/Los_Angeles', label: 'Los Angeles' },
  { zone: 'Australia/Sydney', label: 'Sydney' },
  { zone: 'UTC', label: 'UTC' },
];
