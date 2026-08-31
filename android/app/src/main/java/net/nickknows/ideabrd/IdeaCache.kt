package net.nickknows.ideabrd

import java.io.File

/**
 * The IDEA.md of an idea that lives in its own repository, kept on disk.
 *
 * An idea with a repo is a *reference* on the board: the board file carries
 * its colour, its rank and where it lives, and nothing else. Everything worth
 * showing on the tile — the title, the status, how far along it is, the notes
 * — is in that repository's own IDEA.md.
 *
 * Cloning every one of those to fill in a board would be a poor trade on a
 * phone: an idea repo can be large and the connection is often metered, which
 * is why `fetchLinked` stays a deliberate act. But a board of tiles with no
 * status and no progress is not a board. One file per repo is kilobytes, so
 * the tiles are filled in from this instead, and cloning stays for when you
 * actually open one to work on it.
 *
 * Kept outside every checkout, like [IssueCache]: it is a copy of somebody
 * else's file and must never be committed to this board's repository.
 */
class IdeaCache(private val root: File) {

    private fun fileFor(repo: String) = File(root, repo.replace("/", "__") + ".md")

    /** The last IDEA.md seen for this repo, or null if it has never been read. */
    fun load(repo: String): String? {
        val file = fileFor(repo)
        return if (file.isFile) file.readText() else null
    }

    fun save(repo: String, content: String) {
        root.mkdirs()
        fileFor(repo).writeText(content)
    }

    fun clear(repo: String) {
        fileFor(repo).delete()
    }
}
