# Review: unit M5h (egress, analytics, default payment method, address lookup, terms and teach)

Branch: `claude/unit-m5h-review-wkf418`, compared with `origin/gbot-tui` (`git diff origin/gbot-tui...HEAD`).
Scope checked against the M5h brief and the M5 common rules. This file is the only change made by the review.

## 1. Findings

No blocker or major defect was found. The five RPCs, the parsing rules, the CLI flags, the TUI slash commands, the
parity entries and the docs match the brief. Every verifier command passes (section 4). The findings below are minor.

1. **minor**: `gbot/service/account.py:299-300` (`_card_label`)
   - What is wrong: when the vault list is refused, `_card_label` catches the `ConnectError` and returns `A saved card`.
     The brief's common rule says a refused part of a combined read is shown as the refusal sentence, and the read
     still succeeds. The refusal message is dropped without any sentence.
   - Concrete input: `GetGrokBotDefaultPaymentMethod` returns `{"method": {"vaultCardId": "x"}}` and
     `ListGrokBotStripeLinkPaymentMethods` returns 403 `{"code":"permission_denied","message":"Vault is locked."}`.
     The panel shows `Default payment method: A saved card` and never shows `Vault is locked.`
   - Locked in by `tests/gbot_suite/test_service_account.py:230-233`.
   - Evidence: [OBSERVED gbot/service/account.py:299-300; tests/gbot_suite/test_service_account.py:230-233]

2. **minor**: `gbot/service/account.py:287-291` (`default_payment_method`, wallet branch)
   - What is wrong: any present `wallet` key yields `kind == "wallet"`, including the enum's UNSPECIFIED value. The
     protocol note lists UNSPECIFIED, X_MONEY and STRIPE_LINK for the wallet enum. An unspecified wallet is no wallet,
     so it should read as `none` (or at least not as a wallet). Instead it shows `A wallet`.
   - Concrete input: `{"method": {"wallet": 0}}` or `{"method": {"wallet": "GROK_BOT_PAYMENT_WALLET_UNSPECIFIED"}}`
     gives `DefaultPaymentMethod("wallet", "unknown", "A wallet")`, shown on `/payment` and `gbot account payment` as
     `A wallet`.
   - The test locks this in: `tests/gbot_suite/test_service_account.py:244-245`.
   - Evidence: [OBSERVED gbot/service/account.py:287-291; test lines 244-245]. The UNSPECIFIED = 0 numbering comes from
     `docs/protocol-m5c.md` section 9 [INFERRED that the intent is "no wallet"].

