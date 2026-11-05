const DASH = "—";
const DEFAULT_TZ = "Asia/Kolkata";

export function formatPhone(number: string): string {
  const m = /^\+91(\d{2})(\d{4})(\d{4})$/.exec(number);
  return m ? `+91 ${m[1]} ${m[2]} ${m[3]}` : number;
}

const pad = (n: number) => String(n).padStart(2, "0");

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return DASH;
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${m}:${pad(s % 60)}`;
}

type Parts = { y: number; mo: number; d: number; h: number; mi: number; mon: string };

const formatters = new Map<string, Intl.DateTimeFormat>();

/** One formatter per time zone and month style: building them is slow and the call table formats many cells. */
function formatterFor(tz: string, month: "short" | "numeric"): Intl.DateTimeFormat {
  const key = `${tz}|${month}`;
  let f = formatters.get(key);
  if (!f) {
    f = new Intl.DateTimeFormat("en-US", { timeZone: tz, year: "numeric", month, day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
    formatters.set(key, f);
  }
  return f;
}

function partsIn(date: Date, tz: string): Parts {
  const read = (month: "short" | "numeric") =>
    formatterFor(tz, month)
      .formatToParts(date)
      .reduce<Record<string, string>>((acc, p) => ({ ...acc, [p.type]: p.value }), {});
  const named = read("short");
  const numeric = read("numeric");
  return { y: +named.year, mo: +numeric.month, d: +named.day, h: +named.hour, mi: +named.minute, mon: named.month };
}

/** The calendar date "now" falls on in `tz`, as YYYY-MM-DD. */
export function todayIn(tz: string = DEFAULT_TZ, now: Date = new Date()): string {
  const p = partsIn(now, tz);
  return `${p.y}-${pad(p.mo)}-${pad(p.d)}`;
}

/** A YYYY-MM-DD date moved by `days` (negative goes back). */
export function shiftDay(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

const dayNumber = (p: Parts) => Math.floor(Date.UTC(p.y, p.mo - 1, p.d) / 86_400_000);

/** "Today 14:32", "Yesterday 09:10" or "5 Nov 14:32", in `tz`. */
export function formatWhen(iso: string | null | undefined, tz: string = DEFAULT_TZ, now: Date = new Date()): string {
  if (!iso) return DASH;
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return DASH;
  const p = partsIn(at, tz);
  const time = `${pad(p.h)}:${pad(p.mi)}`;
  const gap = dayNumber(partsIn(now, tz)) - dayNumber(p);
  if (gap === 0) return `Today ${time}`;
  if (gap === 1) return `Yesterday ${time}`;
  return `${p.d} ${p.mon} ${time}`;
}

const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? "" : "s"} ago`;

export function timeAgo(iso: string | null | undefined, now: Date = new Date(), tz: string = DEFAULT_TZ): string {
  if (!iso) return DASH;
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return DASH;
  const s = Math.floor((now.getTime() - at.getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return plural(Math.floor(s / 60), "minute");
  if (s < 86_400) return plural(Math.floor(s / 3600), "hour");
  if (s < 7 * 86_400) return plural(Math.floor(s / 86_400), "day");
  const p = partsIn(at, tz);
  return `${p.d} ${p.mon}`;
}

/** Time since `fromIso` as mm:ss, or h:mm:ss from one hour. */
export function formatElapsed(fromIso: string | null | undefined, now: Date = new Date()): string {
  if (!fromIso) return DASH;
  const from = new Date(fromIso).getTime();
  if (Number.isNaN(from)) return DASH;
  const s = Math.max(0, Math.floor((now.getTime() - from) / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${pad(m)}:${pad(s % 60)}`;
}
