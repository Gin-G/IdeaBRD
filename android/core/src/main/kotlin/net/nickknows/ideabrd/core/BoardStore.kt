package net.nickknows.ideabrd.core

import java.io.File

/**
 * A board, read and written as a directory of files.
 *
 * This is the whole storage layer for a git-only client: a checkout of the
 * board repo is the database, and this class is the only thing that knows the
 * layout. It writes exactly what the server's publisher writes — same file
 * names, same rendering, same ordering keys — so a board edited on a phone and
 * a board published by the server produce the same tree, and a sync between
 * them is a fast-forward rather than a conflict on every file.
 *
 * Nothing here touches git. Committing, pulling and pushing belong to the
 * plugin that owns the repository; this owns what the files say.
 */
class BoardStore(private val root: File) {

    /** One idea on the board: its directory name and what its file says. */
    data class Tile(
        val slug: String,
        val file: ParsedIdeaFile,
        /** Repo-relative path of the tile image, when the directory has one. */
        val logo: String? = null,
    )

    private val ideasDir: File get() = File(root, IDEAS_DIR)

    /** Write the format marker, so the repo declares what it is. */
    fun ensureMarker() {
        val marker = File(root, MARKER_FILE)
        if (!marker.exists()) {
            root.mkdirs()
            marker.writeText(markerContent())
        }
    }

    /** Whether this directory is a board (or is empty enough to become one). */
    fun isBoard(): Boolean = File(root, MARKER_FILE).exists()

    /** Every idea, in board order: by rank, with unranked ideas last. */
    fun read(): List<Tile> =
        (ideasDir.listFiles() ?: emptyArray())
            .filter { it.isDirectory && isSlug(it.name) }
            .mapNotNull { dir ->
                val file = File(dir, IDEA_FILE)
                if (!file.isFile) return@mapNotNull null
                Tile(
                    slug = dir.name,
                    file = parseIdeaFile(file.readText()),
                    logo = dir.listFiles()
                        ?.firstOrNull { it.isFile && it.name.startsWith("idea_logo.") }
                        ?.let { logoPath(dir.name, it.name) },
                )
            }
            .sortedWith(
                compareBy({ it.file.rank == null }, { it.file.rank ?: "" }, { it.slug })
            )

    fun readIdea(slug: String): Tile? = read().firstOrNull { it.slug == slug }

    /** Overwrite one idea's file. The caller owns what the fields say. */
    fun writeIdea(slug: String, idea: ParsedIdeaFile) {
        val dir = File(ideasDir, slug)
        dir.mkdirs()
        val text =
            if (idea.repo != null) {
                // An idea with a repository of its own is recorded here as a
                // reference: its notes and to-dos are tracked there, and a
                // second copy could only ever drift from them.
                renderReferenceFile(
                    repo = idea.repo,
                    rank = idea.rank ?: FIRST,
                    color = idea.color ?: DEFAULT_COLOR,
                )
            } else {
                renderIdeaFile(
                    title = idea.title ?: "Untitled",
                    notes = idea.notes,
                    status = idea.status ?: "idea",
                    progress = idea.progress ?: 0,
                    todos = idea.todos,
                    color = idea.color ?: DEFAULT_COLOR,
                    rank = idea.rank ?: FIRST,
                )
            }
        File(dir, IDEA_FILE).writeText(text)
    }

    /** Add an idea to the end of the board and return it. */
    fun create(title: String, color: String = DEFAULT_COLOR): Tile {
        ensureMarker()
        val existing = read()
        val slug = uniqueSlug(title, existing.map { it.slug }.toSet())
        val idea =
            ParsedIdeaFile(
                title = title,
                status = "idea",
                progress = 0,
                color = color,
                rank = between(existing.lastOrNull()?.file?.rank, null),
            )
        writeIdea(slug, idea)
        return Tile(slug, idea)
    }

    /**
     * Remove an idea, directory and all.
     *
     * Git has no empty directories, so removing every file under one is the
     * same as removing the directory — which is what a deleted tile is.
     */
    fun delete(slug: String): Boolean = File(ideasDir, slug).deleteRecursively()

    /**
     * Put the board in the order given, rewriting as few files as possible.
     *
     * The ranks that are already consistent with the new order are left exactly
     * as they are, so dragging one tile rewrites one file — which is what keeps
     * two devices reordering different tiles from conflicting.
     */
    fun reorder(slugs: List<String>): List<String> {
        val bySlug = read().associateBy { it.slug }
        val ordered = slugs.mapNotNull { bySlug[it] }
        val repaired = repair(ordered.map { it.file.rank })
        val rewritten = mutableListOf<String>()
        ordered.forEachIndexed { i, tile ->
            if (tile.file.rank != repaired[i]) {
                writeIdea(tile.slug, tile.file.copy(rank = repaired[i]))
                rewritten += tile.slug
            }
        }
        return rewritten
    }

    companion object {
        /** The accent colour a tile gets when nobody has chosen one. */
        const val DEFAULT_COLOR = "#6366f1"
    }
}
