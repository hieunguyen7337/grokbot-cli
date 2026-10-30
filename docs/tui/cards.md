# Pending cards in the TUI

The session prompt shows a pending card's details. Tab focuses the prompt;
number keys or Enter choose an answer. Approvals open the confirmation dialog.

| Card | TUI answers |
|---|---|
| Connector grant | Allow once; always allow for this bot; always allow for all team bots; skip |
| Review approval | Approve; deny |
| Local tool permission | Allow once; always allow; deny; never allow |
| Email and Slack drafts | Send; discard; edit before sending |
| Meeting chat draft | Discard |
| Widget | Choose an option; dismiss |
| User form | Submit fields; dismiss |
| Secret request | Submit through a hidden input |

Connector grants use the gateway's `resolveConnectorGrant` command. The other
answerable cards use the backend card RPCs used by the app. Connector approvals
require confirmation; Skip sends immediately. A canceled confirmation sends nothing.

App-only cards show their details and offer only Later. Answer them in the Grok
Bot app:

| Card | Reason for app handoff |
|---|---|
| Virtual card payment | Payment selection and approval may need browser authentication or a passkey |
| Credential request | Brokered login opens 1Password; browser login needs the app or browser credential flow |
| Legacy permission request | No verified generic answer operation exists |
| Meeting join consent | No verified backend answer RPC exists |
| Publish, cookie origin, mobile tool, app secrets requests | No terminal answer path is implemented |
| Payment/account forms and spend guard widgets | Require the app's account or payment flow |
| Channel credential secret | Requires the app's credential flow |

Payment details include the amount, merchant, URL, valid line items and context.
Credential requests show the goal and sites or the target site and purpose.
Legacy permission requests show the permission kind, title, reason and detail.
Control characters display as visible escapes; card text is never interpreted as markup.
