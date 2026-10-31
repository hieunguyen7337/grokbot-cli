# Sharing and access

`/share` shows who has the selected bot and lets you change it. `/invite` accepts
an invite someone sent you. The same things are available from the command line
as [`gbot share`](../gbot.md#share). Both are limited by what the server allows
the account to do: on a personal account with no team most changes are refused,
and the server's own sentence is shown as a plain notice (never a stack trace).

## `/share`

Works in a bot session. The panel `Share <bot>` lists, top to bottom:

- the owner (with `(you)` when that is you);
- each access row: a person, a group, another team or the organization, with the
  name from the server's directory when it has one (`User #12` when it does not)
  and its role, `user` or `manager`;
- `Team row`, on (with its role) or off: the row that gives everyone in the
  team access;
- `Link access`, as the server reports it;
- each manager, and `No managers` when there are none;
- each invite you sent, with its expiry (UTC date), and how many of the bot's
  invites are used.

A part the server refuses is one sentence in its place (for example
`Invites: ...`); the rest of the panel still loads. A failure that is not a
refusal shows the usual error line with `r` to retry.

Keys are shown in the footer only when they apply to the selected row and to what
the server said:

| Key | Does | Confirm |
|-----|------|---------|
| `a` | add a person, group, organization or the team from the directory, then pick a role (skipped when only one role exists) | `Give <name> access to <bot>?` or `Make <name> a manager of <bot>?` |
| `r` | change the selected row's role | `Change <name> to user on <bot>?` or the manager question |
| `x` | remove the selected row | `Remove <name> from <bot>?` |
| `t` | turn the team row on (as `user`) or off; off is hidden when the server will not allow it | `Turn on the team row for <bot>?` / `Turn off the team row for <bot>?` |
| `v` | make the bot visible to the team | `Make <bot> visible to your team?` |
| `p` | share the same bot with the team in place | `Share <bot> with your team in place?` |
| `c` | clone the bot to the team | `Clone <bot> to your team?` |
| `i` | invite an email address (the server sends the email) | `Invite <email> to <bot>?` |
| `e` | revoke the selected invite | `Revoke the invite for <email> to <bot>?` |
| `m` | pick a person to add as, or remove from, the managers | `Make <name> a manager of <bot>?` / `Remove <name> as a manager of <bot>?` |
| `g` | reload | none |

Setting the team row to manager, by `a` or by `r` on the team row, asks
`Make everyone in the team a manager of <bot>?` instead.

Every change is refused in read-only mode with the notice `Read-only mode`, asks
through a confirmation with Cancel focused that names the bot and the change, runs
in a background worker, and reloads the panel afterwards. An access change reads
the access list again just before it is sent and sends the whole list back with
the server's token, so a change someone else made in between is refused rather than
overwritten. The owner is never part of that list. The result is a notice: the
server's sentence for visibility, clone and sharing in place, `Updated access to
<bot>.`, or for an invite whether the email went out and how many invites are used.
The invite link is never shown.

### Sharing in place

After `p` is confirmed and the server starts the job, the panel gets a
`Share in place` row with the state and the step (check, mark, memory, files,
verify files, grants, flip, finish, clear) and reads the status on a timer: after
1 second, then 1.5 times the last wait, never more than 5 seconds. It stops when
the share is done or failed (the notice says why), when the server refuses the
read, after 45 minutes, or when the panel is closed. A transient read error is
retried. The job keeps running on the server either way; `/share` or
`gbot share <bot> --share-status` reads it later.

## `/invite`

Works anywhere. A masked input takes the invite code or the whole link from the
invite email (the code is the link's `token`); it is cleared when you submit and
never shown. The preview lists the sender, the bot, your role, the invite's state
and expiry, whether it was sent to your email address, and whether your account is
eligible. An unknown code, a refusal or a failure stays on the form as a notice,
with the code removed from the message.

`a` appears only when the invite is open, was sent to you and your account is
eligible. It asks `Accept access to <bot>?` (Cancel focused, refused in read-only
mode) and then shows the result as a notice: `Invite accepted.` and one line per
bot, or the sentence for why not.

## What stays in the Grok Bot app

Any access state this version cannot read faithfully (an unrecognized row or role)
makes an access change refuse and point to the app. Returning a team-visible bot to
private, changing link access, and the invite emails themselves are not offered.

Demo replies for `gbot tui --demo` come from `DEMO_RPCS` in
`gbot/service/sharing.py`: they show the owner, the team row, two rows, one manager
and one invite, and answer the team-only changes the way a personal account does.
