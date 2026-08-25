---
status: active
progress: 60
---

# My idea

<!--
IdeaBRD parses this file. It is the source of truth for this idea's tile:
the app re-reads it on every open and commits its own edits back here, so
the shape below matters more than it looks. Anything the parser
(backend/app/ideafile.py) can't read is dropped silently.

  frontmatter  status: one of idea, active, paused, done. progress: 0-100.
               Any other key is ignored.
  # heading    The idea title (first H1).
  prose        Everything outside the Todos section becomes the tile's
               notes, shown on the board — so keep it short. Documentation
               written here is published, not filed away.
  ## Todos     That heading exactly (or "## To-Dos"); "## ToDo", "## TODO"
               and "## Tasks" do not match and the whole list is lost.
               Inside it, only "- [ ] open" / "- [x] done" lines survive:
               sub-headings and blank-line grouping are discarded, and a
               wrapped item is cut at the line break, so keep each to-do on
               one line. The next "## " heading ends the list.
  (#12)        A to-do ending in an issue reference is backed by that issue
               in this repo. The issue wins: its title becomes the to-do's
               text and its open/closed state the checkbox, both here and on
               the board. Ticking the box in the app closes the issue.

Working in this repo? This file is the to-do list — use it rather than
starting a parallel one. Tick items off as you finish them, add new ones as
you find them, and keep status/progress honest: a TODO.md, a plan in a chat
window or a checklist in a commit message is invisible to everyone reading
the board. For work worth assigning, discussing, or writing up at length,
open a real issue and append its "(#12)" to the line — the item is then
tracked by number instead of text, and the issue holds the detail this file
has no room for (prose here is published to the board, not filed away).

To-dos without an issue are matched to the board by exact text, so rewording
one replaces it rather than editing it in place — expect a checked item to
come back unchecked if you reword it. Issue-backed to-dos are matched by
number instead, so keep the "(#12)" and reword freely; drop the reference and
the item becomes an ordinary to-do again (the issue itself is left alone).

HTML comments are stripped on read, so this block never reaches the board.
-->

Some notes.

More notes, with a [link](https://example.com).

## Todos

- [x] set up repo
- [ ] build MVP
- [ ] ship it (#12)
