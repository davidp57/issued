# Triage labels

Matt's triage roles map one to one onto GitHub labels of the same name on `davidp57/issued`.

| Label | Meaning |
|---|---|
| `needs-triage` | raw report, not yet specified |
| `ready-for-agent` | specified; an agent can pick it up |
| `ready-for-human` | blocked on a human action: a test, a decision |
| `needs-info` | waiting for information |
| `wontfix` | will not be done; the reason is in a comment |

Lifecycle labels, with no triage-role equivalent:

| Label | Meaning |
|---|---|
| `in-progress` | being worked on; replaces `ready-for-agent` |
| `paused` | deliberately parked; the reason is in a comment, otherwise it reads as forgotten |

Done is not a label: the issue is closed.

Structural labels: `lot` marks a parent issue holding a PRD, `upstream` marks work meant to be shared with the author.
