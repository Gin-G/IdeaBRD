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
import net.nickknows.ideabrd.core.InvalidRepoRef
import net.nickknows.ideabrd.core.IssueInfo
import net.nickknows.ideabrd.core.LinkedRepoStore
import net.nickknows.ideabrd.core.parseIdeaFile
import net.nickknows.ideabrd.core.ParsedIdeaFile
import net.nickknows.ideabrd.core.ParsedTodo
import net.nickknows.ideabrd.core.applyIssues
import net.nickknows.ideabrd.core.issueEdits
import net.nickknows.ideabrd.core.mergeImportedIssues
import net.nickknows.ideabrd.core.normalizeRepo
import org.eclipse.jgit.lib.PersonIdent
import org.eclipse.jgit.transport.UsernamePasswordCredentialsProvider

/**
 * The board, as git repositories on the phone.
 *
 * This is the half of the git-only client that has to be native: JGit, real
 * working copies, and the merge that happens when a board edited offline meets
 * one edited somewhere else. Everything above it — what an idea is, what the
 * file says, where a tile sits — is in `:core`, shared with the tests and
 * matched byte for byte against the server's renderer.
 *
 * **Two kinds of repository.** The board repo holds every tile. But an idea
 * that has a repository of its own is recorded there as a *reference* — rank,
 * colour and a link, nothing else — because its notes and to-dos are tracked in
 * that repository under its own history. So opening such a tile means reading
 * that repository too, and the app clones it on demand. Without that, a
 * repo-linked idea on the phone is a link and an empty page.
 *
 * **Issues stay GitHub's.** A to-do carrying `(#12)` is owned by that issue:
 * its title and whether it is closed come from GitHub, not from the file, and
 * ticking the box here closes the issue. Between refreshes the last known state
 * is served from a cache, because a board has to open on a train.
 *
 * The design rule is that this exposes *board* operations, not file operations.
 * The web layer asks for ideas and gets ideas; it never sees a path, a blob or
 * a commit.
 */
@CapacitorPlugin(name = "Board")
class BoardPlugin : Plugin() {

    private val work = Executors.newSingleThreadExecutor()

    private val boardDir: File get() = File(context.filesDir, "board")
    private val linkedDir: File get() = File(context.filesDir, "linked")
    private val store: BoardStore get() = BoardStore(boardDir)
    private val issues: IssueCache get() = IssueCache(File(context.filesDir, "issues"))
    private val linkedIdeas: IdeaCache get() = IdeaCache(File(context.filesDir, "linked-ideas"))

    private fun settings() = context.getSharedPreferences("ideabrd-board", 0)

    private fun token(): String? = TokenStore.token(context)

    private fun credentials(): UsernamePasswordCredentialsProvider? =
        token()?.let {
            // GitHub accepts a token as the password against this username; it
            // is never put in the URL, where it would end up in the repo's own
            // config on disk.
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

    private fun boardRepo(): GitRepo? {
        val repo = settings().getString("repo", null) ?: return null
        return GitRepo(boardDir, repo, settings().getString("branch", null))
    }

    /** Where a linked idea's repository is checked out. One directory per repo. */
    /**
     * An absolute path to the tile's artwork, or null.
     *
     * The board file records a repo-relative path, which is meaningless to a
     * WebView — an <img src="ideas/x/idea_logo.png"> resolves against
     * https://localhost and 404s, which is why no logo has ever appeared on
     * the phone. The page turns this into a URL with Capacitor.convertFileSrc.
     *
     * Same order as the idea's own content: the checkout if there is one, then
     * what was last fetched, then the board's own copy for an idea that has no
     * repository of its own.
     */
    private fun logoFor(tile: BoardStore.Tile, linked: GitRepo?, repo: String?): String? {
        if (linked?.cloned == true) {
            linked.dir.listFiles()
                ?.firstOrNull { it.isFile && it.name.startsWith("idea_logo.") }
                ?.let { return it.absolutePath }
        }
        repo?.let { linkedIdeas.logo(it) }?.let { return it.absolutePath }
        return tile.logo?.let { File(boardDir, it).takeIf(File::isFile)?.absolutePath }
    }

    private fun linkedRepo(repo: String) =
        GitRepo(File(linkedDir, repo.replace("/", "__")), repo)

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
        val branch = call.getString("branch")
        background(call) {
            val previous = settings().getString("repo", null)
            if (previous != null && previous != repo && boardDir.exists()) {
                boardDir.deleteRecursively()
            }
            settings().edit().putString("repo", repo).putString("branch", branch).apply()
            val git = GitRepo(boardDir, repo, branch)
            if (!git.cloned) git.clone(credentials())
            // Connecting a board and being shown a grid of blank tiles is not
            // a working board; the ideas are in their own repositories and
            // this is where they get read.
            refreshLinkedIdeas()
            status()
        }
    }

