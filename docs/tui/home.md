# Home loading and card sweep

Home shows what it is doing until the bot list is ready. The line sits above
the list. It fits 80 columns, and the list, the dispatch input and the keys
keep working while it shows. It goes away when loading has settled.

## Loading lines

| Stage | Line | When |
|---|---|---|
| Connecting | `Connecting to Grok Bot... 12 s` | From start until the bot list arrives. The count goes up once a second. After 5 seconds a second line says starting your cloud computer can take about 30 s. |
| Loading | `Loading bots...` | After the bot list arrives, until home lists it. |
| Checking | `Checking for cards 5/16` with a bar | While the newest-page checks of the card sweep run. The count is the bots checked so far out of all bots in the sweep. |
| Older cards | `Checking older cards 1/3` with a bar | After every bot's newest-page check has ended, while the full reads of the waiting bots run. The count is the waiting bots read in full so far out of the waiting bots in the sweep. |

The spinner holds still when animations are off and in `--ascii` mode.
In `--ascii` mode every symbol is plain ASCII: the dots are `...` and the bar
uses `#` and `-`.

## Card sweep

Home lists the bots as soon as the bot list arrives. gbot then checks every
bot for cards that need an answer. Bots that already need input are checked
first, so their cards appear soonest.

- Up to 4 checks run at once. The constant is `CARD_SWEEP_PARALLEL` in
  `gbot/tui/app.py`, and its default is 4.
- The other bots are checked in the order the list shows them, so the bots
  at the top of the list get their cards first.
- The sweep works in two passes. First every bot gets a quick check of its
  newest page only (`HOME_RECENT_PAGES` in `gbot/tui/app.py`), waiting bots
  included. Each bot's newest cards appear as soon as its quick check finishes.
- Then each waiting bot gets a full check that reads every page. These checks
  wait at the end of the sweep, after every quick check, so the older cards of
  a waiting bot show after the rest of the list has its newest cards. The
  waiting bots are the ones the roster shows with a waiting flag or a waiting
  session. A waiting bot's full check starts only after its quick result is on
  home, or after its quick check failed. It is skipped when the bot's cards
  were already refreshed, and a quick result never replaces a full one, the
  sweep's or a refresh's. A warning that both checks report shows once.
- A card further back on a bot that is not waiting does not show during the
  sweep. It shows once that bot's cards are read in full. That happens when the
  bot adds a card, when an entry arrives while the bot is flagged as waiting,
  after a resync, or at the next start if the bot is waiting then.
  `gbot approvals --all` and `gbot approvals --bot <name>` always read in full.
- The sweep ends only when every quick check and every full check has ended.
- The sweep reuses the bot list that was already loaded. It does not list the
  roster again for each bot.
- A 401 from the gateway stops the sweep from starting new checks. The user
  sees one error notice, even when several checks were already running.
- Any other error on one bot shows a short error badge on that bot. It does
  not stop the sweep or show a notice.
- Quitting does not wait for checks that are still running on the network.

## Session and Peek

A session and the Peek panel show a loading line until their first page of
transcript arrives. A failed first page ends the loading line. A session then
shows its error and retry hint. Peek shows its error as a notice.
