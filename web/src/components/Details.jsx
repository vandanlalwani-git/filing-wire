import { fmtDay } from '../lib/time.js'

const DIR_WORD = { negative: 'Adverse', positive: 'Favourable', neutral: 'Unclassified' }

/** A link that still works as the filing ages: BSE moves PDFs from its
 *  "Live" folder to its "History" folder after about three days. */
export function pdfLink(side, today) {
  if (!side || !side.att) return null
  if (side.src === 'NSE') return /^https?:\/\//.test(side.att) ? side.att : null
  const age = (Date.parse(today) - Date.parse(side.ts.slice(0, 10))) / 86400000
  return `https://www.bseindia.com/xml-data/corpfiling/${age >= 3 ? 'AttachHis' : 'AttachLive'}/${side.att}`
}

function linkLabel(side) {
  const ext = (side.att || '').split('.').pop().toLowerCase()
  return `Original filing on ${side.src} (${ext === 'zip' ? 'ZIP' : 'PDF'})`
}

export function whyText(side) {
  const word = DIR_WORD[side.dir] || 'Unclassified'
  const w = side.why
  if (!w) return `${word}: ${side.lab}.`
  if (w.rule || w.reason) {           // new rules (Part C) say which phrase decided it
    const where = w.by === 'pdf' ? 'the PDF says' : 'the text says'
    return side.dir === 'neutral'
      ? `Unclassified: ${(w.reason || 'the text doesn’t say whether this is good or bad news').replace(/\.?$/, '.')}`
      : `${word}: ${w.event || side.lab} — ${where} “${w.text}”.`
  }
  if (w.by === 'phrase') {
    return side.dir === 'neutral'
      ? `Unclassified: the text mentions “${w.text}” (${side.lab}), which doesn’t say whether this is good or bad news.`
      : `${word}: the text mentions “${w.text}”, read as ${side.lab}.`
  }
  if (w.by === 'pdf') return `${word}: the PDF’s pledge table says “${w.text}”.`
  return side.dir === 'neutral'
    ? `Unclassified: the exchange category “${w.text}” doesn’t say whether this is good or bad news.`
    : `${word}: the company filed it under “${w.text}”, read as ${side.lab}.`
}

const fmtAmt = cr => cr >= 100
  ? `Rs ${Math.round(cr).toLocaleString('en-IN')} cr`
  : `Rs ${cr.toLocaleString('en-IN', { maximumFractionDigits: 2 })} cr`

const time = ts => ts.slice(11, 16)
const cats = s => (s.src === 'BSE' && s.cat ? `${s.cat} › ${s.sub || '—'}` : (s.sub || '—'))

function FullText({ side }) {
  const cut = side.src === 'BSE' && /\.\.\.\s*$/.test(side.hl || '')
  return (
    <>
      {side.src === 'BSE' && side.subj && <p className="xs">{side.subj}</p>}
      {side.src === 'NSE' && side.sub && <p className="xs">{side.sub}</p>}
      <p>{side.hl || side.line}</p>
      {cut && <p className="xnote">BSE cuts its own text off here. The full disclosure is in the PDF.</p>}
    </>
  )
}

function Link({ side, today }) {
  const href = pdfLink(side, today)
  if (!href) return <span className="xnote">No attachment was filed.</span>
  return <a href={href} target="_blank" rel="noopener noreferrer">{linkLabel(side)} &#8599;</a>
}

export default function Details({ d, today, state }) {
  if (state === 'loading') return <div className="xp"><p className="xnote">Loading details…</p></div>
  if (state === 'error' || !d) return <div className="xp"><p className="xnote">Couldn’t load the details just now. Tap again to retry.</p></div>
  const t = d.twin
  const pledge = d.pledge || (t && t.pledge)
  return (
    <div className="xp" onClick={e => e.stopPropagation()}>
      <div className="xh">Full text · {d.src} · {time(d.ts)}</div>
      <FullText side={d} />

      <div className="xh">Why this colour</div>
      <p>{whyText(d)}</p>

      {(d.amt || pledge) && <>
        <div className="xh">Read from the PDF</div>
        {d.amt ? <p>Amount: {fmtAmt(d.amt)}</p> : null}
        {pledge ? <p>Pledge: {pledge.label}</p> : null}
      </>}

      <div className="xh">Original filing</div>
      <p><Link side={d} today={today} /></p>

      {t && <>
        <div className="xh">Also filed on {t.src} at {time(t.ts)}{t.ts.slice(0, 10) !== d.ts.slice(0, 10) ? ', ' + fmtDay(t.ts.slice(0, 10)) : ''}</div>
        <FullText side={t} />
        <p><Link side={t} today={today} /></p>
      </>}

      <div className="xh">Exchange categories</div>
      <p className="xm">{d.src} · {cats(d)} · {d.ts.slice(11)}</p>
      {t && <p className="xm">{t.src} · {cats(t)} · {t.ts.slice(11)}</p>}
    </div>
  )
}
