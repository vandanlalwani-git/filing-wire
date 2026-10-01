import { useMemo } from 'react'
import { toMin, fmtMin } from '../lib/time.js'

// v5's intraday tape: 09:00 to midnight in 64 slices, stacked by severity.
export const START = 9 * 60, END = 24 * 60
const BUCKETS = 64, SPAN = (END - START) / BUCKETS
const LABELS = ['09:00', '12:00', '15:00', '18:00', '21:00', '23:59']

export default function Tape({ rows, cutoff, setCutoff }) {
  const { buckets, peak } = useMemo(() => {
    const b = Array.from({ length: BUCKETS }, () => ({ 1: 0, 2: 0, 3: 0, n: 0 }))
    rows.forEach(r => {
      const m = toMin(r.t); if (m < START) return
      const i = Math.min(BUCKETS - 1, Math.floor((m - START) / SPAN))
      b[i][r.sev]++; b[i].n++
    })
    return { buckets: b, peak: Math.max(...b.map(x => x.n), 1) }
  }, [rows])

  return (
    <div id="tape">
      <div id="tapebars">
        {buckets.map((b, i) => {
          const h = b.n ? Math.max(3, (b.n / peak) * 38) : 1
          const from = fmtMin(START + i * SPAN)
          return (
            <div key={i}
              className={'tb' + (START + (i + 1) * SPAN > cutoff ? ' dim' : '')}
              title={from + ' — ' + b.n + ' filings' + (b[3] ? ', ' + b[3] + ' critical' : '')}
              onClick={() => setCutoff(cutoff >= END && i < BUCKETS - 1 ? START + (i + 1) * SPAN : END)}>
              {!b.n
                ? <i className="s1" style={{ height: '1px', opacity: '.4' }}></i>
                : [[3, b[3]], [2, b[2]], [1, b[1]]].map(([s, n]) => n
                    ? <i key={s} className={'s' + s} style={{ height: Math.max(1.5, (n / b.n) * h) + 'px' }}></i>
                    : null)}
            </div>
          )
        })}
      </div>
      <div id="tapelabels">{LABELS.map(t => <span key={t}>{t}</span>)}</div>
    </div>
  )
}
