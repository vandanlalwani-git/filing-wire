"""
PDF enrichment for The Filing Wire. Zero AI calls.

Two extractors, both validated against real BSE filings:

  extract_amount(text)  - anchored rupee extraction. Only returns a figure
                          that sits near a value-anchor phrase. Validated
                          on Indiabulls (naive said 1500cr, truth was
                          1050cr next to "consideration").

  extract_pledge(pdf)   - reads the SEBI Reg 31 table and pulls the
                          "Type of event" cell (Creation / Release /
                          Invocation) plus before/after share counts.

Design rule: when unsure, return None. A missing amount is fine.
A wrong amount is not.
"""

import os
import re

import pdfplumber

# ----------------------------------------------------------- amounts

# Widened after probe v2: Maithan Alloys' real Rs 378cr was missed by the
# original list. These are ordered roughly strongest-signal first.
ANCHORS = [
    r"order\s+value", r"value\s+of\s+the\s+order", r"order\s+worth",
    r"size\s+of\s+the\s+order", r"contract\s+value", r"contract\s+worth",
    r"total\s+order", r"order\s+book", r"work\s+order\s+(?:of|worth|value)",
    r"purchase\s+order\s+(?:of|worth|value)", r"letter\s+of\s+intent\s+(?:of|worth|for)",
    r"total\s+consideration", r"sale\s+consideration", r"consideration",
    r"aggregating\s+to", r"aggregate\s+value", r"aggregate\s+consideration",
    r"deal\s+value", r"transaction\s+value", r"enterprise\s+value",
    r"valued\s+at", r"worth\s+of", r"amounting\s+to", r"value\s+of\s+the\s+contract",
    r"total\s+value", r"project\s+cost", r"investment\s+of",
]
ANCHOR_RX = re.compile("|".join(ANCHORS), re.I)

MONEY_RX = re.compile(
    r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*"
    r"(crore|crores|cr\b|lakh|lakhs|lacs?|million|mn\b|billion|bn\b)?",
    re.I)

# below this we assume it's a fee, stamp duty or share capital, not a deal
MIN_CRORE = 0.5
MAX_CRORE = 5_000_000


def _to_crore(numstr, unit):
    try:
        val = float(numstr.replace(",", ""))
    except (ValueError, AttributeError):
        return None
    u = (unit or "").lower()
    if u.startswith(("crore", "cr")):
        return val
    if u.startswith(("lakh", "lac")):
        return val / 100
    if u.startswith(("million", "mn")):
        return val / 10
    if u.startswith(("billion", "bn")):
        return val * 100
    return val / 1e7                      # bare rupees


def extract_amount(text, window=180):
    """Return {'crore', 'anchor', 'raw'} or None. Silence beats a wrong number."""
    if not text:
        return None
    for am in ANCHOR_RX.finditer(text):
        seg = text[am.end(): am.end() + window]
        mm = MONEY_RX.search(seg)
        if not mm:
            continue
        cr = _to_crore(mm.group(1), mm.group(2))
        if cr is None or not (MIN_CRORE <= cr <= MAX_CRORE):
            continue
        return {"crore": round(cr, 2),
                "anchor": am.group(0).lower(),
                "raw": mm.group(0).strip()}
    return None


def format_amount(cr):
    """1050.0 -> 'Rs 1,050cr'; 4.23 -> 'Rs 4.23cr'"""
    if cr is None:
        return None
    if cr >= 100:
        return f"Rs {cr:,.0f}cr"
    return f"Rs {cr:,.2f}cr".replace(".00cr", "cr")


# ------------------------------------------------------------ pledges

EVENT_RX = re.compile(r"\b(creation|release|invocation|revocation)\b", re.I)

PLEDGE_DIRECTION = {
    "creation":   ("negative", "Pledge created"),
    "invocation": ("negative", "Pledge invoked"),
    "release":    ("positive", "Pledge released"),
    "revocation": ("positive", "Pledge released"),
}


def extract_pledge(pdf_path, max_pages=6):
    """
    Read the SEBI Reg 31 encumbrance table.
    Returns {'event','dir','label','shares'} or None.

    The 'Type of event' column holds the real value (Creation/Release/
    Invocation). Keyword search over the whole page does NOT work - the
    form prints all three words as column headers.
    """
    if not os.path.exists(pdf_path):
        return None
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[:max_pages]:
                for table in (page.extract_tables() or []):
                    for row in table:
                        cells = [str(c).replace("\n", " ").strip()
                                 for c in row if c is not None]
                        if len(cells) < 5:
                            continue
                        joined = " | ".join(cells)
                        # skip header rows: they contain a slash-joined list
                        if re.search(r"creation\s*/\s*rel|type\s+of\s+event", joined, re.I):
                            continue
                        # a data row has an event word in its own cell
                        for cell in cells:
                            m = EVENT_RX.fullmatch(cell.strip().rstrip("*").strip())
                            if not m:
                                continue
                            ev = m.group(1).lower()
                            direction, label = PLEDGE_DIRECTION[ev]
                            nums = [c for c in cells
                                    if re.fullmatch(r"[\d,\s]{4,}", c)]
                            return {"event": ev, "dir": direction,
                                    "label": label,
                                    "shares": nums[0].strip() if nums else None}
    except Exception:
        return None
    return None


def pdf_to_text(pdf_path, max_pages=6):
    """Plain text of the first N pages. Empty string if scanned (~4% of filings)."""
    try:
        out = []
        with pdfplumber.open(pdf_path) as pdf:
            for pg in pdf.pages[:max_pages]:
                out.append(pg.extract_text() or "")
        return "\n".join(out)
    except Exception:
        return ""
