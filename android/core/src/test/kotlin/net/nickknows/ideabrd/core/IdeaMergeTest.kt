package net.nickknows.ideabrd.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * Merging, on the device that needs it most.
 *
 * A phone edits a board offline and syncs later, so meeting a file that moved
 * underneath it is the normal case rather than the unlucky one. Every test here
 * is a shape of "two people changed the file", and the property being defended
 * is that nobody's edit disappears.
 */
class IdeaMergeTest {

    private fun file(
        title: String = "Idea",
        notes: String = "",
        status: String = "active",
        progress: Int = 0,
        todos: List<ParsedTodo> = emptyList(),
        rank: String? = null,
        color: String? = null,
    ) = renderIdeaFile(title, notes, status, progress, todos, guidance = false, color = color, rank = rank)

    private fun merge(base: String?, ours: String, theirs: String): ParsedIdeaFile {
        val (text, parsed) = mergeIdeaFiles(base, ours, theirs, guidance = false)
        assertEquals(parsed.todos, parseIdeaFile(text).todos, "render and parse must agree")
        return parsed
    }

    @Test
    fun `each side keeps the field only it changed`() {
        val merged = merge(
            file(status = "idea", progress = 0),
            file(status = "active", progress = 0),
            file(status = "idea", progress = 60),
        )
        assertEquals("active", merged.status)
        assertEquals(60, merged.progress)
    }

    @Test
    fun `git wins when both changed the same field`() {
        val merged = merge(file(status = "idea"), file(status = "active"), file(status = "done"))
        assertEquals("done", merged.status)
    }

    @Test
    fun `notes edited in different places both survive`() {
        val merged = merge(
            file(notes = "one\ntwo\nthree"),
            file(notes = "one\ntwo\nthree\nfour"),
            file(notes = "zero\none\ntwo\nthree"),
        )
        assertEquals("zero\none\ntwo\nthree\nfour", merged.notes)
    }

    @Test
    fun `notes rewritten on both sides keep both`() {
        val merged = merge(file(notes = "original"), file(notes = "mine"), file(notes = "theirs"))
        assertEquals("theirs\nmine", merged.notes)
    }

    @Test
    fun `additions from both sides are kept`() {
        val merged = merge(
            file(todos = listOf(ParsedTodo("a", false))),
            file(todos = listOf(ParsedTodo("a", false), ParsedTodo("mine", false))),
            file(todos = listOf(ParsedTodo("a", false), ParsedTodo("theirs", false))),
        )
        assertEquals(listOf("a", "mine", "theirs"), merged.todos.map { it.text })
    }

    @Test
    fun `an item deleted on github does not come back`() {
        val both = listOf(ParsedTodo("a", false), ParsedTodo("b", false))
        val merged = merge(
            file(todos = both),
            file(todos = both),
            file(todos = listOf(ParsedTodo("a", false))),
        )
        assertEquals(listOf("a"), merged.todos.map { it.text })
    }

    @Test
    fun `an item deleted here stays deleted`() {
        val both = listOf(ParsedTodo("a", false), ParsedTodo("b", false))
        val merged = merge(
            file(todos = both),
            file(todos = listOf(ParsedTodo("a", false))),
            file(todos = both),
        )
        assertEquals(listOf("a"), merged.todos.map { it.text })
    }

    @Test
    fun `a box ticked on each side of the list keeps both ticks`() {
        val merged = merge(
            file(todos = listOf(ParsedTodo("a", false), ParsedTodo("b", false))),
            file(todos = listOf(ParsedTodo("a", true), ParsedTodo("b", false))),
            file(todos = listOf(ParsedTodo("a", false), ParsedTodo("b", true))),
        )
        assertEquals(listOf(true, true), merged.todos.map { it.done })
    }

    @Test
    fun `an issue backed item is matched by number not text`() {
        val merged = merge(
            file(todos = listOf(ParsedTodo("old wording", false, 12))),
            file(todos = listOf(ParsedTodo("old wording", true, 12))),
            file(todos = listOf(ParsedTodo("new wording", false, 12))),
        )
        assertEquals(1, merged.todos.size)
        assertEquals("new wording", merged.todos[0].text)
        assertEquals(12, merged.todos[0].issue)
    }

    @Test
    fun `without a base nothing is dropped`() {
        val merged = merge(
            null,
            file(todos = listOf(ParsedTodo("a", false), ParsedTodo("mine", false))),
            file(todos = listOf(ParsedTodo("a", false), ParsedTodo("theirs", false))),
        )
        assertEquals(setOf("a", "mine", "theirs"), merged.todos.map { it.text }.toSet())
    }

    @Test
    fun `a linked repo's file never sprouts board keys`() {
        val (text, _) = mergeIdeaFiles(file(), file(status = "done"), file(), guidance = false)
        assertTrue("rank:" !in text && "color:" !in text)
    }

    @Test
    fun `board keys survive a merge of board files`() {
        val merged = merge(
            file(rank = "a0", color = "#111111"),
            file(rank = "a0", color = "#222222"),
            file(rank = "b0", color = "#111111"),
        )
        assertEquals("b0", merged.rank)
        assertEquals("#222222", merged.color)
    }
}
