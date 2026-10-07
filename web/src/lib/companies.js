// The company directory (data/companies.json): every listed company on NSE
// and BSE, one entry per company, keyed by the ISIN of its shares. It is
// about 150 KB over the network, so it is fetched only the first time
// someone searches, imports a CSV or has an old watchlist to convert.
import { normCo } from './watchlist.js'

let pending = null

/** Same matching form as the collector's norm_name(), plus '&' = 'and'. */
export const nameKey = s => normCo(s).replace(/\band\b/g, ' ').replace(/\s+/g, ' ').trim()

export function loadCompanies() {
  if (!pending) {
    pending = fetch('./data/companies.json', { cache: 'no-cache' })
      .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json() })
      .then(build)
      .catch(e => { pending = null; throw e })
  }
  return pending
}

function build(j) {
  const secs = j.sectors || []
  const list = (j.rows || []).map(r => ({
    k: r[0], n: r[1], s: r[2] || '', b: r[3] || '', bs: r[4] || '',
    sec: r[5] >= 0 ? secs[r[5]] : '', last: r[6] || '', susp: !!r[7],
    nk: nameKey(r[1]), ok: (r[8] || []).map(x => x.replace(/\band\b/g, ' ').replace(/\s+/g, ' ').trim()),
  }))
  const byKey = new Map(), byIssuer = new Map(), bySym = new Map(), byCode = new Map(), byName = new Map()
  const clash = new Set()
  const addName = (n, c) => {
    if (!n) return
    const had = byName.get(n)
    if (had && had !== c) clash.add(n)
    else byName.set(n, c)
  }
  for (const c of list) {
    byKey.set(c.k, c)
    if (/^INE/.test(c.k)) byIssuer.set(c.k.slice(0, 7), c)
    if (c.s) bySym.set(c.s, c)
    if (c.bs && !bySym.has(c.bs)) bySym.set(c.bs, c)
    if (c.b) byCode.set(c.b, c)
  }
  for (const c of list) addName(c.nk, c)
  for (const c of list) for (const n of c.ok) if (!byName.has(n)) addName(n, c)
  for (const n of clash) byName.delete(n)
  return { list, byKey, byIssuer, bySym, byCode, byName, day: j.day }
}

/** A watchlist entry for a directory company. */
export const entryOf = c => ({ k: c.k, n: c.n, ...(c.s ? { s: c.s } : {}), ...(c.b ? { b: c.b } : {}) })

/** One value from a CSV, a search box or an old watchlist -> a company, or null.
 *  Accepts an ISIN, a BSE code, an NSE/BSE symbol (with -EQ, .NS ... endings) or a name. */
export function resolve(dir, raw) {
  const v = (raw || '').trim().replace(/^"|"$/g, '')
  if (!v) return null
  const up = v.toUpperCase()
  if (/^IN[A-Z0-9]{10}$/.test(up)) return dir.byKey.get(up) || dir.byIssuer.get(up.slice(0, 7)) || null
  if (/^\d{6}$/.test(up)) return dir.byCode.get(up) || null
  const sym = up.replace(/\.(NS|BO|NSE|BSE)$/, '').replace(/-(EQ|BE|BZ|SM|ST|BL|E1|IL|RL|T)$/, '')
  if (/^[A-Z0-9&._-]+$/.test(sym) && dir.bySym.has(sym)) return dir.bySym.get(sym)
  return dir.byName.get(nameKey(v)) || null
}

/** Search the directory: symbol, BSE code, ISIN or any part of the name. */
export function searchCompanies(dir, query, limit = 8) {
  const q = query.trim()
  if (!q) return []
  const up = q.toUpperCase()
  const nq = nameKey(q)
  const out = []
  for (const c of dir.list) {
    let score = null
    if (c.s === up || c.bs === up || c.b === up || c.k === up) score = 0
    else if (nq && c.nk.startsWith(nq)) score = 1
    else if (/^\d{3,}$/.test(up) && c.b.startsWith(up)) score = 2
    else if (up.length >= 2 && (c.s.startsWith(up) || (c.bs && c.bs.startsWith(up)))) score = 2
    else if (/^INE/.test(up) && up.length >= 5 && c.k.startsWith(up)) score = 2
    else if (nq && (' ' + c.nk).includes(' ' + nq)) score = 3
    else if (nq && c.ok.some(n => n.startsWith(nq) || (' ' + n).includes(' ' + nq))) score = 4
    else if (nq.length >= 3 && c.nk.replace(/ /g, '').includes(nq.replace(/ /g, ''))) score = 5
    if (score !== null) out.push([score, c.susp ? 1 : 0, c.last ? 0 : 1, c.n.length, c])
  }
  out.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2] || a[3] - b[3])
  return out.slice(0, limit).map(x => x[4])
}

/** Which data/recent/<n>.json holds a company: same as build_site.shard()
 *  (build_site.SHARDS must stay 512). */
export const SHARDS = 512
export function shardOf(key, n = SHARDS) {
  let h = 0
  for (let i = 0; i < key.length; i++) h = (Math.imul(h, 31) + key.charCodeAt(i)) >>> 0
  return h % n
}

/** "Tata Consultancy Services" -> "TC"; "3M India" -> "3I". */
export function initials(name) {
  const words = (name || '').replace(/[^A-Za-z0-9 ]+/g, ' ').split(/\s+/)
    .filter(w => w && !/^(the|of|and|ltd|limited|india)$/i.test(w))
  const w = words.length ? words : (name || '?').split(/\s+/)
  return (w[1] ? w[0][0] + w[1][0] : (w[0] || '?').slice(0, 2)).toUpperCase()
}
