package net.nickknows.ideabrd.core

import java.io.File
import java.nio.file.Files
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * Reading an idea out of the repository it lives in.
 *
 * The board repo only points at these, so this is the difference between a
 * tile that says "this idea lives over there" and a tile that is the idea.
 */
class LinkedRepoStoreTest {

    private val root = Files.createTempDirectory("linked").toFile()
    private val store = LinkedRepoStore(root)

    @AfterTest
    fun cleanUp() {
        root.deleteRecursively()
    }

    @Test
    fun `a repo with no idea file has nothing to read`() {
        assertTrue(!store.exists())
        assertNull(store.read())
    }

    @Test
    fun `an idea round trips through the repo's own file`() {
        store.write(
            ParsedIdeaFile(
                title = "Linked idea",
                notes = "kept in its own repo",
                status = "active",
                progress = 40,
                todos = listOf(ParsedTodo("one", true), ParsedTodo("two", false, 12)),
            )
        )
        val read = store.read()!!
        assertEquals("Linked idea", read.title)
        assertEquals("kept in its own repo", read.notes)
        assertEquals("active", read.status)
        assertEquals(40, read.progress)
        assertEquals(listOf(null, 12), read.todos.map { it.issue })
    }

    @Test
    fun `the file it writes carries its own format rules`() {
        store.write(ParsedIdeaFile(title = "Fresh"))
        val text = File(root, IDEA_FILE).readText()
        assertTrue("<!--" in text && "## Todos" in text)
    }

    @Test
    fun `a linked repo's file never carries board keys`() {
        // rank and colour belong to whichever board shows the tile, and a
        // shared idea sits on several at different positions.
        store.write(
            ParsedIdeaFile(title = "Linked", rank = "a0m", color = "#6366f1", repo = "o/r")
        )
        val text = File(root, IDEA_FILE).readText()
        assertTrue("rank:" !in text)
        assertTrue("color:" !in text)
        assertTrue("repo:" !in text)
    }

    @Test
    fun `the tile image beside the file is found, in a stable order`() {
        assertNull(store.logo())
        File(root, "idea_logo.gif").writeText("g")
        File(root, "idea_logo.png").writeText("p")
        assertEquals("idea_logo.png", store.logo()?.name)
    }
}
