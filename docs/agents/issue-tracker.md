# Issue tracker: GitHub issues on the fork

Lots, PRDs and tickets live as GitHub issues on `davidp57/issued`, our fork. Never on `metalogico/issued`, the author's repository.

## Conventions

- A **lot** is a parent issue labelled `lot`. Its body is the PRD.
- A **ticket** is a **sub-issue** of its lot. Blocking edges use GitHub's native "blocked by" relationship.
- One lot = one branch = one PR, whatever the number of tickets.
- Status is carried by labels (see `triage-labels.md`). Done = the issue is closed.
- A lot meant to be shared with the author also carries `upstream`. Its branch starts from `upstream/develop` (see `CLAUDE.md`, *Fork workflow*).

## When a skill says "publish to the issue tracker"

- A PRD → `gh issue create -R davidp57/issued --label lot --label ready-for-agent`, the PRD as the body.
- A ticket → create the issue, then attach it to its lot as a sub-issue, and record its blockers as "blocked by" links:

```bash
gh api -X POST repos/davidp57/issued/issues/<lot>/sub_issues -F sub_issue_id=<ticket issue id>
gh api -X POST repos/davidp57/issued/issues/<ticket>/dependencies/blocked_by -F issue_id=<blocker issue id>
```

The `id` these endpoints expect is the issue's database id (`gh api repos/davidp57/issued/issues/<number> --jq .id`), not its number.

- New issues are created with `ready-for-agent`.

## Pull requests

- A fork PR closes its tickets with `Closes #<n>`: both live on the fork.
- A PR to the author mentions none of our issues, and our issues and PRs never mention the author's.
