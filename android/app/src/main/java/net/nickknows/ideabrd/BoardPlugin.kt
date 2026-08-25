package net.nickknows.ideabrd

import com.getcapacitor.JSArray
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import java.io.File
import java.util.concurrent.Executors
import net.nickknows.ideabrd.core.BoardStore
import net.nickknows.ideabrd.core.IDEA_FILE
import net.nickknows.ideabrd.core.ParsedIdeaFile
import net.nickknows.ideabrd.core.ParsedTodo
import net.nickknows.ideabrd.core.mergeIdeaFiles
import org.eclipse.jgit.api.Git
import org.eclipse.jgit.api.MergeResult
import org.eclipse.jgit.lib.ObjectId
import org.eclipse.jgit.lib.PersonIdent
import org.eclipse.jgit.lib.Repository
import org.eclipse.jgit.revwalk.RevWalk
import org.eclipse.jgit.revwalk.filter.RevFilter
import org.eclipse.jgit.transport.RemoteRefUpdate
import org.eclipse.jgit.transport.UsernamePasswordCredentialsProvider
import org.eclipse.jgit.treewalk.TreeWalk

/**
 * The board, as a git repository on the phone.
 *
 * This is the half of the git-only client that has to be native: JGit, a real
 * working copy, and the merge that happens when a board edited offline meets a
 * board edited somewhere else. Everything above it — what an idea is, what the
 * file says, where a tile sits — is in `:core`, shared with the tests and
 * matched byte for byte against the server's renderer.
 *
 * The design rule is that this plugin exposes *board* operations, not file
 * operations. The web layer asks for the ideas and gets ideas; it never sees a
 * path, a blob or a commit. That keeps one implementation of the format (the
 * Kotlin port) rather than a second one in TypeScript, which would be the same
 * mistake as having two parsers on the server.
 *
 * Every write is its own commit. Syncing is fetch, merge, push, in that order,
 * and a conflict in an IDEA.md is resolved by meaning rather than reported as a
 * conflict — the whole reason `mergeIdeaFiles` exists.
 */
@CapacitorPlugin(name = "Board")
class BoardPlugin : Plugin() {

    private val work = Executors.newSingleThreadExecutor()

    private val repoDir: File
        get() = File(context.filesDir, "board")

    private val store: BoardStore
        get() = BoardStore(repoDir)

    private fun settings() = context.getSharedPreferences("ideabrd-board", 0)

    private fun credentials(): UsernamePasswordCredentialsProvider? =
        TokenStore.token(context)?.let {
            // GitHub accepts a token as the password against this username;
            // the token is never put in the URL, where it would end up in the
            // repo's own config on disk.
            UsernamePasswordCredentialsProvider("x-access-token", it)
        }

    private fun author(): PersonIdent {
        val login = TokenStore.login(context)
        return PersonIdent(
            login ?: "IdeaBRD",
            if (login != null) "$login@users.noreply.github.com"
            else "ideabrd@users.noreply.github.com",
        )
    }

    /** Run off the main thread and turn any failure into a rejected call. */
    private fun background(call: PluginCall, block: () -> JSObject?) {
        work.execute {
            try {
                call.resolve(block() ?: JSObject())
            } catch (e: Exception) {
                call.reject(e.message ?: e.javaClass.simpleName, e)
            }
        }
    }

    // ---- configuration -------------------------------------------------

    /**
     * Point the app at a board repo, cloning it if this device hasn't got it.
     *
     * Changing to a different repo replaces the working copy rather than
     * merging two boards into one directory.
     */
    @PluginMethod
    fun configure(call: PluginCall) {
        val repo = call.getString("repo") ?: return call.reject("repo is required")
        val branch = call.getString("branch") ?: "main"
        background(call) {
            val previous = settings().getString("repo", null)
            if (previous != null && previous != repo && repoDir.exists()) {
                repoDir.deleteRecursively()
            }
            settings().edit().putString("repo", repo).putString("branch", branch).apply()
            if (!File(repoDir, ".git").exists()) clone(repo, branch)
            status()
        }
    }

    @PluginMethod
    fun status(call: PluginCall) {
        background(call) { status() }
    }

