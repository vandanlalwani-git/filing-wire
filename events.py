"""
Event recognition for The Filing Wire. Rules only, zero AI calls.

The exchange category only hints at what a filing is about. The colour now
comes from what the filing itself says:

  1. EVENT   - a fixed catalogue of events (EVENTS below). Each event has
               phrases that must appear in the filing's own text.
  2. EVIDENCE- a row turns green or red only when a specific phrase backs it.
               Reversal phrases ("no penalty", "set aside", "in favour of
               the company", "dismissed", ...) cancel an adverse match.
               The rule id and the exact phrase are stored on the row.
  3. CONFLICT- if the text points one way and the category the other, or
               the filing carries both good and bad signals, the row is grey
               with the reason "conflicting signals".

Text searched, in order:
  * BSE: the subject line and the headline; NSE: the attachment text.
    Category boilerplate the exchange adds to these fields is removed first,
    so a category name can never be the evidence.
  * Notable/Critical rows only: the first pages of the PDF, used only when
    the text above names no event.

"Better unsure than wrong": anything not covered here stays grey.
"""

import re

# ------------------------------------------------------------------ helpers
_WS = re.compile(r"\s+")
_CID = re.compile(r"\(cid:\d+\)")


def norm(s):
    if not s:
        return ""
    s = _CID.sub("", s)
    s = (s.replace("’", "'").replace("‘", "'").replace("“", '"')
          .replace("”", '"').replace("–", "-").replace("—", "-")
          .replace("\xa0", " "))
    return _WS.sub(" ", s).strip().lower()


# BSE puts the category itself into the subject line:
#   "Announcement under Regulation 30 (LODR)-Award_of_Order_Receipt_of_Order"
_BSE_CAT_SUBJ = re.compile(
    r"^(announcement under regulation 30 \(lodr\)\s*-|"
    r"shareholder meeting / postal ballot-|corporate action-|"
    r"corporate insolvency resolution process \(cirp\)-|"
    r"disclosures? (of reasons for encumbrance|under reg)|"
    r"board meeting (intimation|outcome) for\b)", re.I)


# Form text the exchanges' disclosure templates print in every filing of a type.
# It names events in the abstract ("appointment, resignation, removal, death"),
# so it is removed before matching.
_TEMPLATE = re.compile(
    r"(reason for change viz\.?,?|((securities and exchange board of india|sebi) ?\(? ?(listing obligations?( and| &) disclosure requirements?|lodr|prohibition of insider trading)\)? ?(regulations?)?,? ?(20\d\d)?)|receipt of direction or .{0,25}order|including any ad-?interim or interim orders?|appointment, re-?appointment, resignation, removal, death or otherwise|"
    r"date of receipt of direction or order,? including any ad-?interim or interim orders?,? or any other communication( from the authority)?|"
    r"nature and details of the action\(s\) taken,? initiated or order\(s\) passed|"
    r"action\(s\) (taken|initiated),? or orders? passed by any regulatory[^.;]{0,80}|"
    r"details of (the )?violation\(s\) ?/ ?contravention\(s\) committed or alleged to be committed|"
    r"impact on (the )?financial,? operations? (and|or) other activities[^.;]{0,80}|"
    r"substantial acquisition of shares (and|&) takeovers?|"
    r"default by a listed entity[^.]{0,200}|"
    r"neither the company nor any of its promoters or directors is a wilful defaulter or a fraudulent borrower|"
    r"(entity|authority) awarding the order\(s\)|significant terms and conditions of order\(s\)|"
    r"whether order\(s\) ?/ ?contract\(s\) have been awarded|awarded by domestic ?/ ?international entity|"
    r"nature of order\(s\) ?/ ?contract\(s\))")


def clean(t):
    return _TEMPLATE.sub(" ", t)


def filing_text(row):
    """The filing's own words, with the exchange's category boilerplate removed."""
    sub = (row.get("sub") or "").strip()
    if row.get("src") == "NSE":
        t = row.get("hl") or ""
        if sub:
            t = re.sub(r"(has )?informed the exchange (about|regarding)\s*" + re.escape(sub),
                       " ", t, flags=re.I)
            t = t.replace(sub, " ")
        return norm(t)
    subj = row.get("subj") or ""
    if _BSE_CAT_SUBJ.match(subj.strip()) and not re.search(r"board meeting", subj, re.I):
        subj = ""
    hl = row.get("hl") or ""
    if sub:
        if subj.strip().lower().startswith(sub.lower()[:40]):
            subj = ""
        if hl.strip().lower().startswith(sub.lower()[:40]):
            hl = hl.strip()[len(sub):]
    return norm(subj + " || " + hl)


# ------------------------------------------------------------- the catalogue
# dir: +1 favourable, -1 adverse, 0 recognised but not good or bad on its face.
# where: "text" = subject/headline only; "any" = also the PDF.
# block: phrases that cancel this match when they sit near it (reversals).
# dominant: a 0-direction event that wins over any directional match
#           (e.g. an ESG rating "upgrade" is not a credit-rating upgrade).
# Each event can be overridden to a direction by the user (JUDGEMENT below).

AUTH = (r"(gst|cgst|sgst|igst|goods and services tax|customs|excise|service tax|income.?tax|"
        r"tax (department|authorit\w*)|commissioner|assessment unit|assessing officer|dgsto|lgsto|"
        r"deputy commissioner|registrar of companies|\broc\b|trai|telecom regulatory authority|fssai|food safety|"
        r"pollution control board|regional director|ministry of corporate affairs|state tax|"
        r"commercial taxes|adjudicat\w+|dggi|directorate general)")

REVERSAL = (r"(no penalty|(dropp\w*|withdr\w*|cancell?\w*) (the )?(total |entire |whole )?(tax )?demand|penalty (was |has been |is )?(deleted|dropped|waived|set aside|quashed)|"
            r"set aside|quash\w*|in favou?r of the (company|bank|appellant)|favou?rable|"
            r"nullif\w*|annul\w*|(demand|penalty|order)s? (stands? |has been |was |is )?(dropped|deleted|withdrawn|cancelled|revoked)|"
            r"\ballowed the appeals?|appeals? (is |are |has been |have been |was )?\ballowed|"
            r"refund|reduced from|no (such )?demand)")

