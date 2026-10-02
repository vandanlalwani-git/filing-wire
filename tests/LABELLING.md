# How the golden set is labelled

Each filing is read from its own text (BSE headline and subject, NSE
description and attachment text) and, where that is too thin, the first
pages of its PDF. It is then labelled:

- **Favourable**: good for shareholders on the face of the event
- **Adverse**: bad for shareholders on the face of the event
- **Unclassified**: depends on details or context we can't see

Labels are written before any rule, and 30% of filings are held out and not
looked at while rules are written.

## Conventions applied to every filing

| event | label |
|---|---|
| Commercial order or contract received by the company | Favourable |
| Tax / customs / GST / regulator demand, penalty or adverse order against the company | Adverse |
| Ruling, appeal or order in the company's favour (demand dropped, set aside, quashed, refund ordered) | Favourable |
| Compounding of an offence, with a fee paid for a breach | Adverse |
| Insolvency petition filed against / admitted against the company; CIRP; moratorium | Adverse |
| Insolvency petition against the company dismissed or withdrawn | Favourable |
| The company itself filing against a debtor; CIRP of an unrelated party | Unclassified |
| Routine procedure for a company already in insolvency (creditors' meeting notices/outcomes, hearings adjourned, quarterly results under CIRP) | Unclassified: no new development |
| Voluntary liquidation of a non-material subsidiary | Unclassified |
| NCLT-convened shareholder/creditor meetings for a scheme | Unclassified |
| NCLT sanctioning a scheme, merger or demerger | Unclassified (effect depends on the scheme) |
| Credit rating upgrade; outlook raised | Favourable |
| Credit rating downgrade; rating watch negative; outlook cut | Adverse |
| New rating assigned; rating withdrawn at the company's request | Unclassified |
| Statutory auditor resigning mid-term | Adverse |
| Auditor appointed, re-appointed, or leaving at the end of the term | Unclassified |
| Default or delay in paying interest or principal | Adverse |
| Fire, accident, explosion, shutdown, strike at the company's operations | Adverse, unless the filing says operations are normal and there is no material impact (then Unclassified) |
| Plant commissioned, commercial production started, capacity actually added | Favourable |
| Capex or expansion approved or proposed (not yet built) | Unclassified: depends on returns |
| Product launch, marketing press release | Unclassified |
| Industry-wide strike notice not specific to the company | Unclassified |
| Drug regulator: warning letter, import alert, OAI, Form 483 with observations | Adverse |
| Drug regulator: approval, EIR received, inspection closed with zero observations / NAI / VAI | Favourable |
| SEBI or exchange penalty, order or warning against the company | Adverse |
| Search, raid or survey by authorities at the company | Adverse |
| Pledge created or invoked | Adverse |
| Pledge released | Favourable |
| Search concluded and the company says there is no liability or impact (e.g. tax found is fully creditable) | Unclassified |
| Show-cause notice, demand notice, assessment order with a demand, penalty levied | Adverse (even if the company says "no material impact") |
| Appeal lost (appeal dismissed, demand upheld/confirmed) | Adverse |
| Appeal won, demand set aside/deleted/nullified, refund sanctioned after a win, proposed demand cut sharply | Favourable |
| Appeal partly allowed with a reduced amount still confirmed | Unclassified (mixed) |
| Hearing notice, writ petition filed, appeal filed by the tax department (no outcome yet) | Unclassified |
| Fraud found at the company (cyber fraud, misappropriation); SFIO investigation notice | Adverse |
| Fire with injuries/fatality or a stated material loss | Adverse; fire contained with operations normal and no material loss, or a later insurance settlement, is Unclassified |
| Operations fully restored after a disruption | Favourable; partly restored is Unclassified |
| Secretarial, internal or cost auditor resigning | Unclassified |
| ESG rating (any direction) | Unclassified: not a credit event |
| Debt security suspended from trading on maturity, conversion or redemption | Unclassified: routine |
| Contract signed or amended for an order already disclosed | Unclassified: not new news |
| A company name or product name that happens to contain an event word ("Nitin Fire Protection", a "Shutdown" software product) | Unclassified |
| Routine filings (AGM, trading window, newspaper ads, investor meets, results without figures, clarifications) | Unclassified |

## Judgement calls (the owner decides; scored separately)

Dividend declared, buyback, bonus/split, fund raising (QIP, preferential,
rights), acquisition, CEO/CFO/MD resignation, independent director
resignation, credit rating reaffirmed. These are labelled with a
recommendation and flagged `judgement_call: true`; they are excluded from
the accuracy target until a decision is made.

## Splits

`tests/golden.json`: 463 filings. 30% are held out by a fixed hash of the
filing id ("fw-golden-2026|<id>"); the rules were written against the other
70% only. `tests/golden_pairs.json`: 399 merged BSE/NSE pairs, split the
same way ("fw-pairs-2026|<bse>|<nse>").
