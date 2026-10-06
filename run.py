#!/usr/bin/env python3
"""
The Filing Wire - scheduled collector.

Runs on GitHub's free machines every few minutes. Each run reads the record
book (the `data` branch, checked out to --data-dir), fetches what is new from
BSE and NSE, classifies with the fixed rules, pairs cross-listed duplicates,
reads PDFs only where the rules say a PDF can add something, and writes the
record book back.

ZERO AI calls. Rules only.

Two kinds of run, chosen automatically from the IST clock and status.json:

  QUICK  BSE lists filings newest-first. Read page 1, 2, 3 ... and stop after
         the first page on which every filing is already in the record book
         (always at least 2 pages). NSE: one request for the whole day.
  FULL   Re-read every BSE page of the day until BSE's own day total
         (ROWCNT) is reached. Runs on the first run of each IST hour and once
         at about 23:45 IST. Between 00:00 and 01:00 IST it also re-reads
         yesterday, so late-night filings are not lost.

Nothing is ever removed from the record book by a run. A failed exchange
keeps all its existing rows; the failure is recorded in status.json.

    python run.py --data-dir <dir>                 # what the schedule runs
    python run.py --data-dir <dir> --mode full
    python run.py --data-dir <dir> --day 2026-09-15 --day 2026-09-16
"""

import argparse
import json
import logging
import os
import shutil
import signal
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from classify import classify, normalise_text                     # noqa: E402
from classify import RULES as BSE_RULES, OVERRIDES as BSE_OVERRIDES   # noqa: E402
from merge import classify_nse, norm_name, pair_rows              # noqa: E402
import events                                                      # noqa: E402
import results                                                     # noqa: E402
from merge import NSE_RULES, NSE_OVERRIDES                        # noqa: E402
from enrich import (extract_amount, extract_pledge,               # noqa: E402
                    pdf_to_text, format_amount)

from bse import BSE                                               # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# pdfminer prints a line for every odd font it meets; it is noise, not news
logging.getLogger("pdfminer").setLevel(logging.ERROR)

# GitHub's machines run on UTC. Every date and time here is IST, explicitly.
# India has no daylight saving, so a fixed offset is exact.
IST = timezone(timedelta(hours=5, minutes=30))
TS = "%Y-%m-%d %H:%M:%S"

KEEP_DAYS = 90
BSE_PAGE_SIZE = 50
BSE_PAGE_DELAY = 0.6          # seconds between BSE pages; the rule is >= 0.5
PDF_DELAY = 0.6               # seconds between PDF downloads
MAX_PDFS_PER_RUN = 40         # keeps a run short; the rest wait for the next run
PDF_MAX_ATTEMPTS = 3          # a PDF that will not download is retried, then left
HTTP_TIMEOUT = (10, 30)       # connect, read: the default for any request without one
PDF_DOWNLOAD_LIMIT = 30       # seconds for one whole PDF download, however slow the server
PDF_MAX_BYTES = 15_000_000    # bigger files are skipped, not read
PDF_PARSE_LIMIT = 20          # seconds to read text from one PDF
PDF_STAGE_LIMIT = 120         # seconds of PDF work per run; the rest wait for the next run
FULL_AT_NIGHT = (23, 40)      # the "about 23:45" full run fires from 23:40

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
NSE_API = "https://www.nseindia.com/api/corporate-announcements"
NSE_REF = ("https://www.nseindia.com/companies-listing/"
           "corporate-filings-announcements")
BSE_ATTACH_URLS = [
    "https://www.bseindia.com/xml-data/corpfiling/AttachLive/{}",
    "https://www.bseindia.com/xml-data/corpfiling/AttachHis/{}",
]

# ---- PDF fetch gates: copied verbatim from the agreed collector.py ------
BSE_AMOUNT_SUBCATS = {
    "Award of Order / Receipt of Order", "Acquisition", "Joint Venture",
    "Memorandum of Understanding /Agreements", "Raising of Funds",
    "Preferential Issue", "Qualified Institutional Placement",
    "Diversification / Disinvestment", "Issue of Securities",
}
BSE_PLEDGE_SUBCATS = {
    "Disclosures under Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011",
}
# NSE's vocabulary. Note: "Action(s) taken or orders passed" means a
# REGULATORY order, not a purchase order - deliberately not listed here.
NSE_AMOUNT_DESCS = {
    "Bagging/Receiving of orders/contracts", "Awarding of order(s)/contract(s)",
    "Acquisition", "Agreements", "Memorandum of Understanding/Agreements",
    "Amalgamation/Merger", "Diversification/Disinvestment",
    "Issue of Securities", "Qualified Institutional Placement",
    "Rights Issue", "Allotment of Securities", "Sale or disposal",
    "Arrangements for strategic, technical, manufacturing, or marketing tie up",
}
# NSE has no Reg 31 encumbrance category; SAST disclosures arrive here.
NSE_PLEDGE_DESCS = {"Disclosure under SEBI Takeover Regulations"}
# ------------------------------------------------------------------------


# =================================================================== HTTP
class Counter:
    """Counts every HTTP request this process makes, by host. Installed once;
    each run reads the difference, so many runs in one process add up right."""

    def __init__(self):
        self.by_host = {}
        orig = requests.sessions.Session.request
        counter = self

        def counted(session, method, url, *a, **kw):
            host = url.split("/")[2] if "://" in url else url
            counter.by_host[host] = counter.by_host.get(host, 0) + 1
            # no request ever goes out without a timeout, whatever library sent it
            if kw.get("timeout") is None:
                kw["timeout"] = HTTP_TIMEOUT
            return orig(session, method, url, *a, **kw)

        requests.sessions.Session.request = counted

    def snapshot(self):
        return dict(self.by_host)

    def since(self, snap):
        return {h: n - snap.get(h, 0) for h, n in self.by_host.items()
                if n - snap.get(h, 0)}


COUNTER = Counter()


# ============================================================ reference
def load_reference():
    with open(os.path.join(HERE, "sector_map.json"), encoding="utf-8") as f:
        sectors = json.load(f)
    scrip = {}
    with open(os.path.join(HERE, "bse_securities.json"), encoding="utf-8") as f:
        for s in json.load(f):
            scrip[str(s.get("SCRIP_CD"))] = {
                "sym": (s.get("scrip_id") or "").strip().upper(),
                "isin": s.get("ISIN_NUMBER") or None,
            }
    return sectors, scrip


