import Details from './Details.jsx'

const DIR_LABEL = { negative: 'Adverse', positive: 'Favourable', neutral: 'Unclassified' }
const FOOT = 'Disclosure events only, classified by fixed rules. Not investment advice. Source: BSE and NSE public filings.'

export default function Feed({ rows, visible, missing, isToday, limit, setLimit, isWatched, toggleWatch,
  open, toggle, details, detState, today }) {
  let body
  if (rows === null) {
    body = <div id="empty">Loading the wire…</div>
  } else if (missing || !rows.length) {
    body = <div id="empty">{isToday ? 'No disclosures recorded yet today.' : 'No record for this day.'}</div>
  } else if (!visible.length) {
    body = <div id="empty">Nothing matches the current filters.</div>
  } else {
    const newest = [...visible].reverse().slice(0, limit)
    const out = []
    let lastHour = null
    newest.forEach(r => {
      const hr = r.t.slice(0, 2)
      if (hr !== lastHour) {
        out.push(<div key={'h' + hr + r.id} className="hourrule"><span>{hr}00 hrs</span><i></i></div>)
        lastHour = hr
      }
      const w = isWatched(r)
      const isOpen = open.has(r.id)
      const onKey = e => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(r.id) }
      }
      out.push(
        <div key={r.id} className={`entry s${r.sev} ${r.dir}${w ? ' watched' : ''}${isOpen ? ' open' : ''}`}
          onClick={() => toggle(r.id)}>
          <div className="e-time">{r.t}</div>
          <div className="e-mark"><b></b></div>
          <div className="e-sum" role="button" tabIndex={0} aria-expanded={isOpen}
            aria-controls={'x-' + r.id} onKeyDown={onKey}>
            <div className="e-meta">
              <div className="e-tags">
                <span className={'dirmark ' + r.dir}>{DIR_LABEL[r.dir] || 'Unclassified'}</span>
                <span className="tag">{r.lab}</span>
                {r.sec && r.sec !== 'Other' && <span className="tag">· {r.sec}</span>}
                {w && <span className="wflag">Watchlist</span>}
              </div>
              <span className="e-chev" aria-hidden="true">{isOpen ? '−' : '+'}</span>
            </div>
            <div className="e-co">{r.co}</div>
            <div className="e-line">{r.line}</div>
          </div>
          <button className={'star' + (w ? ' on' : '')}
            title={(w ? 'Remove from' : 'Add to') + ' watchlist'}
            aria-label={(w ? 'Remove ' : 'Add ') + r.co + (w ? ' from' : ' to') + ' watchlist'}
            onClick={e => { e.stopPropagation(); toggleWatch(r) }}>{w ? '★' : '☆'}</button>
          {isOpen && (
            <div id={'x-' + r.id} className="e-xwrap">
              <Details d={details && details[r.id]} today={today}
                state={detState === 'ready' && !(details && details[r.id]) ? 'error' : detState} />
            </div>
          )}
        </div>
      )
    })
    if (visible.length > limit) {
      out.push(
        <div key="more" id="more" onClick={() => setLimit(limit + 150)} role="button" tabIndex={0}>
          Show more — {limit} of {visible.length} shown
        </div>
      )
    }
    body = out
  }
  return (
    <div id="feed">
      {body}
      <div id="foot">{FOOT}</div>
    </div>
  )
}
