import { useRef } from 'react'
import { fmtDay, minutesSince, agoText } from '../lib/time.js'

const STATS = [
  { f: 'all',   cls: '',   key: 'all',   label: 'Disclosures' },
  { f: '3',     cls: 'c',  key: 3,       label: 'Critical' },
  { f: '2',     cls: 'n2', key: 2,       label: 'Notable' },
  { f: '1',     cls: '',   key: 1,       label: 'Routine' },
  { f: 'watch', cls: 'w',  key: 'watch', label: 'Watchlist' },
]

export default function Masthead({ day, today, days, setDay, isToday, status, counts, sevF, setSevF }) {
  const picker = useRef(null)
  const known = days.includes(day) ? days : [...days, day].sort()
  const i = known.indexOf(day)
  const prev = i > 0 ? known[i - 1] : null
  const next = i >= 0 && i < known.length - 1 ? known[i + 1] : null
  // last time the exchanges were successfully checked (not merely attempted,
  // and not "last time something new arrived")
  const checkedAt = status?.checked_utc || status?.updated_utc
  const fresh = checkedAt ? agoText(minutesSince(checkedAt)) : null

  const openPicker = () => {
    const el = picker.current
    if (!el) return
    try { el.showPicker() } catch { el.focus(); el.click() }
  }

  return (
    <header>
      <div className="mast">
        <div>
          <h1>The Filing Wire</h1>
          <div className="kicker">
            <span className={'livedot' + (isToday ? '' : ' off')}></span>
            <span className="kdate">
              <button className="knav" onClick={() => prev && setDay(prev)} disabled={!prev}
                aria-label="Previous day">‹</button>
              <button className="knav day" onClick={openPicker} aria-label="Choose a day">
                {fmtDay(day)}
              </button>
              <button className="knav" onClick={() => next && setDay(next)} disabled={!next}
                aria-label="Next day">›</button>
              <input ref={picker} type="date" value={day}
                min={days[0]} max={today}
                onChange={e => e.target.value && setDay(e.target.value)} tabIndex={-1} aria-hidden="true" />
            </span>
            {!isToday && (
              <button className="knav today" onClick={() => setDay(today)}>Today →</button>
            )}
            {fresh && <><span className="sep">·</span><span className="fresh">Updated {fresh}</span></>}
          </div>
        </div>
      </div>
      <div className="stats">
        {STATS.map(s => (
          <div key={s.f} className={`stat ${s.cls}${sevF === s.f ? ' on' : ''}`}
            onClick={() => setSevF(s.f)} role="button" tabIndex={0}
            onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && setSevF(s.f)}>
            <div className="n">{counts[s.key]}</div>
            <div className="l">{s.label}</div>
          </div>
        ))}
      </div>
    </header>
  )
}
