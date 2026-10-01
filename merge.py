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


def pick_canonical(ev_sev, ev_source, partner_sev, promote_sev=True):
    """True if `ev` is the row the feed should show. Higher severity wins;
    ties go to BSE. With promote_sev off this is strict BSE-canonical."""
    if not promote_sev:
        return ev_source == "BSE"
    if ev_sev != partner_sev:
        return ev_sev > partner_sev
    return ev_source == "BSE"


def pair_rows(rows, window=DEDUP_WINDOW_MIN, promote_sev=True):
    """
    Greedy one-to-one pairing over a batch of classified rows, in place.

    Each row is a dict with at least: uid, source ('BSE'/'NSE'),
    company_key, filed_at ('YYYY-MM-DD HH:MM:SS'), sev, isin.
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
            side[r["source"]].append((r["uid"], t, r["sev"], r.get("isin")))

    candidates = []
    for sides in by_company.values():
        for b_uid, b_t, b_sev, b_isin in sides["BSE"]:
            for n_uid, n_t, n_sev, n_isin in sides["NSE"]:
                gap = abs((n_t - b_t).total_seconds())
                if gap > window * 60:
                    continue
                if b_isin and n_isin and b_isin[:ISIN_PREFIX] != n_isin[:ISIN_PREFIX]:
                    continue        # ISIN only ever rejects, never matches
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