# =================================================================== rows
def _subject(raw):
    """BSE's subject line is 'Company - code - Category-Subcategory'; keep the part
    after the company name and code."""
    s = normalise_text(raw.get("NEWSSUB"))
    parts = s.split(" - ", 2)
    return parts[2] if len(parts) == 3 else s


def _why_bse(raw, c):
    """How classify() decided: a headline phrase, or the category the company chose."""
    if c.get("matched_by") == "headline-override":
        h = normalise_text(raw.get("HEADLINE"))
        for rx, _ in BSE_OVERRIDES:
            m = rx.search(h)
            if m:
                return {"by": "phrase", "text": m.group(0)}
    return {"by": "category", "text": (raw.get("SUBCATNAME") or "").strip() or "(none)"}


def _why_nse(raw):
    """Same for classify_nse(): mirrors its override loop exactly."""
    desc = (raw.get("desc") or "").strip()
    text = (raw.get("attchmntText") or "").strip()
    base = NSE_RULES.get(desc) or {"sev": 1}
    for rx, ov in NSE_OVERRIDES:
        m = rx.search(text) or rx.search(desc)
        if m:
            if ov["sev"] >= base["sev"]:
                return {"by": "phrase", "text": m.group(0)}
            break
    return {"by": "category", "text": desc or "(none)"}


def row_from_bse(raw, sectors, scrip):
    ts = (raw.get("NEWS_DT") or raw.get("DT_TM") or "").replace("T", " ")[:19]
    if len(ts) != 19:
        return None
    c = classify(raw)
    ref = scrip.get(str(raw.get("SCRIP_CD")), {})
    return {
        "id": "BSE:" + str(raw.get("NEWSID")),
        "src": "BSE",
        "ts": ts,
        "t": ts[11:16],
        "co": (raw.get("SLONGNAME") or "").replace(" Ltd", "").replace("-$", "").strip(),
        "ck": norm_name(raw.get("SLONGNAME")),
        "sc": str(raw.get("SCRIP_CD") or "") or None,
        "isin": ref.get("isin"),
        "sec": sectors.get(ref.get("sym") or "", "Other"),
        "sev": c["sev"], "dir": c["dir"], "dc": c["dir"], "lab": c["label"], "line": c["line"],
        "sub": (raw.get("SUBCATNAME") or "").strip(),
        "att": raw.get("ATTACHMENTNAME") or None,
        "hl": normalise_text(raw.get("HEADLINE")),          # full, as BSE sends it
        "subj": _subject(raw),
        "cat": (raw.get("CATEGORYNAME") or "").strip(),
        "why": _why_bse(raw, c),
    }


def row_from_nse(raw, sectors):
    ts = (raw.get("sort_date") or "").strip()[:19]
    if len(ts) != 19:
        try:
            ts = datetime.strptime((raw.get("an_dt") or "").strip(),
                                   "%d-%b-%Y %H:%M:%S").strftime(TS)
        except ValueError:
            return None
    c = classify_nse(raw)
    sym = (raw.get("symbol") or "").strip().upper()
    return {
        "id": "NSE:" + str(raw.get("seq_id")),
        "src": "NSE",
        "ts": ts,
        "t": ts[11:16],
        "co": c["co"],
        "ck": norm_name(raw.get("sm_name")),
        "isin": raw.get("sm_isin") or None,
        "sec": sectors.get(sym, "Other"),
        "sev": c["sev"], "dir": c["dir"], "dc": c["dir"], "lab": c["label"], "line": c["line"],
        "sub": (raw.get("desc") or "").strip(),
        "att": raw.get("attchmntFile") or None,
        "hl": normalise_text(raw.get("attchmntText")),      # full, as NSE sends it
        "why": _why_nse(raw),
    }


# ================================================================== fetch
def _bse_day(b, day, page):
    dt = datetime.strptime(day, "%Y-%m-%d")
    data = b.announcements(page_no=page, from_date=dt, to_date=dt)
    rows = data.get("Table", []) or []
    rowcnt = None
    try:
        rowcnt = int((data.get("Table1") or [{}])[0].get("ROWCNT"))
    except (TypeError, ValueError, IndexError):
        pass
    return rows, rowcnt


def fetch_bse(day, known, full, log):
    """
    Returns (raw_rows, info). Never raises: a failure is reported in info and
    whatever was read before it is still returned.

    known: ids already in the record book before this run (quick-run stop rule).
    """
    info = {"pages": 0, "rowcnt": None, "unique": 0, "ok": True, "error": None,
            "stopped": None}
    seen, out = set(), []
    tmp = tempfile.mkdtemp(prefix="bsecache_")
    try:
        with BSE(download_folder=tmp) as b:
            page = 1
            while True:
                if page > 1:
                    time.sleep(BSE_PAGE_DELAY)
                try:
                    rows, rowcnt = _bse_day(b, day, page)
                except Exception as e:                        # network, 429, bad JSON
                    info.update(ok=False, error="%s: %s" % (type(e).__name__, str(e)[:200]),
                                stopped="error on page %d" % page)
                    break
                info["pages"] = page
                if rowcnt is not None:
                    info["rowcnt"] = rowcnt                    # keep the latest figure
                fresh_on_page = 0
                for r in rows:
                    nid = "BSE:" + str(r.get("NEWSID"))
                    if nid in seen:
                        continue                               # page drift while reading
                    seen.add(nid)
                    out.append(r)
                    if nid not in known:
                        fresh_on_page += 1
                target = info["rowcnt"]

                if not rows:
                    if target and len(seen) < target:
                        info.update(ok=False, stopped="empty page %d before day total" % page,
                                    error="BSE returned an empty page %d with %d of %d rows read"
                                          % (page, len(seen), target))
                    else:
                        info["stopped"] = "end of day"
                    break
                if target is not None and len(seen) >= target:
                    info["stopped"] = "reached day total"
                    break
                if len(rows) < BSE_PAGE_SIZE:
                    info["stopped"] = "last page"
                    break
                if not full and page >= 2 and fresh_on_page == 0:
                    info["stopped"] = "quick: page %d all known" % page
                    break
                if target and page > target // BSE_PAGE_SIZE + 5:
                    info.update(ok=False, stopped="page limit",
                                error="read %d pages without reaching day total %s"
                                      % (page, target))
                    break
                page += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    info["unique"] = len(seen)
    log("  BSE %s %s: %d pages, %d rows, day total %s, %s"
        % ("full" if full else "quick", day, info["pages"], info["unique"],
           info["rowcnt"], info["stopped"]))
    return out, info


