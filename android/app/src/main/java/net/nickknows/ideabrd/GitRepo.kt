package net.nickknows.ideabrd

import java.io.File
import net.nickknows.ideabrd.core.IDEA_FILE
import net.nickknows.ideabrd.core.mergeIdeaFiles
import org.eclipse.jgit.api.Git
import org.eclipse.jgit.api.MergeResult
import org.eclipse.jgit.lib.ObjectId
import org.eclipse.jgit.lib.PersonIdent
import org.eclipse.jgit.lib.Repository
import org.eclipse.jgit.revwalk.RevWalk
import org.eclipse.jgit.revwalk.filter.RevFilter
import org.eclipse.jgit.transport.CredentialsProvider
import org.eclipse.jgit.transport.RemoteRefUpdate
import org.eclipse.jgit.treewalk.TreeWalk

/**
 * One git repository on the device, and the four things the app does with one:
 * clone it, commit into it, merge what came from elsewhere, and push.
 *
 * There are two kinds of repository here and they behave identically, which is
 * why this exists rather than living inside the board plugin: the *board* repo
 * holds every idea as `ideas/<slug>/IDEA.md`, and each idea that has a
 * repository of its own holds itself as a root `IDEA.md`. Same file format,
 * same merge, same push — different address.
 *
 * The merge is the part that matters. Git's own three-way merge on an IDEA.md
 * is close to useless, because both sides re-render the whole file: any real
 * edit conflicts on nearly every line. So a conflict in a path ending in
 * IDEA.md is resolved by parsing all three versions out of the object database
 * and merging them by meaning. A conflict in anything else is left exactly as
 * git left it and reported — this knows how to merge ideas, and pretending to
 * know how to merge the rest of somebody's repository would be worse than
 * saying so.
 */
class GitRepo(val dir: File, val repo: String, val branch: String? = null) {

    /** What a sync did: which files were merged for us, and what is still local. */
    data class Outcome(val merged: List<String>, val unsynced: Int)

    class ConflictException(val paths: List<String>) :
        IllegalStateException("Conflicts this app can't merge: ${paths.joinToString()}")

    val cloned: Boolean get() = File(dir, ".git").exists()

    fun clone(credentials: CredentialsProvider?) {
        dir.parentFile?.mkdirs()
        Git.cloneRepository()
            .setURI("https://github.com/$repo.git")
            .setDirectory(dir)
            .setCredentialsProvider(credentials)
            .apply { branch?.let { setBranch(it) } }
            .call()
            .close()
    }

    private inline fun <T> use(block: (Git) -> T): T = Git.open(dir).use(block)

    /** Stage everything and commit, if anything actually changed. */
    fun commitAll(message: String, author: PersonIdent): Boolean = use { git ->
        git.add().addFilepattern(".").call()
        git.add().addFilepattern(".").setUpdate(true).call() // pick up deletions
        if (git.status().call().isClean) return@use false
        git.commit()
            .setMessage("$message (via IdeaBRD)")
            .setAuthor(author)
            .setCommitter(author)
            .call()
        true
    }

    /** Commits made here that the remote has not seen. */
    fun unpushed(): Int = if (!cloned) 0 else use { git -> unpushed(git) }

    private fun unpushed(git: Git): Int {
        val head = git.repository.branch ?: return 0
        val local = git.repository.resolve(head) ?: return 0
        val remote = git.repository.resolve("refs/remotes/origin/$head") ?: return 0
        RevWalk(git.repository).use { walk ->
            walk.markStart(walk.parseCommit(local))
            walk.markUninteresting(walk.parseCommit(remote))
            return walk.count()
        }
    }

    fun isDirty(): Boolean = cloned && use { git -> !git.status().call().isClean }

    /** Fetch, merge what came back, push. Throws [ConflictException] if it can't. */
    fun sync(credentials: CredentialsProvider, author: PersonIdent): Outcome = use { git ->
        val head = git.repository.branch
        git.fetch().setCredentialsProvider(credentials).setRemote("origin").call()

        val remote = git.repository.resolve("refs/remotes/origin/$head")
        val local = git.repository.resolve(head)
        val merged = mutableListOf<String>()

        if (remote != null && remote != local) {
            val result = git.merge().include(remote).setCommit(true).call()
            if (result.mergeStatus == MergeResult.MergeStatus.CONFLICTING) {
                val base = mergeBase(git.repository, local!!, remote)
                val unresolved = mutableListOf<String>()
                result.conflicts.keys.forEach { path ->
                    if (path.endsWith(IDEA_FILE) &&
                        resolveIdeaConflict(git, path, base, local, remote)
                    ) {
                        merged += path
                    } else {
                        unresolved += path
                    }
                }
                if (unresolved.isNotEmpty()) throw ConflictException(unresolved)
                git.commit()
                    .setMessage("Merge (via IdeaBRD)")
                    .setAuthor(author)
                    .setCommitter(author)
                    .call()
            }
        }

        git.push()
            .setCredentialsProvider(credentials)
            .setRemote("origin")
            .add(head)
            .call()
            .forEach { push ->
                push.remoteUpdates.forEach { update ->
                    if (update.status !in ACCEPTED_PUSH) {
                        throw IllegalStateException(
                            "Push to $repo rejected: ${update.status} ${update.message ?: ""}"
                        )
                    }
                }
            }
        Outcome(merged, unpushed(git))
    }

    private fun mergeBase(repository: Repository, a: ObjectId, b: ObjectId): ObjectId? =
        RevWalk(repository).use { walk ->
            walk.revFilter = RevFilter.MERGE_BASE
            walk.markStart(walk.parseCommit(a))
            walk.markStart(walk.parseCommit(b))
            walk.next()?.id
        }

    /** Merge one conflicted IDEA.md by meaning. True when it worked. */
    private fun resolveIdeaConflict(
        git: Git,
        path: String,
        base: ObjectId?,
        ours: ObjectId?,
        theirs: ObjectId,
    ): Boolean {
        val ourText = blob(git.repository, ours, path) ?: return false
        val theirText = blob(git.repository, theirs, path) ?: return false
        val (text, _) = mergeIdeaFiles(base?.let { blob(git.repository, it, path) }, ourText, theirText)
        File(git.repository.workTree, path).writeText(text)
        git.add().addFilepattern(path).call()
        return true
    }

    /** One file's text at one commit, or null if it wasn't there. */
    private fun blob(repository: Repository, commit: ObjectId?, path: String): String? {
        if (commit == null) return null
        RevWalk(repository).use { walk ->
            val tree = walk.parseCommit(commit).tree
            TreeWalk.forPath(repository, path, tree).use { treeWalk ->
                if (treeWalk == null) return null
                return String(repository.open(treeWalk.getObjectId(0)).bytes, Charsets.UTF_8)
            }
        }
    }

    private companion object {
        val ACCEPTED_PUSH = setOf(
            RemoteRefUpdate.Status.OK,
            RemoteRefUpdate.Status.UP_TO_DATE,
        )
    }
}
