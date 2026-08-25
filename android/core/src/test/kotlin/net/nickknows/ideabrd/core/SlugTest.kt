package net.nickknows.ideabrd.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** Slugs name directories, so they have to survive being checked out anywhere. */
class SlugTest {

    @Test
    fun `accents are folded rather than dropped`() {
        assertEquals("idee", slugify("Idée"))
    }

    @Test
    fun `a title with nothing ascii in it still gets a name`() {
        assertEquals("idea", slugify("💡"))
        assertTrue(isSlug(slugify("日本語")))
    }

    @Test
    fun `windows reserved names are suffixed, not replaced`() {
        assertEquals("con-idea", slugify("CON"))
        assertTrue(isSlug(slugify("con")))
    }

    @Test
    fun `slugs are capped and never end in a dash`() {
        val slug = slugify("x".repeat(200))
        assertEquals(MAX_SLUG_LENGTH, slug.length)
        assertTrue(!slug.endsWith("-"))
    }

    @Test
    fun `uniqueness folds case, because checkouts do`() {
        assertEquals("taken-2", uniqueSlug("Taken", setOf("TAKEN")))
    }

    @Test
    fun `a suffix keeps the name within the cap`() {
        val taken = setOf(slugify("y".repeat(100)))
        val next = uniqueSlug("y".repeat(100), taken)
        assertTrue(next.length <= MAX_SLUG_LENGTH)
        assertTrue(next !in taken)
    }
}
