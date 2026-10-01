"""Rules-only classifier for The Filing Wire. Zero AI calls."""
import json, re, os

_HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_HERE, "taxonomy.json"), encoding="utf-8") as f:
    TAX = json.load(f)

RULES = TAX["rules"]
OVERRIDES = [(re.compile(o["pattern"]), o) for o in TAX["headline_overrides"]]

# ------------------------------------------------------- escaping artifacts
# Both feeds ship their text fields with escaping damage. Measured on the
# corpus (5,208 BSE headlines / 3,210 NSE texts): 188 BSE and 24 NSE carry a
# doubled apostrophe (Company''s), 763 BSE headlines end in BSE's own
# four-dot truncation marker, 11 carry a literal <BR><BR>, one NSE row has a
# doubled quote and four carry a non-breaking space.
_DOUBLED_APOS = re.compile(r"'{2,}")
_DOUBLED_QUOT = re.compile(r'"{2,}')
_HTML_TAG = re.compile(r"<\s*/?\s*(?:br|p|div|span|b|i|u|font|strong|em)\b[^>]*>",
                       re.I)
_TRUNC_DOTS = re.compile(r"\.{4,}\s*$")


def normalise_text(s):
    """
    Undo the exchanges' own escaping before any other cleaning.

    BSE sends SQL-escaped apostrophes (Scrutinizer''s Report) and the odd
    HTML fragment; NSE sends the same doubled apostrophes plus non-breaking
    spaces. Left alone these reach the feed verbatim and read as typos.
    """
    if not s:
        return ""
    s = _HTML_TAG.sub(" ", s)
    s = s.replace("\xa0", " ").replace("\u00a0", " ")
    s = _DOUBLED_APOS.sub("'", s)
    s = _DOUBLED_QUOT.sub('"', s)
    s = _TRUNC_DOTS.sub("...", s)
    return re.sub(r"\s+", " ", s).strip()


_JUNK = re.compile(
    r"^(pfa|enclosed|attached|as attached|as per attach\w*|please find\b.{0,30}|"
    r"as per the attach\w*|intimation|n\.?a\.?|nil|please refer.{0,25}|update|"
    r"disclosure|-+|\.+)[\s\.\-]*$", re.I)


def _informative(h):
    h = (h or "").strip()
    if len(h) < 12:
        return False
    if _JUNK.match(h):
        return False
    if re.match(r"^(disclosure|intimation|announcement|submission)\s+under\s+reg", h, re.I) and len(h) < 120:
        return False
    return True


# covering-letter noise that makes a headline unreadable as a feed line
_PREAMBLE = re.compile(
    r"^\s*(dear\s+(sir|madam|sirs)[/\s,]*(madam)?[\s,\.]*|"
    r"respected\s+sir[\s,\.]*|"
    r"(please|kindly)\s+(find|note|refer)\s+(attached|enclosed|herewith|the)?\s*|"
    r"(we|this)\s+(are\s+pleased\s+to|wish\s+to|is\s+to)\s+"
    r"(inform|intimate|submit)\s*(you)?\s*(that|the)?\s*|"
    r"with\s+reference\s+to\s+the\s+above[\s,\.]*|"
    r"pursuant\s+to\s+regulation\s+\d+[^,]{0,60},\s*)+", re.I)


def _clean_line(headline, label):
    """Turn a BSE headline into one readable line, or fall back to the label."""
    h = normalise_text(headline)
    if not _informative(h):
        return label
    prev = None
    while prev != h:                       # strip stacked preambles
        prev = h
        h = _PREAMBLE.sub("", h).strip(" ,.:-")
    if len(h) < 12:
        return label
    # a headline that is mostly regulation citation adds nothing over the label
    if re.match(r"^(disclosure|intimation|announcement|submission)\b", h, re.I) \
            and len(h) < 90:
        return label
    if len(h) > 110:
        # trim trailing punctuation first, or "w.e.f." + "..." reads as "w.e.f...."
        cut = h[:110].rsplit(" ", 1)[0].rstrip(" .,:;-")
        return cut + "..."
    return h


def classify(filing):
    """Returns dict: sev, dir, label, line, matched_by. Never returns unknown."""
    sub = (filing.get("SUBCATNAME") or "(none)").strip() or "(none)"
    headline = normalise_text(filing.get("HEADLINE"))
    company = (filing.get("SLONGNAME") or "").strip()

    base = RULES.get(sub)
    matched_by = "subcategory"
    if base is None:
        base = {"sev": 1, "dir": "neutral", "label": sub}
        matched_by = "subcategory-fallback"

    sev, direction, label = base["sev"], base["dir"], base["label"]

    # headline overrides can only ESCALATE severity, never downgrade
    for rx, ov in OVERRIDES:
        if rx.search(headline):
            if ov["sev"] >= sev:
                sev, direction, label = ov["sev"], ov["dir"], ov["label"]
                matched_by = "headline-override"
            break

    # the plain line: prefer BSE's own headline, but only when it reads cleanly
    line = _clean_line(headline, label)

    return {
        "sev": sev, "dir": direction, "label": label,
        "company": company, "line": line, "matched_by": matched_by,
    }