EVENTS = [
    # ---------------------------------------------------- dominant neutrals
    dict(id="ESG", event="ESG rating", dir=0, dominant=True, where="any",
         rx=r"\besg rating|esg rating|environment(al)?,? social (and|&) governance"),
    dict(id="DEBT-SUSP", event="Debt security suspended on maturity", dir=0, dominant=True, where="text",
         rx=r"(debentures?|ncds?|ccds?|bonds?|commercial papers?).{0,200}suspended.{0,80}on account of (maturity|conversion|redemption)"),
    dict(id="ORDER-UPDATE", event="Update on an order already disclosed", dir=0, dominant=True, where="any",
         rx=r"(update|status) on (the )?order execution|order execution (update|status)|"
            r"amendment\s?(of|in|to)\s?(the |an |existing )?\s?(work\s?order|purchase\s?order|order|contract)|"
            r"(further to|with reference to|in continuation (of|to)) (our|the) (earlier|previous) (intimation|disclosure|letter|communication).{0,300}"
            r"\b(loa|letter of (acceptance|award|intent))\b.{0,300}(contract agreement|entered into|signed|executed)|"
            r"revised intimation|revision (in|of|to) (the |our )?(earlier |previous )?(intimation|disclosure|letter)|inadvertent(ly)? (error|typographical)|"
            r"in continuation (of|to) our (earlier |previous )?(intimation|disclosure|letter)[^|]{0,600}(has |have )?(executed|signed|entered into)[^|]{0,60}(agreement|\bppa\b|contract)"),
    dict(id="BID-L1", event="Lowest/highest bidder, not yet awarded", dir=0, dominant=True, where="any",
         rx=r"(declared|emerged|stood|been) (as )?(the )?(l-?1|lowest bidder|h-?1|highest bidder)",
         block=r"(letters? of (award|acceptance|intent)|\blo[ai]\b|work orders? (has been |was )?(received|issued)|purchase orders? (has been |was )?received|contract win|has (now )?received)",
         window=600),
    dict(id="EMPANEL", event="Empanelled as a vendor, no order yet", dir=0, dominant=True, where="any",
         rx=r"\bempanel\w*"),
    dict(id="FRAMEWORK", event="Framework agreement / potential business, no firm order", dir=0, dominant=True, where="text",
         rx=r"(framework agreement|potential (export )?suppl|indicative (programme|program|value|ceiling)|memorandum of understanding|\bmou\b)"),
    dict(id="ARBITRATION", event="Arbitration or court outcome, not an order", dir=0, dominant=True, where="any",
         rx=r"\barbitra(l|tion|tor|tors)\b"),
    dict(id="ORDER-PLACED", event="Company is placing an order with a supplier (it is the buyer)", dir=0, dominant=True, where="any",
         rx=r"(placement of (the |a )?(purchase |work )?orders?,? on|has placed (the )?(following |an? )?(purchase |work )?orders?|approv\w* (for )?(the )?placement of|"
            r"coal linkages?|supply of [^.]{0,80} to the company|"
            r"(letter of intent|loi|agreement|order|contract)s? (with|on|to) [^.]{0,80}\bfor (the )?(acquisition|purchase|procurement|buying) of|"
            r"(to|will) (acquire|purchase|procure|buy) [^.]{0,40}(aircraft|machines|equipment|vessels?|ships?|rakes|wagons|locomotives))"),
    dict(id="ORDER-CANCEL", event="Order or letter of award cancelled", dir=0, dominant=True, where="any",
         rx=r"((cancell?ation|withdrawal|termination|revocation|annulment|foreclosure|short.?closure) of (the |a )?(letter of (award|acceptance|intent)|loa|loi|order|contract|work order|purchase order)|"
            r"(letter of (award|acceptance|intent)|\bloa\b|order|contract) .{0,120}(has been|was|stands) (cancell?ed|terminated|withdrawn))"),
    dict(id="ORDER-ASSOC", event="Order won by an associate company, not the company or a subsidiary", dir=0, where="any",
         rx=r"\b(our |its |the company'?s? |an )?associate (company|companies|entity|concern)\b"),
    dict(id="BANK-STRIKE", event="Industry-wide bank strike notice", dir=0, dominant=True, where="any",
         rx=r"united forum of bank unions|\bufbu\b|aibea|aiboc|all india (bank )?strike|bank strike"),

    # ---------------------------------------------------------- favourable
    dict(id="RULING-FAV", event="Ruling in the company's favour", dir=+1, where="any",
         rx=r"(favou?rable (\w+ )?(final )?order|order in (our|its|the company's) favou?r|in favou?r of the (company|bank|appellant)|"
            r"\ballowed the appeals? (filed|preferred) by the (company|bank|appellant)|"
            r"appeals? (filed|preferred) by the (company|bank).{0,40}(is |are |has been |have been |was )?\ballowed|"
            r"(set aside|quash\w*|delet\w*|nullif\w*|annul\w*) .{0,60}(demand|penalty|order|assessment)|"
            r"(demand|penalty) (of rs\.? ?[\d,\.]+ ?(crores?|lakhs?)?.{0,30})?(stands? |has been |was |is )?(set aside|quashed|deleted|dropped|annulled|nullified)|"
            r"dismiss\w* the appeals? (filed|preferred) by the (department|revenue|tax)|"
            r"(dropp\w*|withdr\w*|cancell?\w*) (the )?(total |entire |whole )?(tax )?demand|"
            r"refund sanction\w*|reduced from rs)",
         block=r"\b(earlier|previous|prior|past|similar)\b.{0,25}(favou?rable|order)"),
    dict(id="RULING-MIXED", event="Ruling partly in the company's favour", dir=0, dominant=True, where="any",
         rx=r"part(ly|ially) (allowed|set aside)|partial relief"),
    dict(id="INSOLV-DISMISSED", event="Insolvency petition dismissed or withdrawn", dir=+1, where="any",
         rx=r"((insolvency|cirp|section [79]\b|ibc|c\.?p\.? ?\(ib\)).{0,160}(dismiss\w*|withdraw\w*|rejected|closed)|"
            r"(dismiss\w*|withdraw\w*|rejected).{0,120}(insolvency|section [79]\b|c\.?p\.? ?\(ib\)))"),
    dict(id="RATING-UP", event="Credit rating upgraded", dir=+1, where="any",
         rx=r"(ratings?|outlook)\b.{0,80}\bupgrad\w+|\bupgrad\w+ .{0,80}\b(ratings?|outlook)\b|outlook (has been )?(revised|changed|improved) (from \W?\w+\W? )?to \W?positive|"
            r"outlook (has been )?(revised|changed|improved) from \W?negative\W? to \W?stable|(revis\w+|chang\w+|improv\w+) (the )?outlook .{0,25}from \W?negative\W? to \W?(stable|positive)|\w+/positive.{0,40}outlook revised from \W?stable",
         # a form whose column lists the options "new/ upgrade/ downgrade/ reaffirm"
         block=r"(new|positive|negative|stable|assigned|reaffirm\w*|downgrade|withdraw\w*)\s?/\s?(upgrad|downgrad)|upgrad\w*\s?/\s?(downgrad|rating|reaffirm|withdraw|other)", window=40),
    dict(id="ORDER-WIN", event="Order or contract win", dir=+1, where="any",
         rx=r"(\border win\b|contract win|(receiv\w*|secur\w*|bag\w*|won|win|award\w*|receipt of|bagging) .{0,80}"
            r"\b(orders?|contracts?|letters? of (award|intent|acceptance)|loa|loi|work orders?|purchase orders?|mandate)\b|"
            r"letters? of (award|intent|acceptance) .{0,60}\b(from|for|worth|valued|dated)\b|"
            r"has been (awarded|selected as the successful)|renewal of .{0,60}contract.{0,80}increased scope)",
         block=r"(penalty|order.in.original|order.in.appeal|\boio\b|assessment (order|year)|appeal|appellate|tribunal|nclt|\bcourt\b|motion|"
               r"sebi (has )?(passed|issued|order)|order (passed|issued) by (the )?(sebi|securities and exchange board)|"
               r"demand|show.?cause|compounding|settlement|adjudicat|commissioner|customs|excise|income.?tax|"
               r"gst (department|dept|authorit|officer|order)|goods and services tax act|registrar of companies|rera|"
               r"pollution control|regulatory|statutory authority|trai|telecom regulatory|financial disincentive|"
               r"clarification|corrigendum|correction|competition commission|approval of the scheme|scheme of|"
               r"regional director|section 441|\brd order|environment(al)? compensation|"
               r"\bawarding (of )?(the )?contracts? .{0,100}\bto\b|(placed|placing) (an |the )?(purchase |work )?orders? (on|with)|status of (the )?(order )?execution|"
               r"amendment\s?(of|in|to)|\bamended\b|placement of (the |a )?(purchase |work )?orders? on|has placed (the )?(following |an? )?(purchase |work )?orders?|"
               r"cancell?ation of (the |a )?(letter|order|contract|loa|loi|work order|purchase order)|(letter of award|loa|order|contract) .{0,120}(has been|was|stands) (cancell?ed|terminated|withdrawn)|"
               r"non.?binding (letter of intent|loi|term sheet|memorandum)|proposed acquisition|(earlier|previous) (intimation|disclosure).{0,160}(loa|letter of (acceptance|award|intent)))"),
    dict(id="COMMISSION", event="Plant commissioned / production started", dir=+1, where="any",
         rx=r"(successfully commissioned|has (been )?(fully |successfully )?commissioned|commissioning of (a |the )?[\d\.]+ ?(mw|mwp|kw|tpa|tpm|mtpa)|"
            r"commence\w* (of )?(its |the )?commercial (production|operations?)|commercial operation date|"
            r"(capacity expansion|expansion (project|programme|program)|phase).{0,60}(completed|commissioned)|"
            r"inaugurat\w* .{0,60}(facility|plant|unit)|capacity (has been )?(enhanced|added) to|"
            r"operations .{0,120}restored to (their )?regular)",
         block=r"(for (its |our )?(reputed )?clients|executed for|on behalf of|proposed|expected to be|will be commissioned|scheduled|"
               r"postpon\w*|delay\w*|deferr?\w*|pilot plant|(retail|multi.?brand|new) (store|showroom)s?)"),
    dict(id="DRUG-OK", event="Drug regulator: clean inspection / approval", dir=+1, where="any",
         rx=r"((zero|nil|no) (form )?(483 )?observations?|without any (form )?483|"
            r"establishment inspection report|\beir\b|voluntary action indicated|\bvai\b|no action indicated|\bnai\b|"
            r"(not related to|non-?)\s?gmp|no gmp observation|"
            r"(usfda|us fda|fda).{0,60}(final|tentative) approval|(final|tentative) approval.{0,60}(usfda|us fda|fda))"),
    dict(id="BUYBACK-NEW", event="New buyback approved by the board", dir=+1, where="text",
         # the board's own announcement only; the public announcement, the
         # newspaper copy, the certified board resolution, daily reports and
         # the rest of the process that follows are grey
         rx=r"(board[^|]{0,120}\bapprov\w*[^|]{0,80}buy.?back|\bapprov\w*[^|]{0,40}buy.?back|outcome[^|]{0,80}buy.?back|buy.?back[^|]{0,60}\bapprov\w*)",
         block=r"(public announcement|newspaper|advertisement|board resolution|resolution passed|certified|post.?buy|commencement|intention|"
               r"special resolution|postal ballot|shareholders?|letter of offer|record date|daily|completion|closure|\bclosed|extinguish\w*|"
               r"updates? (regarding|on|in respect)|further to|reference to|continuation|corrigendum|tender form|escrow|"
               r"intimation of (the )?(board )?meeting|to consider|will consider|consider and evaluate|proposal to|"
               r"rejected|not approv\w*|did not approve|withdraw\w*|deferred|dropped)", window=400),
    dict(id="ID-RESIGN-GOV", event="Independent director resigned citing governance concerns", dir=-1, where="any",
         rx=r"(governance (concerns?|issues?|lapses?|failures?|deficienc\w*)|"
            r"(disagree\w*|differences? of opinion|difference in opinion) (with|between|over|on|about|regarding)|remains? (a |an )?disagreement|"
            r"lack of (transparency|information|co-?operation|access|independence|oversight)|"
            r"(not|never) (been )?(provided|furnished|given|shared)[^.;]{0,60}(information|documents|records|details)|"
            r"(serious |grave |certain )?concerns? (over|about|regarding|on|with|in relation to|relating to|in respect of|raised|identified)[^.;]{0,80}"
            r"(management|board|functioning|conduct|governance|transactions?|accounts|financial statements|related part\w*|evaluation|chair\w*|audit|disclos\w*)|"
            r"(unable|not able|cannot) to (effectively )?discharge[^.;]{0,40}(duties|responsibilit\w*|role)|in protest|"
            r"irregularit\w*|non-?cooperation|(was|were|been) (kept|left) in the dark)",
         need=r"(?<!non-)(?<!non )(?<!non)independent director[\s\S]{0,4000}(resign|cessation|step(ped)? down)|(resign|cessation|step(ped)? down)[\s\S]{0,4000}(?<!non-)(?<!non )(?<!non)independent director",
         need_window=6000,
         # standard form lines ("whether the resignation is on account of any
         # disagreement") and plain denials never count; "no OTHER material
         # reasons" does not cancel reasons that are stated
         block=r"((\bno|\bnot|without|\bnor|never|none)\b[^.;]{0,40}(disagreement|differences?|concerns?|issues?)|confirmation whether|whether the resignation|"
               r"not on account|is not due|personal (reasons|commitments)|pre-?occupation|other (professional )?commitments|"
               r"to whom(so)?ever (it|this) may concern|all concerned|concerned authorit\w*|governance (framework|report|practices))", window=120),
    dict(id="PLEDGE-REL", event="Pledge released", dir=+1, where="any",
         rx=r"(release|revocation) of (the )?(pledge|encumbrance|pledged)|pledge (released|revoked)"),

    # ------------------------------------------------------------- adverse
    dict(id="DRUG-483", event="Drug regulator: observations / warning", dir=-1, where="any",
         rx=r"(warning letter|import alert|official action indicated|\boai\b|"
            r"form (fda )?[- ]?483 (with|containing) (\w+|\d+)|"
            r"\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+) (\(\d+\) )?(form 483 )?observations?)",
         block=r"(\b(zero|nil|no)\b (form )?(fda )?(483 )?observations?|not related to gmp|non-?gmp|no gmp)"),
    dict(id="TAX-DEMAND", event="Tax / regulatory demand or penalty", dir=-1, where="any",
         rx=r"(show.?cause (cum demand )?notice|\bscn\b|demand (notice|order)|notice of demand|order.in.original|\boio\b|"
            r"assessment order|drc.?0[17]|\bdemand of (inr|rs\.?|₹)|confirm\w* the demand|demand.{0,40}(confirmed|upheld)|"
            r"(dismiss\w*|disallow\w*|reject\w*) the appeal (filed|preferred) by the (company|bank)|"
            r"levy\w* (a )?(penalty|financial disincentive)|penalty (of|amounting|aggregating)|"
            r"(imposed|levied) (a )?(penalty|fine)|(penalty|fine) (has been |was )?(imposed|levied)|"
            r"fine of rs|tax demand)",
         need=AUTH, block=REVERSAL),
    dict(id="COMPOUNDING", event="Compounding / settlement with regulator", dir=-1, where="any",
         rx=r"(compounding (order|fee)|settlement order|consent order|settlement (application|proceedings).{0,60}(order|passed))"),
    dict(id="SEBI-ACTION", event="SEBI / exchange penal action", dir=-1, where="any",
         rx=r"(sebi.{0,80}(order|directions?|penalty|adjudicat\w+).{0,80}(against|non.?complian|violat|alleged)|"
            r"(against|on) the (company|noticee).{0,40}sebi|"
            r"\b(nse|bse|exchanges?|mse)\b.{0,60}\b(levied|imposed|fined|fines?)\b|\bfines? .{0,40}(levied|imposed) by (the )?(nse|bse|exchange)|"
            r"securities appellate tribunal.{0,120}dismiss\w*|\bsat\b.{0,80}dismiss\w*)",
         block=REVERSAL),
    dict(id="SEARCH", event="Search / raid by authorities", dir=-1, where="any",
         rx=r"(\b(search|seizure|raid|survey) (and seizure )?(operations?|proceedings?|action)?.{0,80}"
            r"(enforcement directorate|\bed\b|income.?tax|gst|sebi|cbi|dggi|directorate)|"
            r"(enforcement directorate|\bed\b|sebi|gst|income.?tax|dggi|cbi).{0,80}(conducted|initiated|carried out) (a )?\b(search|raid|survey))",
         block=r"(concluded|completed).{0,300}(no (material )?(impact|liability)|input tax credit|eligible to avail)|"
               r"(no (material )?(impact|liability)|input tax credit|eligible to avail).{0,300}(concluded|completed)", pdf_block=True, window=400),
    dict(id="DEFAULT", event="Default on interest / principal", dir=-1, where="any",
         # an actual event only: "has defaulted on", "delay in payment of
         # interest due on <date>". The quarterly default-disclosure form and
         # the standard clauses in loan paperwork never count.
         rx=r"((has|have|had) (defaulted|committed (a )?default) (in|on)|"
            r"delay(ed)? in (the )?(payment|servicing|repayment) of (the )?(interest|principal|instal\w*|coupon|redemption)[^.;]{0,120}\bdue on\b|"
            r"(interest|principal|instal\w*|coupon|redemption amount)[^.;]{0,80}\bdue on\b[^.;]{0,80}(has|have) not been (paid|serviced)|"
            r"(unable|could not|failed) to (pay|service|repay|make (the )?payment of)[^.;]{0,60}(interest|principal|instal\w*|coupon|dues))",
         block=r"(\bnil\b|no default|not (in )?default|neither the company nor|is not a wilful|quarter(ly)?\b|as on (the )?(last day|date|quarter)|"
               r"\bc-?1\b|\bc-?2\b|total amount of outstanding|event of default|events of default|in case of (any )?default|if the (company|borrower)|"
               r"shall (be )?(deemed|constitute)|cured|regularis\w*|regulariz\w*|since (been )?paid|paid on)", window=240),
    dict(id="FIRE", event="Fire / accident at a facility", dir=-1, where="any",
         rx=r"(major fire|fire (broke out|incident|accident|occurred)|explosion|blast at|fatal\w*|rupture|"
            r"accident (at|in) (the )?(plant|factory|unit|facility|site))",
         block=r"(operations? (was |were |are |is )?(resumed|normal|not (affected|disrupted|impacted))|no (material )?(financial )?(loss|impact)|"
               r"insurance claim .{0,40}(settled|received)|restored)", pdf_block=True),
    dict(id="SHUTDOWN", event="Plant shutdown / closure order", dir=-1, where="text",
         rx=r"(closure (order|direction)|order(ed)? .{0,40}closure|(plant|unit|factory|operations?) .{0,40}(shut ?down|suspended|halted)|lock.?out declared)",
         block=r"(resum\w+|restored|normal|set aside|quash\w*|stay\w*|revoked)"),
    dict(id="AUD-RESIGN", event="Statutory auditor resigned", dir=-1, where="text",
         rx=r"(resign\w* .{0,80}statutory auditors?|statutory auditors? .{0,80}resign\w*|resignation of (the )?auditors?\b)", window=320,
         block=r"(secretarial|internal|cost) auditor|conclusion of .{0,20}annual general meeting|legal and regulatory requirements|removal|death|"
               r"casual vacancy|appointment ?/ ?resignation|appoint\w* .{0,40}(as|of) (the )?statutory auditor"),
    dict(id="RATING-DOWN", event="Credit rating downgraded / watch negative", dir=-1, where="any",
         # an actual downgrade only: rating letters also carry "factors that
         # could lead to a downgrade" in every press release
         rx=r"((has been|have been|was|were|is|are|stands?) downgraded|downgraded (to|from)|downgrade of (the )?(long|short|rating)|"
            r"(placed|put|kept|retained) (on|under) (credit |rating )?watch with negative|rating watch (with )?negative|"
            r"outlook (has been |was )?(revised|changed) (from \W?\w+\W? )?to \W?negative)",
         block=r"((could|may|would|might|will|can) (lead|trigger|result|warrant|prompt|also)|sensitivit\w*|factors|in case of|if the|"
               r"downgrade (trigger|factor)|definition|rating scale)", window=120),
    dict(id="INSOLV-ADMIT", event="Insolvency petition admitted / CIRP started", dir=0, where="any",
         rx=r"(admit\w* .{0,120}(insolvency|section [79]\b|cirp)|(initiat\w*|commence\w*) (of )?(the )?(corporate insolvency resolution process|cirp)\b.{0,60}(against|of) the company|"
            r"order of moratorium|moratorium (has been )?(declared|imposed))",
         block=r"(dismiss\w*|withdraw\w*|reject\w*|scheme of|amalgamation|merger|demerger|second motion|first motion|"
               r"committee of creditors|\bcoc\b|meeting|financial results|quarter|resolution plan)"),
    dict(id="FRAUD", event="Fraud / investigation", dir=-1, where="any",
         rx=r"(cyber fraud|fraud(ulent)? (incident|transactions?|payments?)|fraud .{0,40}(detected|identified|committed)|"
            r"serious fraud investigation office|\bsfio\b|forensic audit .{0,40}(initiated|ordered|appointed))",
         block=r"(fraudulent borrower|wilful defaulter or a fraudulent|writ petition)"),
    dict(id="PLEDGE-NEW", event="Pledge created / invoked", dir=-1, where="any",
         rx=r"creation of (the )?(pledge|encumbrance)|pledge (created|invoked)|invocation of (the )?(pledge|encumbrance)",
         block=r"no (further|new) (pledge|encumbrance)|increase in .{0,40}(amount|facilit)"),

    # ------------------------------------------- recognised, not coloured
    dict(id="REG-ORDER", event="Order from a tax or regulatory authority", dir=0, where="any",
         rx=r"(order.in.(original|appeal)|\boio\b|appeal order|assessment order|penalty order|demand order|"
            r"compounding order|refund (sanction )?order|"
            r"(orders?|directions?) (dated [\w ,]{0,20})?(passed |issued |received )?(by|from) (the )?(hon'?ble )?([\w&,.()-]+ ){0,5}"
            r"(gst|cgst|sgst|tax|customs|excise|commissioner|tribunal|nclt|nclat|court|sebi|securities and exchange board|"
            r"registrar of companies|regional director|pollution control|rera|trai|fssai|enforcement directorate|income.?tax))"),
    dict(id="NCLT-SCHEME", event="NCLT step on a merger/scheme", dir=0, where="any",
         rx=r"((scheme|amalgamation|merger|demerger|arrangement).{0,160}(nclt|national company law tribunal|tribunal)|"
            r"(nclt|national company law tribunal|tribunal).{0,160}(scheme|amalgamation|merger|demerger|arrangement)|"
            r"(first|second) motion|nclt.?convened|court convened)"),
    dict(id="CIRP-ROUTINE", event="Routine step in an ongoing insolvency", dir=0, where="any",
         rx=r"(committee of creditors|\bcoc\b|resolution professional|under (corporate insolvency|cirp)|\(in cirp\))"),
    dict(id="DEFAULT-FORM", event="Loan default disclosure", dir=0, where="text",
         rx=r"(defaults? (on|in) (the )?(payment|repayment)|default in (re)?payment|\bdefault(ed)?\b)"),
    dict(id="RATING-SAME", event="Credit rating reaffirmed / assigned / withdrawn", dir=0, where="any",
         rx=r"(re-?affirm\w*|\baffirmed|ratings? (has been |have been )?assigned|assigned .{0,30}rating|rating.{0,40}withdrawn)"),
    dict(id="AUD-APPOINT", event="Auditor appointed", dir=0, where="text",
         rx=r"(appoint\w*|re-?appoint\w*) .{0,60}(statutory|secretarial|internal|cost) auditors?|(secretarial|internal|cost) auditor"),
    dict(id="EXCH-QUERY", event="Exchange query / clarification", dir=0, dominant=True, where="text",
         rx=r"(sought clarification|clarification (sought|on|regarding) (the )?(price|volume|news|media)|price movement|spurt in volume|movement in (price|volume)|"
            r"news (item|verification)|rumou?r|response .{0,30}awaited)"),
    dict(id="COURT-STEP", event="Court / tribunal procedure, no outcome", dir=0, dominant=True, where="any",
         rx=r"(notice of hearing|(has|have) filed (a |an )?writ petition|writ petition (has been |was )?filed|"
            r"appeal (filed|preferred) by (the )?(gst|tax|income|department|revenue)|next (date of )?hearing)"),
    dict(id="CAPEX", event="Capex / expansion approved", dir=0, where="text",
         rx=r"(capital (budget\w*|expenditure) (outlay )?.{0,40}approv\w*|approv\w* .{0,60}(capex|capital expenditure|capital budget))"),
    dict(id="STRIKE", event="Strike / labour notice", dir=0, where="text",
         rx=r"\bstrike\b|lock.?out"),

    # -------------------------------- judgement calls: the user decides
    dict(id="JC-DIVIDEND", event="Dividend", dir=0, jc="dividend", where="text",
         rx=r"\bdividend"),
    dict(id="JC-BUYBACK", event="Buyback", dir=0, jc="buyback", where="text",
         rx=r"buy.?back"),
    dict(id="JC-BONUS", event="Bonus / split", dir=0, jc="bonus/split", where="text",
         rx=r"\bbonus\b|sub.?division|stock split|split of"),
    dict(id="JC-FUNDRAISE", event="Fund raising", dir=0, jc="fund raising", where="text",
         rx=r"\bqip\b|qualified institutions? placement|preferential (issue|allotment|basis)|rights issue|"
            r"raising of funds|fund ?rais\w+|\bfccbs?\b|warrants"),
    dict(id="JC-ACQUISITION", event="Acquisition", dir=0, jc="acquisition", where="text",
         rx=r"acqui(re|red|sition|ring)\b|stake in"),
    dict(id="JC-CXO-RESIGN", event="CEO/CFO/MD resignation", dir=0, jc="CEO/CFO/MD resignation", where="text",
         rx=r"(resign\w*|cessation|step(ped|s)? down).{0,80}\b(ceo|cfo|chief executive|chief financial|managing director|\bmd\b)|"
            r"\b(ceo|cfo|chief executive|chief financial|managing director)\b.{0,80}(resign\w*|cessation)"),
    dict(id="JC-ID-RESIGN", event="Independent director resignation", dir=0, jc="independent director resignation", where="text",
         rx=r"(resign\w*|cessation).{0,80}independent director|independent director.{0,80}(resign\w*|cessation)"),
]

