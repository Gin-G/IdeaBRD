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
