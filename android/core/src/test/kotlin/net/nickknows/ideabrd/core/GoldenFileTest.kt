package net.nickknows.ideabrd.core

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * The port, held against the original's output.
 *
 * Everything else in this suite checks that the Kotlin parser behaves sensibly.
 * This checks the thing that actually matters: that it writes the *same bytes*
 * the Python renderer writes. Two renderers that merely agree on meaning still
 * produce a diff on every idea the first time a board is edited on a phone, and
 * a merge conflict on the edit after that.
 *
 * The fixtures live in `fixtures/idea-files/` at the repo root and are
 * regenerated from Python (see `backend/tests/regenerate_golden.py`). If this
 * fails, one of the two implementations moved and the other has not.
 */
class GoldenFileTest {

    private val fixtures =
        File(System.getProperty("ideabrd.fixtures") ?: "../../fixtures", "idea-files")

    private fun golden(name: String): String = File(fixtures, name).readText()

    @Test
    fun `a full idea renders exactly as the server renders it`() {
        val rendered = renderIdeaFile(
            title = "My idea",
            notes = "Some notes.\n\nMore notes, with a [link](https://example.com).",
            status = "active",
            progress = 60,
            todos = listOf(
                ParsedTodo("set up repo", true),
                ParsedTodo("build MVP", false),
                ParsedTodo("ship it", false, 12),
            ),
        )
        assertEquals(golden("full.md"), rendered)
    }

    @Test
    fun `a bare idea renders exactly as the server renders it`() {
        assertEquals(
            golden("minimal.md"),
            renderIdeaFile("Fresh", "", "idea", 0, guidance = false),
        )
    }

    @Test
    fun `a board copy renders exactly as the server renders it`() {
        val rendered = renderIdeaFile(
            title = "On a board",
            notes = "Kept in someone's board repo.",
            status = "paused",
            progress = 25,
            todos = listOf(ParsedTodo("one", false)),
            color = "#6366f1",
            rank = "a0m",
        )
        assertEquals(golden("board.md"), rendered)
    }

    @Test
    fun `a reference renders exactly as the server renders it`() {
        assertEquals(
            golden("reference.md"),
            renderReferenceFile("octocat/hello", "a0m", "#ec4899"),
        )
    }

    @Test
    fun `a public board copy renders exactly as the server renders it`() {
        val rendered = renderIdeaFile(
            title = "Shown off",
            notes = "On the owner's public page.",
            status = "active",
            progress = 80,
            todos = listOf(ParsedTodo("one", true)),
            color = "#6366f1",
            rank = "a0m",
            public = true,
        )
        assertEquals(golden("public-board.md"), rendered)
    }

    @Test
    fun `a public reference renders exactly as the server renders it`() {
        assertEquals(
            golden("public-reference.md"),
            renderReferenceFile("octocat/hello", "a0m", "#ec4899", public = true),
        )
    }

    @Test
    fun `a site renders exactly as the server renders it`() {
        val rendered = renderIdeaFile(
            title = "Runs somewhere",
            notes = "Has a site it is happy to show.",
            status = "active",
            progress = 50,
            guidance = false,
            site = "https://runs.example.net",
            sitePublic = true,
        )
        assertEquals(golden("site.md"), rendered)
        val parsed = parseIdeaFile(golden("site.md"))
        assertEquals("https://runs.example.net", parsed.site)
        assertTrue(parsed.sitePublic)
    }

    @Test
    fun `sites are accepted and refused exactly as the server does`() {
        assertEquals("https://hydrow.example.net", normalizeSite("hydrow.example.net"))
        assertEquals("http://x.example/app", normalizeSite("http://x.example/app"))
        assertEquals(null, normalizeSite("  "))
        assertEquals(null, normalizeSite("not a site"))
        assertEquals(null, normalizeSite("javascript:alert(1)"))
        // site_public means nothing without a site.
        assertTrue(!parseIdeaFile("---\nsite_public: true\n---\n\n# A\n").sitePublic)
    }

    @Test
    fun `the public flag survives a board rewrite`() {
        // A reorder re-renders every moved tile from its parse; a flag the
        // parse dropped would silently unpublish the tile on the next drag.
        val parsed = parseIdeaFile(golden("public-reference.md"))
        assertTrue(parsed.public)
        assertEquals(
            golden("public-reference.md"),
            renderReferenceFile(parsed.repo!!, parsed.rank!!, parsed.color!!, parsed.public),
        )
        assertTrue(!parseIdeaFile(golden("reference.md")).public)
    }

    @Test
    fun `every fixture parses back to what it says`() {
        val full = parseIdeaFile(golden("full.md"))
        assertEquals("My idea", full.title)
        assertEquals("active", full.status)
        assertEquals(60, full.progress)
        assertEquals(listOf("set up repo", "build MVP", "ship it"), full.todos.map { it.text })
        assertEquals(12, full.todos.last().issue)
        assertTrue("<!--" !in full.notes)

        val board = parseIdeaFile(golden("board.md"))
        assertEquals("a0m", board.rank)
        assertEquals("#6366f1", board.color)

        assertEquals("octocat/hello", parseIdeaFile(golden("reference.md")).repo)
    }
}