def bse_pdf_session():
    """PDFs on bseindia.com are fetched with exactly the headers the pinned
    bse library sends. BSE refuses (HTTP 403) cloud machines that present an
    outdated browser identity, so this must stay in step with the library."""
    s = requests.Session()
    tmp = tempfile.mkdtemp(prefix="bsehdr_")
    try:
        with BSE(download_folder=tmp) as b:
            s.headers.update(dict(b.session.headers))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return s


def nse_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    })
    s.get("https://www.nseindia.com/", timeout=20)
    time.sleep(1.5)
    s.get(NSE_REF, timeout=20)
    time.sleep(1.5)
    return s


def fetch_nse(session, first_day, last_day, log):
    """One request for the whole range. DD-MM-YYYY, snake_case params only:
    camelCase fromDate/toDate silently returns just 20 rows."""
    info = {"requests": 1, "returned": 0, "ok": True, "error": None}
    d1 = datetime.strptime(first_day, "%Y-%m-%d").strftime("%d-%m-%Y")
    d2 = datetime.strptime(last_day, "%Y-%m-%d").strftime("%d-%m-%Y")
    try:
        r = session.get(NSE_API, params={"index": "equities",
                                         "from_date": d1, "to_date": d2},
                        headers={"Referer": NSE_REF}, timeout=40)
        if r.status_code != 200:
            raise RuntimeError("HTTP %d" % r.status_code)
        data = r.json()
        rows = data if isinstance(data, list) else data.get("data", [])
    except Exception as e:
        info.update(ok=False, error="%s: %s" % (type(e).__name__, str(e)[:200]))
        log("  NSE %s..%s: FAILED %s" % (first_day, last_day, info["error"]))
        return [], info
    info["returned"] = len(rows)
    log("  NSE %s..%s: %d rows" % (first_day, last_day, len(rows)))
    return rows, info


# ============================================================ enrichment
def wants_pdf(row):
    """(want_amount, want_pledge) - the only two things enrich.py can add.
    Same rule as collector.py, read off this row's own fields."""
    if row["sev"] < 2 or not row.get("att"):
        return False, False
    sub = row.get("sub", "")
    if row["src"] == "BSE":
        return (sub in BSE_AMOUNT_SUBCATS or row["lab"] in ("Order win", "Acquisition"),
                sub in BSE_PLEDGE_SUBCATS)
    return sub in NSE_AMOUNT_DESCS, sub in NSE_PLEDGE_DESCS


def wants_events(row):
    """Notable/Critical rows whose own text names no decisive event: the PDF
    may (events.py reads its first pages)."""
    return ((row["sev"] >= 2 or (row["sev"] >= 1 and events.low_sev_pdf(row)))
            and bool(row.get("att")) and not events.is_pledge_pdf(row)
            and events.needs_pdf(row))


def cache_key(row):
    att = row["att"]
    if row["src"] == "NSE":
        att = att.rsplit("/", 1)[-1]
    return row["src"] + ":" + att


def download_pdf(row, bse_sess, nse_sess, tmpdir):
    """The PDF on disk, or None. Never takes longer than PDF_DOWNLOAD_LIMIT per
    address tried: a server that trickles bytes is cut off, not waited for."""
    urls = ([u.format(row["att"]) for u in BSE_ATTACH_URLS] if row["src"] == "BSE"
            else [row["att"]])
    sess = bse_sess if row["src"] == "BSE" else nse_sess
    for url in urls:
        try:
            kw = {"headers": {"Referer": NSE_REF}} if row["src"] == "NSE" else {}
            start = time.time()
            with sess.get(url, timeout=(10, 20), stream=True, **kw) as r:
                if r.status_code != 200:
                    continue
                buf = bytearray()
                for chunk in r.iter_content(65536):
                    buf += chunk
                    if time.time() - start > PDF_DOWNLOAD_LIMIT or len(buf) > PDF_MAX_BYTES:
                        buf = None
                        break
            if buf and buf[:4] == b"%PDF":
                path = os.path.join(tmpdir, "doc.pdf")
                with open(path, "wb") as f:
                    f.write(buf)
                return path
        except requests.RequestException:
            continue
    return None


class _Overtime(Exception):
    pass


def _with_limit(seconds, fn, *a):
    """Run fn, giving up after `seconds` (Linux/macOS main thread; elsewhere
    it simply runs)."""
    if not hasattr(signal, "SIGALRM") or threading.current_thread() is not threading.main_thread():
        return fn(*a)

    def _stop(*_):
        raise _Overtime()
    old = signal.signal(signal.SIGALRM, _stop)
    signal.alarm(seconds)
    try:
        return fn(*a)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def read_pdf(path, want_amount, want_pledge, row=None):
    """Same order and thresholds as collector.py's enrich_event. For a
    Notable/Critical row the events found on the first pages are kept too."""
    text = pdf_to_text(path)
    if len(text) < 50:                      # scanned, ~4% of filings
        return {"s": "scanned"}
    ev = (events.scan_pdf(row, text) if row is not None
          and (row["sev"] >= 2 or events.low_sev_pdf(row)) else None)
    out = {"s": "no_match"}
    if want_pledge:
        pl = extract_pledge(path)
        if pl:
            out = {"s": "pledge", "pl": {"event": pl["event"], "dir": pl["dir"],
                                         "label": pl["label"]}}
    if out["s"] == "no_match" and want_amount:
        amt = extract_amount(text)
        if amt:
            out = {"s": "amount", "amt": amt["crore"]}
    if ev is not None:
        out["ev"] = ev
    return out


