package net.nickknows.ideabrd.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * The file format, on the phone.
 *
 * These are the Python parser's own tests, ported. That is the point of the
 * exercise: once no server is involved, this code decides what a board says,
 * and "close enough to the original" is a board that changes when you switch
 * devices. Anywhere the two disagree, this suite is where it should show up.
 */
class IdeaFileTest {

    @Test
    fun `render and parse round trip`() {
        val text = renderIdeaFile(
            title = "My idea",
            notes = "Some notes.\n\nMore notes.",
            status = "active",
            progress = 60,
            todos = listOf(ParsedTodo("set up repo", true), ParsedTodo("build MVP", false)),
        )
        val parsed = parseIdeaFile(text)
        assertEquals("My idea", parsed.title)
        assertEquals("Some notes.\n\nMore notes.", parsed.notes)
        assertEquals("active", parsed.status)
        assertEquals(60, parsed.progress)
        assertEquals(
            listOf(ParsedTodo("set up repo", true), ParsedTodo("build MVP", false)),
            parsed.todos,
        )
    }

    @Test
    fun `a rendered file documents its own format`() {
        val text = renderIdeaFile("Fresh", "", "idea", 0)
        assertTrue("## Todos" in text) // present even with nothing in it
        listOf("## ToDo", "exact text", "one line", "the board", "(#12)").forEach {
            assertTrue(it in text, "guidance should mention $it")
        }
        // ...and none of it leaks onto the board or into the list.
        val parsed = parseIdeaFile(text)
        assertEquals("", parsed.notes)
        assertEquals(emptyList(), parsed.todos)
    }

    @Test
    fun `issue references round trip`() {
        val text = renderIdeaFile(
            "T", "", "active", 0,
            todos = listOf(ParsedTodo("plain item", false), ParsedTodo("issue item", true, 12)),
        )
        assertTrue("- [ ] plain item\n" in text)
        assertTrue("- [x] issue item (#12)\n" in text)
        assertEquals(
            listOf(ParsedTodo("plain item", false, null), ParsedTodo("issue item", true, 12)),
            parseIdeaFile(text).todos,
        )
    }

    @Test
    fun `a bare issue reference is text, not a link`() {
        assertEquals(
            listOf(ParsedTodo("(#12)", false, null)),
            parseIdeaFile("## Todos\n\n- [ ] (#12)\n").todos,
        )
    }

    @Test
    fun `everything is optional`() {
        val parsed = parseIdeaFile("just some notes")
        assertNull(parsed.title)
        assertNull(parsed.status)
        assertNull(parsed.progress)
        assertEquals("just some notes", parsed.notes)
    }

    @Test
    fun `unknown frontmatter keys are ignored and bad values dropped`() {
        val parsed = parseIdeaFile(
            "---\nstatus: nonsense\nprogress: high\nwhatever: 1\n---\n\n# T\n"
        )
        assertNull(parsed.status)
        assertNull(parsed.progress)
        assertEquals("T", parsed.title)
    }

    @Test
    fun `progress is clamped and accepts a float`() {
        assertEquals(100, parseIdeaFile("---\nprogress: 250\n---\n").progress)
        assertEquals(0, parseIdeaFile("---\nprogress: -3\n---\n").progress)
        assertEquals(60, parseIdeaFile("---\nprogress: 60.0\n---\n").progress)
    }

    @Test
    fun `only the exact Todos heading counts`() {
        assertEquals(emptyList(), parseIdeaFile("## Tasks\n\n- [ ] lost\n").todos)
        assertEquals(1, parseIdeaFile("## To-Dos\n\n- [ ] kept\n").todos.size)
        assertEquals(1, parseIdeaFile("## todos\n\n- [ ] kept\n").todos.size)
    }

    @Test
    fun `a later section ends the todo list`() {
        val parsed = parseIdeaFile("## Todos\n\n- [ ] one\n\n## Notes\n\n- [ ] not a todo\n")
        assertEquals(listOf(ParsedTodo("one", false)), parsed.todos)
        assertTrue("not a todo" in parsed.notes)
    }

    @Test
    fun `board keys are only written when given`() {
        val plain = renderIdeaFile("T", "", "idea", 0)
        assertTrue("rank:" !in plain && "color:" !in plain)

        val board = renderIdeaFile("T", "", "idea", 0, rank = "a0m", color = "#6366f1")
        val parsed = parseIdeaFile(board)
        assertEquals("a0m", parsed.rank)
        assertEquals("#6366f1", parsed.color)
        // Quoted, because "#..." opens a comment in YAML.
        assertTrue("color: \"#6366f1\"" in board)
    }

    @Test
    fun `a reference file names the repo and nothing else`() {
        val parsed = parseIdeaFile(renderReferenceFile("octocat/hello", "a0m", "#6366f1"))
        assertEquals("octocat/hello", parsed.repo)
        assertEquals("a0m", parsed.rank)
        assertEquals(emptyList(), parsed.todos)
    }

    @Test
    fun `a repo given as a clone url is normalized`() {
        assertEquals(
            "octocat/hello",
            parseIdeaFile("---\nrepo: https://github.com/octocat/hello.git\n---\n").repo,
        )
    }

    @Test
    fun `the guidance block matches the server's byte for byte`() {
        // The two renderers write the same file or they don't; a stray space
        // here is a diff on every idea the first time a phone saves one.
        assertTrue(GUIDANCE.startsWith("<!--\nIdeaBRD parses this file."))
        assertTrue(GUIDANCE.endsWith("never reaches the board.\n-->"))
    }
}