    @PluginMethod
    fun status(call: PluginCall) {
        background(call) { status() }
    }

    private fun status(): JSObject {
        val git = boardRepo()
        val result = JSObject()
        result.put("repo", git?.repo)
        result.put("branch", settings().getString("branch", "main") ?: "main")
        result.put("cloned", git?.cloned == true)
        result.put("authenticated", token() != null)
        result.put("login", TokenStore.login(context))
        if (git?.cloned == true) {
            // "Unsynced" counts commits made here that the remote has not seen —
            // across the board repo and every idea repo, since a person who
            // edited a linked idea offline is owed the same warning.
            result.put("unsynced", git.unpushed() + linkedClones().sumOf { it.unpushed() })
            result.put("dirty", git.isDirty())
        }
        return result
    }

    /** Every linked idea repo this device has a checkout of. */
    private fun linkedClones(): List<GitRepo> =
        store.read()
            .mapNotNull { it.file.repo }
            .distinct()
            .map { linkedRepo(it) }
            .filter { it.cloned }

    // ---- reading -------------------------------------------------------

    @PluginMethod
    fun listIdeas(call: PluginCall) {
        background(call) {
            // Anything never read gets read now. After the first open this
            // costs nothing, and it means a board connected before there was
            // a cache — or an idea linked since — fills itself in rather than
            // waiting for someone to think of syncing.
            refreshLinkedIdeas(onlyMissing = true)
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

    /**
     * One tile as the web layer sees it.
     *
     * For an idea with a repository of its own, the board file supplies only
     * where it sits — rank, colour, the link — and the content comes from that
     * repository's checkout when there is one. Never from the network: a read
     * has to work on a train, and cloning is something the person asks for.
     */
    private fun tileJson(tile: BoardStore.Tile, withTodos: Boolean): JSObject {
        val repo = tile.file.repo
        val linked = repo?.let { linkedRepo(it) }
        // Where the idea actually is, best copy first: a checkout if this one
        // has been fetched to work on, otherwise the last IDEA.md read from
        // the repo, otherwise the board's reference — which carries the colour
        // and the link and nothing anyone wants to read.
        val content =
            if (linked?.cloned == true) {
                LinkedRepoStore(linked.dir).read()
            } else {
                repo?.let { linkedIdeas.load(it) }?.let { parseIdeaFile(it) }
            }
        val idea = content ?: tile.file
        val known = repo?.let { issues.load(it) } ?: emptyMap()

        val json = JSObject()
        json.put("slug", tile.slug)
        json.put("title", idea.title ?: tile.slug)
        json.put("status", idea.status ?: "idea")
        json.put("progress", idea.progress ?: 0)
        // Colour and rank are the board's, never the idea's own repo's.
        json.put("color", tile.file.color ?: BoardStore.DEFAULT_COLOR)
        json.put("rank", tile.file.rank)
        json.put("repo", repo)
        json.put("logo", logoFor(tile, linked, repo))
        json.put("notes", idea.notes)
        json.put("linked", repo != null)
        json.put("linkedCloned", linked?.cloned == true)
        json.put("unsynced", linked?.unpushed() ?: 0)
        if (withTodos) {
            val todos = JSArray()
            applyIssues(idea.todos, known).forEachIndexed { index, todo ->
                val issue = todo.issue?.let { known[it] }
                todos.put(
                    JSObject()
                        .put("index", index)
                        .put("text", todo.text)
                        .put("done", todo.done)
                        .put("issue", todo.issue)
                        .put("issueUrl", issue?.htmlUrl)
                        .put("labels", JSArray(issue?.labels.orEmpty().toTypedArray()))
                        .put("assignee", issue?.assignee)
                        .put("comments", issue?.comments ?: 0)
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
            boardRepo()?.commitAll("Add idea: ${tile.file.title}", author())
            tileJson(store.readIdea(tile.slug)!!, withTodos = true)
        }
    }

    /**
     * Overwrite one idea from what the page holds.
     *
     * Fields the caller leaves out keep the value already in the file, so a
     * page that only knows about the checkbox it just ticked does not have to
     * send the whole idea back to avoid erasing the rest of it.
     *
     * Where the idea goes depends on where it lives: into its own repository
     * when it has one and we have a checkout, into the board repo otherwise.
     * Writing an idea's content into the board would be creating the second
     * copy the reference layout exists to avoid.
     */
    @PluginMethod
    fun writeIdea(call: PluginCall) {
        val slug = call.getString("slug") ?: return call.reject("slug is required")
        background(call) {
            val tile = store.readIdea(slug)
                ?: throw IllegalArgumentException("No idea called $slug on this board")
            val linked = checkout(tile)
            val current = linked?.store?.read() ?: tile.file

            val submitted = call.getArray("todos", null)?.let { array ->
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
                title = call.getString("title") ?: current.title,
                notes = call.getString("notes") ?: current.notes,
                status = call.getString("status") ?: current.status,
                progress = call.getInt("progress") ?: current.progress,
                color = call.getString("color") ?: tile.file.color,
                rank = tile.file.rank,
                repo = tile.file.repo,
                todos = submitted ?: current.todos,
            )

            if (linked != null) {
                linked.store.write(updated)
                linked.git.commitAll("Update idea: ${updated.title}", author())
                // The colour is the board's to keep, so a change to it still
                // rewrites the board's own file.
                if (updated.color != tile.file.color) {
                    store.writeIdea(slug, tile.file.copy(color = updated.color))
                    boardRepo()?.commitAll("Recolour tile: ${updated.title}", author())
                }
                mirrorIssues(linked.repo, current.todos, updated.todos)
            } else {
                store.writeIdea(slug, updated)
                boardRepo()?.commitAll("Update idea: ${updated.title}", author())
            }
            tileJson(store.readIdea(slug)!!, withTodos = true)
        }
    }

    /** An idea's own repository, once this device has a checkout of it. */
    private data class Checkout(
        val repo: String,
        val git: GitRepo,
        val store: LinkedRepoStore,
    )

    private fun checkout(tile: BoardStore.Tile): Checkout? =
        tile.file.repo?.let { repo ->
            linkedRepo(repo).takeIf { it.cloned }?.let { Checkout(repo, it, LinkedRepoStore(it.dir)) }
        }

    /**
     * Push a ticked box or a retitled item back to the issue that owns it.
     *
     * Best-effort, exactly like the server: a failure leaves the board ahead of
     * GitHub, and the next refresh resolves it the other way, because the issue
     * always wins in the end.
     */
    private fun mirrorIssues(repo: String, before: List<ParsedTodo>, after: List<ParsedTodo>) {
        val token = token() ?: return
        issueEdits(before, after).forEach { todo ->
            GitHubApi.updateIssue(repo, todo.issue!!, todo.text, todo.done, token)
        }
    }

    @PluginMethod
    fun deleteIdea(call: PluginCall) {
        val slug = call.getString("slug") ?: return call.reject("slug is required")
        background(call) {
            val title = store.readIdea(slug)?.file?.title ?: slug
            store.delete(slug)
            // Only the tile goes. An idea with a repository of its own still
            // has one, and deleting somebody's repository because a board was
            // tidied up would be a startling thing for a board to do.
            boardRepo()?.commitAll("Remove idea: $title", author())
            JSObject().put("deleted", slug)
        }
    }

    @PluginMethod
    fun reorder(call: PluginCall) {
        val slugs = call.getArray("slugs") ?: return call.reject("slugs is required")
        background(call) {
            val order = (0 until slugs.length()).map { slugs.getString(it) }
            val rewritten = store.reorder(order)
            if (rewritten.isNotEmpty()) boardRepo()?.commitAll("Reorder board", author())
            JSObject().put("rewritten", JSArray(rewritten.toTypedArray()))
        }
    }

    // ---- syncing -------------------------------------------------------

    /**
     * Fetch, merge and push the board — and every idea repo this device holds.
     *
     * Syncing one and not the other would be the worst of both: a board that
     * says an idea changed, and an idea repo that never heard about it.
     */
    @PluginMethod
    fun sync(call: PluginCall) {
        background(call) {
            val credentials = credentials()
                ?: throw IllegalStateException("Sign in to GitHub before syncing")
            val board = boardRepo() ?: throw IllegalStateException("No board repo configured")
            val merged = mutableListOf<String>()
            merged += board.sync(credentials, author()).merged
            linkedClones().forEach { linked ->
                merged += linked.sync(credentials, author()).merged
                refreshIssues(linked.repo)
            }
            refreshLinkedIdeas()
            JSObject()
                .put("merged", JSArray(merged.toTypedArray()))
                .put("unsynced", board.unpushed() + linkedClones().sumOf { it.unpushed() })
        }
    }

    /**
     * Fetch an idea that lives in its own repository — cloning it the first time.
     *
     * This is what turns a reference on the board into the idea itself, so it
     * is also where the app first asks the network for anything on the person's
     * behalf. It is always a deliberate action, never a side effect of opening
     * a tile: an idea repo can be large, and a phone is often on a metered
     * connection.
     */
    @PluginMethod
    fun fetchLinked(call: PluginCall) {
        val slug = call.getString("slug") ?: return call.reject("slug is required")
        background(call) {
            val tile = store.readIdea(slug)
                ?: throw IllegalArgumentException("No idea called $slug on this board")
            val repo = tile.file.repo
                ?: throw IllegalStateException("This idea has no repository of its own")
            val credentials = credentials()
                ?: throw IllegalStateException("Sign in to GitHub first")
            val linked = linkedRepo(repo)
            if (!linked.cloned) linked.clone(credentials) else linked.sync(credentials, author())
            refreshIssues(repo)
            tileJson(store.readIdea(slug)!!, withTodos = true)
        }
    }

    // ---- the GitHub side ------------------------------------------------
    //
    // Three actions that have to create something on GitHub before the board
    // can point at it. Each is an explicit request, and each reports its
    // failure rather than swallowing it the way a background refresh does: an
    // action that silently did nothing is worse than an error.

    /**
     * Open an issue for a to-do and bind the two together.
     *
     * From then on the issue owns that item's text and whether it is done, and
     * the file just carries the reference. That is what gives the item a stable
     * identity: plain to-dos are matched between file and board by exact text,
     * so rewording one replaces it, where a promoted one can be reworded
     * freely.
     */
    @PluginMethod
    fun promoteTodo(call: PluginCall) {
        val slug = call.getString("slug") ?: return call.reject("slug is required")
        val index = call.getInt("index") ?: return call.reject("index is required")
        background(call) {
            val token = token() ?: throw IllegalStateException("Sign in to GitHub first")
            val (tile, content, writer) = editable(slug)
            val repo = tile.file.repo
                ?: throw IllegalStateException("This idea has no repository to open an issue in")
            val todo = content.todos.getOrNull(index)
                ?: throw IllegalArgumentException("No to-do at position $index")
            if (todo.issue != null) return@background tileJson(tile, withTodos = true)

            val issue = GitHubApi.createIssue(
                repo,
                todo.text,
                "Tracked on the IdeaBRD board under **${content.title ?: slug}**.",
                token,
            ) ?: throw IllegalStateException("GitHub refused to open the issue")

            val todos = content.todos.toMutableList()
            todos[index] = todo.copy(issue = issue.number)
            writer(content.copy(todos = todos), "Link todo to issue #${issue.number}")
            issues.save(repo, issues.load(repo).values + issue)
            tileJson(store.readIdea(slug)!!, withTodos = true)
        }
    }

    /** Adopt the repo's issues as to-dos — the direction the board never had. */
    @PluginMethod
    fun importIssues(call: PluginCall) {
        val slug = call.getString("slug") ?: return call.reject("slug is required")
        background(call) {
            val token = token() ?: throw IllegalStateException("Sign in to GitHub first")
            val (tile, content, writer) = editable(slug)
            val repo = tile.file.repo
                ?: throw IllegalStateException("This idea has no repository to import from")
            val found = GitHubApi.listIssues(repo, token)
            if (found.isNotEmpty()) issues.save(repo, found.values)
            // Closed issues are a repo's history; a board is for what is still
            // in flight, so only open ones are adopted.
            val merged = mergeImportedIssues(content.todos, found.values.filter { !it.closed })
            val added = merged.size - content.todos.size
            if (added > 0) writer(content.copy(todos = merged), "Import $added issue(s) as to-dos")
            JSObject()
                .put("imported", added)
                .put("idea", tileJson(store.readIdea(slug)!!, withTodos = true))
        }
    }

    /**
     * Give a note-only idea a repository of its own, and move it in.
     *
     * An idea held on a board has nowhere for anyone else to link: a board is
     * one person's, and a directory in it is not something a second person can
     * be given access to. Its own repository is what sharing means — so this
     * creates one, pushes the idea into it, and leaves the board holding a
     * reference to where it now lives.
     */
    @PluginMethod
    fun createRepoForIdea(call: PluginCall) {
        val slug = call.getString("slug") ?: return call.reject("slug is required")
        val name = call.getString("name") ?: return call.reject("name is required")
        background(call) {
            val token = token() ?: throw IllegalStateException("Sign in to GitHub first")
            val credentials = credentials()!!
            val tile = store.readIdea(slug)
                ?: throw IllegalArgumentException("No idea called $slug on this board")
            if (tile.file.repo != null) {
                throw IllegalStateException("This idea already lives in ${tile.file.repo}")
            }
            val full = GitHubApi.createRepo(
                name,
                call.getString("org"),
                call.getBoolean("private", true) ?: true,
                tile.file.title ?: name,
                token,
            ) ?: throw IllegalStateException("GitHub refused to create $name")

            // The idea moves in: its own repo gets the content, and the board
            // keeps only where it is. Push before rewriting the board, so a
            // failure leaves the board pointing at nothing rather than pointing
            // at a repo that hasn't got the idea.
            val linked = linkedRepo(full)
            linked.clone(credentials)
            LinkedRepoStore(linked.dir).write(tile.file)
            linked.commitAll("Track idea in IDEA.md", author())
            linked.sync(credentials, author())

            store.writeIdea(slug, tile.file.copy(repo = full))
            boardRepo()?.commitAll("Move idea into ${full}", author())
            refreshIssues(full)
            tileJson(store.readIdea(slug)!!, withTodos = true)
        }
    }

    /**
     * Point a held idea at a repository that already exists.
     *
     * Two cases, and the difference matters. If that repo already has an
     * IDEA.md then it already holds an idea, and linking adopts it: the board
     * keeps only where it is, and the repo's copy is the one that counts.
     *
     * If it has none, linking would mean *writing* one into somebody's
     * repository, which is the one thing the app never does unprompted — so
     * the first call changes nothing and answers `needsSeed`, and only a second
     * call with `seed` set goes ahead. The board entry is rewritten last, after
     * the idea is safely in the repo: the opposite order would leave the board
     * pointing at a repository that hasn't got it.
     */
    @PluginMethod
    fun linkRepo(call: PluginCall) {
        val slug = call.getString("slug") ?: return call.reject("slug is required")
        val requested = call.getString("repo") ?: return call.reject("repo is required")
        val seed = call.getBoolean("seed", false) ?: false
        background(call) {
            val repo = try {
                normalizeRepo(requested)
            } catch (e: InvalidRepoRef) {
                throw IllegalArgumentException("Not a repository: $requested")
            }
            val credentials = credentials()
                ?: throw IllegalStateException("Sign in to GitHub first")
            val tile = store.readIdea(slug)
                ?: throw IllegalArgumentException("No idea called $slug on this board")
            tile.file.repo?.let {
                throw IllegalStateException("This idea already lives in $it")
            }

            val linked = linkedRepo(repo)
            if (!linked.cloned) linked.clone(credentials)
            val linkedStore = LinkedRepoStore(linked.dir)

            if (!linkedStore.exists()) {
                if (!seed) {
                    return@background JSObject()
                        .put("needsSeed", true)
                        .put("repo", repo)
                }
                linkedStore.write(tile.file)
                linked.commitAll("Track idea in IDEA.md", author())
                linked.sync(credentials, author())
            }

            store.writeIdea(slug, tile.file.copy(repo = repo))
            boardRepo()?.commitAll("Move idea into $repo", author())
            refreshIssues(repo)
            JSObject()
                .put("needsSeed", false)
                .put("idea", tileJson(store.readIdea(slug)!!, withTodos = true))
        }
    }

    /**
     * Where an idea's content is, and how to write it back.
     *
     * An idea with a repository of its own is edited there; one held on the
     * board is edited in the board. Both callers below need the same three
     * things, and getting the destination wrong would create the second copy
     * the reference layout exists to avoid.
     */
    private fun editable(
        slug: String,
    ): Triple<BoardStore.Tile, ParsedIdeaFile, (ParsedIdeaFile, String) -> Unit> {
        val tile = store.readIdea(slug)
            ?: throw IllegalArgumentException("No idea called $slug on this board")
        val linked = checkout(tile)
        if (linked != null) {
            val content = linked.store.read()
                ?: throw IllegalStateException("${linked.repo} has no IDEA.md yet")
            return Triple(tile, content) { updated, message ->
                linked.store.write(updated)
                linked.git.commitAll(message, author())
            }
        }
        if (tile.file.repo != null) {
            throw IllegalStateException("Fetch ${tile.file.repo} before editing this idea")
        }
        return Triple(tile, tile.file) { updated, message ->
            store.writeIdea(slug, updated)
            boardRepo()?.commitAll(message, author())
        }
    }

    /** Update the cached issues for a repo. Silent on failure — it is a cache. */
    /**
     * Read the IDEA.md of every idea that lives in its own repository.
     *
     * One small request each, and failures are silent on purpose: a board that
     * shows what it last knew beats a board that refuses to open because one
     * repository was renamed or the train went into a tunnel.
     */
    private fun refreshLinkedIdeas(onlyMissing: Boolean = false) {
        val token = token() ?: return
        store.read()
            .mapNotNull { it.file.repo }
            .distinct()
            .filter { !onlyMissing || linkedIdeas.load(it) == null }
            .forEach { repo ->
                GitHubApi.readIdeaFile(repo, token)?.let { linkedIdeas.save(repo, it) }
                if (linkedIdeas.logo(repo) == null) {
                    GitHubApi.readIdeaLogo(repo, token)?.let { (name, bytes) ->
                        linkedIdeas.saveLogo(repo, name, bytes)
                    }
                }
            }
    }

    private fun refreshIssues(repo: String) {
        val token = token() ?: return
        val found: Map<Int, IssueInfo> =
            try {
                GitHubApi.listIssues(repo, token)
            } catch (_: Exception) {
                return
            }
        if (found.isNotEmpty()) issues.save(repo, found.values)
    }
}
