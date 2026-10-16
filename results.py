"""
Quarterly results, coloured from numbers instead of words. Rules only.

BSE publishes listed companies' results as structured figures (free, no
key): revenue, net profit and exceptional items for any quarter, standalone
and consolidated. Where BSE has none (NBFCs, AMCs, brokers, insurers, some
banks) or has not posted them yet, the company's own XBRL filing on NSE is
used. A results filing is compared with the SAME quarter a year earlier,
consolidated if both quarters have it (a company that reported consolidated
figures a year ago is waited for), else standalone. For consolidated results the profit used is the profit
attributable to owners of the parent, read from the company's own XBRL on
NSE; when that is not available (BSE-only company, or the figure left
blank) the total profit is used and the row says so.

  GREEN  profit up 10% or more and revenue not down; or a loss turned
         into a profit
  RED    profit down more than 10%; a profit turned into a loss; or a
         bigger loss than a year ago
  GREY   small or mixed changes; a smaller loss (still a loss); a change
         driven mostly (more than half) by exceptional items; no year-ago
         figures; no revenue; life insurers (accounting profit is not the
         measure); companies with figures on neither BSE nor NSE

The expanded row shows the numbers and which profit and basis were used,
e.g. "Owners' profit +23% YoY, revenue +11% (consolidated)".
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


def _exceptional(d):
    """Exceptional items (before tax) for the quarter, or None if unknown."""
    v = _num(d.get("Exceptional Item"))
    if v is not None:
        return v
    pbt = _num(d.get("Profit (+)/ Loss (-) from Ordinary Activities before Tax"))
    pre = _num(d.get("Profit after Interest but before Exceptional Items"))
    if pbt is None or pre is None or (pbt == 0 and pre != 0):    # a blank PBT is not a loss
        return None
    return round(pbt - pre, 4)


def _figures(d, cons):
    if not d or not (d.get("Date End") or "").strip():
        return None
    rev = _pick(d, REV)
    pat = _pick(d, PAT_CON if cons else PAT_STD)
    if cons and pat == 0 and _num(d.get("Net Profit")):
        pat = _num(d.get("Net Profit"))
    if rev is None or pat is None:
        return None
    return {"end": d.get("Date End"), "rev": rev, "pat": pat, "exc": _exceptional(d)}


# ---- owners' share of profit, from the company's own XBRL on NSE ---------
NSE_LIST = "https://www.nseindia.com/api/integrated-filing-results"
_MON = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()


def _qe(end):
    """'30-Jun-26' -> '30-JUN-2026' (NSE's quarter-end format)."""
    dd, mon, yy = end.split("-")
    return "%s-%s-20%s" % (dd, mon.upper(), yy)


def _owners_from_xbrl(text):
    m = re.search(r'<in-capmkt:ProfitOrLossAttributableToOwnersOfParent\b[^>]*contextRef="OneD"[^>]*>([^<]*)<', text)
    v = _num(m.group(1)) if m else None
    i = re.search(r"<in-capmkt:ISIN\b[^>]*>([^<]*)<", text)
    return (v / 1e6 if v else None), (i.group(1).strip() if i else None)


def owners(bse_sess, nse_sess, sc, cur_end, ly_end):
    """(current, year_ago) profit attributable to owners of the parent, in
    Rs million, or (None, None) when NSE does not have both."""
    time.sleep(DELAY)
    meta = bse_sess.get(API + "ComHeadernew/w", params={"quotetype": "EQ", "scripcode": sc, "seriesid": ""},
                        timeout=(10, 30)).json()
    sym, isin = (meta.get("SecurityId") or "").strip(), (meta.get("ISIN") or "").strip()
    if not sym:
        return None, None
    time.sleep(DELAY)
    lst = nse_sess.get(NSE_LIST, params={"symbol": sym, "type": "Integrated Filing- Financials"},
                       timeout=(10, 30)).json().get("data", [])
    out = []
    for end in (cur_end, ly_end):
        cands = [x for x in lst if (x.get("qe_Date") or "").upper() == _qe(end) and x.get("consolidated") == "Consolidated"]
        cands.sort(key=lambda x: (x.get("type_Sub") or "Original") != "Original")
        if not cands or not cands[0].get("xbrl"):
            return None, None
        time.sleep(DELAY)
        v, xi = _owners_from_xbrl(nse_sess.get(cands[0]["xbrl"], timeout=(10, 30)).text)
        if v is None or (isin and xi and xi != isin):
            return None, None
        out.append(v)
    return out[0], out[1]


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


# ---- figures from the company's own XBRL on NSE --------------------------
# BSE has no structured figures for NBFCs, AMCs, brokers, insurers and some
# banks, and for other companies its figures can arrive a day late, the
# standalone ones first. NSE's integrated filing carries the company's own
# XBRL, both bases, from the moment it files. Each format names its lines
# differently: (format, revenue, profit for the period, owners' share,
# exceptional items before tax). The first format whose profit line is
# present is used.
XBRL_FORMATS = (
    ("company", ("RevenueFromOperations",), ("ProfitLossForPeriod",),
     ("ProfitOrLossAttributableToOwnersOfParent",), ("ExceptionalItemsBeforeTax",)),
    ("bank", ("InterestEarned",), ("ProfitLossForThePeriod", "ProfitLossFromOrdinaryActivitiesAfterTax"),
     ("ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates",), ("ExceptionalItems",)),
    ("general insurer", ("NetPremiumWritten", "PremiumEarned"), ("ProfitLossAfterTax",), (), ()),
    ("life insurer", ("NetPremiumIncome",), ("ProfitLossAfterTaxAndExtraordinaryItems",), (), ()),
)
_LAST_DAY = {3: 31, 6: 30, 9: 30, 12: 31}


def quarter_of(q):
    """BSE quarter code -> (year, month): 130.00 is June 2026."""
    months = int(round((float(q) - 130) * 3))
    t = 2026 * 12 + 5 + months
    return t // 12, t % 12 + 1


def _ctx(text, y, mo):
    """The XBRL context covering exactly this quarter, with no breakdown."""
    smo = mo - 2
    start, end = "%d-%02d-01" % (y, smo), "%d-%02d-%02d" % (y, mo, _LAST_DAY[mo])
    for cid, body in re.findall(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', text, re.S):
        if ("<xbrli:startDate>%s<" % start) in body and ("<xbrli:endDate>%s<" % end) in body \
                and "explicitMember" not in body and "typedMember" not in body:
            return cid
    return None


def _tag(text, ctx, names):
    for n in names:
        m = re.search(r'<in-capmkt:%s\b[^>]*contextRef="%s"[^>]*>([^<]*)<' % (n, re.escape(ctx)), text)
        v = _num(m.group(1)) if m else None
        if v is not None:
            return v / 1e6                           # rupees -> Rs million, as BSE
    return None


def xbrl_figures(text, y, mo, cons):
    """{end, rev, pat, exc, fmt[, owners]} for the quarter, or None."""
    ctx = _ctx(text, y, mo)
    if not ctx:
        return None
    for fmt, rev, pat, own, exc in XBRL_FORMATS:
        p = _tag(text, ctx, pat)
        if p is None:
            continue
        r = _tag(text, ctx, rev)
        if r is None:
            return None
        f = {"end": "%02d-%s-%02d" % (_LAST_DAY[mo], _MON[mo - 1].title(), y % 100),
             "rev": r, "pat": p, "exc": _tag(text, ctx, exc) if exc else None, "fmt": fmt}
        o = _tag(text, ctx, own) if (cons and own) else None
        if o:
            f["owners"] = o
        return f
    return None


class NseXbrl:
    """The company's integrated-filing XBRL on NSE, fetched only when needed."""

    def __init__(self, bse_sess, nse_sess, sc):
        self.bse, self.nse, self.sc, self._lst, self.isin = bse_sess, nse_sess, sc, None, None

    def _list(self):
        if self._lst is None:
            self._lst = []
            time.sleep(DELAY)
            meta = self.bse.get(API + "ComHeadernew/w", params={"quotetype": "EQ", "scripcode": self.sc,
                                                                "seriesid": ""}, timeout=(10, 30)).json()
            sym, self.isin = (meta.get("SecurityId") or "").strip(), (meta.get("ISIN") or "").strip()
            if sym:
                time.sleep(DELAY)
                self._lst = self.nse.get(NSE_LIST, params={"symbol": sym, "type": "Integrated Filing- Financials"},
                                         timeout=(10, 30)).json().get("data", [])
        return self._lst

    def on_nse(self):
        """False once the company is known to have no NSE filings at all."""
        return self._lst is None or bool(self._lst)

    def quarter(self, basis, y, mo):
        qe = "%02d-%s-%d" % (_LAST_DAY[mo], _MON[mo - 1], y)
        cands = [x for x in self._list() if (x.get("qe_Date") or "").upper() == qe
                 and x.get("consolidated") == basis and x.get("xbrl")]
        # a revision corrects the original (seen: an original filed with the
        # half-year's dates): newest file first, then the older ones
        cands.sort(key=lambda x: [int(n) for n in re.findall(r"_(\d{6,8})_", x["xbrl"])] or [0], reverse=True)
        for c in cands[:3]:
            time.sleep(DELAY)
            text = self.nse.get(c["xbrl"], timeout=(10, 30)).text
            i = re.search(r"<in-capmkt:ISIN\b[^>]*>([^<]*)<", text)
            # same issuer (the first 7 characters): a split or a debt ISIN in an
            # older file is still the same company
            if self.isin and i and i.group(1).strip()[:7] != self.isin[:7]:
                continue                             # another company's file
            f = xbrl_figures(text, y, mo, basis == "Consolidated")
            if f:
                return f
        return None

    def pair(self, basis, q):
        y, mo = quarter_of(q)
        c = self.quarter(basis, y, mo)
        return (c, self.quarter(basis, y - 1, mo)) if c else (None, None)


def lookup(sess, nse_sess, sc, q, wait, x=None):
    """(basis, current, year_ago, source, still_waiting).
    Consolidated from BSE, else consolidated from NSE's XBRL; a company that
    reported consolidated figures a year ago is waited for (while `wait`)
    rather than judged on standalone figures; then standalone from BSE,
    else from NSE's XBRL. `x` may be passed in to see afterwards whether the
    company is on NSE at all (x.on_nse())."""
    qly = "%.2f" % (float(q) - 4)
    c = _figures(_con(sess, sc, q), True)
    cl = _figures(_con(sess, sc, qly), True)
    if c and cl:
        if nse_sess is not None:
            try:            # owners' share of profit, from NSE; total profit if not there
                c["owners"], cl["owners"] = owners(sess, nse_sess, sc, c["end"], cl["end"])
            except Exception:
                pass
        return "consolidated", c, cl, "bse", False
    if x is None:              # (x=False: the company is known not to be on NSE)
        x = NseXbrl(sess, nse_sess, sc) if nse_sess is not None else None
    xl = None
    if x:
        xc, xl = x.pair("Consolidated", q)
        if xc and xl:
            return "consolidated", xc, xl, "nse", False
    if (cl or xl) and wait:
        return None, None, None, None, True
    s = _figures(_std(sess, sc, q), False)
    sl = _figures(_std(sess, sc, qly), False) if s else None
    if s and sl:
        return "standalone", s, sl, "bse", False
    if x:
        xs, xsl = x.pair("Standalone", q)
        if xs and xsl:
            return "standalone", xs, xsl, "nse", False
    if s:
        return "standalone", s, None, "bse", False
    return None, None, None, None, False


def _pct(a, b):
    return None if b in (None, 0) or a is None else (a - b) / abs(b) * 100


def _fmt(x):
    return "n/a" if x is None else "%+.0f%%" % x


def _label(basis, cur):
    if basis != "consolidated":
        return "Net profit", "standalone"
    if cur.get("owners") is not None:
        return "Owners' profit", "consolidated"
    return "Total profit", "consolidated; owners' share not available"


def _p(f):
    return f["owners"] if f.get("owners") is not None else f["pat"]


def summary(basis, cur, ly):
    name, how = _label(basis, cur)
    pc, pl = _p(cur), _p(ly)
    if (pc > 0) != (pl > 0):
        pat = "%s: %s" % (name, "turned to a profit (a loss a year ago)" if pc > 0 else "turned to a loss (a profit a year ago)")
    elif pc < 0 and pl < 0:
        pat = "%s: %s loss than a year ago" % (name, "bigger" if pc < pl else "smaller")
    else:
        pat = "%s %s YoY" % (name, _fmt(_pct(pc, pl)))
    return "%s, revenue %s (%s)" % (pat, _fmt(_pct(cur["rev"], ly["rev"])), how)


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
    if cur.get("fmt") == "life insurer":
        return {"dir": "neutral", "text": None,
                "reason": "life insurer: accounting profit does not show how the business is doing "
                          "(value of new business does), so it is not coloured"}
    if not ly or not _year_ago(cur, ly):
        return {"dir": "neutral", "text": None, "reason": "no figures for the same quarter last year"}
    if cur.get("owners") is None or ly.get("owners") is None:     # like for like
        cur, ly = dict(cur, owners=None), dict(ly, owners=None)
    s = summary(basis, cur, ly)
    pc, pl = _p(cur), _p(ly)
    rp, pp = _pct(cur["rev"], ly["rev"]), _pct(pc, pl)
    if pl > 0 and pc <= 0:
        d = "negative"                                   # profit turned into a loss
    elif pl <= 0 < pc:
        d = "positive"                                   # loss turned into a profit
    elif pl < 0 and pc < 0:
        if pc < pl * 1.01:
            d = "negative"                               # a bigger loss
        else:
            return {"dir": "neutral", "text": s, "reason": "%s - still a loss" % s}
    elif pp is None:
        return {"dir": "neutral", "text": s, "reason": "%s - no comparison" % s}
    elif pp < -10:
        d = "negative"
    elif pp >= 10 and (rp is None or rp >= 0):
        d = "positive"
    else:
        return {"dir": "neutral", "text": s, "reason": "%s - small or mixed change" % s}
    # a move made mostly of exceptional items is not the business doing better or worse
    ec, el = cur.get("exc"), ly.get("exc")
    if ec is not None and el is not None:
        de, dp = ec - el, pc - pl
        if dp and de and (de > 0) == (dp > 0) and abs(de) > 0.5 * abs(dp):
            return {"dir": "neutral", "text": s,
                    "reason": "%s - driven by exceptional item (%+.1f vs %+.1f Rs m before tax)" % (s, ec, el)}
    return {"dir": d, "text": s}


def review(basis, cur, ly):
    """The numbers behind a decision, for the daily review file:
    (profit used, profit change, revenue change, exceptional items)."""
    if not cur or not ly:
        return None
    if cur.get("owners") is None or ly.get("owners") is None:
        cur, ly = dict(cur, owners=None), dict(ly, owners=None)
    name, how = _label(basis, cur)
    pc, pl = _p(cur), _p(ly)
    if (pc > 0) != (pl > 0):
        pchg = "loss to profit" if pc > 0 else "profit to loss"
    elif pc < 0 and pl < 0:
        pchg = "bigger loss" if pc < pl else "smaller loss"
    else:
        pchg = _fmt(_pct(pc, pl))
    pchg += " (%s vs %s Rs m)" % (_money(pc), _money(pl))
    ec, el = cur.get("exc"), ly.get("exc")
    exc = "not given" if ec is None or el is None else "%s vs %s Rs m" % (_money(ec), _money(el))
    return "%s (%s)" % (name, how), pchg, _fmt(_pct(cur["rev"], ly["rev"])), exc


def _money(x):
    return "{:,.1f}".format(x)
