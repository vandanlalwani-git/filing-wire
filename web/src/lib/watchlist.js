// The watchlist lives only in this browser (localStorage). Every access is
// wrapped: private windows and some browsers throw on storage access.
//
// Since 7 Oct 2026 each entry is a company identity, not a name:
//   { k: ISIN (company key), n: name, s: NSE symbol, b: BSE code }
// Filings carry the same key (r.k), so a renamed company or a different
// spelling on BSE and NSE still matches. An old name the directory could not
// identify is kept as { n } and matched by name, as before.
const KEY = 'fw_watch2'
const OLD_KEY = 'fw_watchlist'      // the old name list; never deleted, so nothing is lost
const NOTE_KEY = 'fw_watch2_note'

function read(k, dflt) {
  try { const v = localStorage.getItem(k); return v === null ? dflt : JSON.parse(v) } catch { return dflt }
}
function write(k, v) {
  try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* not available */ }
}

/** { entries, legacy }: legacy is the old name list while it still needs converting. */
export function loadWatch() {
  const entries = read(KEY, null)
  if (Array.isArray(entries)) return { entries, legacy: null }
  const old = read(OLD_KEY, [])
  const legacy = Array.isArray(old) ? old.filter(x => typeof x === 'string' && x.trim()) : []
  return { entries: [], legacy: legacy.length ? legacy : null }
}
export function saveWatch(entries) { write(KEY, entries) }
export function loadNote() { return read(NOTE_KEY, '') }
export function saveNote(s) { write(NOTE_KEY, s) }

/** Company-name key, same rule as the collector's norm_name(): so
 *  "ACME Solar Holdings" and "Acme Solar Holdings Limited" are one company. */
export const normCo = s =>
  (s || '').toLowerCase()
    .replace(/\b(ltd|limited|the)\b/g, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()

/** Add entries not already on the list (same key, or same name for name-only ones). */
export function mergeEntries(list, add) {
  const keys = new Set(list.filter(e => e.k).map(e => e.k))
  const names = new Set(list.filter(e => !e.k).map(e => normCo(e.n)))
  const out = [...list], added = []
  for (const e of add) {
    if (e.k ? keys.has(e.k) : names.has(normCo(e.n))) continue
    if (e.k) keys.add(e.k); else names.add(normCo(e.n))
    out.push(e); added.push(e)
  }
  return { list: out, added }
}

/**
 * Convert the old name list. `resolve(name)` gives a directory company or
 * null; `fromRows` maps a name as the feed shows it to a company key.
 * Returns { entries, unmatched }.
 */
export function convertLegacy(names, resolve, entryOf, fromRows) {
  const entries = [], unmatched = []
  for (const n of names) {
    const c = resolve(n)
    if (c) entries.push(entryOf(c))
    else if (fromRows.has(normCo(n))) entries.push({ k: fromRows.get(normCo(n)), n })
    else { entries.push({ n }); unmatched.push(n) }
  }
  return { entries: mergeEntries([], entries).list, unmatched }
}

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
 * Read a broker export or any CSV of companies. Each row is identified by
 * its ISIN, BSE code, NSE/BSE symbol or company name, whichever columns the
 * file has (Zerodha: Symbol or Instrument, and ISIN). A file without a
 * header row is read as one value per row.
 * Returns { found: [company...], unrecognised: [value...] }
 */
export function parseWatchCsv(text, resolve) {
  const rows = text.replace(/^﻿/, '').split(/\r?\n/).map(splitCsvLine).filter(r => r.some(Boolean))
  if (!rows.length) return { found: [], unrecognised: [] }
  const head = rows[0].map(h => h.toLowerCase())
  const find = rx => head.findIndex(h => rx.test(h))
  const cols = [
    find(/\bisin\b/),
    find(/(scrip|security|bse)\s*code|^code$/),
    find(/symbol|instrument|ticker|^scrip$|^stock$/),
    find(/company|^name$|(security|stock|scrip) name/),
  ].filter(i => i >= 0)
  const hasHeader = cols.length > 0
  const order = hasHeader ? [...new Set(cols)] : [0]
  const found = [], unrecognised = []
  for (const r of rows.slice(hasHeader ? 1 : 0)) {
    const vals = order.map(i => (r[i] || '').trim())
      .filter(v => v && (/^\d{6}$/.test(v) || !/^[\d.,\s-]+$/.test(v)))
    if (!vals.length || /^(grand )?total$/i.test(vals[0])) continue
    let c = null
    for (const v of vals) { c = resolve(v); if (c) break }
    if (c) found.push(c)
    else unrecognised.push(vals.find(v => !/^IN[A-Z0-9]{10}$/i.test(v)) || vals[0])
  }
  return { found, unrecognised }
}