def apply_enrichment(row, entry):
    """Idempotent: an amount is rebuilt from the label, a pledge replaces
    the fields outright, so applying twice gives the same row."""
    if not entry:
        return
    if entry.get("s") == "pledge":
        pl = entry["pl"]
        row["dir"], row["lab"], row["line"] = pl["dir"], pl["label"], pl["label"]
        row["why"] = {"by": "pdf", "text": pl["label"]}
    elif entry.get("s") == "amount":
        row["amt"] = entry["amt"]
        row["line"] = "%s - %s" % (row["lab"], format_amount(entry["amt"]))


def reapply_cached(rows, days, cache):
    """Hidden duplicates are never downloaded, but if their PDF was already read
    (while they were shown, or by their twin's run) keep that result on them:
    the screen shows the other exchange's version when a row is expanded."""
    for r in rows:
        if not r.get("dup_of") or r["ts"][:10] not in days:
            continue
        want_amount, want_pledge = wants_pdf(r)
        if want_amount or want_pledge:
            e = cache.get(cache_key(r))
            if e and e.get("s") in ("amount", "pledge"):
                apply_enrichment(r, e)


def enrich(shown, cache, bse_sess, nse_sess, budget, enabled, log):
    stats = {"eligible": 0, "cache_hits": 0, "downloads": 0, "download_failed": 0,
             "deferred": 0}
    tmpdir = tempfile.mkdtemp(prefix="pdf_")
    stage_start = time.time()
    try:
        for row in shown:
            want_amount, want_pledge = wants_pdf(row)
            want_ev = wants_events(row)
            if not (want_amount or want_pledge or want_ev):
                continue
            stats["eligible"] += 1
            key = cache_key(row)
            entry = cache.get(key)
            done = entry and (entry["s"] != "fetch_failed" or entry.get("n", 0) >= PDF_MAX_ATTEMPTS)
            # an entry read before events.py existed has no "ev"; read it again
            # once, unless the PDF can never give text
            if done and want_ev and "ev" not in entry and entry["s"] in ("amount", "pledge", "no_match"):
                done = False
            if done:
                stats["cache_hits"] += 1
                apply_enrichment(row, entry)
                continue
            ext = row["att"].rsplit(".", 1)[-1].lower() if "." in row["att"] else ""
            if ext and ext != "pdf":
                # NSE sometimes attaches a .zip; it can never be read as a PDF,
                # so record that once instead of downloading it at all
                cache[key] = {"s": "not_pdf", "d": row["ts"][:10]}
                stats["cache_hits"] += 1
                continue
            if (not enabled or stats["downloads"] + stats["download_failed"] >= budget
                    or time.time() - stage_start > PDF_STAGE_LIMIT):
                stats["deferred"] += 1
                continue
            if stats["downloads"] + stats["download_failed"]:
                time.sleep(PDF_DELAY)
            path = download_pdf(row, bse_sess, nse_sess, tmpdir)
            if not path:
                n = (entry or {}).get("n", 0) + 1
                cache[key] = {"s": "fetch_failed", "n": n, "d": row["ts"][:10]}
                stats["download_failed"] += 1
                continue
            try:
                result = _with_limit(PDF_PARSE_LIMIT, read_pdf, path, want_amount, want_pledge, row)
            except _Overtime:
                # counted as a failed attempt: tried again in a later run, up to
                # PDF_MAX_ATTEMPTS, never allowed to hold this run up
                result = {"s": "fetch_failed", "n": (entry or {}).get("n", 0) + 1,
                          "err": "took too long to read"}
            except Exception as e:
                result = {"s": "unreadable", "err": type(e).__name__}
            finally:
                os.remove(path)
            result["d"] = row["ts"][:10]
            cache[key] = result
            stats["downloads"] += 1
            apply_enrichment(row, result)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    log("  PDFs: %d eligible, %d from cache, %d downloaded, %d failed, %d deferred"
        % (stats["eligible"], stats["cache_hits"], stats["downloads"],
           stats["download_failed"], stats["deferred"]))
    return stats


# ============================================================ record book
def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


# Two files per day:
#   book/<day>.json  the record book: every filing, duplicates included, with
#                    what later runs need (matching key, ISIN, subcategory,
#                    attachment, first-seen time, which run found it)
#   days/<day>.json  what the screen reads: shown filings only, v5's fields
BOOK_FIELDS = ("id", "src", "ts", "co", "ck", "sc", "isin", "sec", "sev", "sev0", "dir", "dc", "lab",
               "line", "amt", "sub", "att", "fs", "by", "hl", "subj", "cat", "why")
SCREEN_FIELDS = ("id", "t", "ts", "co", "sec", "sev", "dir", "lab", "line")


def load_day(data_dir, day):
    rows = _read(os.path.join(data_dir, "book", day + ".json"), {}).get("rows", [])
    for r in rows:
        r.pop("dup", None)
        r["t"] = r["ts"][11:16]
    return rows


def save_day(data_dir, day, rows):
    book, screen = [], []
    for r in sorted(rows, key=lambda x: (x["ts"], x["id"])):
        b = {k: r[k] for k in BOOK_FIELDS if r.get(k) is not None}
        if r.get("dup_of"):
            b["dup"] = r["dup_of"]
        else:
            screen.append({k: r[k] for k in SCREEN_FIELDS})
        book.append(b)
    _write(os.path.join(data_dir, "book", day + ".json"), {"day": day, "rows": book})
    _write(os.path.join(data_dir, "days", day + ".json"), {"day": day, "rows": screen})
    return len(screen), len(book) - len(screen)


def prune(data_dir, today, cache):
    cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    removed = 0
    for sub in ("days", "book"):
        d = os.path.join(data_dir, sub)
        if os.path.isdir(d):
            for name in os.listdir(d):
                if name[:10] < cutoff:
                    os.remove(os.path.join(d, name))
                    removed += 1
    for k in [k for k, v in cache.items() if v.get("d", "9999") < cutoff]:
        del cache[k]
    return removed