    private fun status(): JSObject {
        val repo = settings().getString("repo", null)
        val result = JSObject()
        result.put("repo", repo)
        result.put("branch", settings().getString("branch", "main"))
        result.put("cloned", File(repoDir, ".git").exists())
        result.put("authenticated", TokenStore.token(context) != null)
        result.put("login", TokenStore.login(context))
        if (File(repoDir, ".git").exists()) {
            Git.open(repoDir).use { git ->
                // "Unsynced" is the count of commits made here that the remote
                // has not seen — the thing a person actually wants to know when
                // they are about to get on a plane.
                result.put("unsynced", unpushed(git))
                result.put("dirty", !git.status().call().isClean)
            }
        }
        return result
    }

    private fun clone(repo: String, branch: String) {
        repoDir.parentFile?.mkdirs()
        Git.cloneRepository()
            .setURI("https://github.com/$repo.git")
            .setDirectory(repoDir)
            .setBranch(branch)
            .setCredentialsProvider(credentials())
            .call()
            .close()
    }

    private fun unpushed(git: Git): Int {
        val branch = git.repository.branch ?: return 0
        val local = git.repository.resolve(branch) ?: return 0
        val remote = git.repository.resolve("refs/remotes/origin/$branch") ?: return 0
        RevWalk(git.repository).use { walk ->
            walk.markStart(walk.parseCommit(local))
            walk.markUninteresting(walk.parseCommit(remote))
            return walk.count()
        }
    }

    // ---- reading -------------------------------------------------------

    @PluginMethod
    fun listIdeas(call: PluginCall) {
        background(call) {
            val ideas = JSArray()
            store.read().forEach { ideas.put(tileJson(it, withTodos = false)) }
            JSObject().put("ideas", ideas)
        }
    }

    @PluginMethod
    fun readIdea(call: PluginCall) {
        val slug = call.getString("slug") ?: return call.reject("slug is required")
        background(call) {
            store.readIdea(slug)?.let { tileJson(it, withTodos = true) }
                ?: throw IllegalArgumentException("No idea called $slug on this board")
        }
    }

    private fun tileJson(tile: BoardStore.Tile, withTodos: Boolean): JSObject {
        val json = JSObject()
        json.put("slug", tile.slug)
        json.put("title", tile.file.title)
        json.put("status", tile.file.status ?: "idea")
        json.put("progress", tile.file.progress ?: 0)
        json.put("color", tile.file.color ?: BoardStore.DEFAULT_COLOR)
        json.put("rank", tile.file.rank)
        json.put("repo", tile.file.repo)
        json.put("logo", tile.logo)
        json.put("notes", tile.file.notes)
        if (withTodos) {
            val todos = JSArray()
            tile.file.todos.forEach { todo ->
                todos.put(
                    JSObject()
                        .put("text", todo.text)
                        .put("done", todo.done)
                        .put("issue", todo.issue)
                )
            }
            json.put("todos", todos)
        }
        return json
    }

    // ---- writing -------------------------------------------------------

    @PluginMethod
    fun createIdea(call: PluginCall) {
        val title = call.getString("title") ?: return call.reject("title is required")
        background(call) {
            val tile = store.create(title, call.getString("color") ?: BoardStore.DEFAULT_COLOR)
            commit("Add idea: ${tile.file.title}")
            tileJson(store.readIdea(tile.slug)!!, withTodos = true)
        }
    }

    /**
     * Overwrite one idea from what the page holds.
     *
     * Fields the caller leaves out keep the value already in the file, so a
     * page that only knows about the checkbox it just ticked does not have to
     * send the whole idea back to avoid erasing the rest of it.
     */
    @PluginMethod
    fun writeIdea(call: PluginCall) {
        val slug = call.getString("slug") ?: return call.reject("slug is required")
        background(call) {
            val current = store.readIdea(slug)
                ?: throw IllegalArgumentException("No idea called $slug on this board")
            val todos = call.getArray("todos", null)?.let { array ->
                (0 until array.length()).map { i ->
                    val item = array.getJSONObject(i)
                    ParsedTodo(
                        text = item.getString("text"),
                        done = item.optBoolean("done", false),
                        issue = if (item.has("issue") && !item.isNull("issue")) {
                            item.getInt("issue")
                        } else {
                            null
                        },
                    )
                }
            }
            val updated = ParsedIdeaFile(
                title = call.getString("title") ?: current.file.title,
                notes = call.getString("notes") ?: current.file.notes,
                status = call.getString("status") ?: current.file.status,
                progress = call.getInt("progress") ?: current.file.progress,
                color = call.getString("color") ?: current.file.color,
                rank = current.file.rank,
                repo = call.getString("repo") ?: current.file.repo,
                todos = todos ?: current.file.todos,
            )
            store.writeIdea(slug, updated)
            commit("Update idea: ${updated.title}")
            tileJson(store.readIdea(slug)!!, withTodos = true)
        }
    }

