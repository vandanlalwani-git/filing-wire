# The Filing Wire

**Live site: https://vandanlalwani-git.github.io/filing-wire/**

The Filing Wire is a live feed of company announcements filed with India's two
stock exchanges, BSE and NSE. Each filing is shown as one plain line. Its
colour shows the direction — Adverse, Favourable or Unclassified — and its
weight shows how much it matters: Critical, Notable or Routine. When a company
files the same announcement on both exchanges, it appears once.

**Disclosure events only, classified by fixed rules. Not investment advice.**
No AI is used anywhere: every filing is sorted by a fixed list of rules, and
when the rules can't tell whether news is good or bad, it is marked
Unclassified rather than guessed.

## Rare rules

Two events are too rare to test on 30 past filings, so they were switched on
after showing no wrong colour on every filing available: a new buyback
approved by the board (Favourable) and an independent director resigning over
governance concerns (Adverse). Every time either one colours a filing it is
recorded in `rare_rules_log.json` on the `data` branch (date, company, the
phrase that triggered it, link to the filing) for a weekly review.
If a rare-rule colour is wrong, it gets switched off.

## How often it updates

The site updates roughly every 5 to 30 minutes. It runs on GitHub's free
schedule, which is set for every 5 minutes but often starts late when GitHub
is busy. The top of the page always says how fresh the data is ("Updated 4 min
ago"), and shows a short notice if updates are running late or one of the
exchanges couldn't be reached.

You can look back at earlier days with the date arrows at the top. The site
keeps the last 90 days.

## If the site says "Updated N hours ago"

GitHub pauses scheduled jobs in a repository that has had no activity for
60 days. If that happens, the site stops updating but keeps showing the last
data it had. To switch it back on:

1. Open https://github.com/vandanlalwani-git/filing-wire
2. Under the repository name, click **Actions**.
3. In the left sidebar, click **Collector**.
4. If you see a message that the workflow is disabled, click
   **Enable workflow**.
5. To update straight away instead of waiting for the next scheduled run:
   on the same page click **Run workflow**, leave the options as they are,
   and click the green **Run workflow** button. The site updates within a
   couple of minutes.

If Collector is switched on but the site is still not updating, the newest run
in the list will have a red mark. Click it to see what went wrong. The site
keeps showing the last good data in the meantime.
