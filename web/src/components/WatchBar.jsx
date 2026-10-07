import { useState } from 'react'
import { parseWatchCsv, mergeEntries } from '../lib/watchlist.js'
import { loadCompanies, resolve, entryOf } from '../lib/companies.js'

/** Shown on the Watchlist tab: count, CSV import, clear, and any note about
 *  the one-time conversion of an old watchlist. */
export default function WatchBar({ entries, setEntries, note, clearNote }) {
  const [msg, setMsg] = useState('')

  async function onFile(e) {
    const file = e.target.files && e.target.files[0]
    e.target.value = ''
    if (!file) return
    setMsg('Reading…')
    let text, dir
    try {
      [text, dir] = await Promise.all([file.text(), loadCompanies()])
    } catch {
      setMsg('Could not read that file, or the company list did not load. Please try again.')
      return
    }
    const { found, unrecognised } = parseWatchCsv(text, v => resolve(dir, v))
    const { list, added } = mergeEntries(entries, found.map(entryOf))
    setEntries(list)
    const dupes = new Set(found.map(c => c.k)).size - added.length
    let m = `Added ${added.length} compan${added.length === 1 ? 'y' : 'ies'}`
    if (dupes) m += ` · ${dupes} already on the list`
    if (unrecognised.length) {
      m += ` · ${unrecognised.length} row${unrecognised.length === 1 ? '' : 's'} not recognised: ` +
        unrecognised.slice(0, 8).join(', ') + (unrecognised.length > 8 ? '…' : '')
    }
    if (!found.length && !unrecognised.length) {
      m = 'No companies found. Use a .csv with a Symbol, ISIN, BSE code or company name column.'
    }
    setMsg(m)
  }

  return (
    <div id="watchbar">
      <span className="wb-count">{entries.length} {entries.length === 1 ? 'company' : 'companies'} watched</span>
      <label>
        Import CSV
        <input type="file" accept=".csv,text/csv,text/plain" onChange={onFile} />
      </label>
      {entries.length > 0 && (
        <button onClick={() => {
          if (window.confirm('Remove every company from your watchlist?')) { setEntries([]); setMsg('') }
        }}>Clear</button>
      )}
      {msg && <span className="wb-msg">{msg}</span>}
      {note && (
        <span className="wb-msg wb-note">
          {note} <button onClick={clearNote}>OK</button>
        </span>
      )}
    </div>
  )
}