    @PluginMethod
    fun deleteIdea(call: PluginCall) {
        val slug = call.getString("slug") ?: return call.reject("slug is required")
        background(call) {
            val title = store.readIdea(slug)?.file?.title ?: slug
            store.delete(slug)
            commit("Remove idea: $title")
            JSObject().put("deleted", slug)
        }
    }

    @PluginMethod
    fun reorder(call: PluginCall) {
        val slugs = call.getArray("slugs") ?: return call.reject("slugs is required")
        background(call) {
            val order = (0 until slugs.length()).map { slugs.getString(it) }
            val rewritten = store.reorder(order)
            if (rewritten.isNotEmpty()) commit("Reorder board")
            JSObject().put("rewritten", JSArray(rewritten.toTypedArray()))
        }
    }

    /** Stage everything under the board and commit it, if anything changed. */
    private fun commit(message: String) {
        Git.open(repoDir).use { git ->
            git.add().addFilepattern(".").call()
            git.add().addFilepattern(".").setUpdate(true).call() // pick up deletions
            if (git.status().call().isClean) return
            git.commit()
                .setMessage("$message (via IdeaBRD)")
                .setAuthor(author())
                .setCommitter(author())
                .call()
        }
    }

    // ---- syncing -------------------------------------------------------

    /**
     * Fetch, merge and push, in that order.
     *
     * The merge is where the offline story is either kept or broken. Git's own
     * three-way merge on an IDEA.md is nearly useless: both sides re-render the
     * whole file, so any real edit conflicts on every line. Those conflicts are
     * resolved here by parsing both versions and merging them by meaning, using
     * the same code the server uses — so two people editing different parts of
     * an idea never see a conflict at all, and neither loses their edit.
     *
     * A conflict in anything that isn't an IDEA.md is left alone and reported:
     * this knows how to merge ideas, and pretending to know how to merge the
     * rest of somebody's repository would be worse than saying so.
     */
    @PluginMethod
    fun sync(call: PluginCall) {
        background(call) {
            val credentials = credentials()
                ?: throw IllegalStateException("Sign in to GitHub before syncing")
            val result = JSObject()
            Git.open(repoDir).use { git ->
                val branch = git.repository.branch
                git.fetch().setCredentialsProvider(credentials).setRemote("origin").call()

                val remote = git.repository.resolve("refs/remotes/origin/$branch")
                val local = git.repository.resolve(branch)
                val resolved = mutableListOf<String>()
                val conflicts = mutableListOf<String>()

                if (remote != null && remote != local) {
                    val merge = git.merge().include(remote).setCommit(true).call()
                    if (merge.mergeStatus == MergeResult.MergeStatus.CONFLICTING) {
                        val base = mergeBase(git.repository, local!!, remote)
                        merge.conflicts.keys.forEach { path ->
                            if (path.endsWith(IDEA_FILE) &&
                                resolveIdeaConflict(git, path, base, local, remote)
                            ) {
                                resolved += path
                            } else {
                                conflicts += path
                            }
                        }
                        if (conflicts.isEmpty()) {
                            git.commit()
                                .setMessage("Merge board (via IdeaBRD)")
                                .setAuthor(author())
                                .setCommitter(author())
                                .call()
                        } else {
                            // Leave the working copy as git left it: a person
                            // with a real conflict needs to see it, and an app
                            // that "resolves" it by picking a side is how
                            // somebody's afternoon disappears.
                            throw IllegalStateException(
                                "Conflicts this app can't merge: ${conflicts.joinToString()}"
                            )
                        }
                    }
                }

                val pushed = git.push()
                    .setCredentialsProvider(credentials)
                    .setRemote("origin")
                    .add(branch)
                    .call()
                pushed.forEach { push ->
                    push.remoteUpdates.forEach { update ->
                        if (update.status !in ACCEPTED_PUSH) {
                            throw IllegalStateException(
                                "Push rejected: ${update.status} ${update.message ?: ""}"
                            )
                        }
                    }
                }
                result.put("merged", JSArray(resolved.toTypedArray()))
                result.put("unsynced", unpushed(git))
            }
            result
        }
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
        val baseText = base?.let { blob(git.repository, it, path) }
        val (merged, _) = mergeIdeaFiles(baseText, ourText, theirText)
        File(git.repository.workTree, path).writeText(merged)
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
