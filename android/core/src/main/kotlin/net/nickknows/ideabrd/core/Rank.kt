package net.nickknows.ideabrd.core

/**
 * Fractional ranks: ordering keys that keep a reorder down to one file.
 *
 * A port of `backend/app/rank.py`. Board order lives in the ideas themselves
 * rather than in a manifest, because a manifest is the one file every device
 * would conflict on. A rank is a base-36 string compared lexicographically,
 * with the one property that matters: there is always room to name a key
 * strictly between any two others, so moving a tile rewrites that tile's file
 * and nothing else.
 *
 * Ranks are compared as plain strings, never parsed as numbers, so `"z" < "za"`
 * holds everywhere the board is read — Postgres, Python and here alike.
 */

const val DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
private const val BASE = 36

/** Rank of the first tile on an empty board: the midpoint of the space. */
val FIRST: String = DIGITS[BASE / 2].toString()

class InvalidRank(message: String) : IllegalArgumentException(message)

/**
 * Whether a string can be compared as a rank.
 *
 * Deliberately lenient about trailing zeros: [between] never emits one, but a
 * hand-edited file may hold one and it still orders correctly.
 */
fun isRank(value: String): Boolean =
    value.isNotEmpty() && value.all { DIGITS.indexOf(it) >= 0 }

private fun digitsOf(value: String?): List<Int> =
    value?.map { DIGITS.indexOf(it) } ?: emptyList()

private fun render(digits: List<Int>): String =
    digits.joinToString("") { DIGITS[it].toString() }

/**
 * A rank strictly between [lo] and [hi]; null means the open end.
 *
 * Throws [InvalidRank] if the bounds aren't ordered, since a caller passing a
 * stale pair would otherwise get a key that silently sorts somewhere else.
 */
fun between(lo: String? = null, hi: String? = null): String {
    listOfNotNull(lo, hi).forEach { if (!isRank(it)) throw InvalidRank("Not a rank: $it") }
    if (lo != null && hi != null && lo >= hi) throw InvalidRank("Bounds out of order: $lo >= $hi")

    val low = digitsOf(lo)
    var high: List<Int>? = if (hi != null) digitsOf(hi) else null
    val out = mutableListOf<Int>()
    var i = 0
    while (true) {
        // Past the end of lo, the smallest digit still keeps us above it: any
        // continuation of a prefix sorts after the prefix itself.
        val x = if (i < low.size) low[i] else 0
        val y = high?.let { if (i < it.size) it[i] else BASE } ?: BASE
        if (y - x > 1) {
            out += (x + y) / 2
            return render(out)
        }
        out += x
        // Now strictly below hi on this digit, so hi constrains nothing further
        // — "a…" sorts before "b" whatever follows the "a".
        if (y - x == 1) high = null
        i += 1
    }
}

/**
 * [count] ranks in ascending order, spread evenly across the space.
 *
 * Used to give an existing board its first ranks. Spacing them evenly rather
 * than chaining [between] leaves room to insert anywhere without lengthening a
 * key on the first move.
 */
fun initial(count: Int): List<String> {
    if (count <= 0) return emptyList()
    var width = 1
    var span = BASE.toLong()
    while (span < (count + 1).toLong() * 2) {
        width += 1
        span *= BASE
    }
    return (1..count).map { i ->
        var value = span * i / (count + 1)
        val digits = ArrayDeque<Int>()
        repeat(width) {
            digits.addFirst((value % BASE).toInt())
            value /= BASE
        }
        // Trailing zeros carry no order, and dropping them keeps keys short
        // without changing where any of them sorts.
        render(digits.toList()).trimEnd(DIGITS[0]).ifEmpty { DIGITS[1].toString() }
    }
}

/** [count] ranks strictly between the bounds, bisecting so they stay short. */
private fun spread(lo: String?, hi: String?, count: Int): List<String> {
    if (count <= 0) return emptyList()
    val half = count / 2
    val mid = between(lo, hi)
    return spread(lo, mid, half) + mid + spread(mid, hi, count - half - 1)
}

/**
 * Ranks for the order given, rewriting as few of them as possible.
 *
 * [ranks] is the board in the order it should end up, holding each idea's
 * current rank or null for one that has never had a rank. Every rank already
 * consistent with the order comes back untouched — so a single tile moving
 * rewrites a single file, which is the entire reason ranks are fractional.
 *
 * Keeping the most ranks means keeping a longest strictly increasing
 * subsequence of the ones already set. Quadratic, which is the right trade for
 * a board of tiles: obviously correct, and n is what fits on a screen.
 */
fun repair(ranks: List<String?>): List<String> {
    val n = ranks.size
    if (n == 0) return emptyList()

    val best = IntArray(n)
    val prev = IntArray(n) { -1 }
    for (i in 0 until n) {
        val current = ranks[i] ?: continue
        best[i] = 1
        for (j in 0 until i) {
            val other = ranks[j] ?: continue
            if (other < current && best[j] + 1 > best[i]) {
                best[i] = best[j] + 1
                prev[i] = j
            }
        }
    }
    val keep = mutableSetOf<Int>()
    var end = (0 until n).maxByOrNull { best[it] } ?: -1
    while (end != -1 && best[end] > 0) {
        keep += end
        end = prev[end]
    }

    val out = MutableList<String?>(n) { if (it in keep) ranks[it] else null }
    var i = 0
    while (i < n) {
        if (out[i] != null) {
            i += 1
            continue
        }
        var j = i
        while (j < n && out[j] == null) j += 1
        val lo = if (i > 0) out[i - 1] else null
        val hi = if (j < n) out[j] else null
        spread(lo, hi, j - i).forEachIndexed { offset, value -> out[i + offset] = value }
        i = j
    }
    return out.filterNotNull()
}
