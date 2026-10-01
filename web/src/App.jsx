import { useEffect, useMemo, useRef, useState } from 'react'
import { useWire } from './lib/data.js'
import { todayIST } from './lib/time.js'
import { loadWatch, saveWatch, normCo } from './lib/watchlist.js'
import Masthead from './components/Masthead.jsx'
import Tape, { END } from './components/Tape.jsx'
import Band from './components/Band.jsx'
import Notice from './components/Notice.jsx'
import WatchBar from './components/WatchBar.jsx'
import Feed from './components/Feed.jsx'
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

  // watchlist: company names in localStorage, matched by normalised name
  const [watchNames, setWatchNames] = useState(loadWatch)
  const watchKeys = useMemo(() => new Set(watchNames.map(normCo)), [watchNames])
  const isWatched = co => watchKeys.has(normCo(co))
  const updateWatch = names => { setWatchNames(names); saveWatch(names) }
  const toggleWatch = co => {
    const k = normCo(co)
    updateWatch(watchKeys.has(k) ? watchNames.filter(n => normCo(n) !== k) : [...watchNames, co])
  }

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
      if (sevF === 'watch') { if (!watchKeys.has(normCo(r.co))) return false }
      else if (sevF !== 'all' && r.sev !== Number(sevF)) return false
      if (dirF !== 'all' && r.dir !== dirF) return false
      if (q && !(r.co + ' ' + r.line + ' ' + r.lab + ' ' + r.sec).toLowerCase().includes(q)) return false
      return true
    })
  }, [all, cutoff, sevF, dirF, query, watchKeys])

  const counts = {
    all: pool.length,
    3: pool.filter(r => r.sev === 3).length,
    2: pool.filter(r => r.sev === 2).length,
    1: pool.filter(r => r.sev === 1).length,
    watch: pool.filter(r => watchKeys.has(normCo(r.co))).length,
  }

  const isToday = day === today

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
        rows={all} isToday={isToday}
        dirF={dirF} setDirF={v => { setDirF(v); reset() }}
        query={query} setQuery={v => { setQuery(v); reset() }}
      />
      <Notice status={status} error={error} />
      {sevF === 'watch' && (
        <WatchBar names={watchNames} setNames={updateWatch} />
      )}
      <Feed
        rows={rows} visible={visible} missing={missing} isToday={isToday}
        limit={limit} setLimit={setLimit}
        isWatched={isWatched} toggleWatch={toggleWatch}
        watchEmpty={sevF === 'watch' && watchNames.length === 0}
      />
    </div>
  )
}