# The user's decisions on judgement calls: +1, -1 or 0 per event.
# 0 (grey) is the recommendation until the user decides otherwise.
JUDGEMENT = {
    "dividend": 0, "buyback": 0, "bonus/split": 0, "fund raising": 0,
    "acquisition": 0, "CEO/CFO/MD resignation": 0,
    "independent director resignation": 0, "credit rating reaffirmed": 0,
}
# Decided by the user in Oct 2026: all of the above stay grey. Two narrower
# events are coloured instead, each once it passes its own blind test:
#   BUYBACK-NEW   a new buyback approved by the board (daily/progress reports grey)
#   ID-RESIGN-GOV an independent director resigning over governance concerns

_BY_ID = {e["id"]: e for e in EVENTS}
for e in EVENTS:
    e["_rx"] = re.compile(e["rx"])
    e["_block"] = re.compile(e["block"]) if e.get("block") else None
    e["_need"] = re.compile(e["need"]) if e.get("need") else None

WINDOW = 160          # characters either side of a match checked for reversals
NEED_WINDOW = 400     # context that must contain the authority for TAX-DEMAND


# adverse tax phrases that report an OUTCOME (the company lost), as opposed to
# phrases that merely name the order being appealed
_TAX_LOST = re.compile(r"(confirm|upheld|dismiss|disallow|reject|levy|levied|imposed|penalty of|fine of|demand of)")


