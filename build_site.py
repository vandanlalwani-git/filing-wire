#!/usr/bin/env python3
"""
Assemble the public website folder from the built screen and the record book.

Only what the screen reads is published to the website:
    data/days/<day>.json   one file per day; severity-0 "noise" is left out,
                           as the taxonomy says (raw feed only) and v5 shows
    data/days/index.json   the list of days that exist (for the date picker)
    data/status.json       freshness and per-exchange health
    data/symbols.json      trading symbol -> company name, for CSV import
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


def write_details(data_dir, out, days):
    book_dir = os.path.join(data_dir, "book")
    det_dir = os.path.join(out, "data", "details")
    os.makedirs(det_dir, exist_ok=True)
    try:
        with open(os.path.join(data_dir, "enrich_cache.json"), encoding="utf-8") as f:
            cache = json.load(f)
    except (FileNotFoundError, ValueError):
        cache = {}
    for day in days:
        p = os.path.join(book_dir, day + ".json")
        if not os.path.isfile(p):
            continue
        with open(p, encoding="utf-8") as f:
            rows = json.load(f).get("rows", [])
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

    src_days = os.path.join(a.data_dir, "days")
    out_days = os.path.join(a.out, "data", "days")
    os.makedirs(out_days, exist_ok=True)
    days = []
    if os.path.isdir(src_days):
        for name in sorted(os.listdir(src_days)):
            if len(name) == 15 and name.endswith(".json"):        # YYYY-MM-DD.json
                with open(os.path.join(src_days, name), encoding="utf-8") as f:
                    d = json.load(f)
                d["rows"] = [r for r in d.get("rows", []) if r.get("sev", 0) >= 1]
                with open(os.path.join(out_days, name), "w", encoding="utf-8") as f:
                    json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
                days.append(name[:10])
    with open(os.path.join(out_days, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"days": days}, f, separators=(",", ":"))

    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "bse_securities.json"), encoding="utf-8") as f:
        symbols = {(x.get("scrip_id") or "").strip().upper(): x.get("Scrip_Name")
                   for x in json.load(f) if x.get("scrip_id") and x.get("Scrip_Name")}
    with open(os.path.join(a.out, "data", "symbols.json"), "w", encoding="utf-8") as f:
        json.dump(symbols, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    write_details(a.data_dir, a.out, days)

    status = os.path.join(a.data_dir, "status.json")
    if os.path.isfile(status):
        shutil.copy2(status, os.path.join(a.out, "data", "status.json"))
    print("site: %d day files, status %s" % (len(days),
                                             "yes" if os.path.isfile(status) else "missing"))


if __name__ == "__main__":
    main()
