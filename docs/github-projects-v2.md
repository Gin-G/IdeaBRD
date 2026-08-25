# GitHub Projects v2: decided against

**Decision: no.** An idea's work is tracked in its repository's issues, which is
already wired up in both directions, and the board mirrors that. Projects v2
would add a third place for the same items to live.

This was carried as an open question on the board for a while. Writing down why
it was closed is more useful than leaving it open, since the reasons are the
kind that get rediscovered expensively.

## What it would have bought

A GitHub Project is a board with columns, custom fields and views, kept by
GitHub. Ideas already have a status (`idea`/`active`/`paused`/`done`) and to-dos
that can be GitHub issues, so a project would give: a second board view of the
same items, on GitHub, with a Status field that could be mapped to ours.

## What it would have cost

**None of the existing GitHub client is reusable.** Projects v2 is GraphQL-only.
`app/github.py` is REST throughout — every helper, every error mapping, every
test fixture. Supporting projects means a second client, a second set of error
translations and a second thing to keep working.

**Every existing GitHub login has to re-authorize.** It needs the `project`
scope. OAuth tokens do not gain scopes: a token minted before the app asked for
one keeps the scopes it had, so *every* connected account would have to go
through the flow again, and until they did the feature would be invisible in a
way that looks like a bug. The `read:org` scope taught this lesson already —
which is why `whoami` reads the granted scopes from the response header rather
than assuming.

**A project is not owned by an idea.** Projects belong to a user or an
organisation, not to a repository. So an idea would need its own project id
stored, plus a mapping from our four statuses onto that project's Status field
options — which are per-project, user-renameable, and may not exist at all. That
mapping is configuration nobody wants to fill in, and it silently rots when
someone renames a column.

**Two boards is worse than one.** The failure mode is not a missing feature, it
is an idea that says "active" here and sits in "Done" there, with no answer to
which is right.

## What we did instead

The direction that was missing turned out to be the cheap one: the board could
push a to-do to GitHub as an issue but never pick up issues that started there.
Importing a repository's issues as to-dos (`POST /api/ideas/{id}/todos/import`)
closes that loop with the REST client we already had, no new scope, and no
second source of truth — the issue stays authoritative for its own title and
state, exactly as a promoted to-do already did.

If this is ever reopened, the thing to check first is whether GitHub has given
Projects a REST surface, and whether the `project` scope can be requested
incrementally. Both of those are what make it expensive, and both are GitHub's
to change.
