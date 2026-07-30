"""Shared rules for tile logo images, used by the upload API and by git sync.

The repo-side name is `idea_logo.<ext>` at the repo root, next to IDEA.md, so a
repo carries its own tile artwork the same way it carries its own idea file.
"""

from __future__ import annotations

# Raster formats only: an SVG is a script-execution vector when served back.
ALLOWED_LOGO_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
}
MAX_LOGO_BYTES = 1024 * 1024

LOGO_STEM = "idea_logo"

# Extension -> content type. "jpeg" is accepted on the way in even though
# uploads are written as "jpg", since a repo may already spell it either way.
EXT_TO_CONTENT_TYPE = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}

# Preference order when a repo somehow holds more than one idea_logo.*, so the
# adopted image is stable rather than dependent on GitHub's listing order.
LOGO_NAMES = tuple(f"{LOGO_STEM}.{ext}" for ext in ("png", "webp", "jpg", "jpeg", "gif"))


def logo_path_for(content_type: str) -> str:
    """Repo path an uploaded image of this content type is committed to."""
    return f"{LOGO_STEM}.{ALLOWED_LOGO_TYPES[content_type]}"


def content_type_for_path(path: str) -> str | None:
    """Content type implied by a repo logo path, or None if it isn't an image."""
    _, _, ext = path.rpartition(".")
    return EXT_TO_CONTENT_TYPE.get(ext.lower())
