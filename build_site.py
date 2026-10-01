#!/usr/bin/env python3
"""
Assemble the public website folder from the built screen and the record book.

Only what the screen reads is published to the website:
    data/days/<day>.json   one file per day
    data/days/index.json   the list of days that exist (for the date picker)
    data/status.json       freshness and per-exchange health
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
                shutil.copy2(os.path.join(src_days, name), out_days)
                days.append(name[:10])
    with open(os.path.join(out_days, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"days": days}, f, separators=(",", ":"))

    status = os.path.join(a.data_dir, "status.json")
    if os.path.isfile(status):
        shutil.copy2(status, os.path.join(a.out, "data", "status.json"))
    print("site: %d day files, status %s" % (len(days),
                                             "yes" if os.path.isfile(status) else "missing"))


if __name__ == "__main__":
    main()