_REGULATOR_DOC = re.compile(
    r"(regional director|section 441|compounding|pollution control board|environment(al)? compensation|order.in.original|show.?cause|penalty (of|order|imposed|levied|amounting)|assessment order|demand notice|"
    r"income.?tax act|cgst act|gst act|customs act|central excise|sebi .{0,30}order|order passed by|appellate)")


def _hits(text, where, blocked=None):
    out = []
    if not text:
        return out
    regulator_doc = where == "pdf" and bool(_REGULATOR_DOC.search(text))
    for e in EVENTS:
        if where == "pdf" and e["where"] != "any":
            continue
        if regulator_doc and e["id"] == "ORDER-WIN":
            continue
        for m in e["_rx"].finditer(text):
            a, b = m.start(), m.end()
            w = e.get("window", WINDOW)
            ctx = text[max(0, a - w): b + w]
            if e["_block"] and e["_block"].search(ctx):
                if blocked is not None:
                    blocked.add(e["id"])
                continue
            nw = e.get("need_window", NEED_WINDOW)
            if e["_need"] and not e["_need"].search(text[max(0, a - nw): b + nw]):
                continue
            out.append({"rule": e["id"], "event": e["event"], "dir": _dir(e),
                        "phrase": text[a:b][:120], "dominant": e.get("dominant", False),
                        "src": where,
                        "lost": e["id"] == "TAX-DEMAND" and bool(_TAX_LOST.search(text[a:b]))})
            break
    return out


