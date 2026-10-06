"""
Quarterly results, coloured from numbers instead of words. Rules only.

BSE publishes every listed company's results as structured figures (free,
no key): revenue and net profit for any quarter, standalone and
consolidated. A results filing is compared with the SAME quarter a year
earlier, consolidated if both quarters have it, else standalone:

  GREEN  net profit up 10% or more and revenue not down,
         or a loss turned into a profit with revenue not down
  RED    net profit down more than 10%, a profit turned into a loss,
         or a loss that widened by more than 10%
  GREY   anything else: small or mixed changes, a loss that narrowed,
         no year-ago figures, no revenue, or a company type whose figures
         are not wired in yet (NBFC and insurer formats)

The expanded row shows the numbers, e.g. "PAT +23% YoY, revenue +11%
(consolidated)", so anyone can check them against the filing.
"""

import re
import time
from datetime import datetime

API = "https://api.bseindia.com/BseIndiaAPI/api/"
DELAY = 0.6

EVENT = "Quarterly results"
REV = ["Net Sales/Revenue From Operations", "Net Sales", "Revenue From Operations",
       "Interest Earned/Net Income from sales/services"]
PAT_CON = ["Net Profit after Mino Inter & Share of P & L", "Net Profit"]
PAT_STD = ["Net Profit"]
MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}


def is_result(row):
    return row.get("src") == "BSE" and row.get("cat") == "Result" and row.get("sub") == "Financial Results"


def _num(s):
    s = (s or "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def quarter_end(row):
    """The quarter a results filing is about: named in its own text when it
    says so, else the last quarter that ended before the filing month."""
    d = datetime.strptime(row["ts"][:10], "%Y-%m-%d")
    t = ((row.get("subj") or "") + " " + (row.get("hl") or "")).lower()
    m = re.search(r"(quarter|period|year|months?)\s*(and[\w ]{0,30})?ended\s*(on\s*)?(\d{1,2})?(st|nd|rd|th)?[\s.,/-]*"
                  r"(jan\w*|feb\w*|mar\w*|apr\w*|may|jun\w*|jul\w*|aug\w*|sep\w*|oct\w*|nov\w*|dec\w*|0?[369]|12)[\s.,/-]*(20\d\d)", t)
    if m:
        mon = m.group(6)
        mo = int(mon) if mon.isdigit() else MONTHS[mon[:3]]
        if mo in (3, 6, 9, 12):
            return int(m.group(7)), mo
    y, mo = d.year, d.month - 1
    while mo not in (3, 6, 9, 12):
        mo -= 1
        if mo == 0:
            y, mo = y - 1, 12
    return y, mo


def qcode(y, mo):
    """BSE's quarter code: June 2026 is 130.00, one step per quarter."""
    months = (y - 2026) * 12 + (mo - 6)
    return "%.2f" % (130 + months / 3)


def _pick(d, keys):
    for k in keys:
        v = _num(d.get(k))
        if v is not None:
            return v
    return None


def _figures(d, cons):
    if not d or not (d.get("Date End") or "").strip():
        return None
    rev = _pick(d, REV)
    pat = _pick(d, PAT_CON if cons else PAT_STD)
    if cons and pat == 0 and _num(d.get("Net Profit")):
        pat = _num(d.get("Net Profit"))
    if rev is None or pat is None:
        return None
    return {"end": d.get("Date End"), "rev": rev, "pat": pat}


def _std(sess, sc, q):
    time.sleep(DELAY)
    j = sess.get(API + "Corp_detailedResult_Transpose_ng/w", params={"Scrip_cd": sc, "Qtr": q},
                 timeout=(10, 30)).json()
    return {x["fld_desc"]: x["Value"] for x in j.get("table1", [])}


def _con(sess, sc, q):
    time.sleep(DELAY)
    r = sess.get(API + "Corp_BSEDnBResults_SEBI_Consolidated_Res_ng/w",
                 params={"type1": "c", "strtype": q, "strscripcd": sc, "strscripname": "x",
                         "strresultType": "", "action": "show"}, timeout=(10, 30))
    try:
        j = r.json()
    except ValueError:
        return {}
    return {x["Description"]: x["Amount"] for x in j} if isinstance(j, list) else {}


def fetch(sess, sc, q):
    """(basis, current, year_ago) from BSE, or (None, None, None)."""
    qly = "%.2f" % (float(q) - 4)
    c = _figures(_con(sess, sc, q), True)
    if c:
        cl = _figures(_con(sess, sc, qly), True)
        if cl:
            return "consolidated", c, cl
    s = _figures(_std(sess, sc, q), False)
    if not s:
        return None, None, None
    return "standalone", s, _figures(_std(sess, sc, qly), False)


def _pct(a, b):
    return None if b in (None, 0) or a is None else (a - b) / abs(b) * 100


def _fmt(x):
    return "n/a" if x is None else "%+.0f%%" % x


def summary(basis, cur, ly):
    if (cur["pat"] > 0) != (ly["pat"] > 0):
        pat = "PAT turned %s" % ("to a profit (loss a year ago)" if cur["pat"] > 0 else "to a loss (profit a year ago)")
    else:
        pat = "PAT %s YoY" % _fmt(_pct(cur["pat"], ly["pat"]))
    return "%s, revenue %s (%s)" % (pat, _fmt(_pct(cur["rev"], ly["rev"])), basis)


def _year_ago(cur, ly):
    """The comparison quarter must end exactly one year before the current one."""
    try:
        c = datetime.strptime(cur["end"], "%d-%b-%y")
        l = datetime.strptime(ly["end"], "%d-%b-%y")
    except (ValueError, TypeError, KeyError):
        return False
    return (c.year - l.year, c.month, c.day) == (1, l.month, l.day)


def judge(basis, cur, ly):
    """{'dir': positive/negative/neutral, 'text': numbers, 'reason': why grey}."""
    if not cur:
        return {"dir": "neutral", "text": None,
                "reason": "no structured figures for this filing (yet), or a company type not wired in"}
    if not ly or not _year_ago(cur, ly):
        return {"dir": "neutral", "text": None, "reason": "no figures for the same quarter last year"}
    s = summary(basis, cur, ly)
    rp, pp = _pct(cur["rev"], ly["rev"]), _pct(cur["pat"], ly["pat"])
    if ly["pat"] > 0 and cur["pat"] <= 0:
        return {"dir": "negative", "text": s}
    if ly["pat"] <= 0 < cur["pat"]:
        if rp is None or rp >= 0:
            return {"dir": "positive", "text": s}
        return {"dir": "neutral", "text": s, "reason": "%s - mixed" % s}
    if ly["pat"] < 0 and cur["pat"] < 0:
        if cur["pat"] < ly["pat"] * 1.10:
            return {"dir": "negative", "text": s + " - loss widened"}
        return {"dir": "neutral", "text": s, "reason": "%s - still loss-making" % s}
    if pp is None:
        return {"dir": "neutral", "text": s, "reason": "%s - no comparison" % s}
    if pp < -10:
        return {"dir": "negative", "text": s}
    if pp >= 10 and (rp is None or rp >= 0):
        return {"dir": "positive", "text": s}
    return {"dir": "neutral", "text": s, "reason": "%s - small or mixed change" % s}