# =========================================================== run planning
def plan(now, status, mode, with_yesterday=False):
    """Quick or full, and which days. Pure function of the clock and status."""
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    if mode == "auto":
        last = status.get("last_full_run_ist")
        last_dt = datetime.strptime(last, TS).replace(tzinfo=IST) if last else None
        night = now.replace(hour=FULL_AT_NIGHT[0], minute=FULL_AT_NIGHT[1],
                            second=0, microsecond=0)
        full = (last_dt is None
                or last_dt.strftime("%Y-%m-%d %H") != now.strftime("%Y-%m-%d %H")
                or (now >= night and last_dt < night))
    else:
        full = mode == "full"
    # a day whose last BSE read was refused part-way is read in full next time
    # (not more often than every 10 minutes, so a BSE that is refusing us is
    # not asked for whole days every 5 minutes)
    retry = [d for d in status.get("bse_retry_days", []) if d in (yesterday, today)]
    last = status.get("last_full_run_ist")
    rested = not last or now - datetime.strptime(last, TS).replace(tzinfo=IST) >= timedelta(minutes=10)
    if retry and mode == "auto" and rested:
        full = True
    days = [yesterday, today] if (full and (now.hour == 0 or with_yesterday or yesterday in retry)) else [today]
    return ("full" if full else "quick"), days