def _dir(e):
    if e.get("jc"):
        return JUDGEMENT.get(e["jc"], 0)
    if e["id"] == "RATING-SAME":
        return JUDGEMENT.get("credit rating reaffirmed", 0)
    return e["dir"]


_OLD = {"positive": 1, "negative": -1}


def _prep(text, row):
    t = clean(text)
    co = norm(row.get("co"))
    return t.replace(co, " ") if co else t


ORDER_VETO = {"REG-ORDER", "TAX-DEMAND", "COMPOUNDING", "SEBI-ACTION", "BID-L1", "EMPANEL",
              "ORDER-UPDATE", "COURT-STEP", "NCLT-SCHEME",
              "ORDER-PLACED", "ORDER-CANCEL", "ORDER-ASSOC", "ARBITRATION"}


def text_hits(row, blocked=None):
    return _hits(_prep(filing_text(row), row), "text", blocked)


def text_events(row):
    """Rule ids named in the filing's own text (used to tell filings apart)."""
    return {h["rule"] for h in text_hits(row)}


def scan_pdf(row, pdf_text):
    """
    What the first pages of a PDF say, in a form small enough to cache:
    the events found (rule id + phrase) and the events whose reversal
    phrases appear ("fire contained, operations normal").
    """
    p = _prep(norm(pdf_text or "")[:6000], row)
    if len(p) < 50:
        return {"hits": [], "blocks": []}
    hits = [{"rule": h["rule"], "phrase": h["phrase"], "lost": h["lost"]}
            for h in _hits(p, "pdf")]
    blocks = [e["id"] for e in EVENTS if e.get("pdf_block") and e["_block"].search(p)]
    return {"hits": hits, "blocks": blocks}


