// Everything the screen says about dates and times is in IST, whatever the
// visitor's own time zone is.
const IST = 'Asia/Kolkata'

const DAY_FMT = new Intl.DateTimeFormat('en-CA', {
  timeZone: IST, year: 'numeric', month: '2-digit', day: '2-digit',
})
const PARTS_FMT = new Intl.DateTimeFormat('en-GB', {
  timeZone: IST, weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
})

/** Today's date in IST, as YYYY-MM-DD. */
export const todayIST = () => DAY_FMT.format(new Date())

/** Weekday and minutes-past-midnight right now in IST. */
export function nowIST() {
  const p = Object.fromEntries(PARTS_FMT.formatToParts(new Date()).map(x => [x.type, x.value]))
  return { weekday: p.weekday, minutes: Number(p.hour) * 60 + Number(p.minute) }
}

/** "2026-10-01" -> "1 October 2026" (same wording as v5). */
export const fmtDay = d =>
  new Date(d + 'T00:00:00Z').toLocaleDateString('en-GB', {
    day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC',
  })

/** Whole minutes since an ISO UTC timestamp. */
export const minutesSince = iso => Math.max(0, Math.floor((Date.now() - Date.parse(iso)) / 60000))

/** "3 min ago", "just now", "2 h ago" */
export function agoText(mins) {
  if (mins < 1) return 'just now'
  if (mins < 90) return `${mins} min ago`
  const h = Math.round(mins / 60)
  return h < 48 ? `${h} h ago` : `${Math.round(h / 24)} days ago`
}

export const toMin = t => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5))

export function fmtMin(m) {
  const h = Math.floor(m / 60), mm = Math.round(m % 60)
  return String(h).padStart(2, '0') + ':' + String(mm).padStart(2, '0')
}

/** "2026-10-06" -> "6 Oct" */
export const fmtShort = d =>
  new Date(d + 'T00:00:00Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' })
