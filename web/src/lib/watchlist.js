// The watchlist lives only in this browser (localStorage). Every access is
// wrapped: private windows and some browsers throw on storage access.
const KEY = 'fw_watchlist'

export function loadWatch() {
  try { return JSON.parse(localStorage.getItem(KEY) || '[]') } catch { return [] }
}
export function saveWatch(names) {
  try { localStorage.setItem(KEY, JSON.stringify(names)) } catch { /* not available */ }
}

/** Company-name key, same rule as the collector's norm_name(): so
 *  "ACME Solar Holdings" and "Acme Solar Holdings Limited" are one company. */
export const normCo = s =>
  (s || '').toLowerCase()
    .replace(/\b(ltd|limited|the)\b/g, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()

function splitCsvLine(line) {
  const out = []; let cur = ''; let q = false
  for (let i = 0; i < line.length; i++) {
    const c = line[i]
    if (q) {
      if (c === '"' && line[i + 1] === '"') { cur += '"'; i++ }
      else if (c === '"') q = false
      else cur += c
    } else if (c === '"') q = true
    else if (c === ',' || c === ';' || c === '\t') { out.push(cur); cur = '' }
    else cur += c
  }
  out.push(cur)
  return out.map(x => x.trim())
}

/**
 * Read a CSV of company names or trading symbols (one per row, or a column
 * headed Company / Name / Symbol / Instrument ...). Symbols are turned into
 * company names using the exchange's own list.
 * Returns { names: [...], unrecognised: [...] }
 */
export function parseWatchCsv(text, symbols) {
  const rows = text.split(/\r?\n/).map(splitCsvLine).filter(r => r.some(Boolean))
  if (!rows.length) return { names: [], unrecognised: [] }
  const head = rows[0].map(h => h.toLowerCase())
  let col = head.findIndex(h => /company|name|security/.test(h))
  if (col < 0) col = head.findIndex(h => /symbol|instrument|scrip|stock|ticker|tradingsymbol/.test(h))
  const hasHeader = col >= 0
  if (col < 0) col = 0
  const names = [], unrecognised = []
  for (const r of rows.slice(hasHeader ? 1 : 0)) {
    const v = (r[col] || '').replace(/^"|"$/g, '').trim()
    if (!v || /^[\d.,\s-]+$/.test(v)) continue
    const sym = v.toUpperCase().replace(/-(EQ|BE|BZ|SM|ST)$/, '')
    if (symbols && symbols[sym]) names.push(symbols[sym])
    else if (/^[A-Z0-9&.\-]+$/.test(v) && !v.includes(' ')) unrecognised.push(v)
    else names.push(v)
  }
  return { names, unrecognised }
}
