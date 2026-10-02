"""
Merge BSE and NSE disclosure feeds into one stream. Zero AI calls.

Dedup: dual-listed companies file the same disclosure to both exchanges.
Measured on 2026-09-08: ~50% of NSE rows have a BSE twin. The match rate
flattens after a +/-30 minute window, so 30 is the honest setting.

Join key: normalised company name, NOT ISIN. bse_securities.json only
covers BSE Group A (698 companies), giving ISIN for 26% of NSE names,
while normalised names match 75%. ISIN is used as a confirming signal
where available.
"""

import json
import os
import re
from datetime import datetime

from classify import normalise_text

_HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_HERE, "taxonomy_nse.json"), encoding="utf-8") as f:
    NSE_TAX = json.load(f)

NSE_RULES = NSE_TAX["rules"]
NSE_OVERRIDES = [(re.compile(o["pattern"]), o) for o in NSE_TAX["text_overrides"]]

DEDUP_WINDOW_MIN = 30


# ------------------------------------------------------------- helpers
def norm_name(s):
    s = (s or "").lower()
    s = re.sub(r"\b(ltd|limited|the)\b", "", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _mins(ts):
    """
    '2026-09-08T14:23:11' or '2026-09-08 14:23:11' -> ABSOLUTE minutes.

    Absolute, not minutes-past-midnight: clock time alone matched a filing
    against one from a previous day at the same hour, which silently dropped
    real NSE rows as duplicates, and broke across midnight entirely.
    """
    if not ts:
        return -1
    try:
        dt = datetime.strptime(str(ts)[:19].replace("T", " "),
                               "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return -1
    return int(dt.timestamp() // 60)


def _clean(text, label):
    # same escaping artifacts as BSE: doubled apostrophes, nbsp, stray tags
    t = normalise_text(text)
    if len(t) < 12:
        return label
    # NSE writes "X Limited has informed the Exchange about Y" - trim the stem
    t = re.sub(r"^.{0,70}?\bhas informed the Exchange (about|regarding|that)\s*",
               "", t, flags=re.I).strip()
    if len(t) < 8:
        return label
    if len(t) > 110:
        # trim trailing punctuation first, else "w.e.f." + "..." -> "w.e.f...."
        return t[:110].rsplit(" ", 1)[0].rstrip(" .,:;-") + "..."
    return t[0].upper() + t[1:] if t else label


# ------------------------------------------------------- NSE classifier
def classify_nse(row):
    desc = (row.get("desc") or "").strip()
    text = (row.get("attchmntText") or "").strip()

    base = NSE_RULES.get(desc)
    if base is None:
        base = {"sev": 1, "dir": "neutral", "label": desc or "Disclosure"}

    sev, direction, label = base["sev"], base["dir"], base["label"]

    for rx, ov in NSE_OVERRIDES:
        if rx.search(text) or rx.search(desc):
            if ov["sev"] >= sev:
                sev, direction, label = ov["sev"], ov["dir"], ov["label"]
            break

    return {
        "src": "NSE",
        "co": (row.get("sm_name") or "").replace(" Limited", "").strip(),
        "sym": row.get("symbol"),
        "isin": row.get("sm_isin"),
        "ts": row.get("sort_date"),
        "t": (row.get("sort_date") or "")[11:16],
        "sev": sev, "dir": direction, "label": label,
        "line": _clean(text, label),
    }


# ------------------------------------------------- duplicate pairing
# Dual-listed companies file the same disclosure to both exchanges. This
# is the agreed rule, carried over unchanged from the working collector:
#
#   * a twin is the same normalised company name within +/-30 minutes,
#     compared on the FULL timestamp (never clock time alone)
#   * pairing is ONE-TO-ONE: every candidate pair is sorted by time gap,
#     smallest first, and each row can be used at most once
#   * ISIN, where both rows have it, can only REJECT a match, never make one;
#     only the first 9 characters are compared (country + company code +
#     security type, e.g. INE806T01). The rest changes when a company
#     reissues its shares, and BSE's list and NSE's feed are often on
#     different issues of the same share
#   * of each pair the row with the higher severity is kept WHOLE - its own
#     label, line, direction and attachment; ties go to BSE
#   * nothing is ever stitched across the two rows
#
# The older "drop any NSE row with a BSE twin" version that used to live
# here has been removed so there is only one rule.

_TS_FMT = "%Y-%m-%d %H:%M:%S"
ISIN_PREFIX = 9          # INE806T01 012 vs INE806T01 020 -> same company, same share


# ------------------------------------------------- merge tightening
# A company often files several different things within minutes (AGM result,
# trading-window closure, record date ...). Pairing by name and time alone
# then joins the wrong halves. Two rows are NOT paired when both have a
# specific kind and the kinds clearly differ. Kinds come from the label for
# routine filings (where the exchanges' categories are reliable) and from the
# events found in the filing's own text. Labels that can hold many kinds of
# news (General, Insolvency / tribunal matter, Regulatory action ...) have no
# kind, so they can still pair; that is how BSE's "Order win" label on a tax
# order still pairs with NSE's "Regulatory action" version of the same filing.
# Checked on 399 hand-labelled pairs from Sept 2026 (tests/golden_pairs.json).
KIND_RULES = [
 (None, r"^(general disclosure|general update|update|updates|press release.*|board meeting outcome|board outcome revised|outcome filed without prior intimation|material issue disclosed|newspaper publication|disclosure|other disclosure|uncategorised filing|meeting update|committee meeting|addendum|public announcement|clarification|corrigendum|revision of outcome|revised outcome)$"),
 ("credit rating", r"credit rating|rating"),
 ("trading window", r"trading window"),
 ("insider / takeover", r"insider|sast|substantial shareholding|pledge|takeover|encumbr|open offer|promoter|structural digital database|acquirer"),
 ("shareholder meeting / annual report", r"agm|egm|shareholders meeting|postal ballot|court convened|annual report|voting result|scrutini|e-voting"),
 ("board meeting notice", r"board meeting called|board meeting cancelled|board meeting intimation"),
 ("results", r"result|integrated filing- financial|financial statement"),
 ("investor meeting", r"analyst|investor|earnings call|transcript|conference call|presentation"),
 ("people", r"management change|appoint|resign|retire|director|cessation|kmp|company secretary|auditor|ceo|cfo|chairman|demise|senior management"),
 ("record date / dividend", r"record date|book closure|dividend"),
 ("monthly business update", r"monthly business"),
 ("operations", r"production|operations|incident|capacity|strike|lockout|disrupt|closure of operations"),
 ("insolvency", r"creditors|resolution plan|insolvency|cirp"),
 ("compliance filing", r"certificate loss|duplicate share|registrar|share transfer|address change"),
 ("regulatory / legal", r"default|rumour"),
 ("capital / financing", r"allot|securities|esop|preferential|qip|placement|rights issue|raising of funds|fund rais|bonus|split|buyback|buy back|warrant|ncd|debenture|bond|conversion|redemption|delisting|commercial paper|interest rate|guarantee|57 \(|capital|share"),
 ("deal / business", r"acqui|agreement|\bmou\b|joint venture|order|contract|amalgamation|merger|scheme of arrangement|restructuring|diversification|disinvest|sale|disposal|tie.?up|new line|rescission|termination|incorporation|subsidiary|investment|product"),
 ("regulatory / legal", r"regulatory|litigation|fraud|default|penalt|\bfine\b|clarification|queried|news verification|rumour|spurt|price movement|suspension|licen|tax|enforcement|nclt|order passed|show cause"),
 ("compliance filing", r"brsr|moa|aoa|certificate|monitoring agency|deviation|related party|compliance|governance|secretarial|shareholding pattern|loss of share|duplicate|kyc|reconciliation|name change|registered office|code of conduct|asset liability"),
]
# routine kinds, where the exchanges' own categories are reliable; the other
# kinds (operations, insolvency, regulatory / legal) cover too much to judge
STRICT_KINDS = {"credit rating", "trading window", "insider / takeover",
                "shareholder meeting / annual report", "board meeting notice", "results",
                "investor meeting", "people", "record date / dividend",
                "monthly business update", "compliance filing", "capital / financing",
                "deal / business"}
_KIND_RX = [(k, re.compile(rx, re.I)) for k, rx in KIND_RULES]
# events found in the text that identify one specific filing; a shared one
# means both rows report the same thing even if their labels disagree
SAME_EVENT = {"TAX-DEMAND", "RULING-FAV", "RULING-MIXED", "ORDER-WIN", "COMPOUNDING",
              "SEBI-ACTION", "NCLT-SCHEME", "FIRE", "SEARCH", "DEFAULT", "RATING-UP",
              "RATING-DOWN", "AUD-RESIGN", "COMMISSION", "DRUG-OK", "DRUG-483",
              "PLEDGE-NEW", "PLEDGE-REL", "FRAUD", "INSOLV-ADMIT", "INSOLV-DISMISSED",
              "SHUTDOWN", "COURT-STEP", "CIRP-ROUTINE", "ORDER-UPDATE", "JC-BONUS"}
COMPATIBLE = {frozenset({"record date / dividend", "capital / financing"})}


def label_kind(label):
    l = (label or "").strip()
    for k, rx in _KIND_RX:
        if rx.search(l):
            return k if k in STRICT_KINDS else None
    return None


def clearly_different(b, n):
    """b, n: rows with 'lab' and 'ev' (set of event rule ids from the text)."""
    eb, en = b.get("ev") or set(), n.get("ev") or set()
    if eb & en & SAME_EVENT:
        return False
    kb, kn = label_kind(b.get("lab")), label_kind(n.get("lab"))
    if "EXCH-QUERY" in eb:
        kb = "exchange query"
    if "EXCH-QUERY" in en:
        kn = "exchange query"
    if not kb or not kn or kb == kn:
        return False
    return frozenset({kb, kn}) not in COMPATIBLE


def pick_canonical(ev_sev, ev_source, partner_sev, promote_sev=True):
    """True if `ev` is the row the feed should show. Higher severity wins;
    ties go to BSE. With promote_sev off this is strict BSE-canonical."""
    if not promote_sev:
        return ev_source == "BSE"
    if ev_sev != partner_sev:
        return ev_sev > partner_sev
    return ev_source == "BSE"


def pair_rows(rows, window=DEDUP_WINDOW_MIN, promote_sev=True, tighten=True):
    """
    Greedy one-to-one pairing over a batch of classified rows, in place.

    Each row is a dict with at least: uid, source ('BSE'/'NSE'),
    company_key, filed_at ('YYYY-MM-DD HH:MM:SS'), sev, isin; and for merge
    tightening, lab and ev (see clearly_different).
    Sets on every row:
        dup_of        uid of the kept twin, on the hidden row only
        paired_with   uid of the other half, on both rows
        promoted_from uid of the hidden BSE row, on a kept NSE row only
    Any previous pairing is cleared first, so the same input always gives
    the same output.

    Returns [(kept_uid, hidden_uid, promoted_bool), ...]
    """
    for r in rows:
        r["dup_of"] = r["paired_with"] = r["promoted_from"] = None

    by_company = {}
    for r in rows:
        if not r.get("company_key"):
            continue
        try:
            t = datetime.strptime(r["filed_at"], _TS_FMT)
        except (TypeError, ValueError):
            continue
        side = by_company.setdefault(r["company_key"], {"BSE": [], "NSE": []})
        if r.get("source") in side:
            side[r["source"]].append((r["uid"], t, r["sev"], r.get("isin"), r))

    candidates = []
    for sides in by_company.values():
        for b_uid, b_t, b_sev, b_isin, b_row in sides["BSE"]:
            for n_uid, n_t, n_sev, n_isin, n_row in sides["NSE"]:
                gap = abs((n_t - b_t).total_seconds())
                if gap > window * 60:
                    continue
                if b_isin and n_isin and b_isin[:ISIN_PREFIX] != n_isin[:ISIN_PREFIX]:
                    continue        # ISIN only ever rejects, never matches
                if tighten and clearly_different(b_row, n_row):
                    continue        # two different filings by the same company
                candidates.append((gap, b_uid, b_sev, n_uid, n_sev))
    candidates.sort(key=lambda c: (c[0], c[1], c[3]))

    index = {r["uid"]: r for r in rows}
    taken, made = set(), []
    for gap, b_uid, b_sev, n_uid, n_sev in candidates:
        if b_uid in taken or n_uid in taken:
            continue
        taken.add(b_uid)
        taken.add(n_uid)
        bse_wins = pick_canonical(b_sev, "BSE", n_sev, promote_sev)
        keep, drop = (b_uid, n_uid) if bse_wins else (n_uid, b_uid)
        index[drop]["dup_of"] = keep
        index[drop]["paired_with"] = keep
        index[keep]["paired_with"] = drop
        index[keep]["promoted_from"] = None if bse_wins else drop
        made.append((keep, drop, not bse_wins))
    return made
