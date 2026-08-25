package net.nickknows.ideabrd.core

import java.nio.file.Files
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * A checkout of the board repo, used as the database.
 *
 * The tests that matter here are the ones about *writing*: the phone has to
 * produce the same tree the server's publisher produces, or the first sync
 * after installing the app is a diff on every file.
 */
class BoardStoreTest {

    private val root = Files.createTempDirectory("board").toFile()
    private val store = BoardStore(root)

    @AfterTest
    fun cleanUp() {
        root.deleteRecursively()
    }

    @Test
    fun `an empty directory is not a board until it is marked`() {
        assertTrue(!store.isBoard())
        store.ensureMarker()
        assertTrue(store.isBoard())
        assertEquals(
            """
            {
              "version": 1,
              "layout": "ideas/<slug>/IDEA.md",
              "generator": "IdeaBRD"
            }
            """.trimIndent() + "\n",
            java.io.File(root, MARKER_FILE).readText(),
        )
    }

    @Test
    fun `ideas are read in rank order`() {
        store.create("First")
        store.create("Second")
        store.create("Third")
        assertEquals(listOf("first", "second", "third"), store.read().map { it.slug })
    }

    @Test
    fun `a new idea lands at the end and gets its own directory`() {
        store.create("My great idea")
        val tile = store.read().single()
        assertEquals("my-great-idea", tile.slug)
        assertTrue(java.io.File(root, ideaFilePath("my-great-idea")).isFile)
        assertEquals("idea", tile.file.status)
        assertTrue(isRank(tile.file.rank!!))
    }

    @Test
    fun `two ideas with the same title get different directories`() {
        store.create("Same")
        store.create("Same")
        assertEquals(listOf("same", "same-2"), store.read().map { it.slug }.sorted())
    }

    @Test
    fun `editing an idea rewrites only its own file`() {
        store.create("One")
        store.create("Two")
        val before = java.io.File(root, ideaFilePath("two")).readText()
        val one = store.readIdea("one")!!
        store.writeIdea("one", one.file.copy(status = "done", progress = 100))

        assertEquals("done", store.readIdea("one")!!.file.status)
        assertEquals(before, java.io.File(root, ideaFilePath("two")).readText())
    }

    @Test
    fun `reordering rewrites one file, not the board`() {
        store.create("A")
        store.create("B")
        store.create("C")
        val rewritten = store.reorder(listOf("c", "a", "b"))
        assertEquals(listOf("c"), rewritten)
        assertEquals(listOf("c", "a", "b"), store.read().map { it.slug })
    }

    @Test
    fun `deleting an idea takes its directory with it`() {
        store.create("Gone")
        assertTrue(store.delete("gone"))
        assertTrue(store.read().isEmpty())
        assertTrue(!java.io.File(root, ideaDir("gone")).exists())
    }

    @Test
    fun `an idea with its own repo is written as a reference`() {
        val tile = store.create("Linked")
        store.writeIdea(tile.slug, tile.file.copy(repo = "octocat/hello", notes = "copied"))
        val written = store.readIdea("linked")!!.file
        assertEquals("octocat/hello", written.repo)
        // No second copy of the notes: that is the drift this layout avoids.
        assertTrue("copied" !in written.notes)
        assertTrue("lives in" in written.notes)
    }

    @Test
    fun `a directory that is not a slug is ignored`() {
        store.create("Real")
        java.io.File(root, "$IDEAS_DIR/Not A Slug").mkdirs()
        java.io.File(root, "$IDEAS_DIR/Not A Slug/$IDEA_FILE").writeText("# Nope\n")
        assertEquals(listOf("real"), store.read().map { it.slug })
    }

    @Test
    fun `a tile picks up the logo sitting beside its file`() {
        val tile = store.create("Pictured")
        java.io.File(root, logoPath(tile.slug, "idea_logo.png")).writeText("not really a png")
        assertEquals("ideas/pictured/idea_logo.png", store.readIdea("pictured")!!.logo)
        assertNull(store.readIdea("pictured")!!.file.repo)
    }
}
