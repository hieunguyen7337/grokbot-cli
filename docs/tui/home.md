# Home loading and card sweep

Home shows what it is doing until the bot list is ready. The line sits above
the list. It fits 80 columns, and the list, the dispatch input and the keys
keep working while it shows. It goes away when loading has settled.

## Loading lines

| Stage | Line | When |
|---|---|---|
| Connecting | `Connecting to Grok Bot... 12 s` | From start until the bot list arrives. The count goes up once a second. After 5 seconds a second line says starting your cloud computer can take about 30 s. |
| Loading | `Loading bots...` | After the bot list arrives, until home lists it. |
| Checking | `Checking for cards 5/16` with a bar | While the card sweep runs. The count is the bots checked so far out of all bots in the sweep. |

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
- Each bot's cards appear as soon as its check finishes.
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