def _expand(h):
    e = _BY_ID[h["rule"]]
    return {"rule": e["id"], "event": e["event"], "dir": _dir(e), "phrase": h["phrase"],
            "dominant": e.get("dominant", False), "src": "pdf", "lost": h.get("lost", False)}


# Rules whose headline match is confirmed against the PDF before colouring:
# the PDF may show the "order" is the company's own purchase, a cancellation,
# an associate's win, an arbitration, a bid status or a follow-up.
PDF_CHECK = {"ORDER-WIN"}


def needs_pdf(row):
    """True when the filing's own text names no decisive event, or names one
    that is only coloured after the PDF has been checked."""
    hits = text_hits(row)
    if {h["rule"] for h in hits} & PDF_CHECK:
        return True
    return not [h for h in hits if (h["dir"] != 0 or h["dominant"])
                and not (h["rule"] == "TAX-DEMAND" and not h["lost"])]


# Filings the exchanges rate routine whose PDF can still change the picture:
# an independent director's resignation letter may cite governance concerns;
# a default disclosure may report an actual missed payment.
LOW_SEV_PDF = {"JC-ID-RESIGN", "DEFAULT-FORM"}


_DEFAULT_CAT = re.compile(r"default", re.I)


def low_sev_pdf(row):
    return bool({h["rule"] for h in text_hits(row)} & LOW_SEV_PDF
                or _DEFAULT_CAT.search(row.get("sub") or ""))


