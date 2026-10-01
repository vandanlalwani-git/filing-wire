import { useEffect, useRef, useState } from 'react'

const POLL_MS = 60 * 1000

// GitHub Pages lets browsers keep files for up to 10 minutes. 'no-cache'
// makes the browser ask the server every time; an unchanged file costs a
// tiny "not modified" reply, a changed one arrives straight away.
async function getJson(url) {
  const r = await fetch(url, { cache: 'no-cache' })
  if (r.status === 404) return { missing: true }
  if (!r.ok) throw new Error('HTTP ' + r.status)
  return { data: await r.json() }
}

/**
 * Live data for one day: the day's filings, the list of days in the record
 * book, and status.json. Everything re-fetches every 60 seconds; new filings
 * appear without a reload.
 */
export function useWire(day) {
  const [rows, setRows] = useState(null)        // null = still loading
  const [missing, setMissing] = useState(false)
  const [days, setDays] = useState([])
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)
  const dayRef = useRef(day)
  dayRef.current = day

  useEffect(() => {
    let alive = true
    setRows(null); setMissing(false)

    async function tick() {
      try {
        const [st, idx, d] = await Promise.all([
          getJson('./data/status.json'),
          getJson('./data/days/index.json'),
          getJson(`./data/days/${day}.json`),
        ])
        if (!alive || dayRef.current !== day) return
        if (st.data) setStatus(st.data)
        if (idx.data) setDays(idx.data.days || [])
        if (d.missing) { setMissing(true); setRows([]) }
        else {
          setMissing(false)
          // severity 0 is "noise - raw feed only" in the taxonomy; v5 never shows it
          setRows((d.data.rows || []).filter(r => r.sev >= 1))
        }
        setError(null)
      } catch (e) {
        if (alive) setError(e.message || 'network error')   // keep showing what we have
      }
    }

    tick()
    const id = setInterval(tick, POLL_MS)
    return () => { alive = false; clearInterval(id) }
  }, [day])

  return { rows, missing, days, status, error }
}
