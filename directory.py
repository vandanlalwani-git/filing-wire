#!/usr/bin/env python3
"""
The company directory: every listed company, one entry per ISIN.

Sources (free, official, no login):
    NSE  EQUITY_L.csv (main board) and SME_EQUITY_L.csv (Emerge)
    BSE  every active equity scrip, all groups, plus suspended ones (bse library)

refresh() runs inside the collector at most once a day and keeps each
source's last good copy in <data>/directory.json: if a source fails, the
previous day's list for that source is used. build_site.py publishes the
merged list for the screen's search and watchlist.

    python directory.py --data-dir data          # refresh now (testing)
"""
import argparse
import csv
import io
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
IST = timezone(timedelta(hours=5, minutes=30))
FILE = "directory.json"
REFRESH_FROM_HOUR = 7          # NSE rewrites its lists overnight
RETRY_MINUTES = 60             # a failed source is tried again an hour later
NSE_LISTS = ("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
             "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def _fetch_nse():
    """[[symbol, name, isin], ...] from both NSE lists; raises if either is unusable."""
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "text/csv,*/*"})
    out = []
    for url in NSE_LISTS:
        r = s.get(url, timeout=30)
        r.raise_for_status()
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig", errors="replace"))))
        head = [h.strip().upper().replace("_", " ") for h in rows[0]]
        i_sym, i_name, i_isin = head.index("SYMBOL"), head.index("NAME OF COMPANY"), head.index("ISIN NUMBER")
        got = [[x[i_sym].strip().upper(), " ".join(x[i_name].split()), x[i_isin].strip().upper()]
               for x in rows[1:] if len(x) > i_isin and x[i_sym].strip()]
        if len(got) < (1000 if "EQUITY_L" in url and "SME" not in url else 100):
            raise ValueError("%s: only %d rows" % (url.rsplit("/", 1)[-1], len(got)))
        out += got
    return out


def _fetch_bse(status="Active", least=2000):
    """[[code, name, isin, bse_symbol, short_name], ...] for every equity scrip
    with this status, all groups."""
    from bse import BSE
    with BSE(tempfile.mkdtemp()) as b:
        data = b.listSecurities(group="", segment="Equity", status=status)
    out = [[str(x.get("SCRIP_CD") or "").strip(),
            " ".join((x.get("Issuer_Name") or x.get("Scrip_Name") or "").split()),
            (x.get("ISIN_NUMBER") or "").strip().upper(),
            (x.get("scrip_id") or "").strip().upper(),
            " ".join((x.get("Scrip_Name") or "").split())]
           for x in data if x.get("SCRIP_CD")]
    if len(out) < least:
        raise ValueError("BSE %s list: only %d rows" % (status, len(out)))
    return out


def _due(src, today, now):
    if src.get("day") == today:
        return False
    tried = src.get("tried")
    if tried:
        t = datetime.strptime(tried, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST)
        if now - t < timedelta(minutes=RETRY_MINUTES):
            return False
    return True


def refresh(data_dir, now=None, log=print, force=False):
    """Fetch any source not yet read today. Never raises; never empties a source."""
    now = now or datetime.now(IST)
    if not force and now.hour < REFRESH_FROM_HOUR:
        return False
    today, stamp = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d %H:%M:%S")
    path = os.path.join(data_dir, FILE)
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (FileNotFoundError, ValueError):
        d = {}
    changed = False
    # suspended companies still file (and are still held), so they are listed too
    for name, fn in (("nse", _fetch_nse), ("bse", _fetch_bse),
                     ("bse_susp", lambda: _fetch_bse("Suspended", 300))):
        src = d.get(name) or {}
        if not force and not _due(src, today, now):
            continue
        src["tried"] = stamp
        try:
            rows = fn()
            src.update(day=today, rows=rows, error=None)
            log("  directory: %s %d companies" % (name.upper(), len(rows)))
        except Exception as e:
            src["error"] = "%s: %s" % (type(e).__name__, str(e)[:200])
            log("  directory: %s FAILED (%s), keeping the list from %s"
                % (name.upper(), src["error"], src.get("day") or "never"))
        d[name] = src
        changed = True
    if changed:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    return changed


def tidy(name):
    """'ABB INDIA LIMITED' / 'ABB India Ltd.' -> 'ABB India' style display name."""
    n = " ".join((name or "").split())
    for suf in (" limited", " ltd.", " ltd", " ltd-$", "-$"):
        if n.lower().endswith(suf):
            n = n[: -len(suf)].rstrip(" ,.")
    if n.isupper() and len(n) > 5:
        # all-capitals names read badly; keep short words (ABB, NTPC) as they are
        n = " ".join(w if (len(w) <= 4 and w.isalpha() and w not in ("OF", "AND", "THE", "FOR", "WITH"))
                     or not w.isalpha() else w.capitalize() for w in n.split())
        n = n.replace(" Of ", " of ").replace(" And ", " and ").replace(" The ", " the ")
    return n


