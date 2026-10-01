import { useEffect, useMemo, useRef, useState } from 'react'

const CHIPS = [
  ['all', 'All'], ['negative', 'Adverse'], ['positive', 'Favourable'], ['neutral', 'Unclassified'],
]

export default function Band({ rows, isToday, dirF, setDirF, query, setQuery }) {
  const [open, setOpen] = useState(false)
  const wrap = useRef(null)
  const companies = useMemo(() => [...new Set(rows.map(r => r.co))].sort(), [rows])

  useEffect(() => {
    const close = e => { if (wrap.current && !wrap.current.contains(e.target)) setOpen(false) }
    document.addEventListener('click', close)
    return () => document.removeEventListener('click', close)
  }, [])

  const q = query.trim().toLowerCase()
  const hits = q ? companies.filter(c => c.toLowerCase().includes(q)).slice(0, 40) : []

  return (
    <div id="band">
      <div className="chips">
        {CHIPS.map(([d, label]) => (
          <div key={d} className={'chip' + (dirF === d ? ' on' : '')}
            onClick={() => setDirF(d)} role="button" tabIndex={0}
            onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && setDirF(d)}>{label}</div>
        ))}
      </div>
      <div id="searchwrap" ref={wrap}>
        <input id="search" placeholder="Search company or keyword…" autoComplete="off"
          value={query} type="search" enterKeyHint="search"
          onChange={e => { setQuery(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)} />
        <div id="drop" className={open && q ? 'open' : ''}>
          {q && !hits.length && (
            <div className="dopt none">
              No results — no disclosures filed by that company {isToday ? 'today' : 'on this day'}
            </div>
          )}
          {hits.map(c => {
            const n = rows.filter(r => r.co === c).length
            const crit = rows.filter(r => r.co === c && r.sev === 3).length
            return (
              <div key={c} className="dopt" onClick={() => { setQuery(c); setOpen(false) }}>
                <span className="dn">{c}</span>
                <span className="dc">{n} filing{n > 1 ? 's' : ''}{crit ? ' · ' + crit + ' critical' : ''}</span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