# =================================================================== main
def run(data_dir, mode="auto", backfill_days=None, enrich_on=True, now=None,
        max_pdfs=MAX_PDFS_PER_RUN, log=print, with_yesterday=False):
    global RARE_DATA_DIR
    RARE_DATA_DIR = data_dir
    t0 = time.time()
    snap = COUNTER.snapshot()
    now = now or datetime.now(IST)
    now_s = now.strftime(TS)
    sectors, scrip = load_reference()
    status = _read(os.path.join(data_dir, "status.json"), {})
    cache = _read(os.path.join(data_dir, "enrich_cache.json"), {})

    if backfill_days:
        kind, days = "backfill", sorted(backfill_days)
    else:
        kind, days = plan(now, status, mode, with_yesterday)
    full = kind in ("full", "backfill")
    log("%s run at %s IST for %s" % (kind.upper(), now_s, ", ".join(days)))

    # 1. record book for these days, plus the day before as pairing context
    context_day = (datetime.strptime(days[0], "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    book = {}
    for d in [context_day] + days:
        for r in load_day(data_dir, d):
            book[r["id"]] = r
    known = set(book)

    # 2. fetch
    fetched, ex = [], {}
    bse_info = {}
    for d in days:
        raws, info = fetch_bse(d, known, full, log)
        bse_info[d] = info
        fetched += [x for x in (row_from_bse(r, sectors, scrip) for r in raws) if x]
    ex["BSE"] = {"ok": all(i["ok"] for i in bse_info.values()),
                 "error": "; ".join(i["error"] for i in bse_info.values() if i["error"]) or None,
                 "pages": sum(i["pages"] for i in bse_info.values()),
                 "by_day": bse_info}

    nse_rows, nse_info = [], {"ok": False, "error": None, "returned": 0}
    nse_sess = None
    try:
        nse_sess = nse_session()
        nse_rows, nse_info = fetch_nse(nse_sess, days[0], days[-1], log)
    except Exception as e:
        nse_info.update(ok=False, error="priming: %s: %s" % (type(e).__name__, str(e)[:200]))
        log("  NSE: FAILED %s" % nse_info["error"])
    fetched += [x for x in (row_from_nse(r, sectors) for r in nse_rows) if x]
    ex["NSE"] = nse_info

    # 3. union with the book; nothing is ever dropped. First sighting is kept.
    loaded = {context_day} | set(days)
    new_ids = []
    for r in fetched:
        d = r["ts"][:10]
        if d not in loaded:
            # a filing dated some other day: load that whole day first, or
            # writing it back would replace the day with this one row
            for old in load_day(data_dir, d):
                book.setdefault(old["id"], old)
                known.add(old["id"])
            loaded.add(d)
        old = book.get(r["id"])
        if old:
            r["fs"], r["by"] = old.get("fs"), old.get("by")
        else:
            r["fs"], r["by"] = now_s, kind
            new_ids.append(r["id"])
        book[r["id"]] = r                       # fresh classification wins
    # write the days this run covers, plus any day that gained a filing
    touched = set(days) | {book[i]["ts"][:10] for i in new_ids}

    # 4. pair duplicates, one-to-one, over everything loaded
    rows = list(book.values())
    _pair_inplace(rows)

    # 5. PDFs, only for rows the screen will show
    bse_sess = bse_pdf_session()
    shown = [r for r in rows if not r.get("dup_of") and r["ts"][:10] in touched]
    pdf = enrich(shown, cache, bse_sess, nse_sess or bse_sess, max_pdfs, enrich_on, log)
    reapply_cached(rows, touched, cache)
    rcache = _read(os.path.join(data_dir, RESULTS_CACHE), {})
    if enrich_on and "RESULTS" in events.LIVE:
        results_stage(shown, rcache, bse_sess, now, log)
    colour(rows, touched, cache, rcache)

    # 6. write
    written = {}
    for d in sorted(touched):
        written[d] = save_day(data_dir, d, [r for r in rows if r["ts"][:10] == d])
    today = now.strftime("%Y-%m-%d")
    pruned = prune(data_dir, today, cache) if not backfill_days else 0
    if not backfill_days:
        cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
        for k in [k for k, v in rcache.items() if v.get("d", "9999") < cutoff]:
            del rcache[k]
    _write(os.path.join(data_dir, "enrich_cache.json"), cache)
    _write(os.path.join(data_dir, RESULTS_CACHE), rcache)

    runtime = round(time.time() - t0, 1)
    used = COUNTER.since(snap)
    metrics = {"kind": kind, "days": days, "runtime_s": runtime,
               "requests": used, "requests_total": sum(used.values()),
               "bse_pages": ex["BSE"]["pages"], "new_rows": len(new_ids),
               "written": written, "pdf": pdf, "pruned_files": pruned}

    if not backfill_days:
        prev = status.get("exchanges", {})
        exchanges = {}
        for name in ("BSE", "NSE"):
            e = ex[name]
            today_rows = [r for r in rows if r["src"] == name and r["ts"][:10] == today]
            exchanges[name] = {
                "ok": bool(e["ok"]),
                "error": e.get("error"),
                "rows_today": len(today_rows),
                "last_ok_ist": now_s if e["ok"] else prev.get(name, {}).get("last_ok_ist"),
            }
        # "checked" is what the screen's "Updated N min ago" shows: the last
        # time at least one exchange was actually read. A quiet run with
        # nothing new still counts; a run where both exchanges failed does not.
        if ex["BSE"]["ok"] or ex["NSE"]["ok"]:
            checked = now_s
        else:
            checked = status.get("checked_ist") or max(
                [e.get("last_ok_ist") for e in prev.values() if e.get("last_ok_ist")] or [None],
                key=lambda x: x or "")
        last_new = now_s if new_ids else status.get("last_new_ist")
        # BSE refusals: counted per IST day; a refused day is re-read in full
        blocks = {k: v for k, v in status.get("bse_blocks", {}).items()
                  if k >= (now - timedelta(days=14)).strftime("%Y-%m-%d")}
        retry = set(status.get("bse_retry_days", []))
        for d, info in bse_info.items():
            if info["ok"]:
                if full:
                    retry.discard(d)
            else:
                blocks[today] = blocks.get(today, 0) + 1
                retry.add(d)
        retry = sorted(d for d in retry if d >= (now - timedelta(days=1)).strftime("%Y-%m-%d"))
        _write(os.path.join(data_dir, "status.json"), {
            "updated_ist": now_s,                      # last attempt, success or not
            "updated_utc": _utc(now_s),
            "checked_ist": checked,                    # last successful check
            "checked_utc": _utc(checked),
            "last_new_ist": last_new,                  # last time a new filing arrived
            "last_new_utc": _utc(last_new),
            "run": kind,
            "days": days,
            "last_full_run_ist": now_s if kind == "full" else status.get("last_full_run_ist"),
            "exchanges": exchanges,
            "bse_blocks": blocks,          # refused/failed BSE reads per IST day
            "bse_retry_days": retry,       # days to read in full on the next run
            "runtime_s": runtime,
            "requests": sum(used.values()),
            "new_rows": len(new_ids),
        })
    log("  done: %d new, %d requests, %.1fs" % (len(new_ids), sum(used.values()), runtime))
    return metrics, ex


def _utc(ist):
    """'YYYY-MM-DD HH:MM:SS' in IST -> 'YYYY-MM-DDTHH:MM:SSZ', or None."""
    if not ist:
        return None
    return (datetime.strptime(ist, TS).replace(tzinfo=IST)
            .astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))


def _pair_inplace(rows):
    """Run merge.pair_rows on the record-book rows and copy the result back."""
    view = [{"uid": r["id"], "source": r["src"], "company_key": r.get("ck"),
             "filed_at": r["ts"], "sev": r["sev"], "isin": r.get("isin"),
             "lab": r.get("lab"), "ev": events.text_events(r)} for r in rows]
    pair_rows(view)
    for r, v in zip(rows, view):
        r["dup_of"] = v["dup_of"]


def _why(out):
    return {k: out[k] for k in ("rule", "event", "text", "reason", "by") if out.get(k)}


def colour(rows, days, cache, rcache=None):
    """
    Decide each row's colour from its own words (events.py). Rows of `days`
    only; other rows keep what they have. The category direction stays in
    "dc" so this can be re-run any number of times with the same result.
    """
    index = {r["id"]: r for r in rows}
    mine = [r for r in rows if r["ts"][:10] in days]
    for r in mine:
        if "dc" not in r:                     # filed before events.py existed
            r["dc"] = "neutral" if events.is_pledge_pdf(r) else r["dir"]
        entry = cache.get(cache_key(r)) if r.get("att") else None
        info = (entry or {}).get("ev")
        if info is None and entry and (entry["s"] in ("scanned", "not_pdf", "unreadable")
                                       or (entry["s"] == "fetch_failed"
                                           and entry.get("n", 0) >= PDF_MAX_ATTEMPTS)):
            info = {"hits": [], "blocks": []}   # can never give text: nothing in it
        out = events.decide(r, pdf_info=info)
        res = result_outcome(r, rcache)
        if res is not None:
            out = res
        r["dir"], r["why"] = out["dir"], _why(out)
        # a routine-looking filing the rules colour (an independent director
        # resigning over governance concerns) is shown as Notable; "sev0"
        # keeps the exchange-category severity so re-colouring can undo it
        if out["dir"] != "neutral" and r["sev"] < 2:
            r.setdefault("sev0", r["sev"])
            r["sev"] = 2
        elif "sev0" in r and out["dir"] == "neutral":
            r["sev"] = r.pop("sev0")
        lab = events.better_label(r, out.get("rules") or [])
        if lab:
            if r.get("line", "").startswith(r["lab"]):
                r["line"] = lab + r["line"][len(r["lab"]):]
            r["lab"] = lab
    log_rare(rows, mine)
    # the two halves of a merged pair must not point opposite ways
    for r in mine:
        k = index.get(r.get("dup_of"))
        if k is not None and events.pair_conflict(k, r):
            for x in (k, r):
                x["dir"], x["why"] = "neutral", _why(events.PAIR_CONFLICT)


RESULTS_CACHE = "results_cache.json"
RESULTS_PER_RUN = 40            # results filings looked up per run
RESULTS_STAGE_LIMIT = 90        # seconds of results lookups per run
RESULTS_RETRY_MIN = 20          # minutes between tries while BSE has no figures yet
RESULTS_MAX_TRIES = 12


def _rkey(r):
    y, mo = results.quarter_end(r)
    return "%s|%s" % (r.get("sc"), results.qcode(y, mo))


def results_stage(shown, rcache, sess, now, log):
    """Look up structured figures for new results filings (BSE's own data,
    current quarter and the same quarter a year earlier). Figures that are
    not out yet are tried again later, up to RESULTS_MAX_TRIES times."""
    t0, done, found = time.time(), 0, 0
    sess.headers.setdefault("Referer", "https://www.bseindia.com/")
    for r in shown:
        if not results.is_result(r) or r["sev"] < 2 or not r.get("sc"):
            continue
        k = _rkey(r)
        e = rcache.get(k) or {}
        if e.get("final"):
            continue
        last = e.get("t")
        if last and (now - datetime.strptime(last, TS).replace(tzinfo=IST)).total_seconds() < RESULTS_RETRY_MIN * 60:
            continue
        if done >= RESULTS_PER_RUN or time.time() - t0 > RESULTS_STAGE_LIMIT:
            break
        done += 1
        try:
            basis, cur, ly = results.fetch(sess, r["sc"], k.split("|")[1])
        except Exception as ex:                       # network trouble: try later
            rcache[k] = dict(e, t=now.strftime(TS), n=e.get("n", 0) + 1, err=type(ex).__name__)
            continue
        n = e.get("n", 0) + 1
        rcache[k] = {"b": basis, "c": cur, "l": ly, "t": now.strftime(TS), "n": n,
                     "d": r["ts"][:10], "final": bool(cur) or n >= RESULTS_MAX_TRIES}
        found += bool(cur)
    if done:
        log("  results: %d looked up, %d with figures" % (done, found))


def result_outcome(r, rcache):
    """The results rule's decision for a results filing, or None to leave
    the row to the word rules."""
    if not rcache or not results.is_result(r) or not r.get("sc"):
        return None
    e = rcache.get(_rkey(r))
    if not e or not e.get("final"):
        return None
    j = results.judge(e.get("b"), e.get("c"), e.get("l"))
    out = {"dir": j["dir"], "rule": "RESULTS", "event": results.EVENT, "text": j.get("text"),
           "reason": j.get("reason"), "by": "data"}
    if out["dir"] != "neutral" and "RESULTS" not in events.LIVE:
        out = dict(out, dir="neutral", reason="%s: not coloured yet - this rule is still being tested" % results.EVENT)
    return out


RARE_LOG = "rare_rules_log.json"
RARE_DATA_DIR = None             # set by run()/repair(): where the log is kept


def _link(r):
    att = r.get("att") or ""
    if r["src"] == "BSE" and att:
        return "https://www.bseindia.com/xml-data/corpfiling/AttachLive/" + att
    return att if att.startswith("http") else ""


def log_rare(rows, mine):
    """Every time a rare rule (events.RARE) colours a filing, keep a line for
    the owner's weekly review: date, company, phrase, link. A rule found wrong
    is switched off."""
    if not RARE_DATA_DIR:
        return
    path = os.path.join(RARE_DATA_DIR, RARE_LOG)
    log = _read(path, [])
    seen = {e["id"] for e in log}
    added = False
    for r in mine:
        w = r.get("why") or {}
        if w.get("rule") in events.RARE and r["dir"] != "neutral" and r["id"] not in seen \
                and not r.get("dup_of"):
            log.append({"id": r["id"], "date": r["ts"][:16], "company": r["co"],
                        "rule": w["rule"], "colour": r["dir"], "phrase": w.get("text"),
                        "link": _link(r)})
            seen.add(r["id"])
            added = True
    if added:
        _write(path, sorted(log, key=lambda e: e["date"]))


# ================================================================ backfill
BACKFILL_DAY_PAUSE = 5          # seconds between days, on top of page delays


def backfill(data_dir, first, last, log=print, progress="backfill.json"):
    """
    One-time history load, day by day, oldest first. Gentle: the normal page
    delay, a pause between days, no PDFs. Resumable: days already confirmed
    complete in book/backfill.json are skipped. Stops at the first BSE error
    instead of pushing through.

    Returns 0 when every day is done, 3 when it stopped early.
    """
    prog_path = os.path.join(data_dir, "book", progress)
    prog = _read(prog_path, {})
    d0 = datetime.strptime(first, "%Y-%m-%d")
    d1 = datetime.strptime(last, "%Y-%m-%d")
    if d1 < d0:
        raise SystemExit("backfill: end date is before start date")
    total_req, stopped = 0, False
    day = d0
    while day <= d1:
        d = day.strftime("%Y-%m-%d")
        day += timedelta(days=1)
        if prog.get(d, {}).get("complete"):
            log("%s already complete, skipped" % d)
            continue
        metrics, ex = run(data_dir, backfill_days=[d], enrich_on=False, log=log)
        info = ex["BSE"]["by_day"][d]
        rows = load_day(data_dir, d)
        saved = {x: sum(1 for r in rows if r["src"] == x) for x in ("BSE", "NSE")}
        complete = bool(info["ok"] and ex["NSE"]["ok"]
                        and info["rowcnt"] is not None and saved["BSE"] == info["rowcnt"]
                        and saved["NSE"] == ex["NSE"]["returned"])
        prog[d] = {"bse_total": info["rowcnt"], "bse_saved": saved["BSE"],
                   "nse_returned": ex["NSE"]["returned"], "nse_saved": saved["NSE"],
                   "requests": metrics["requests_total"], "complete": complete,
                   "error": info["error"] or ex["NSE"].get("error")}
        total_req += metrics["requests_total"]
        _write(prog_path, prog)
        log("  %s: BSE saved %s of %s, NSE saved %s of %s -> %s"
            % (d, saved["BSE"], info["rowcnt"], saved["NSE"], ex["NSE"]["returned"],
               "complete" if complete else "NOT complete"))
        if not info["ok"] or not ex["NSE"]["ok"]:
            log("backfill: an exchange returned errors on %s - stopping here; "
                "run it again later and it resumes from this day" % d)
            stopped = True
            break
        time.sleep(BACKFILL_DAY_PAUSE)
    log("backfill: %d requests this session" % total_req)
    return 3 if stopped else 0


# ================================================================== repair
REPAIR_PDF_BUDGET = 900         # PDFs one repair run may read, gently, for rule checks


def repair(data_dir, first, last, log=print, fetch=True):
    """
    Re-pair and re-colour past days from the record book after a rule change.
    Nothing is fetched from the exchanges' announcement lists. The only
    network use: PDFs that were never read of filings whose colour waits on a
    PDF check (events.PDF_CHECK) or that the exchanges rate routine but whose
    PDF can change the picture (events.low_sev_pdf), at the normal polite pace.
    Each day is paired together with the day before it, exactly as a live
    run does. PDF results already in the cache are re-applied to any filing
    that is now shown; nothing else about a filing changes.
    """
    global RARE_DATA_DIR
    RARE_DATA_DIR = data_dir
    snap = COUNTER.snapshot()
    cache = _read(os.path.join(data_dir, "enrich_cache.json"), {})
    rcache = _read(os.path.join(data_dir, RESULTS_CACHE), {})
    sess = {}
    read = 0
    d0 = datetime.strptime(first, "%Y-%m-%d")
    d1 = datetime.strptime(last, "%Y-%m-%d")
    totals = {"before": 0, "after": 0, "rows": 0}
    day = d0
    while day <= d1:
        d = day.strftime("%Y-%m-%d")
        prev = (day - timedelta(days=1)).strftime("%Y-%m-%d")
        day += timedelta(days=1)
        book = _read(os.path.join(data_dir, "book", d + ".json"), {}).get("rows", [])
        if not book:
            continue
        before = sum(1 for r in book if r.get("dup"))
        rows = load_day(data_dir, prev) + load_day(data_dir, d)
        _pair_inplace(rows)
        mine = [r for r in rows if r["ts"][:10] == d]
        if fetch and read < REPAIR_PDF_BUDGET:
            need = [r for r in mine if not r.get("dup_of") and r.get("att")
                    and ((r["sev"] >= 2 and events.text_events(r) & events.PDF_CHECK)
                         or (r["sev"] >= 1 and events.low_sev_pdf(r)))
                    and "ev" not in (cache.get(cache_key(r)) or {})]
            if need:
                if not sess:
                    sess["bse"] = bse_pdf_session()
                    try:
                        sess["nse"] = nse_session()
                    except Exception:
                        sess["nse"] = sess["bse"]
                st = enrich(need, cache, sess["bse"], sess["nse"], REPAIR_PDF_BUDGET - read,
                            True, log=lambda *_: None)
                read += st["downloads"] + st["download_failed"]
        enrich([r for r in mine if not r.get("dup_of")], cache, None, None, 0, False,
               log=lambda *_: None)
        reapply_cached(mine, {d}, cache)
        colour(rows, {d}, cache, rcache)
        save_day(data_dir, d, mine)
        after = sum(1 for r in mine if r.get("dup_of"))
        totals["before"] += before
        totals["after"] += after
        totals["rows"] += len(mine)
        log("  %s: %d filings, duplicates %d -> %d" % (d, len(mine), before, after))
    _write(os.path.join(data_dir, "enrich_cache.json"), cache)
    used = sum(COUNTER.since(snap).values())
    log("repair: %d filings, duplicates merged %d -> %d, PDFs read for rule checks: %d, "
        "network requests: %d" % (totals["rows"], totals["before"], totals["after"], read, used))
    return 0


# ============================================================ public check
import re as _re                                                   # noqa: E402

# Anything that looks like a path on a computer. URLs are fine (a "/home/"
# inside https://... is preceded by a letter and is not matched).
_PRIVATE = _re.compile(r"(?<![\w.])(?:/Users/|/home/|/private/|/tmp/|/var/folders/|[A-Za-z]:\\\\)")


def check_public(data_dir):
    """Exit non-zero if anything in the record book looks like it came from a
    machine rather than from the exchanges or this program's bookkeeping."""
    bad = []
    for root, dirs, files in os.walk(data_dir):
        dirs[:] = [x for x in dirs if x != ".git"]
        for name in files:
            p = os.path.join(root, name)
            with open(p, encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    m = _PRIVATE.search(line)
                    if m:
                        bad.append("%s line %d: %r" % (os.path.relpath(p, data_dir), i,
                                                      line[max(0, m.start() - 30):m.end() + 30]))
    if bad:
        print("PRIVATE-LOOKING CONTENT - refusing to publish:")
        for b in bad[:20]:
            print("  " + b)
        return 1
    print("public check: nothing machine-specific found")
    return 0


# ==================================================================== main
def main():
    ap = argparse.ArgumentParser(description="The Filing Wire collector")
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--mode", choices=("auto", "quick", "full"), default="auto")
    ap.add_argument("--with-yesterday", action="store_true",
                    help="a full run also rebuilds yesterday (manual runs)")
    ap.add_argument("--day", action="append", help="rebuild a past IST day (repeatable)")
    ap.add_argument("--backfill", nargs=2, metavar=("FROM", "TO"),
                    help="one-time history load, YYYY-MM-DD YYYY-MM-DD")
    ap.add_argument("--refetch", nargs=2, metavar=("FROM", "TO"),
                    help="re-read past days from the exchanges once (to add stored text)")
    ap.add_argument("--repair", nargs=2, metavar=("FROM", "TO"),
                    help="re-pair past days from the record book, no network")
    ap.add_argument("--check-public", action="store_true",
                    help="scan the record book for anything private, then exit")
    ap.add_argument("--no-enrich", action="store_true", help="never download a PDF")
    ap.add_argument("--max-pdfs", type=int, default=MAX_PDFS_PER_RUN)
    ap.add_argument("--now", help="pretend IST time 'YYYY-MM-DD HH:MM' (testing)")
    ap.add_argument("--metrics", help="write run metrics JSON here")
    a = ap.parse_args()

    if a.check_public:
        sys.exit(check_public(a.data_dir))
    if a.repair:
        for x in a.repair:
            datetime.strptime(x, "%Y-%m-%d")           # reject anything else
        sys.exit(repair(a.data_dir, a.repair[0], a.repair[1]))
    if a.refetch:
        for x in a.refetch:
            datetime.strptime(x, "%Y-%m-%d")
        sys.exit(backfill(a.data_dir, a.refetch[0], a.refetch[1], progress="refetch.json"))
    if a.backfill:
        for x in a.backfill:
            datetime.strptime(x, "%Y-%m-%d")           # reject anything else
        sys.exit(backfill(a.data_dir, a.backfill[0], a.backfill[1]))

    now = (datetime.strptime(a.now, "%Y-%m-%d %H:%M").replace(tzinfo=IST)
           if a.now else None)
    metrics, ex = run(a.data_dir, a.mode, a.day, not a.no_enrich, now, a.max_pdfs,
                      with_yesterday=a.with_yesterday)
    if a.metrics:
        _write(a.metrics, {"metrics": metrics, "exchanges": ex})
    # One exchange down is not a failure: it is recorded in status.json and
    # the run stays green. Only both down at once is reported as a failure.
    if not a.day and not ex["BSE"]["ok"] and not ex["NSE"]["ok"]:
        print("BOTH exchanges failed this run")
        sys.exit(2)


if __name__ == "__main__":
    main()
