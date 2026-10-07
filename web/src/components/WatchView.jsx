import { useEffect, useMemo, useState } from 'react'
import Details from './Details.jsx'
import { shardOf, initials } from '../lib/companies.js'
import { normCo } from '../lib/watchlist.js'
import { fmtShort } from '../lib/time.js'

const DIR_LABEL = { negative: 'Adverse', positive: 'Favourable', neutral: 'Unclassified' }
const POLL_MS = 60 * 1000
const FIRST = 5          // filings shown per company before "Show all"

/**
 * The Watchlist tab: every watched company, with its filings from the last
 * 30 days. Each company's filings come from data/recent/<n>.json, one small
 * file per group of companies, so a watchlist of 10 companies downloads
 * about 30 KB however many days it covers.
 */
export default function WatchView({ entries, dayRows, dirF, today, onRemove }) {
  const shards = useMemo(
    () => [...new Set(entries.filter(e => e.k).map(e => shardOf(e.k)))].sort((a, b) => a - b),
    [entries])
  const [recent, setRecent] = useState({})          // key -> [[day, t, sev, dir, lab, line, id], ...]
  const [state, setState] = useState('loading')
  const shardKey = shards.join(',')

  useEffect(() => {
    let alive = true
    async function tick() {
      try {
        const parts = await Promise.all(shards.map(n =>
          fetch(`./data/recent/${n}.json`, { cache: 'no-cache' })
            .then(r => (r.ok ? r.json() : r.status === 404 ? {} : Promise.reject(new Error('HTTP ' + r.status))))))
        if (!alive) return
        setRecent(Object.assign({}, ...parts))
        setState('ready')
      } catch {
        if (alive) setState(s => (s === 'ready' ? 'ready' : 'error'))   // keep what we have
      }
    }
    tick()
    const id = setInterval(tick, POLL_MS)
    return () => { alive = false; clearInterval(id) }
  }, [shardKey])                                     // eslint-disable-line react-hooks/exhaustive-deps

  // expanded rows; details come from that day's details file, loaded on first use
  const [open, setOpen] = useState(() => new Set())
  const [det, setDet] = useState({})                 // day -> { state, rows }
  const loadDay = async day => {
    setDet(d => ({ ...d, [day]: { state: 'loading', rows: null } }))
    try {
      const r = await fetch(`./data/details/${day}.json`, { cache: 'no-cache' })
      if (!r.ok) throw new Error('HTTP ' + r.status)
      const j = await r.json()
      setDet(d => ({ ...d, [day]: { state: 'ready', rows: j.rows || {} } }))
    } catch {
      setDet(d => ({ ...d, [day]: { state: 'error', rows: null } }))
    }
  }
  const toggle = (id, day) => {
    const willOpen = !open.has(id)
    setOpen(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
    const d = det[day]
    if (willOpen && (!d || d.state === 'error' || (d.state === 'ready' && !d.rows[id]))) loadDay(day)
  }
  const [all, setAll] = useState(() => new Set())   // companies showing every filing

  const items = entries.map(e => {
    let list
    if (e.k) list = recent[e.k] || []
    else {
      // a name the directory could not identify: only the day on screen can be searched by name
      const nk = normCo(e.n)
      list = (dayRows || []).filter(r => normCo(r.co) === nk).reverse()
        .map(r => [r.ts.slice(0, 10), r.t, r.sev, r.dir, r.lab, r.line, r.id])
    }
    if (dirF !== 'all') list = list.filter(x => x[3] === dirF)
    return { e, list }
  })
  // most recent filing first; companies with nothing (yet) at the end, A to Z
  items.sort((a, b) => {
    const la = a.list[0], lb = b.list[0]
    if (la && lb) return (lb[0] + lb[1]).localeCompare(la[0] + la[1])
    if (la || lb) return la ? -1 : 1
    return a.e.n.localeCompare(b.e.n)
  })

  if (!entries.length) {
    return (
      <div id="feed">
        <div id="empty">Your watchlist is empty. Search any listed company and tap ☆, tap ☆ on a filing, or import a CSV.</div>
      </div>
    )
  }

  return (
    <div id="feed" className="watchview">
      <div className="wv-note">
        Filings from the last 30 days{dirF !== 'all' ? ` · ${DIR_LABEL[dirF]} only` : ''}
        {state === 'loading' && ' · loading…'}
        {state === 'error' && ' · could not load past filings, retrying'}
      </div>
      {items.map(({ e, list }) => {
        const id = e.k || 'n:' + e.n
        const showAll = all.has(id)
        const shown = showAll ? list : list.slice(0, FIRST)
        const codes = [e.s && 'NSE ' + e.s, e.b && 'BSE ' + e.b].filter(Boolean).join(' · ')
        return (
          <section key={id} className="wco">
            <div className="wco-head">
              <span className="badge" aria-hidden="true">{initials(e.n)}</span>
              <div className="wco-id">
                <div className="wco-name">{e.n}</div>
                <div className="wco-codes">{codes || (e.k ? e.k : 'Matched by name')}</div>
              </div>
              <button className="star on" title="Remove from watchlist"
                aria-label={'Remove ' + e.n + ' from watchlist'} onClick={() => onRemove(e)}>★</button>
            </div>
            {!list.length && (
              <div className="wco-none">
                {state === 'loading' && e.k ? 'Loading…'
                  : dirF !== 'all' ? 'No ' + DIR_LABEL[dirF].toLowerCase() + ' filings in the last 30 days'
                  : 'No filings yet — they’ll appear here'}
              </div>
            )}
            {shown.map(([day, t, sev, dir, lab, line, rid]) => {
              const isOpen = open.has(rid)
              const d = det[day]
              const st = !d ? 'loading' : d.state === 'ready' && !d.rows[rid] ? 'error' : d.state
              return (
                <div key={rid} className={`entry s${sev} ${dir}${isOpen ? ' open' : ''}`}
                  onClick={() => toggle(rid, day)}>
                  <div className="e-time">
                    <span className="e-day">{day === today ? 'Today' : fmtShort(day)}</span>
                    <span>{t}</span>
                  </div>
                  <div className="e-mark"><b></b></div>
                  <div className="e-sum" role="button" tabIndex={0} aria-expanded={isOpen}
                    onKeyDown={ev => {
                      if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); toggle(rid, day) }
                    }}>
                    <div className="e-meta">
                      <div className="e-tags">
                        <span className={'dirmark ' + dir}>{DIR_LABEL[dir] || 'Unclassified'}</span>
                        <span className="tag">{lab}</span>
                      </div>
                      <span className="e-chev" aria-hidden="true">{isOpen ? '−' : '+'}</span>
                    </div>
                    <div className="e-line">{line}</div>
                  </div>
                  <div></div>
                  {isOpen && (
                    <div className="e-xwrap">
                      <Details d={d && d.rows && d.rows[rid]} today={today} state={st} />
                    </div>
                  )}
                </div>
              )
            })}
            {list.length > FIRST && (
              <div className="wco-more" role="button" tabIndex={0}
                onClick={() => setAll(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })}>
                {showAll ? 'Show fewer' : `Show all ${list.length} filings`}
              </div>
            )}
          </section>
        )
      })}
      <div id="foot">Disclosure events only, classified by fixed rules. Not investment advice. Source: BSE and NSE public filings.</div>
    </div>
  )
}

