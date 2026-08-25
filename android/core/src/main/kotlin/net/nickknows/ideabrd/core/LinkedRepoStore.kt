package net.nickknows.ideabrd.core

import java.io.File

/**
 * An idea that lives in a repository of its own, read from a checkout of it.
 *
 * The board repo holds such an idea as a *reference* — rank, colour and a link,
 * nothing else — because its notes and to-dos are tracked in that repository
 * under its own history, and a second copy could only ever drift. Which means a
 * client reading only the board repo can see that the idea exists and nothing
 * about what it says.
 *
 * So the phone reads the linked repository too: its root IDEA.md is the idea,
 * in exactly the format the server writes there. Note what is *not* written
 * here — no `rank`, no `color`, no `repo` key. Those belong to whichever board
 * is showing the tile, and a shared idea sits on several boards at different
 * positions; putting them in the idea's own file would make one board's layout
 * everybody's.
 */
class LinkedRepoStore(private val root: File) {

    private val ideaFile: File get() = File(root, IDEA_FILE)

    /** Whether this checkout has an idea file to read. */
    fun exists(): Boolean = ideaFile.isFile

    fun read(): ParsedIdeaFile? =
        if (exists()) parseIdeaFile(ideaFile.readText()) else null

    /** Write the idea back, with the format rules it carries for its next editor. */
    fun write(idea: ParsedIdeaFile) {
        root.mkdirs()
        ideaFile.writeText(
            renderIdeaFile(
                title = idea.title ?: "Untitled",
                notes = idea.notes,
                status = idea.status ?: "idea",
                progress = idea.progress ?: 0,
                todos = idea.todos,
            )
        )
    }

    /** The tile image committed beside the idea file, if the repo carries one. */
    fun logo(): File? =
        LOGO_NAMES.map { File(root, it) }.firstOrNull { it.isFile }

    companion object {
        /**
         * Preference order when a repo somehow holds more than one, so the
         * image adopted is stable rather than dependent on listing order.
         */
        val LOGO_NAMES = listOf(
            "idea_logo.png",
            "idea_logo.webp",
            "idea_logo.jpg",
            "idea_logo.jpeg",
            "idea_logo.gif",
        )
    }
}
