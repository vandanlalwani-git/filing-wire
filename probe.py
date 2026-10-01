#!/usr/bin/env python3
"""
The Filing Wire - GitHub access probe

Question this answers: can GitHub's free machines reach BSE and NSE?
NSE is known to block cloud machines, and so far we have only ever
tested from a home connection.

Makes no AI calls and needs no passwords or keys. Safe to run in a
public repository. Tries each exchange three times, then writes a short
verdict to the run's summary page.
"""

import os
import time
from datetime import datetime, timedelta, timezone

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

IST = timezone(timedelta(hours=5, minutes=30))
LINES = []


def log(msg=""):
    print(msg, flush=True)
    LINES.append(str(msg))


# ----------------------------------------------------------------- BSE
def probe_bse():
    log("## BSE")
    results = []
    try:
        from bse import BSE
    except ImportError:
        log("Could not import the 'bse' package.")
        return ["error"]

    os.makedirs("bse_cache", exist_ok=True)
    for attempt in range(1, 4):
        try:
            t0 = time.time()
            with BSE(download_folder="bse_cache") as bse:
                data = bse.announcements()
            dt = time.time() - t0
            rows = data.get("Table", [])
            total = None
            try:
                total = int(data.get("Table1", [{}])[0].get("ROWCNT", 0))
            except Exception:
                pass
            log(f"- attempt {attempt}: OK, {len(rows)} rows on page 1 "
                f"(day total reported: {total}) in {dt:.2f}s")
            results.append("ok" if rows else "empty")
        except Exception as e:
            log(f"- attempt {attempt}: FAILED - {type(e).__name__}: {str(e)[:140]}")
            results.append("fail")
        time.sleep(3)
    return results


# ----------------------------------------------------------------- NSE
def nse_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    })
    # the cookie priming sequence that worked from the home connection
    s.get("https://www.nseindia.com/", timeout=20)
    time.sleep(1.5)
    s.get("https://www.nseindia.com/companies-listing/corporate-filings-announcements",
          timeout=20)
    time.sleep(1.5)
    return s


def probe_nse():
    log("\n## NSE")
    results = []
    now = datetime.now(IST)
    frm = (now - timedelta(days=1)).strftime("%d-%m-%Y")
    to = now.strftime("%d-%m-%Y")
    url = "https://www.nseindia.com/api/corporate-announcements"
    ref = "https://www.nseindia.com/companies-listing/corporate-filings-announcements"

    for attempt in range(1, 4):
        try:
            s = nse_session()
            t0 = time.time()
            r = s.get(url, params={"index": "equities", "from_date": frm, "to_date": to},
                      headers={"Referer": ref}, timeout=30)
            dt = time.time() - t0
            if r.status_code == 200:
                try:
                    data = r.json()
                    rows = data if isinstance(data, list) else data.get("data", [])
                    log(f"- attempt {attempt}: OK, {len(rows)} rows in {dt:.2f}s")
                    results.append("ok" if rows else "empty")
                except Exception:
                    log(f"- attempt {attempt}: HTTP 200 but not JSON. Start of body: "
                        f"{r.text[:120]!r}")
                    results.append("notjson")
            else:
                log(f"- attempt {attempt}: BLOCKED - HTTP {r.status_code} in {dt:.2f}s. "
                    f"Start of body: {r.text[:120]!r}")
                results.append(f"http{r.status_code}")
        except Exception as e:
            log(f"- attempt {attempt}: FAILED - {type(e).__name__}: {str(e)[:140]}")
            results.append("fail")
        time.sleep(5)
    return results


def verdict(name, res):
    good = sum(1 for x in res if x == "ok")
    if good == len(res):
        return f"{name}: WORKS ({good}/{len(res)})"
    if good == 0:
        return f"{name}: BLOCKED or broken (0/{len(res)})"
    return f"{name}: UNRELIABLE ({good}/{len(res)})"


if __name__ == "__main__":
    log(f"# Filing Wire access probe")
    log(f"Run at {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')} IST "
        f"from a GitHub-hosted machine\n")

    bse_res = probe_bse()
    nse_res = probe_nse()

    log("\n## Verdict")
    log(f"- {verdict('BSE', bse_res)}")
    log(f"- {verdict('NSE', nse_res)}")
    log("\nRun this a few times at different hours before deciding: "
        "a single pass can be lucky or unlucky.")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(LINES) + "\n")
