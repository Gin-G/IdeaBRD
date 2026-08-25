package net.nickknows.ideabrd.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** Fractional ranks. The only property that matters: there is always room. */
class RankTest {

    @Test
    fun `between always lands strictly inside`() {
        assertTrue(between(null, null).isNotEmpty())
        assertTrue(between("i", null) > "i")
        assertTrue(between(null, "i") < "i")
        val mid = between("i", "r")
        assertTrue(mid in "i".."r" && mid != "i" && mid != "r")
    }

    @Test
    fun `a key grows only when the gap runs out`() {
        val mid = between("a", "b")
        assertTrue(mid > "a" && mid < "b")
        assertEquals("ai", mid)
    }

    @Test
    fun `repeated bisection stays ordered`() {
        var lo = between(null, null)
        var hi = between(lo, null)
        repeat(50) {
            val mid = between(lo, hi)
            assertTrue(mid > lo && mid < hi, "$lo < $mid < $hi")
            hi = mid
        }
        assertTrue(lo < hi)
    }

    @Test
    fun `bad bounds are refused rather than silently misplaced`() {
        assertFailsWith<InvalidRank> { between("r", "i") }
        assertFailsWith<InvalidRank> { between("!", null) }
    }

    @Test
    fun `initial spreads evenly and stays sorted`() {
        val ranks = initial(10)
        assertEquals(10, ranks.size)
        assertEquals(ranks.sorted(), ranks)
        assertEquals(ranks.toSet().size, ranks.size)
    }

    @Test
    fun `repair keeps every rank already in order`() {
        val ranks = listOf("a", "b", "c")
        assertEquals(ranks, repair(ranks))
    }

    @Test
    fun `repair rewrites only what moved`() {
        // "c" dragged to the front: one file should change, not three.
        val moved = listOf<String?>("c", "a", "b")
        val fixed = repair(moved)
        assertEquals(fixed.sorted(), fixed)
        assertEquals(listOf("a", "b"), fixed.drop(1))
    }

    @Test
    fun `repair fills in ideas that never had a rank`() {
        val fixed = repair(listOf(null, "m", null))
        assertEquals(fixed.sorted(), fixed)
        assertEquals("m", fixed[1])
    }

    @Test
    fun `is rank is lenient about trailing zeros`() {
        assertTrue(isRank("a0"))
        assertTrue(!isRank(""))
        assertTrue(!isRank("A"))
    }
}
