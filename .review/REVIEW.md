# Review of unit M5d (cloud agents, apps, app secrets, publish proposals)

Scope: `git diff origin/gbot-tui...HEAD` on `claude/unit-m5d-review-gwypta` (11 files). Reviewed the service, CLI and TUI modules in full, the three test files, the docs, and `docs/parity.json`. The verifier passes (section 4), but the review found defects against the brief. Nothing was fixed.

## 1. Findings (most severe first)

### F1 - major: a cloud agent with a very negative `createdAt` crashes the info view
- Where: `gbot/service/cloud_agents.py:122-128` (`CloudAgentInfo.fields`, `datetime.fromtimestamp` with no guard); reached from the CLI at `gbot/commands/cloud_agents.py:309-310` and from the TUI at `gbot/tui/slash/cloud_agents.py:439` and `:448` (`loaded` calls `content()` on the UI thread).
- Wrong: the guard is `self.created_at < 10**14`, which accepts large negative values. `datetime.fromtimestamp` then raises. The brief says nothing raises on an odd reply.
- Input: `getCloudAgentInfo` reply `{"bcId": "b", "createdAt": -10**14}`.
- Observed: `s.info(t, "b").fields` raises `ValueError: year -1199 is out of range` (probe run on this branch).
- Evidence: [OBSERVED gbot/service/cloud_agents.py:122-128] and [INFERRED: the TUI call path at `tui/slash/cloud_agents.py:448` runs inside Textual's message loop, so the error is not caught and ends the app].

### F2 - major: visibility is sent as the short name, not the full enum name
- Where: `gbot/service/cloud_agents.py:312-316` (`_visibility` returns the lowercase short name), used at `:336` and `:509`. Tests pin the short names at `tests/gbot_suite/test_service_cloud_agents.py:187` and `:361` and `tests/gbot_suite/test_cli_cloud_agents.py:105` and `:116`.
- Wrong: the common rules say to send enums as full names. `docs/protocol-m5b.md:153-154` gives only the values "private, team and public" and no full wire name. The unit should have sent the documented form, or reported the full name as unresolved. Neither was done.
- Input: `update_app(..., "team")` sends `"visibility": "team"`.
- Evidence: [OBSERVED code and tests]; the full-name requirement is [INFERRED from the brief and the protocol note, which has no full name].

### F3 - major: a refused "tell secrets set" call is not shown as a refusal
- Where: `gbot/tui/slash/cloud_agents.py:314-321` (`_AppSecretForm.save`) and `gbot/commands/cloud_agents.py:239-246` (`run_cloud_agent`, set path). Neither call is wrapped by `refusal()`.
- Wrong: the secret set succeeds, then `tellCloudAgentAppSecretsSet` is refused with a server code (for example `permission_denied`). The refusal is not converted to its sentence. In the TUI the raw `str(error)` reaches `_submit_error`. In the CLI the ConnectError goes to the generic handler.
- Input: `setCloudAgentAppSecrets` returns `{"applyNeeded": true}` and `tellCloudAgentAppSecretsSet` raises `ConnectError(403, {"code": "permission_denied", "message": "Not on this account."})`.
- Evidence: [OBSERVED: no try or `refusal()` around those calls]; the resulting message text is [INFERRED].

### F4 - minor: a conversation reply with a `messages` mapping hides a valid `turns` list
- Where: `gbot/service/cloud_agents.py:213-217` (`_messages` returns on the first Mapping under `messages`, `conversation` or `turns`).
- Wrong: the brief says to take the first list among the three keys. A Mapping under an earlier key ends the search.
- Input: `{"messages": {"x": 1}, "turns": [{"text": "hi"}]}` returns `()`. The expected result is one message `("unknown", "hi")`.
- Evidence: [OBSERVED probe]. The test at `tests/gbot_suite/test_service_cloud_agents.py` does not cover this case.

### F5 - minor: a reply that says `state: FAILED` with no `ok` or `error` counts as success
- Where: `gbot/service/cloud_agents.py:298-305` (`_result`: `ok` defaults to `not error`).
- Input: `updateCloudAgentPublishApp` returns `{"state": "FAILED", "message": "Slug taken"}`. The result is `AppResult(ok=True, state="failed", ...)`.
- Effect: `gbot apps --update ...` prints "Slug taken" and exits 0 (`gbot/commands/cloud_agents.py:81-84`). The TUI `_mutate` does not raise (`gbot/tui/slash/cloud_agents.py:76`), so the notice is treated as a success.
- Evidence: [OBSERVED probe]; that `FAILED` means refused is [INFERRED], since the reply shape is UNKNOWN in the protocol note.

### F6 - minor: `app_secret_names` lists any string-valued reply as secret names
- Where: `gbot/service/cloud_agents.py:378-379`.
- Input: `getCloudAgentAppSecrets` returns `{"status": "ok"}`. `app_secret_names` returns `("status",)`. The CLI prints `status` as a secret and the TUI shows a row for it.
- Evidence: [OBSERVED probe].

### F7 - minor: URLs are not removed from every reply field the brief covers
- Where: `gbot/service/cloud_agents.py:268-275` (`_app`: `slug`, `apex`, `bc_id` are not passed through `_safe`), `:484` (proposal `slug`), `:221` (`Message.role`) and `:353-362` (secret names). `_safe` is applied only to some fields.
- The brief says any URL in a reply must not reach output.
- Input: `listCloudAgentPublishedApps` returns `{"kind": "on", "apps": [{"slug": "https://x.invalid/?ticket=t", "apex": "a", "visibility": "team"}]}`. The CLI prints the link.
- Evidence: [OBSERVED probe `apps(t5).apps[0].slug` returns the URL unchanged; output path is [INFERRED from `gbot/commands/cloud_agents.py:87-94`, which passes `slug` through]].

### F8 - minor: a refused single change writes the refusal to stdout
- Where: `gbot/commands/cloud_agents.py:81-84` (`_write_result` writes the message through `ctx.out.write` and returns 1).
- The brief says a refused change exits 1 with the server's message as the error message. Here it goes to stdout and stderr is empty. The test at `tests/gbot_suite/test_cli_cloud_agents.py:201-204` asserts `out == "Busy"`, which pins the deviation.
- Evidence: [OBSERVED code and test].

### F9 - minor: the TUI empty states for conversation and proposals are blank
- Where: `gbot/tui/slash/cloud_agents.py:428-437`. The conversation and proposal sections are shown only `if self.messages` and `if self.proposals`. With no messages or proposals, nothing is shown.
- The brief says an empty state is one plain sentence, not an empty list. The CLI does print sentences (`No messages.`, `No publish proposals.`); the TUI does not.
- Evidence: [OBSERVED code].

### F10 - minor: the app form silently changes an unknown visibility to private
- Where: `gbot/tui/slash/cloud_agents.py:113` (`app.visibility if app.visibility in _CHOICES else "private"`).
- Input: an app whose reply has `visibility` = `unspecified` or `unknown`. The form opens with `private` selected, and saving sends `private` without the user choosing it. The confirm title (`Update app <slug> as private?`) does show the change, which partly mitigates it.
- Evidence: [OBSERVED code]; the confirm text is [OBSERVED at `:128-130`].

### F11 - minor: the docs headings do not match the brief's names
- Where: `docs/gbot.md` (new sections named `## apps` and `## cloud-agent`).
- The brief names `## gbot apps` and `## gbot cloud-agent`. The implementation follows the convention of the other 38 sections (`## bot`, `## approvals`, and so on), which is reasonable, but it differs from the literal brief. The flags are all documented.
- Evidence: [OBSERVED `grep -n "^## " docs/gbot.md`].

### F12 - minor: one secret assertion passes only because the implementation mutates its own payload
- Where: `tests/gbot_suite/test_tui_cloud_agents.py:345` (`SECRET not in repr(service.transport.calls)`) and `tests/gbot_suite/test_service_cloud_agents.py:313` (`fake.calls[0][2]["secrets"] == []`). `set_app_secrets` clears the list in place (`gbot/service/cloud_agents.py:430`).
- If the transport kept a copy of the payload, the first assertion would still say nothing about it. The second test pins the in-place clearing, not the behaviour the brief asks for.
- Evidence: [OBSERVED code].

No other defect was found in the parsing paths, the TUI key bindings, confirm texts, read-only refusals, Cancel focus, or the thread workers. The brief's parity and docs flag coverage checks pass (section 2 and section 3).

## 2. Parity entries changed

Compared with `origin/gbot-tui`. 13 entries changed and none were added or removed. Each changed from `planned`:

| Entry | Old status | New status | Note |
|---|---|---|---|
| getCloudAgentInfo | planned | done | Implemented in gbot.service.cloud_agents |
| getCloudAgentConversation | planned | done | Implemented in gbot.service.cloud_agents |
| stopCloudAgent | planned | done | Implemented in gbot.service.cloud_agents |
| listCloudAgentPublishedApps | planned | done | Implemented in gbot.service.cloud_agents |
| updateCloudAgentPublishApp | planned | done | Implemented in gbot.service.cloud_agents |
| unpublishCloudAgentPublishApp | planned | done | Implemented in gbot.service.cloud_agents |
| getCloudAgentAppSecrets | planned | done | Implemented in gbot.service.cloud_agents |
| setCloudAgentAppSecrets | planned | done | Implemented in gbot.service.cloud_agents |
| tellCloudAgentAppSecretsSet | planned | done | Implemented in gbot.service.cloud_agents (old note: "Report the outcome of supplying cloud app secrets.") |
| getCloudAgentPublishProposals | planned | done | Implemented in gbot.service.cloud_agents |
| confirmCloudAgentPublishProposal | planned | done | Implemented in gbot.service.cloud_agents |
| dismissCloudAgentPublishProposal | planned | done | Implemented in gbot.service.cloud_agents |
| createCloudAgentAppsGateTicket | planned | handoff | The app opens the gate in its in-app web view with a short-lived ticket; open the app in Grok Bot. (old note: "Obtain access to a published cloud app.") |

The statuses and notes match the brief. `docs/parity.json` is valid JSON.

## 3. Out-of-scope files changed

- `tests/gbot_suite/test_docs.py`: two regex lines changed (the `## ([\w-]+)` heading split at line 35 and the `gbot ([\w-]+)` example match at line 50). The change is needed so the hyphenated `cloud-agent` heading is checked, but the brief did not list this file. Commit `98da3da`.

No other file outside the brief's list changed. `docs/parity.md` was not edited. The snapshot is only the new `tests/gbot_suite/snapshots/panel-apps.svg`.

## 4. Verifier commands (final output lines)

Setup: `uv sync --locked --all-extras --group dev` (run first; a plain `uv run --no-sync` before it had created an empty `.venv` with no dependencies, which caused 86 collection errors). `.venv` is git-ignored.

- `uv run --no-sync pytest tests/gbot_suite -q -p no:cacheprovider`
  ```
  ........................................................................ [ 97%]
  ..............................................                           [100%]
  1558 passed in 192.53s (0:03:12)
  ```
- `uv run --no-sync ruff check groken gbot tests`
  ```
  All checks passed!
  ```
- `uv run --no-sync ruff format --check gbot tests/gbot_suite`
  ```
  215 files already formatted
  ```
- `uv run --no-sync basedpyright --level error`
  ```
  0 errors, 0 warnings, 0 notes
  ```
- `uv run --no-sync python -m json.tool docs/parity.json > /dev/null && echo parity ok`
  ```
  parity ok
  ```

All verifier gates pass. The findings above are defects the gates do not catch.
