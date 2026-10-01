import { nowIST, minutesSince, agoText } from '../lib/time.js'

const STALE_MIN = 45
const WEEKDAYS = new Set(['Mon', 'Tue', 'Wed', 'Thu', 'Fri'])

function lastGood(iso) {
  // "2026-10-02 14:05:00" -> "14:05" today, or "1 Oct 14:05" earlier
  if (!iso) return null
  const [d, t] = iso.split(' ')
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' }).format(new Date())
  if (d === today) return t.slice(0, 5)
  const dd = new Date(d + 'T00:00:00Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' })
  return dd + ' ' + t.slice(0, 5)
}

/** A small, calm notice - only when the data is late or an exchange failed. */
export default function Notice({ status, error }) {
  const lines = []
  if (status?.updated_utc) {
    const mins = minutesSince(status.updated_utc)
    const { weekday, minutes } = nowIST()
    if (WEEKDAYS.has(weekday) && minutes >= 9 * 60 && minutes < 18 * 60 && mins > STALE_MIN) {
      lines.push(`Updates are running late — the last one was ${agoText(mins)}. New filings will appear when it catches up.`)
    }
    for (const name of ['BSE', 'NSE']) {
      const ex = status.exchanges?.[name]
      if (ex && ex.ok === false) {
        const when = lastGood(ex.last_ok_ist)
        lines.push(`${name} could not be reached in the last update.` +
          (when ? ` Its filings are shown as of ${when}.` : ''))
      }
    }
  }
  if (error && !lines.length) lines.push('Could not refresh just now. Showing the last data received.')
  if (!lines.length) return null
  return (
    <div id="notice" role="status">
      <span className="nl">Notice</span>
      <span>{lines.join(' ')}</span>
    </div>
  )
}