def is_pledge_pdf(row):
    w = row.get("why") or {}
    return (w.get("by") == "pdf" and not w.get("rule")) or w.get("rule") == "PLEDGE-PDF"


def decide(row, pdf_text=None, pdf_info=None):
    """
    Returns {"dir": "positive"|"negative"|"neutral", "rule", "event",
             "text" (the phrase), "reason", "by": "text"|"pdf"}.
    `row` is a book row (src, sub, subj, hl, dc or dir, sev ...).
    PDF findings (`pdf_info` from scan_pdf, or raw `pdf_text`) are used only
    for Notable/Critical rows.
    """
    # the existing pledge reading from the PDF table stays exactly as it was
    if is_pledge_pdf(row) and row.get("dir") in ("positive", "negative"):
        w = row.get("why") or {}
        return {"dir": row["dir"], "rule": "PLEDGE-PDF", "event": row.get("lab"),
                "text": w.get("text"), "reason": None, "by": "pdf"}

    if row.get("sev", 0) < 2 and not low_sev_pdf(row):
        pdf_info = None
    elif pdf_info is None and pdf_text:
        pdf_info = scan_pdf(row, pdf_text)
    blocks = set((pdf_info or {}).get("blocks") or [])

    blocked = set()
    raw = text_hits(row, blocked)
    # not yet checked against its PDF: wait (the next run reads it)
    if (pdf_info is None and row.get("sev", 0) >= 2 and row.get("att")
            and {h["rule"] for h in raw} & PDF_CHECK & LIVE):
        h = [h for h in raw if h["rule"] in PDF_CHECK][0]
        return {"dir": "neutral", "rule": h["rule"], "event": h["event"], "text": h["phrase"],
                "reason": "%s: waiting for the PDF to be checked" % h["event"], "by": "text",
                "rules": sorted({x["rule"] for x in raw})}
    # a headline "order" the PDF shows to be a regulator's order, a bid status,
    # an empanelment or a follow-up to an order already disclosed is not a win
    pdf_rules = {h["rule"] for h in (pdf_info or {}).get("hits") or []}
    order_veto = bool(pdf_rules & ORDER_VETO or "ORDER-ASSOC" in {h["rule"] for h in raw})
    if order_veto:
        raw = [h for h in raw if h["rule"] != "ORDER-WIN"]
    # a headline event whose outcome the PDF qualifies is dropped
    hits = [h for h in raw if not (_BY_ID[h["rule"]].get("pdf_block") and h["rule"] in blocks)]
    # an event the headline reverses ("set aside", "no impact") is not
    # brought back by the PDF's longer retelling of the same story
    vetoed = ({h["rule"] for h in raw} - {h["rule"] for h in hits}) | blocked
    if order_veto:
        vetoed.add("ORDER-WIN")
    by = "text"
    # read the PDF when the headline names no decisive event. A headline that
    # only names a tax notice ("update on show cause notice") is not decisive:
    # the outcome may be in the PDF.
    decisive = [h for h in hits if (h["dir"] != 0 or h["dominant"])
                and not (h["rule"] == "TAX-DEMAND" and not h["lost"])]
    if not decisive and pdf_info:
        ph = [_expand(h) for h in pdf_info.get("hits") or [] if h["rule"] not in vetoed]
        if ph:
            hits, by = hits + ph, "pdf"
    out = _resolve(hits, row, by)
    out["rules"] = sorted({h["rule"] for h in hits})
    return out


