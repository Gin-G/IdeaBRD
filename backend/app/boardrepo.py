"""Layout of the central board repo — one directory per idea, no manifest.

A board is a git repo whose shape is the whole schema::

    .ideabrd                        format version marker
    ideas/<slug>/IDEA.md            the idea, in the format the app already writes
    ideas/<slug>/idea_logo.<ext>    the tile image, when there is one

There is deliberately no board.yaml. A manifest holding order and colour is a
file every reorder rewrites, which makes it the one thing two devices are
guaranteed to conflict on — so order and colour live in each idea's own
frontmatter instead (``rank`` and ``color``), and the board is built by listing
``ideas/``. Moving a tile touches one file.

A directory here is not the same thing as a *linked* repo. An idea that links
its own repo keeps its content there, and its directory on the board holds a
stub carrying only what the board owns: rank, colour, and the ``repo`` pointer.
That split is why ``render_idea_file`` writes the board-level keys only when it
is given them — a linked repo's own IDEA.md must not sprout someone else's
board position.

Slugs name directories, so they are chosen to survive being checked out
anywhere: lowercase ASCII, no dots, nothing Windows reserves, and unique
without relying on case. A slug is assigned once and then left alone —
retitling an idea moves nothing, because a rename in git is a delete plus an
add, and every clone would have to resolve it.
"""

from __future__ import annotations

import re
import unicodedata

FORMAT_VERSION = 1
MARKER_FILE = ".ideabrd"
IDEAS_DIR = "ideas"
IDEA_FILE = "IDEA.md"

MAX_SLUG_LENGTH = 60
FALLBACK_SLUG = "idea"

# Windows refuses these as filenames whatever the extension, and a board that
# can't be cloned on one desktop is a board with a missing tile.
_RESERVED_NAMES = frozenset(
    ["con", "prn", "aux", "nul"]
    + [f"com{i}" for i in range(1, 10)]
    + [f"lpt{i}" for i in range(1, 10)]
)

_UNSAFE_RE = re.compile(r"[^a-z0-9]+")


def slugify(title: str) -> str:
    """Turn an idea title into a directory name.

    Accents are folded rather than dropped, so "Idée" becomes "idee" instead of
    "ide". Titles with nothing ASCII left in them (a CJK title, an emoji) fall
    back to a generic name and lean on ``unique_slug`` to tell them apart.
    """
    folded = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = _UNSAFE_RE.sub("-", folded.lower()).strip("-")[:MAX_SLUG_LENGTH].strip("-")
    if not slug or slug in _RESERVED_NAMES:
        # A reserved name is suffixed rather than replaced, so "con" stays
        # recognisable as the idea the user named.
        slug = f"{slug}-{FALLBACK_SLUG}" if slug else FALLBACK_SLUG
    return slug


def unique_slug(title: str, taken: set[str] | frozenset[str]) -> str:
    """A slug for ``title`` that no idea on this board is using yet.

    ``taken`` is compared case-insensitively: slugs are already lowercase, but
    macOS and Windows checkouts fold case, so two directories differing only in
    case would collide on the very machines this is meant to run on.
    """
    lowered = {t.lower() for t in taken}
    base = slugify(title)
    if base not in lowered:
        return base
    # Leave room for the suffix rather than letting the name exceed the cap.
    for n in range(2, 10_000):
        suffix = f"-{n}"
        candidate = f"{base[: MAX_SLUG_LENGTH - len(suffix)].strip('-')}{suffix}"
        if candidate not in lowered:
            return candidate
    raise ValueError(f"No free slug for {title!r}")


def is_slug(value: str) -> bool:
    """Whether a directory name is one this layout would have written."""
    return (
        bool(value)
        and len(value) <= MAX_SLUG_LENGTH
        and value not in _RESERVED_NAMES
        and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value) is not None
    )


def idea_dir(slug: str) -> str:
    return f"{IDEAS_DIR}/{slug}"


def idea_file_path(slug: str) -> str:
    return f"{IDEAS_DIR}/{slug}/{IDEA_FILE}"


def logo_path(slug: str, filename: str) -> str:
    """Path for a tile logo already named by ``app.logos.logo_path_for``."""
    return f"{IDEAS_DIR}/{slug}/{filename}"


README_FILE = "README.md"
REPO_DESCRIPTION = "IdeaBRD board"
# Marks the README as one this app wrote, so a later publish knows it may
# rewrite it. Without it, a README somebody wrote themselves would be
# indistinguishable from ours and would eventually be overwritten.
README_SENTINEL = "<!-- Managed by IdeaBRD. Edit the ideas, not this file. -->"


def github_stub_readmes(repo: str) -> set[bytes]:
    """The README GitHub writes when it initialises a repo, in both its forms.

    A repo the app just created carries one of these, and replacing it with
    something useful is the point. Matching it exactly rather than guessing at
    "looks like a stub" keeps a README anyone wrote themselves out of reach.
    """
    name = repo.split("/")[-1]
    return {
        f"# {name}\n".encode(),
        # What GitHub actually writes when the repo has a description: the
        # heading and the description on consecutive lines, no blank between.
        f"# {name}\n{REPO_DESCRIPTION}\n".encode(),
        f"# {name}\n\n{REPO_DESCRIPTION}\n".encode(),
    }


def render_readme(login: str | None, repo: str) -> bytes:
    """The board's own README: what this repo is, and how to read it.

    Whoever opens this repo — a person, or an agent handed the URL — sees only
    the files, so the layout has to explain itself here the same way each
    IDEA.md carries its own format rules.
    """
    owner = f"{login}'s" if login else "An"
    return f"""# {owner} idea board

{README_SENTINEL}

This repository *is* the board. Every idea is a directory, so the whole thing
can be cloned, read and edited without the app running.

## Layout

```
{MARKER_FILE}                     format version
{IDEAS_DIR}/<slug>/{IDEA_FILE}         one idea
{IDEAS_DIR}/<slug>/idea_logo.png   its tile image, when it has one
```

A slug is assigned once and never follows the title around: renaming a
directory in git is a delete plus an add, and every clone would have to
reconcile it.

## An idea

```markdown
---
status: active
progress: 60
color: "#6366f1"
rank: "a0m"
---

# Title

Notes, shown on the tile.

## Todos

- [x] done item
- [ ] open item
```

`status`, `progress`, the title, the notes and the to-dos are the idea itself.

`color` and `rank` belong to *this* board rather than to the idea. `rank` is a
fractional key compared as plain text, never as a number — it is what lets a
tile move without renumbering every file below it, so reordering the board
rewrites one file.

## Ideas that live elsewhere

An idea with a repository of its own is recorded here as a reference — its
frontmatter and a link, nothing more:

```markdown
---
color: "#6366f1"
rank: "a0m"
repo: owner/name
---

# owner/name

This idea lives in [owner/name](https://github.com/owner/name).
```

Its notes, progress, to-dos and tile image are in that repository, tracked by
its own history, and that is the copy that counts. Nothing is duplicated here,
so there is nothing here that can fall out of date with it — and it is where
anyone collaborating on that idea should be working.

Ideas without a repository of their own are held in this one in full, because
this is the only place they exist.

## Editing

Edits made here are **overwritten on the next publish**. The app still keeps the
board in its database and treats that as the source of truth, publishing this
repo from it — so this copy is for reading, cloning and reviewing, not yet for
writing back. That changes when the app reads this repo as authoritative.
""".encode()
