#!/usr/bin/env python3
"""
Assemble the public website folder from the built screen and the record book.

Only what the screen reads is published to the website:
    data/days/<day>.json   one file per day; severity-0 "noise" is left out,
                           as the taxonomy says (raw feed only) and v5 shows
    data/days/index.json   the list of days that exist (for the date picker)
    data/status.json       freshness and per-exchange health
    data/symbols.json      trading symbol -> company name (kept for older screens)
    data/companies.json    every listed company (directory.py), for search,
                           the watchlist and CSV import; loaded only when used
    data/recent/<n>.json   each company's filings over the last 30 days, split
                           into 512 small files by company; the Watchlist tab
                           loads only the files for the companies watched
    data/details/<day>.json  everything shown when a row is expanded: the full
                           text each exchange sent, why it got its colour, any
                           amount or pledge read from the PDF, the attachment,
                           and the other exchange's version if it was merged.
                           Loaded by the screen only when someone expands a row.
The internal record book (book/) and the PDF cache stay on the data branch.

    python build_site.py --data-dir data --out site [--app web/dist]
"""
import argparse
import json
import os
import shutil

import directory
from merge import norm_name

RECENT_DAYS = 30
SHARDS = 512

PLACEHOLDER = """<!doctype html><meta charset="utf-8">
<title>The Filing Wire</title>
<p>The Filing Wire &mdash; data endpoint. The screen is coming.</p>
<p><a href="data/status.json">status.json</a> &middot;
<a href="data/days/index.json">days/index.json</a></p>
"""


def _cache_key(r):
    att = r.get("att") or ""
    if r.get("src") == "NSE":
        att = att.rsplit("/", 1)[-1]
    return (r.get("src") or "") + ":" + att


def _side(r, cache):
    """One exchange's version of a filing, as the expanded row shows it."""
    d = {k: r[k] for k in ("src", "ts", "cat", "sub", "subj", "hl", "lab", "dir",
                           "sev", "line", "att", "amt", "why") if r.get(k) not in (None, "")}
    e = cache.get(_cache_key(r)) if r.get("att") else None
    if e and e.get("s") == "pledge":
        d["pledge"] = e.get("pl")
    return d


def shard(key):
    """Which recent/<n>.json holds a company. The screen computes the same."""
    h = 0
    for ch in key:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return h % SHARDS


def load_cache(data_dir):
    try:
        with open(os.path.join(data_dir, "enrich_cache.json"), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def write_details(det_dir, day, rows, cache):
    twins = {r["dup"]: r for r in rows if r.get("dup")}
    det = {}
    for r in rows:
        if r.get("dup") or r.get("sev", 0) < 1:
            continue                      # only rows the screen shows
        d = _side(r, cache)
        t = twins.get(r["id"])
        if t:
            d["twin"] = _side(t, cache)
        det[r["id"]] = d
    with open(os.path.join(det_dir, day + ".json"), "w", encoding="utf-8") as f:
        json.dump({"day": day, "rows": det}, f, ensure_ascii=False, separators=(",", ":"))


def company_keys(rows, key, known):
    """filing id -> company key, for the rows the screen shows. A filing
    merged from both exchanges uses whichever side can be identified."""
    twins = {r["dup"]: r for r in rows if r.get("dup")}
    out = {}
    for r in rows:
        if r.get("dup"):
            continue
        k = key(r)
        t = twins.get(r["id"])
        if t and k not in known:
            kt = key(t)
            if kt in known:
                k = kt
        if k:
            out[r["id"]] = k
    return out


def write_companies(out, comp, last, today, seen):
    """data/companies.json: [key, name, nse, bse, bse symbol, sector, last
    filing day, suspended, other names]. Other names are the exchanges' other
    spellings and any name the company filed under in the record book (so an
    old name still finds it), already in the screen's matching form."""
    secs = sorted({e["sec"] for e in comp.values() if e.get("sec")})
    si = {s: i for i, s in enumerate(secs)}
    rows = []
    for k, e in sorted(comp.items(), key=lambda kv: kv[1]["name"].lower()):
        main = norm_name(e["name"])
        other = sorted({norm_name(n) for n in e.get("names", []) + sorted(seen.get(k, ()))} - {main, ""})
        rows.append([k, e["name"], e.get("nse") or "", e.get("bse") or "",
                     e["bsym"] if e.get("bsym") and e.get("bsym") != e.get("nse") else "",
                     si.get(e.get("sec"), -1), last.get(k, ""), 1 if e.get("susp") else 0, other])
    p = os.path.join(out, "data", "companies.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"v": 1, "day": today, "shards": SHARDS, "recent_days": RECENT_DAYS,
                   "sectors": secs, "rows": rows}, f, ensure_ascii=False, separators=(",", ":"))
    return os.path.getsize(p)