# Rules allowed to colour a row. Every other rule still names the event and
# still counts towards "conflicting signals", but leaves the row grey until it
# passes its own blind test (at least 95% right on fresh filings).
# Stage 1 (6 Oct 2026): only rules that were right every time in blind tests.
LIVE = {"AUD-RESIGN", "RATING-UP", "TAX-DEMAND", "FIRE",
        "PLEDGE-NEW", "PLEDGE-REL", "PLEDGE-PDF",
        # Stage 2: 106 of 110 right (96.4%) on fresh, blind-labelled August filings
        "ORDER-WIN"}

# Labels the exchanges' categories gave that the filing's own text contradicts.
# The row keeps its category in "sub"/"cat"; only the tag shown changes.
RELABEL = {
    "TAX-DEMAND": "Tax / regulatory order", "REG-ORDER": "Tax / regulatory order",
    "COMPOUNDING": "Compounding / settlement",
    "SEBI-ACTION": "SEBI / exchange action", "RULING-FAV": "Ruling on a dispute",
    "RULING-MIXED": "Ruling on a dispute", "COURT-STEP": "Court / tribunal step",
    "NCLT-SCHEME": "NCLT step on a scheme",
}
_WRONG_LABEL = {
    "Order win": {"TAX-DEMAND", "REG-ORDER", "COMPOUNDING", "SEBI-ACTION", "RULING-FAV", "RULING-MIXED", "COURT-STEP"},
    "Order awarded": {"TAX-DEMAND", "REG-ORDER", "COMPOUNDING", "SEBI-ACTION", "RULING-FAV", "RULING-MIXED", "COURT-STEP"},
    "Insolvency / tribunal matter": {"NCLT-SCHEME", "COURT-STEP"},
    "Insolvency proceedings": {"NCLT-SCHEME"},
}


def better_label(row, rules):
    """The tag to show instead of a category label the text contradicts, or None."""
    bad = _WRONG_LABEL.get(row.get("lab"))
    if not bad:
        return None
    for r in rules:
        if r in bad:
            return RELABEL[r]
    return None


def _gate(out):
    """Stage switch: a rule not yet proven leaves the row grey, saying so."""
    if out["dir"] != "neutral" and out["rule"] not in LIVE:
        return dict(out, dir="neutral",
                    reason="%s: not coloured yet - this rule is still being tested" % out["event"])
    return out


def _resolve(hits, row, by):
    return _gate(_resolve_all(hits, row, by))


def _resolve_all(hits, row, by):
    grey = {"dir": "neutral", "rule": None, "event": None, "text": None, "by": by}
    dom = [h for h in hits if h["dominant"]]
    if dom:
        h = dom[0]
        return dict(grey, rule=h["rule"], event=h["event"], text=h["phrase"],
                    reason="%s is not good or bad on its face" % h["event"])
    pos = [h for h in hits if h["dir"] > 0]
    neg = [h for h in hits if h["dir"] < 0]
    if [h for h in pos if h["rule"] == "RULING-FAV"] and neg and \
            all(h["rule"] == "TAX-DEMAND" and not h["lost"] for h in neg):
        neg = []      # an appeal won: the demand is only named as what was appealed
    if pos and neg:
        return dict(grey, rule="CONFLICT", event=None, text=None,
                    reason="conflicting signals: %s vs %s" % (pos[0]["event"], neg[0]["event"]))
    if not pos and not neg:
        if hits:
            h = hits[0]
            jc = h["rule"].startswith("JC-") or h["rule"] == "RATING-SAME"
            return dict(grey, rule=h["rule"], event=h["event"], text=h["phrase"],
                        reason=("%s: not coloured - how to colour this kind of filing is still to be decided" if jc
                                else "%s is not good or bad on its face") % h["event"])
        return dict(grey, reason="no specific phrase in the filing says this is good or bad news")
    h = (pos or neg)[0]
    d = "positive" if pos else "negative"
    old = _OLD.get(row.get("dc", row.get("dir")), 0)
    if old and old != (1 if pos else -1):
        return dict(grey, rule="CONFLICT", event=h["event"], text=h["phrase"],
                    reason="conflicting signals: the text says %s but the category says %s"
                    % (h["event"].lower(), "good news" if old > 0 else "bad news"))
    return {"dir": d, "rule": h["rule"], "event": h["event"], "text": h["phrase"],
            "reason": None, "by": h["src"] if h["src"] == "pdf" else "text"}


def pair_conflict(a, b):
    """BSE and NSE versions of one filing point opposite ways -> both grey."""
    da, db = _OLD.get(a.get("dir"), 0), _OLD.get(b.get("dir"), 0)
    return bool(da and db and da != db)


PAIR_CONFLICT = {"dir": "neutral", "rule": "CONFLICT", "event": None, "text": None,
                 "reason": "conflicting signals: the BSE and NSE versions point different ways",
                 "by": "text"}