3. **minor**: `gbot/service/account.py:47` (`_int`, also `_enum` at lines 35-37)
   - What is wrong: the parsers do not guard the decimal string length. `int()` raises `ValueError` on a decimal
     string over 4300 digits, so a reply that the brief says must never raise on an odd shape does raise.
   - Concrete input: a reply with a 5000-digit string for `weeklyActiveUsers` (or `userId`) raises out of
     `analytics()`. In the CLI it becomes an error; in the TUI the panel body shows the exception text.
   - Probe run: `_int('9'*5000)` and `_enum('9'*5000, 'GROK_BOT_PAYMENT_WALLET', (...))` both raise
     `ValueError: Exceeds the limit (4300 digits) for integer string conversion`.
   - Evidence: [OBSERVED by running gbot.service.account._int and _enum in the repo's venv]. Severity is low because it
     needs an absurd reply, but it breaks the stated rule.

4. **minor**: `gbot/service/account.py:196` (`analytics`)
   - What is wrong: the signature is `Analytics | Refusal | None`. The brief's design names `analytics(transport,
     bot_id) -> Analytics | None`. Non-`not_found` refusals are returned as a `Refusal` value, not raised. The behaviour
     is what the brief's refusal rule wants (a notice, not a crash), but the typed contract differs from the brief
     and from the other functions here, which take the same approach as `egress_policy`.
   - Evidence: [OBSERVED gbot/service/account.py:196]

5. **minor**: the same-session-token tests cannot fail for the regression they name.
   - `tests/gbot_suite/test_service_account.py:380-398` (`test_same_session_token_for_suggest_and_resolve`) replaces
     `service.new_session_token` with a constant and then passes a literal `SESSION` to `resolve_address`. It never
     runs the lookup flow, so it passes whatever the flow does with its token.
   - `tests/gbot_suite/test_cli_account.py:33` and `:180-204` and `tests/gbot_suite/test_tui_account.py:182` and
     `:206-211` also patch `new_session_token` to a constant. A regression where the CLI or TUI calls
     `new_session_token()` a second time for the resolve step still returns the same value, so those tests still pass.
   - Concrete mutation: call `service.new_session_token()` again inside the `--pick` branch of
     `gbot/commands/account.py:136` (`_address`). Every test in this file still passes.
   - Evidence: [INFERRED from reading the tests; I did not run this mutation because the review changes nothing else].

6. **minor**: `gbot/tui/slash/account.py:57-64` (`_Read.reload`)
   - What is wrong: each `g` press starts a new thread worker with no sequence check, and `loaded` overwrites the
     panel with whichever result arrives last. A slow earlier load can replace a newer result.
   - Concrete state: the first load is still running when the user presses `g` again after changing the reply. If the
     first thread finishes second, the panel shows the old reply.
   - Evidence: [INFERRED from the code; no test covers two overlapping reloads]

Nothing in the review depends on live services. No secret (the vault card id or the session token) reaches output,
notices, errors or reprs in the code or in the tests I read.

## 2. Parity entries changed

Compared with `git show origin/gbot-tui:docs/parity.json` (574 entries before and after, no added or removed entries).
Only these seven entries changed, and each changed only `status` and `note`:

| name | old status | new status | note |
| --- | --- | --- | --- |
| getTeachRecordingStatus | planned | handoff | Teach recording runs on the desktop; see it in the Grok Bot app. |
| GetGrokBotAgentAnalytics | planned | done | Implemented in gbot.service.account |
| GetGrokBotDefaultPaymentMethod | planned | done | Implemented in gbot.service.account |
| GetGrokBotEgressPolicy | planned | done | Implemented in gbot.service.account |
| MarkGrokBotTermsSeen | planned | handoff | The app records when the person has seen its terms; accept terms in the Grok Bot app. |
| ResolveGrokBotAddress | planned | done | Implemented in gbot.service.account |
| SuggestGrokBotAddresses | planned | done | Implemented in gbot.service.account |

These match the brief's section 4 exactly.

## 3. Out-of-scope files changed

None. `git diff --stat origin/gbot-tui...HEAD` lists only in-scope files:
`docs/gbot.md`, `docs/parity.json`, `docs/tui/account.md`, `gbot/commands/account.py`, `gbot/service/account.py`,
`gbot/tui/slash/account.py`, `tests/gbot_suite/snapshots/panel-analytics.svg`, `tests/gbot_suite/test_cli_account.py`,
`tests/gbot_suite/test_service_account.py`, `tests/gbot_suite/test_tui_account.py`.

## 4. Verifier commands (final output lines)

`uv run --no-sync pytest tests/gbot_suite -q -p no:cacheprovider` (exit 0)
```
........................................................................ [ 95%]
....................................................................     [100%]
1508 passed in 197.25s (0:03:17)
```

`uv run --no-sync ruff check groken gbot tests` (exit 0)
```
All checks passed!
```

`uv run --no-sync ruff format --check gbot tests/gbot_suite` (exit 0)
```
215 files already formatted
```

`uv run --no-sync basedpyright --level error` (exit 0)
```
0 errors, 0 warnings, 0 notes
```

`uv run --no-sync python -m json.tool docs/parity.json > /dev/null && echo parity ok` (exit 0)
```
parity ok
```
