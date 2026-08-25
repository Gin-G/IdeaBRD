package net.nickknows.ideabrd.core

/**
 * GitHub issues, as a to-do list sees them.
 *
 * A to-do carrying a trailing `(#12)` is backed by that issue, and from then on
 * the issue owns its text and whether it is done — the checkbox in the file is
 * a cache of the issue's state, not the other way round. The server applies
 * that rule on every pull (`gitsync._pull_issues`); this is the same rule for
 * the phone, kept here in `:core` so it can be tested without a network.
 *
 * The extra context — labels, who it is assigned to, how much discussion it has
 * — is not in the file and never goes into it. It is carried alongside, for
 * display, and is only as fresh as the last refresh.
 */

/** One issue, in the shape a tile needs. */
data class IssueInfo(
    val number: Int,
    val title: String,
    val state: String,
    val htmlUrl: String,
    val labels: List<String> = emptyList(),
    val assignee: String? = null,
    val comments: Int = 0,
) {
    val closed: Boolean get() = state == "closed"
}

/**
 * Apply live issues to the to-dos that reference them. The issue wins.
 *
 * A reference to an issue we have no copy of is left exactly as the file has
 * it: not knowing an issue's state is a reason to say nothing about it, not a
 * reason to claim it is open.
 */
fun applyIssues(
    todos: List<ParsedTodo>,
    issues: Map<Int, IssueInfo>,
): List<ParsedTodo> =
    todos.map { todo ->
        val issue = todo.issue?.let { issues[it] } ?: return@map todo
        todo.copy(
            text = issue.title.ifEmpty { todo.text },
            done = issue.closed,
        )
    }

/**
 * Issue edits that should be pushed back, given what the list used to say.
 *
 * Ticking a box in the app closes the issue, and retitling an item renames it —
 * the same two-way binding the web app has. Only items whose *own* text or
 * state changed are returned, so a list rewritten for unrelated reasons doesn't
 * generate a pile of pointless PATCHes.
 */
fun issueEdits(
    before: List<ParsedTodo>,
    after: List<ParsedTodo>,
): List<ParsedTodo> {
    val previous = before.filter { it.issue != null }.associateBy { it.issue }
    return after.filter { todo ->
        val was = todo.issue?.let { previous[it] } ?: return@filter false
        was.done != todo.done || was.text != todo.text
    }
}


/**
 * Add a to-do for every issue the list doesn't already reference.
 *
 * The board could always push work into GitHub — promote a to-do and it becomes
 * an issue — but never pick up work that started there, so a repo with a
 * hundred issues arrived at an empty tile. Importing is that missing direction,
 * and it binds the same way round: an imported item is issue-backed, so the
 * issue keeps owning its title and its state.
 *
 * Issues already referenced are skipped, so importing twice is a no-op rather
 * than a pile of duplicates. Order is by issue number, which is the order they
 * were opened in.
 */
fun mergeImportedIssues(
    todos: List<ParsedTodo>,
    issues: Collection<IssueInfo>,
): List<ParsedTodo> {
    val known = todos.mapNotNull { it.issue }.toSet()
    val imported = issues
        .filter { it.number !in known }
        .sortedBy { it.number }
        .map { ParsedTodo(it.title, it.closed, it.number) }
    return todos + imported
}
