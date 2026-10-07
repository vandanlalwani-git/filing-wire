import { useEffect, useMemo, useRef, useState } from 'react'
import { useWire } from './lib/data.js'
import { todayIST } from './lib/time.js'
import { loadWatch, saveWatch, loadNote, saveNote, normCo, mergeEntries, convertLegacy } from './lib/watchlist.js'
import { loadCompanies, resolve, entryOf } from './lib/companies.js'
import Masthead from './components/Masthead.jsx'
import Tape, { END } from './components/Tape.jsx'
import Band from './components/Band.jsx'
import Notice from './components/Notice.jsx'
import WatchBar from './components/WatchBar.jsx'
import Feed from './components/Feed.jsx'
import WatchView from './components/WatchView.jsx'
import { toMin } from './lib/time.js'

export default function App() {
  const [today, setToday] = useState(todayIST())
  const [day, setDay] = useState(today)
  const { rows, missing, days, status, error } = useWire(day)

  // filters - same state and defaults as v5
  const [sevF, setSevF] = useState('all')
  const [dirF, setDirF] = useState('all')
  const [query, setQuery] = useState('')
  const [cutoff, setCutoff] = useState(END)
  const [limit, setLimit] = useState(100)

  // watchlist: companies by ISIN in localStorage (see lib/watchlist.js)
  const [watch, setWatch] = useState(loadWatch)
  const [note, setNote] = useState(loadNote)
  // until an old name list is converted, its names keep working as before
  const entries = useMemo(() => watch.legacy ? watch.legacy.map(n => ({ n })) : watch.entries, [watch])
  const keySet = useMemo(() => new Set(entries.filter(e => e.k).map(e => e.k)), [entries])
  const nameSet = useMemo(() => new Set(entries.filter(e => !e.k).map(e => normCo(e.n))), [entries])
  const isWatched = r => (r.k && keySet.has(r.k)) || nameSet.has(normCo(r.co))
  const isWatchedKey = k => keySet.has(k)
  const updateWatch = list => { setWatch({ entries: list, legacy: null }); saveWatch(list) }
  const addEntry = e => {
    updateWatch(mergeEntries(entries, [e]).list)
    // fill in the NSE symbol and BSE code, for the Watchlist tab
    if (e.k && !e.s && !e.b) {
      loadCompanies().then(dir => {
        const c = dir.byKey.get(e.k)
        if (c) setWatch(w => {
          const list = w.entries.map(x => (x.k === e.k ? { ...entryOf(c), n: x.n } : x))
          saveWatch(list)
          return { entries: list, legacy: null }
        })
      }).catch(() => {})
    }
  }
  const removeEntry = e => updateWatch(entries.filter(x => (e.k ? x.k !== e.k : x.k || normCo(x.n) !== normCo(e.n))))
  const toggleWatch = r => {
    if (isWatched(r)) updateWatch(entries.filter(x => !((r.k && x.k === r.k) || (!x.k && normCo(x.n) === normCo(r.co)))))
    else addEntry(r.k ? { k: r.k, n: r.co } : { n: r.co })
  }
  const toggleCompany = c => (keySet.has(c.k) ? removeEntry({ k: c.k }) : addEntry(entryOf(c)))
  const clearNote = () => { setNote(''); saveNote('') }

  // a clock for "Updated N min ago", and the roll-over at IST midnight
  const [, setTick] = useState(0)
  const todayRef = useRef(today)
  useEffect(() => {
    const id = setInterval(() => {
      setTick(t => t + 1)
      const t = todayIST()
      if (t !== todayRef.current) {
        const prev = todayRef.current
        todayRef.current = t
        setToday(t)
        setDay(d => (d === prev ? t : d))      // follow "today" only if we were on it
      }
    }, 30 * 1000)
    return () => clearInterval(id)
  }, [])

  // a new day or a filter change starts from the top, like v5
  const reset = () => setLimit(100)
  useEffect(() => { setCutoff(END); reset() }, [day])

  const all = rows || []
  const pool = useMemo(() => all.filter(r => toMin(r.t) <= cutoff), [all, cutoff])
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return all.filter(r => {
      if (toMin(r.t) > cutoff) return false
      if (sevF !== 'all' && sevF !== 'watch' && r.sev !== Number(sevF)) return false
      if (dirF !== 'all' && r.dir !== dirF) return false
      if (q && !(r.co + ' ' + r.line + ' ' + r.lab + ' ' + r.sec).toLowerCase().includes(q)) return false
      return true
    })
  }, [all, cutoff, sevF, dirF, query])

  const counts = {
    all: pool.length,
    3: pool.filter(r => r.sev === 3).length,
    2: pool.filter(r => r.sev === 2).length,
    1: pool.filter(r => r.sev === 1).length,
    watch: pool.filter(isWatched).length,
  }

  const isToday = day === today

  // one-time conversion of an old name-based watchlist to company IDs
  useEffect(() => {
    if (!watch.legacy || rows === null) return
    let alive = true
    loadCompanies().then(dir => {
      if (!alive) return
      const fromRows = new Map((rows || []).filter(r => r.k).map(r => [normCo(r.co), r.k]))
      const { entries: list, unmatched } = convertLegacy(watch.legacy, v => resolve(dir, v), entryOf, fromRows)
      updateWatch(list)
      const n = watch.legacy.length
      const msg = unmatched.length
        ? `Watchlist upgraded: ${n - unmatched.length} of ${n} companies now matched by ISIN. ` +
          `Could not identify ${unmatched.length}: ${unmatched.join(', ')} (kept, matched by name).`
        : `Watchlist upgraded: all ${n} companies now matched by ISIN.`
      setNote(msg); saveNote(msg)
    }).catch(() => {})                     // try again on the next load
    return () => { alive = false }
  }, [watch.legacy, rows === null])        // eslint-disable-line react-hooks/exhaustive-deps

  // expanded rows; their details load from a separate file on first use
  const [open, setOpen] = useState(() => new Set())
  const [det, setDet] = useState({ day: null, rows: null, state: 'idle' })
  useEffect(() => { setOpen(new Set()); setDet({ day: null, rows: null, state: 'idle' }) }, [day])
  const loadDetails = async () => {
    setDet(d => ({ ...d, day, state: 'loading' }))
    try {
      const r = await fetch(`./data/details/${day}.json`, { cache: 'no-cache' })
      if (!r.ok) throw new Error('HTTP ' + r.status)
      const j = await r.json()
      setDet({ day, rows: j.rows || {}, state: 'ready' })
    } catch {
      setDet({ day, rows: null, state: 'error' })
    }
  }
  const toggle = id => {
    const willOpen = !open.has(id)
    setOpen(prev => {
      const n = new Set(prev)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })
    // first expand of the day, a retry after an error, or a row newer than the loaded file
    if (willOpen && (det.day !== day || det.state === 'error' || det.state === 'idle' ||
                     (det.state === 'ready' && !det.rows[id]))) loadDetails()
  }

  return (
    <div id="shell">
      <div id="perf"></div>
      <Masthead
        day={day} today={today} days={days} setDay={setDay} isToday={isToday}
        status={status} counts={counts}
        sevF={sevF} setSevF={v => { setSevF(v); reset() }}
      />
      <Tape rows={all} cutoff={cutoff} setCutoff={c => { setCutoff(c); reset() }} />
      <Band
        rows={all} isToday={isToday} today={today}
        dirF={dirF} setDirF={v => { setDirF(v); reset() }}
        query={query} setQuery={v => { setQuery(v); reset() }}
        onPickFiling={c => { setQuery(c); reset(); if (sevF === 'watch') setSevF('all') }}
        isWatchedKey={isWatchedKey} toggleCompany={toggleCompany}
      />
      <Notice status={status} error={error} />
      {sevF === 'watch' ? (
        <>
          <WatchBar entries={entries} setEntries={updateWatch} note={note} clearNote={clearNote} />
          <WatchView entries={entries} dayRows={all} dirF={dirF} today={today} onRemove={removeEntry} />
        </>
      ) : (
        <Feed
          rows={rows} visible={visible} missing={missing} isToday={isToday}
          limit={limit} setLimit={setLimit}
          isWatched={isWatched} toggleWatch={toggleWatch}
          open={open} toggle={toggle} details={det.rows} detState={det.state} today={today}
        />
      )}
    </div>
  )
}
