package net.nickknows.ideabrd.core

/**
 * Merge two versions of an IDEA.md by meaning rather than by line.
 *
 * A port of `backend/app/ideamerge.py`, and the piece the phone needs most: a
 * device that edits a board offline and syncs later is *guaranteed* to meet a
 * file that moved underneath it. Merging the text would not help — both sides
 * re-render the whole file, so a line diff sees a rewrite even when nothing
 * changed. What both sides share is the structure the parser knows about, so
 * that is what gets merged.
 *
 * Three-way where a base is available (the version we last had in common,
 * which for a git checkout is the merge base), two-way where it isn't. Two-way
 * keeps everything from both sides, because without a base an item missing from
 * one side is indistinguishable from an item the other side just added.
 *
 * Git wins ties, except where nothing has to lose: a status can only have one
 * value, so the repo's wins, but prose that both sides rewrote keeps both — the
 * duplication is visible and happens once, where a dropped paragraph is
 * invisible and permanent.
 */

private data class TodoKey(val kind: String, val value: String)

private fun keyOf(todo: ParsedTodo): TodoKey =
    if (todo.issue != null) TodoKey("issue", todo.issue.toString())
    else TodoKey("text", todo.text)

private fun <T> pick(base: T?, ours: T, theirs: T): T {
    if (ours == theirs) return ours
    if (base != null && ours == base) return theirs
    if (base != null && theirs == base) return ours
    return theirs
}

/**
 * Line-level three-way merge, anchored on lines both sides left alone.
 *
 * Notes are prose, and prose is the one part of the file where two people
 * editing different paragraphs is ordinary. A region both rewrote keeps both
 * versions, the repo's first.
 */
internal fun mergeLines(
    base: List<String>,
    ours: List<String>,
    theirs: List<String>,
): List<String> {
    if (base == ours) return theirs
    if (base == theirs) return ours

    val oursAt = matchMap(base, ours)
    val theirsAt = matchMap(base, theirs)
    val anchors = oursAt.keys.intersect(theirsAt.keys).sorted()

    val merged = mutableListOf<String>()
    var b = 0
    var o = 0
    var t = 0
    for (i in anchors + base.size) {
        val oi = oursAt[i] ?: ours.size
        val ti = theirsAt[i] ?: theirs.size
        val baseSeg = base.subList(b, i)
        val ourSeg = ours.subList(o, oi)
        val theirSeg = theirs.subList(t, ti)
        when {
            ourSeg == baseSeg -> merged += theirSeg
            theirSeg == baseSeg || ourSeg == theirSeg -> merged += ourSeg
            else -> {
                merged += theirSeg
                merged += ourSeg
            }
        }
        if (i < base.size) {
            merged += base[i]
            b = i + 1
            o = oi + 1
            t = ti + 1
        }
    }
    return merged
}

/**
 * Map each base line index to the matching index in [other].
 *
 * A longest-common-subsequence walk, which is what Python's difflib gives the
 * original. Only lines matched in *both* versions become anchors, so this being
 * a plain LCS rather than difflib's autojunk-aware variant changes which lines
 * anchor, never whether the result keeps everyone's edits.
 */
private fun matchMap(base: List<String>, other: List<String>): Map<Int, Int> {
    val n = base.size
    val m = other.size
    val table = Array(n + 1) { IntArray(m + 1) }
    for (i in n - 1 downTo 0) {
        for (j in m - 1 downTo 0) {
            table[i][j] =
                if (base[i] == other[j]) table[i + 1][j + 1] + 1
                else maxOf(table[i + 1][j], table[i][j + 1])
        }
    }
    val map = mutableMapOf<Int, Int>()
    var i = 0
    var j = 0
    while (i < n && j < m) {
        when {
            base[i] == other[j] -> {
                map[i] = j
                i += 1
                j += 1
            }
            table[i + 1][j] >= table[i][j + 1] -> i += 1
            else -> j += 1
        }
    }
    return map
}

private fun mergeNotes(base: String?, ours: String, theirs: String): String {
    if (base == null) return if (ours != theirs) theirs else ours
    return mergeLines(base.split("\n"), ours.split("\n"), theirs.split("\n"))
        .joinToString("\n")
        .trim()
}