def _issuer(isin):
    """INE117A01022 -> INE117A: the company part of an Indian ISIN. None for
    rights entitlements (type 20), partly-paid lines (IN9), mutual funds (INF)
    and blanks, which are not companies of their own."""
    isin = (isin or "").upper()
    if len(isin) == 12 and isin.startswith("INE") and isin[7:9] != "20":
        return isin[:7]
    return None


def merged(data_dir):
    """One entry per company, keyed by the ISIN of its main listed shares:
    {key, isin, name, nse, bse, bsym, sec, names, susp, codes}.
    Every line of the same issuer (old ISINs, a suspended earlier listing)
    folds into one company."""
    try:
        with open(os.path.join(data_dir, FILE), encoding="utf-8") as f:
            d = json.load(f)
    except (FileNotFoundError, ValueError):
        d = {}
    with open(os.path.join(HERE, "sector_map.json"), encoding="utf-8") as f:
        sectors = json.load(f)
    groups = {}
    # rank: NSE first, then BSE active ordinary shares, then other BSE active, then suspended
    for sym, name, isin in (d.get("nse") or {}).get("rows", []):
        if _issuer(isin):
            groups.setdefault(_issuer(isin), []).append(
                (0, {"isin": isin, "nse": sym, "name": name, "names": [name]}))
    for src, susp in (("bse", False), ("bse_susp", True)):
        for code, name, isin, bsym, *short in (d.get(src) or {}).get("rows", []):
            if _issuer(isin):
                rank = 3 if susp else (1 if isin[7:9] == "01" else 2)
                groups.setdefault(_issuer(isin), []).append(
                    (rank, {"isin": isin, "bse": code, "bsym": bsym, "name": name,
                            "names": [n for n in [name] + short if n]}))
    out = {}
    for lines in groups.values():
        lines.sort(key=lambda x: x[0])
        main = lines[0][1]
        bse = [ln for r, ln in lines if "bse" in ln]
        bse.sort(key=lambda ln: ln["isin"] != main["isin"])       # same shares first
        nse = next((ln for r, ln in lines if "nse" in ln), None)
        e = {"key": main["isin"], "isin": main["isin"],
             "nse": nse["nse"] if nse else None,
             "bse": bse[0]["bse"] if bse else None,
             "bsym": bse[0]["bsym"] if bse else None,
             "codes": sorted({ln["bse"] for ln in bse}),
             "names": [n for r, ln in lines for n in ln["names"]],
             "susp": all(r == 3 for r, ln in lines)}
        # NSE's name, unless it is written in capitals and BSE has one that is not
        cands = ([nse["name"]] if nse else []) + (bse[0]["names"] if bse else [])
        name = tidy(next((n for n in cands if not n.isupper()), cands[0]))
        # BSE cuts long names at 35 letters: use a longer spelling of the same name
        low = name.lower()
        longer = [tidy(n) for n in cands if tidy(n).lower().startswith(low) and len(tidy(n)) > len(name)]
        if len(name) >= 30 and longer:
            name = max(longer, key=len)
            if name.isupper():
                name = tidy(name)
        e["name"] = name
        e["sec"] = sectors.get(e["nse"] or "") or sectors.get(e["bsym"] or "")
        out[e["key"]] = e
    return out


def resolver(m):
    """row -> company key. By ISIN (its issuer part), then BSE code, then
    (for filings saved before the BSE code was recorded, 7 Oct 2026) the
    exchange's own company name against every official name in the directory.
    A name shared by two companies is never used."""
    from merge import norm_name
    by_issuer = {_issuer(k): k for k in m}
    by_bse = {c: k for k, e in m.items() for c in e["codes"]}
    by_name = {}
    # suspended scrips often share a name with the company's current listing:
    # active names first, suspended ones only for names not already taken
    for susp in (False, True):
        tier, clash = {}, set()
        for k, e in m.items():
            if bool(e.get("susp")) != susp:
                continue
            for n in set(norm_name(x) for x in e.get("names", []) + [e["name"]]):
                if n and tier.get(n, k) != k:
                    clash.add(n)
                tier.setdefault(n, k)
        for n, k in tier.items():
            if n not in clash:
                by_name.setdefault(n, k)

    def key(r):
        if _issuer(r.get("isin")) in by_issuer:
            return by_issuer[_issuer(r["isin"])]
        if r.get("sc") in by_bse:
            return by_bse[r["sc"]]
        k = by_name.get(r.get("ck") or norm_name(r.get("co")))
        if k:
            return k
        return r.get("isin") or ("B" + r["sc"] if r.get("sc") else None)
    return key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--no-fetch", action="store_true", help="only summarise the saved lists")
    a = ap.parse_args()
    if not a.no_fetch:
        refresh(a.data_dir, force=True)
    m = merged(a.data_dir)
    print("%d companies (%d on both, %d NSE only, %d BSE only, %d of them suspended)" % (
        len(m), sum(1 for e in m.values() if e.get("nse") and e.get("bse")),
        sum(1 for e in m.values() if e.get("nse") and not e.get("bse")),
        sum(1 for e in m.values() if e.get("bse") and not e.get("nse")),
        sum(1 for e in m.values() if e.get("susp"))))


if __name__ == "__main__":
    main()
