import { useEffect, useMemo, useRef, useState } from 'react'
import { loadCompanies, searchCompanies, initials } from '../lib/companies.js'
import { fmtShort } from '../lib/time.js'

const CHIPS = [
  ['all', 'All'], ['negative', 'Adverse'], ['positive', 'Favourable'], ['neutral', 'Unclassified'],
]

export default function Band({ rows, isToday, today, dirF, setDirF, query, setQuery, onPickFiling,
  isWatchedKey, toggleCompany }) {
  const [open, setOpen] = useState(false)
  const wrap = useRef(null)
  const companies = useMemo(() => [...new Set(rows.map(r => r.co))].sort(), [rows])

  // the company directory is fetched the first time someone uses search
  const [dir, setDir] = useState(null)
  const [dirState, setDirState] = useState('idle')
  const wantDir = () => {
    if (dir || dirState === 'loading') return
    setDirState('loading')
    loadCompanies().then(d => { setDir(d); setDirState('ready') }).catch(() => setDirState('error'))
  }

  useEffect(() => {
    const close = e => { if (wrap.current && !wrap.current.contains(e.target)) setOpen(false) }
    document.addEventListener('click', close)
    return () => document.removeEventListener('click', close)
  }, [])

  const q = query.trim().toLowerCase()
  const hits = q ? companies.filter(c => c.toLowerCase().includes(q)).slice(0, 40) : []
  const found = useMemo(() => (dir && q ? searchCompanies(dir, query) : []), [dir, query, q])

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
        <input id="search" placeholder="Search any company, symbol or keyword…" autoComplete="off"
          value={query} type="search" enterKeyHint="search"
          onChange={e => { setQuery(e.target.value); setOpen(true); wantDir() }}
          onFocus={() => { setOpen(true); wantDir() }} />
        <div id="drop" className={open && q ? 'open' : ''}>
          <div className="dgrp">Filings {isToday ? 'today' : 'on this day'}</div>
          {q && !hits.length && (
            <div className="dopt none">
              No disclosures filed by that company {isToday ? 'today' : 'on this day'}
            </div>
          )}
          {hits.map(c => {
            const n = rows.filter(r => r.co === c).length
            const crit = rows.filter(r => r.co === c && r.sev === 3).length
            return (
              <div key={c} className="dopt" onClick={() => { onPickFiling(c); setOpen(false) }}>
                <span className="dn">{c}</span>
                <span className="dc">{n} filing{n > 1 ? 's' : ''}{crit ? ' · ' + crit + ' critical' : ''}</span>
              </div>
            )
          })}
          <div className="dgrp">Companies</div>
          {dirState === 'loading' && <div className="dopt none">Loading the list of listed companies…</div>}
          {dirState === 'error' && (
            <div className="dopt none retry" onClick={() => { setDirState('idle'); wantDir() }}>
              Could not load the company list. Tap to try again.
            </div>
          )}
          {dir && !found.length && <div className="dopt none">No listed company matches</div>}
          {found.map(c => {
            const w = isWatchedKey(c.k)
            const codes = [c.s && 'NSE ' + c.s, c.b && 'BSE ' + c.b].filter(Boolean).join(' · ')
            const last = c.last ? 'Last filing ' + (c.last === today ? 'today' : fmtShort(c.last)) : 'No recent filings'
            return (
              <div key={c.k} className="dopt dco" role="button" tabIndex={0}
                aria-label={(w ? 'Remove ' : 'Add ') + c.n + (w ? ' from' : ' to') + ' watchlist'}
                onClick={() => toggleCompany(c)}
                onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleCompany(c) } }}>
                <span className={'badge' + (w ? ' on' : '')} aria-hidden="true">{initials(c.n)}</span>
                <span className="dco-id">
                  <span className="dn">{c.n}</span>
                  <span className="dc">{codes}{c.susp ? ' · suspended' : ''} · {last}</span>
                </span>
                <span className={'star' + (w ? ' on' : '')} aria-hidden="true">{w ? '★' : '☆'}</span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