/**
 * Merge two to-do lists, keeping each side's additions and deletions.
 *
 * Order follows the repo's list, since that is the one a person arranged by
 * hand; items only this side has are slotted in after whatever preceded them
 * here, so an item added at the top of the board does not come back at the
 * bottom of the file.
 */
private fun mergeTodos(
    base: List<ParsedTodo>?,
    ours: List<ParsedTodo>,
    theirs: List<ParsedTodo>,
): List<ParsedTodo> {
    val oursBy = ours.associateBy { keyOf(it) }
    val theirsBy = theirs.associateBy { keyOf(it) }
    val baseBy = base?.associateBy { keyOf(it) } ?: emptyMap()

    fun survives(key: TodoKey): Boolean {
        if (key in oursBy && key in theirsBy) return true
        // No base: an absence proves nothing, so keep it. With one, an item on
        // one side only is kept when it is an addition there and dropped when
        // it is a deletion on the other.
        return base == null || key !in baseBy
    }

    fun merged(key: TodoKey): ParsedTodo {
        val ourItem = oursBy[key]
        val theirItem = theirsBy[key]
        if (ourItem == null) return theirItem!!
        if (theirItem == null) return ourItem
        val baseItem = baseBy[key]
        return ParsedTodo(
            text = pick(baseItem?.text, ourItem.text, theirItem.text),
            done = pick(baseItem?.done, ourItem.done, theirItem.done),
            issue = ourItem.issue ?: theirItem.issue,
        )
    }

    val out = theirs.filter { survives(keyOf(it)) }.map { merged(keyOf(it)) }.toMutableList()
    val placed = theirs.map { keyOf(it) }.toMutableSet()
    var previous: TodoKey? = null
    for (item in ours) {
        val key = keyOf(item)
        if (key !in placed && survives(key)) {
            val at =
                if (previous == null) 0
                else out.indexOfFirst { keyOf(it) == previous }.let {
                    if (it < 0) out.size else it + 1
                }
            out.add(at, merged(key))
            placed += key
        }
        previous = key
    }
    return out
}

/** Merge two parsed idea files into one, field by field. */
fun mergeParsed(
    base: ParsedIdeaFile?,
    ours: ParsedIdeaFile,
    theirs: ParsedIdeaFile,
): ParsedIdeaFile =
    ParsedIdeaFile(
        title = pick(base?.title, ours.title, theirs.title),
        notes = mergeNotes(base?.notes, ours.notes, theirs.notes),
        status = pick(base?.status, ours.status, theirs.status),
        progress = pick(base?.progress, ours.progress, theirs.progress),
        color = pick(base?.color, ours.color, theirs.color),
        rank = pick(base?.rank, ours.rank, theirs.rank),
        repo = pick(base?.repo, ours.repo, theirs.repo),
        todos = mergeTodos(base?.todos, ours.todos, theirs.todos),
    )

/**
 * Merge two IDEA.md files, returning the rendered result and its parse.
 *
 * The parse comes back with it so the caller can write the merged state
 * wherever it keeps the board in the same breath as writing the file — a merge
 * that lands in the repo but not on the board is just a different way of losing
 * an edit.
 */
fun mergeIdeaFiles(
    base: String?,
    ours: String,
    theirs: String,
    guidance: Boolean = true,
): Pair<String, ParsedIdeaFile> {
    val parsed =
        mergeParsed(
            base?.let { parseIdeaFile(it) },
            parseIdeaFile(ours),
            parseIdeaFile(theirs),
        )
    // A file the parser found no title in still has to be rendered with one;
    // falling back through both sides keeps the merge from inventing a name.
    val title = parsed.title ?: ""
    val rendered =
        renderIdeaFile(
            title = title,
            notes = parsed.notes,
            status = parsed.status ?: "idea",
            progress = parsed.progress ?: 0,
            todos = parsed.todos,
            guidance = guidance,
            color = parsed.color,
            rank = parsed.rank,
            repo = parsed.repo,
        )
    return rendered to parsed.copy(title = title.ifEmpty { null })
}
