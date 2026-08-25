package net.nickknows.ideabrd.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** The issue owns its item — the same rule the server applies on every pull. */
class IssuesTest {

    private fun issue(number: Int, title: String, state: String = "open") =
        IssueInfo(number, title, state, "https://github.com/o/r/issues/$number")

    @Test
    fun `a closed issue ticks its to-do`() {
        val todos = listOf(ParsedTodo("Build MVP", false, 12))
        val applied = applyIssues(todos, mapOf(12 to issue(12, "Build MVP", "closed")))
        assertTrue(applied.single().done)
    }

    @Test
    fun `a renamed issue renames its to-do`() {
        val applied = applyIssues(
            listOf(ParsedTodo("old wording", false, 12)),
            mapOf(12 to issue(12, "new wording")),
        )
        assertEquals("new wording", applied.single().text)
        assertEquals(12, applied.single().issue)
    }

    @Test
    fun `an issue we have no copy of leaves the item alone`() {
        val todos = listOf(ParsedTodo("Build MVP", true, 12))
        assertEquals(todos, applyIssues(todos, emptyMap()))
    }

    @Test
    fun `a plain to-do is never touched`() {
        val todos = listOf(ParsedTodo("just a note", false))
        assertEquals(todos, applyIssues(todos, mapOf(12 to issue(12, "something else"))))
    }

    @Test
    fun `an issue with no title keeps whatever the file said`() {
        val applied = applyIssues(
            listOf(ParsedTodo("from the file", false, 12)),
            mapOf(12 to issue(12, "")),
        )
        assertEquals("from the file", applied.single().text)
    }

    @Test
    fun `ticking an issue-backed box is an edit to push back`() {
        val before = listOf(ParsedTodo("Build MVP", false, 12), ParsedTodo("plain", false))
        val after = listOf(ParsedTodo("Build MVP", true, 12), ParsedTodo("plain", true))
        val edits = issueEdits(before, after)
        assertEquals(listOf(12), edits.map { it.issue })
        assertTrue(edits.single().done)
    }

    @Test
    fun `an unchanged list generates no edits`() {
        val todos = listOf(ParsedTodo("Build MVP", false, 12))
        assertEquals(emptyList(), issueEdits(todos, todos))
    }

    @Test
    fun `importing adds an item per issue, oldest first`() {
        val merged = mergeImportedIssues(
            listOf(ParsedTodo("already here", false)),
            listOf(issue(9, "Newer"), issue(7, "Older", "closed")),
        )
        assertEquals(listOf("already here", "Older", "Newer"), merged.map { it.text })
        assertEquals(listOf(null, 7, 9), merged.map { it.issue })
        assertTrue(merged[1].done)
    }

    @Test
    fun `importing twice adds nothing`() {
        val once = mergeImportedIssues(emptyList(), listOf(issue(3, "One")))
        assertEquals(once, mergeImportedIssues(once, listOf(issue(3, "One"))))
    }

    @Test
    fun `reordering alone is not an issue edit`() {
        val a = ParsedTodo("one", false, 1)
        val b = ParsedTodo("two", false, 2)
        assertEquals(emptyList(), issueEdits(listOf(a, b), listOf(b, a)))
    }
}
