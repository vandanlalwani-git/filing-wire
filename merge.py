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


# ------------------------------------------------------------ the merge
def merge(bse_rows, nse_rows, classify_bse, sec_rows=None,
          window=DEDUP_WINDOW_MIN):
    """
    bse_rows    : raw BSE announcement dicts
    nse_rows    : raw NSE announcement dicts
    classify_bse: the BSE classify() function
    sec_rows    : optional bse_securities.json, used to attach ISIN where known
    Returns (merged_rows, stats)
    """
    scrip2isin = {}
    if sec_rows:
        for s in sec_rows:
            if s.get("ISIN_NUMBER"):
                scrip2isin[str(s.get("SCRIP_CD"))] = s["ISIN_NUMBER"]

    out = []
    index = {}                      # norm name -> [minutes]

    for x in bse_rows:
        r = classify_bse(x)
        key = norm_name(x.get("SLONGNAME"))
        ts = x.get("NEWS_DT")
        out.append({
            "src": "BSE",
            "co": (x.get("SLONGNAME") or "").replace(" Ltd", "").replace("-$", "").strip(),
            "sym": None,
            "isin": scrip2isin.get(str(x.get("SCRIP_CD"))),
            "ts": ts, "t": (ts or "")[11:16],
            "sev": r["sev"], "dir": r["dir"], "label": r["label"],
            "line": r["line"],
        })
        index.setdefault(key, []).append(_mins(ts))

    dupes = 0
    for row in nse_rows:
        c = classify_nse(row)
        key = norm_name(row.get("sm_name"))
        t = _mins(row.get("sort_date"))
        twins = index.get(key, [])
        if any(abs(t - bt) <= window for bt in twins if bt >= 0):
            dupes += 1
            continue                # BSE copy already in the feed
        out.append(c)

    out.sort(key=lambda z: z["ts"] or "")
    stats = {
        "bse": len(bse_rows),
        "nse": len(nse_rows),
        "duplicates_dropped": dupes,
        "merged": len(out),
        "nse_unique": len(nse_rows) - dupes,
    }
    return out, stats
