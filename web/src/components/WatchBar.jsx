import { useState } from 'react'
import { parseWatchCsv, normCo } from '../lib/watchlist.js'

/** Shown when the Watchlist count is selected: count, CSV import, clear. */
export default function WatchBar({ names, setNames }) {
  const [msg, setMsg] = useState('')

  async function onFile(e) {
    const file = e.target.files && e.target.files[0]
    e.target.value = ''
    if (!file) return
    try {
      const [text, symbols] = await Promise.all([
        file.text(),
        fetch('./data/symbols.json', { cache: 'no-cache' }).then(r => (r.ok ? r.json() : {})).catch(() => ({})),
      ])
      const { names: found, unrecognised } = parseWatchCsv(text, symbols)
      const have = new Set(names.map(normCo))
      const add = []
      for (const n of found) {
        const k = normCo(n)
        if (k && !have.has(k)) { have.add(k); add.push(n) }
      }
      setNames([...names, ...add])
      let m = `Added ${add.length} compan${add.length === 1 ? 'y' : 'ies'}`
      if (found.length - add.length) m += ` · ${found.length - add.length} already on the list`
      if (unrecognised.length) {
        m += ` · ${unrecognised.length} symbol${unrecognised.length === 1 ? '' : 's'} not recognised: ` +
          unrecognised.slice(0, 6).join(', ') + (unrecognised.length > 6 ? '…' : '')
      }
      setMsg(m)
    } catch {
      setMsg('Could not read that file. Use a .csv with one company name or symbol per row.')
    }
  }

  return (
    <div id="watchbar">
      <span className="wb-count">{names.length} {names.length === 1 ? 'company' : 'companies'} watched</span>
      <label>
        Import CSV
        <input type="file" accept=".csv,text/csv,text/plain" onChange={onFile} />
      </label>
      {names.length > 0 && (
        <button onClick={() => {
          if (window.confirm('Remove every company from your watchlist?')) { setNames([]); setMsg('') }
        }}>Clear</button>
      )}
      {msg && <span className="wb-msg">{msg}</span>}
    </div>
  )
}