def write_recent(out, recent):
    d = os.path.join(out, "data", "recent")
    os.makedirs(d, exist_ok=True)
    parts = {}
    for k, items in recent.items():
        parts.setdefault(shard(k), {})[k] = sorted(items, key=lambda x: (x[0], x[1]), reverse=True)
    for n in range(SHARDS):
        with open(os.path.join(d, "%d.json" % n), "w", encoding="utf-8") as f:
            json.dump(parts.get(n, {}), f, ensure_ascii=False, separators=(",", ":"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--app", help="folder with the built screen (index.html etc.)")
    a = ap.parse_args()

    if os.path.exists(a.out):
        shutil.rmtree(a.out)
    if a.app and os.path.isfile(os.path.join(a.app, "index.html")):
        shutil.copytree(a.app, a.out)
    else:
        os.makedirs(a.out)
        with open(os.path.join(a.out, "index.html"), "w", encoding="utf-8") as f:
            f.write(PLACEHOLDER)

    comp = directory.merged(a.data_dir)
    key = directory.resolver(comp)
    cache = load_cache(a.data_dir)
    src_days = os.path.join(a.data_dir, "days")
    out_days = os.path.join(a.out, "data", "days")
    det_dir = os.path.join(a.out, "data", "details")
    os.makedirs(out_days, exist_ok=True)
    os.makedirs(det_dir, exist_ok=True)
    names = sorted(n for n in (os.listdir(src_days) if os.path.isdir(src_days) else [])
                   if len(n) == 15 and n.endswith(".json"))          # YYYY-MM-DD.json
    recent_from = names[-RECENT_DAYS][:10] if len(names) >= RECENT_DAYS else ""
    days, last, recent, seen = [], {}, {}, {}
    for name in names:
        day = name[:10]
        try:
            with open(os.path.join(a.data_dir, "book", name), encoding="utf-8") as f:
                book = json.load(f).get("rows", [])
        except FileNotFoundError:
            book = []
        keys = company_keys(book, key, comp)
        with open(os.path.join(src_days, name), encoding="utf-8") as f:
            d = json.load(f)
        d["rows"] = [r for r in d.get("rows", []) if r.get("sev", 0) >= 1]
        for r in d["rows"]:
            k = keys.get(r["id"])
            if k:
                r["k"] = k                 # the company, for the watchlist
                last[k] = day
                seen.setdefault(k, set()).add(r["co"])
                if day >= recent_from:
                    recent.setdefault(k, []).append(
                        [day, r["t"], r["sev"], r["dir"], r["lab"], r["line"], r["id"]])
        with open(os.path.join(out_days, name), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
        write_details(det_dir, day, book, cache)
        days.append(day)
    with open(os.path.join(out_days, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"days": days}, f, separators=(",", ":"))

    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "bse_securities.json"), encoding="utf-8") as f:
        symbols = {(x.get("scrip_id") or "").strip().upper(): x.get("Scrip_Name")
                   for x in json.load(f) if x.get("scrip_id") and x.get("Scrip_Name")}
    with open(os.path.join(a.out, "data", "symbols.json"), "w", encoding="utf-8") as f:
        json.dump(symbols, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    size = write_companies(a.out, comp, last, days[-1] if days else "", seen)
    write_recent(a.out, recent)
    print("site: %d companies (%d KB before compression), %d with filings in the last %d days"
          % (len(comp), size // 1024, len(recent), RECENT_DAYS))

    status = os.path.join(a.data_dir, "status.json")
    if os.path.isfile(status):
        shutil.copy2(status, os.path.join(a.out, "data", "status.json"))
    print("site: %d day files, status %s" % (len(days),
                                             "yes" if os.path.isfile(status) else "missing"))


if __name__ == "__main__":
    main()
