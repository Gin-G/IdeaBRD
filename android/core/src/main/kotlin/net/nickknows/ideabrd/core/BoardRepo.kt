package net.nickknows.ideabrd.core

import java.text.Normalizer

/**
 * Layout of the central board repo — one directory per idea, no manifest.
 *
 * A port of `backend/app/boardrepo.py`. The shape of the repo is the whole
 * schema:
 *
 *     .ideabrd                        format version marker
 *     ideas/<slug>/IDEA.md            the idea
 *     ideas/<slug>/idea_logo.<ext>    the tile image, when there is one
 *
 * Order and colour live in each idea's own frontmatter rather than in a
 * board.yaml, so moving a tile touches one file instead of the one file every
 * device shares.
 *
 * Slugs name directories, so they are chosen to survive being checked out
 * anywhere: lowercase ASCII, no dots, nothing Windows reserves, unique without
 * relying on case. A slug is assigned once and then left alone — retitling an
 * idea moves nothing, because a rename in git is a delete plus an add.
 */

const val FORMAT_VERSION = 1
const val MARKER_FILE = ".ideabrd"
const val IDEAS_DIR = "ideas"
const val IDEA_FILE = "IDEA.md"
const val MAX_SLUG_LENGTH = 60
private const val FALLBACK_SLUG = "idea"

/** Windows refuses these as filenames whatever the extension. */
private val RESERVED_NAMES: Set<String> =
    (listOf("con", "prn", "aux", "nul") +
        (1..9).map { "com$it" } +
        (1..9).map { "lpt$it" }).toSet()

private val UNSAFE_RE = Regex("[^a-z0-9]+")
private val SLUG_RE = Regex("[a-z0-9]+(-[a-z0-9]+)*")

/**
 * Turn an idea title into a directory name.
 *
 * Accents are folded rather than dropped, so "Idée" becomes "idee" instead of
 * "ide". Titles with nothing ASCII left in them fall back to a generic name and
 * lean on [uniqueSlug] to tell them apart.
 */
fun slugify(title: String): String {
    val folded = Normalizer.normalize(title, Normalizer.Form.NFKD)
        .filter { it.code < 128 }
    var slug = UNSAFE_RE.replace(folded.lowercase(), "-").trim('-')
    if (slug.length > MAX_SLUG_LENGTH) slug = slug.substring(0, MAX_SLUG_LENGTH).trim('-')
    if (slug.isEmpty() || slug in RESERVED_NAMES) {
        // A reserved name is suffixed rather than replaced, so "con" stays
        // recognisable as the idea the user named.
        slug = if (slug.isEmpty()) FALLBACK_SLUG else "$slug-$FALLBACK_SLUG"
    }
    return slug
}

/**
 * A slug for [title] that no idea on this board is using yet.
 *
 * [taken] is compared case-insensitively: slugs are already lowercase, but
 * macOS and Windows checkouts fold case, so two directories differing only in
 * case would collide on the very machines this is meant to run on.
 */
fun uniqueSlug(title: String, taken: Set<String>): String {
    val lowered = taken.map { it.lowercase() }.toSet()
    val base = slugify(title)
    if (base !in lowered) return base
    for (n in 2..9999) {
        val suffix = "-$n"
        val head = base.take(MAX_SLUG_LENGTH - suffix.length).trim('-')
        val candidate = "$head$suffix"
        if (candidate !in lowered) return candidate
    }
    throw IllegalStateException("No free slug for $title")
}

/** Whether a directory name is one this layout would have written. */
fun isSlug(value: String): Boolean =
    value.isNotEmpty() &&
        value.length <= MAX_SLUG_LENGTH &&
        value !in RESERVED_NAMES &&
        SLUG_RE.matches(value)

fun ideaDir(slug: String): String = "$IDEAS_DIR/$slug"

fun ideaFilePath(slug: String): String = "$IDEAS_DIR/$slug/$IDEA_FILE"

fun logoPath(slug: String, filename: String): String = "$IDEAS_DIR/$slug/$filename"

/** The `.ideabrd` file, which is both a version and a claim on the layout. */
fun markerContent(): String =
    """
    {
      "version": $FORMAT_VERSION,
      "layout": "$IDEAS_DIR/<slug>/$IDEA_FILE",
      "generator": "IdeaBRD"
    }
    """.trimIndent() + "\n"
