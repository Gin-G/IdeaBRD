package net.nickknows.ideabrd.core

/**
 * Render and parse IDEA.md — the git-side representation of an idea.
 *
 * This is a port of `backend/app/ideafile.py`, and it is deliberately a *port*
 * rather than a reimplementation: the same leniency, the same field names, the
 * same guidance block, the same rules about what survives a round trip. The two
 * have to agree exactly, because the whole point of moving the board into git is
 * that the phone and the server are reading the same files. A parser that is
 * merely similar would show a different board depending on which one read it.
 *
 * The format:
 *
 *     ---
 *     status: active
 *     progress: 60
 *     ---
 *
 *     # Title
 *
 *     Free-form markdown notes.
 *
 *     ## Todos
 *
 *     - [x] done item
 *     - [ ] open item
 *
 * Parsing is lenient so hand-edits on GitHub don't break sync: frontmatter, the
 * H1 and the Todos section are all optional, and unknown keys are ignored.
 */

val VALID_STATUSES = listOf("idea", "active", "paused", "done")

private val COLOR_RE = Regex("^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
private val TODO_RE = Regex("""^\s*[-*]\s*\[( |x|X)]\s*(.*\S)\s*$""")
private val TODOS_HEADING_RE = Regex("^##\\s+to-?dos\\s*$", RegexOption.IGNORE_CASE)

/**
 * A trailing "(#12)" binds the item to a GitHub issue. The non-empty remainder
 * keeps a bare "- [ ] (#12)" as literal text rather than a link to an issue
 * with no to-do attached.
 */
private val ISSUE_SUFFIX_RE = Regex("""^(.+?)\s*\(#(\d+)\)$""")

/**
 * Whole-line comments take their newline with them, so removing the guidance
 * block doesn't leave a blank gap behind in the notes.
 */
private val COMMENT_BLOCK_RE = Regex("""(?m)^[ \t]*<!--[\s\S]*?-->[ \t]*\r?\n?""")
private val COMMENT_RE = Regex("""<!--[\s\S]*?-->""")

/** One item on the list. [issue] is the GitHub issue backing it, if any. */
data class ParsedTodo(val text: String, val done: Boolean, val issue: Int? = null)

/**
 * An idea as a file holds it. [color], [rank] and [repo] are board-level keys,
 * written only into a board repo's copy — null for a linked repo's own IDEA.md,
 * which carries the idea but nobody's board position for it.
 */
data class ParsedIdeaFile(
    val title: String? = null,
    val notes: String = "",
    val status: String? = null,
    val progress: Int? = null,
    val color: String? = null,
    val rank: String? = null,
    val repo: String? = null,
    val todos: List<ParsedTodo> = emptyList(),
)

/**
 * The rules, written into every file we render.
 *
 * Whoever edits the file next — a person on GitHub, or an agent handed the repo
 * — sees only the file, not this code. Comments are stripped on the way back in,
 * so the block round-trips without ever reaching the board.
 *
 * Kept byte-identical to the Python GUIDANCE: a file rewritten on the phone must
 * not produce a diff against the same file rewritten by the server.
 */
val GUIDANCE: String = """
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
""".trim()

private fun stripComments(body: String): String =
    COMMENT_RE.replace(COMMENT_BLOCK_RE.replace(body, ""), "")

/** Split "Build MVP (#12)" into ("Build MVP", 12); no suffix means no issue. */
private fun splitIssueRef(text: String): Pair<String, Int?> {
    val m = ISSUE_SUFFIX_RE.matchEntire(text) ?: return text to null
    return m.groupValues[1] to m.groupValues[2].toIntOrNull()
}

/**
 * Render an idea as IDEA.md.
 *
 * The `## Todos` heading is always written, empty list or not: a heading that is
 * already there gets filled in, where a missing one gets invented under whatever
 * name the editor guesses (and then parsed as notes).
 *
 * [color], [rank] and [repo] are omitted unless given, so a board repo's copy
 * can carry a tile's position while the same renderer keeps writing linked repos
 * exactly as it did before.
 */
fun renderIdeaFile(
    title: String,
    notes: String,
    status: String,
    progress: Int,
    todos: List<ParsedTodo> = emptyList(),
    guidance: Boolean = true,
    color: String? = null,
    rank: String? = null,
    repo: String? = null,
): String {
    val lines = mutableListOf("---", "status: $status", "progress: $progress")
    // Quoted because "#..." opens a comment in YAML, and a board file that only
    // our own lenient parser can read is a trap for anything else.
    if (color != null) lines += "color: \"$color\""
    if (rank != null) lines += "rank: \"$rank\""
    if (repo != null) lines += "repo: $repo"
    lines += listOf("---", "", "# $title", "")
    if (guidance) lines += listOf(GUIDANCE, "")
    if (notes.isNotBlank()) lines += listOf(notes.trim(), "")
    lines += listOf("## Todos", "")
    todos.forEach { item ->
        val box = if (item.done) "x" else " "
        val ref = item.issue?.let { " (#$it)" } ?: ""
        lines += "- [$box] ${item.text}$ref"
    }
    if (todos.isNotEmpty()) lines += ""
    return lines.joinToString("\n")
}

/**
 * A board entry for an idea whose content lives in its own repository.
 *
 * The board records that the idea is on it and where it sits; the repo named
 * here holds the idea. The body is derived entirely from [repo], so there is
 * nothing here that can fall out of date with it.
 */
fun renderReferenceFile(repo: String, rank: String, color: String): String =
    listOf(
        "---",
        "color: \"$color\"",
        "rank: \"$rank\"",
        "repo: $repo",
        "---",
        "",
        "# $repo",
        "",
        "This idea lives in [$repo](https://github.com/$repo).",
        "",
        "This board records which ideas are on it and where each one lives.",
        "The idea itself — its notes, progress and to-dos — is in that",
        "repository's own IDEA.md, which is the copy that counts.",
        "",
    ).joinToString("\n")

/** Frontmatter as a map, plus the index of the first body line. */
private fun parseFrontmatter(lines: List<String>): Pair<Map<String, String>, Int> {
    if (lines.isEmpty() || lines[0].trim() != "---") return emptyMap<String, String>() to 0
    val fm = mutableMapOf<String, String>()
    for (i in 1 until lines.size) {
        val line = lines[i]
        if (line.trim() == "---") return fm to i + 1
        val colon = line.indexOf(':')
        if (colon > 0) {
            val key = line.substring(0, colon).trim().lowercase()
            fm[key] = line.substring(colon + 1).trim().trim('\'', '"')
        }
    }
    // No closing fence — treat the whole thing as body.
    return emptyMap<String, String>() to 0
}

fun parseIdeaFile(text: String): ParsedIdeaFile {
    val lines = text.split("\n").map { it.trimEnd('\r') }
    val (fm, bodyStart) = parseFrontmatter(lines)
    // Comments are stripped before anything reads the body: the guidance block
    // spans lines and quotes "- [ ]" examples, which would otherwise land in
    // notes or be picked up as to-dos. Frontmatter is parsed first so a "---"
    // inside a comment can't move the fence.
    val body = stripComments(lines.drop(bodyStart).joinToString("\n")).split("\n")

    val status = fm["status"]?.takeIf { it in VALID_STATUSES }
    val progress = fm["progress"]?.let { raw ->
        raw.toDoubleOrNull()?.toInt()?.coerceIn(0, 100)
    }
    // Board-level keys are validated and otherwise dropped, in keeping with the
    // rest of the parser: a hand-edited colour or rank that can't be used should
    // cost that one field, not the file.
    val color = fm["color"]?.takeIf { COLOR_RE.matches(it) }?.lowercase()
    val rank = fm["rank"]?.takeIf { isRank(it) }
    val repo = fm["repo"]?.let { normalizeRepoOrNull(it) }

    var title: String? = null
    val noteLines = mutableListOf<String>()
    val todos = mutableListOf<ParsedTodo>()
    var inTodos = false

    for (line in body) {
        if (title == null && line.startsWith("# ") && noteLines.none { it.isNotBlank() }) {
            title = line.substring(2).trim().ifEmpty { null }
            noteLines.clear() // drop blank lines that preceded the title
            continue
        }
        if (TODOS_HEADING_RE.matches(line.trim())) {
            inTodos = true
            continue
        }
        if (inTodos) {
            if (line.startsWith("## ")) { // a later section ends the todo list
                inTodos = false
                noteLines += line
                continue
            }
            val m = TODO_RE.matchEntire(line)
            if (m != null) {
                val (itemText, issue) = splitIssueRef(m.groupValues[2])
                todos += ParsedTodo(itemText, m.groupValues[1].lowercase() == "x", issue)
            }
            // non-item lines inside the Todos section are ignored
            continue
        }
        noteLines += line
    }

    return ParsedIdeaFile(
        title = title,
        notes = noteLines.joinToString("\n").trim(),
        status = status,
        progress = progress,
        color = color,
        rank = rank,
        repo = repo,
        todos = todos,
    )
}
