import type {
	Board,
	BoardOwners,
	Idea,
	IdeaSummary,
	Identity,
	ImportedIssues,
	Providers,
	PublishResult,
	Status,
	Todo,
	User
} from '$lib/types';
import { Auth, Board as BoardPlugin, type NativeTile } from './plugins';

/**
 * The board, read from git instead of from an API.
 *
 * The Android app runs the same pages as the browser build, so rather than
 * teaching every component about two worlds, this implements the same surface
 * the HTTP client exposes and is swapped in for it (see `$lib/api`). A tile
 * doesn't know whether its notes came from Postgres or from a checkout, and it
 * shouldn't have to.
 *
 * Two things are genuinely different and worth understanding:
 *
 * **Ideas are slugs, not numbers.** Git has no autoincrement, and inventing one
 * would mean keeping a manifest — the one file every device is guaranteed to
 * conflict on. Ids are therefore hashed from the slug: stable across restarts,
 * stable across devices, and never written anywhere.
 *
 * **Some things are simply not here.** Collaborators, invitations and issue
 * promotion are server features that assume an account system. Rather than
 * failing obscurely, they say so: on a git-only board, sharing an idea means
 * giving it a repository and adding people to that.
 */

const NOT_ON_DEVICE =
	'Not available on the git-only board. Sharing here means giving the idea its ' +
	'own repository and adding people to it on GitHub.';

function unavailable(): never {
	throw new Error(NOT_ON_DEVICE);
}

/**
 * A stable positive integer for a slug (FNV-1a, folded to 31 bits).
 *
 * Deterministic on purpose: the page routes by id, so a number that changed on
 * every launch would break every link the moment the app restarted.
 */
function idFor(slug: string): number {
	let hash = 0x811c9dc5;
	for (let i = 0; i < slug.length; i++) {
		hash ^= slug.charCodeAt(i);
		hash = Math.imul(hash, 0x01000193);
	}
	return (hash >>> 1) || 1;
}

/** Slugs seen so far, so an id coming back from the page can be resolved. */
const slugs = new Map<number, string>();

function remember(slug: string): number {
	const id = idFor(slug);
	slugs.set(id, slug);
	return id;
}

async function slugFor(id: number): Promise<string> {
	const known = slugs.get(id);
	if (known) return known;
	// A cold start straight into /ideas/123: nothing has been listed yet.
	(await BoardPlugin.listIdeas()).ideas.forEach((tile) => remember(tile.slug));
	const found = slugs.get(id);
	if (!found) throw new Error('That idea is not on this board');
	return found;
}

/** Todo ids are positions within an idea; the file has no other identity. */
function todoId(slug: string, index: number): number {
	return idFor(`${slug}#${index}`);
}

const todoLocations = new Map<number, { slug: string; index: number }>();

function toTodos(tile: NativeTile): Todo[] {
	return (tile.todos ?? []).map((todo) => {
		const id = todoId(tile.slug, todo.index);
		todoLocations.set(id, { slug: tile.slug, index: todo.index });
		return {
			id,
			text: todo.text,
			done: todo.done,
			position: todo.index,
			github_issue_number: todo.issue,
			github_issue_url: todo.issueUrl,
			// As fresh as the last fetch: the issue is GitHub's, and this is
			// what it last said.
			github_issue_labels: todo.labels.length ? todo.labels : null,
			github_issue_assignee: todo.assignee,
			github_issue_comments: todo.issue !== null ? todo.comments : null
		};
	});
}

function toSummary(tile: NativeTile): IdeaSummary {
	return {
		id: remember(tile.slug),
		title: tile.title ?? tile.slug,
		status: (tile.status as Status) ?? 'idea',
		progress: tile.progress,
		color: tile.color,
		logo_url: tile.logo,
		github_repo: tile.repo,
		position: 0,
		role: 'owner',
		shared: false,
		has_collaborators: false,
		owner: null
	};
}

function toIdea(tile: NativeTile): Idea {
	const now = new Date().toISOString();
	return {
		...toSummary(tile),
		notes: tile.notes,
		created_at: now,
		updated_at: now,
		todos: toTodos(tile),
		git_synced_at: null,
		git_sync_error: null,
		// An idea that lives in its own repo has nothing here until that repo
		// is cloned — the board only records where it is.
		git_file_missing: tile.linked && !tile.linkedCloned
	};
}

/** Write a to-do list back through the idea that owns it. */
async function writeTodos(slug: string, todos: Todo[]): Promise<NativeTile> {
	return BoardPlugin.writeIdea({
		slug,
		// Only the three fields the file holds. The rest is the issue's, and
		// the plugin pushes a ticked box back to it.
		todos: todos.map((t) => ({
			index: t.position,
			text: t.text,
			done: t.done,
			issue: t.github_issue_number,
			issueUrl: null,
			labels: [],
			assignee: null,
			comments: 0
		}))
	});
}

async function readTodos(slug: string): Promise<Todo[]> {
	return toTodos(await BoardPlugin.readIdea({ slug }));
}

export const nativeApi = {
	providers: async (): Promise<Providers> => ({ google: false, github: true, dev: false }),

	me: async (): Promise<User> => {
		const status = await Auth.status();
		if (!status.authenticated) {
			// Same shape the HTTP client uses for "not signed in", so the layout
			// shows its sign-in screen rather than an error.
			throw Object.assign(new Error('Not authenticated'), { status: 401 });
		}
		return {
			id: 1,
			email: status.login ? `${status.login}@users.noreply.github.com` : 'local',
			name: status.login,
			avatar_url: status.login ? `https://github.com/${status.login}.png` : null
		};
	},

	identities: async (): Promise<Identity[]> => {
		const status = await Auth.status();
		return status.authenticated
			? [
					{
						provider: 'github',
						email: null,
						github_login: status.login,
						has_repo_token: true
					}
				]
			: [];
	},

	unlinkIdentity: async () => Auth.signOut(),
	logout: async () => {
		await Auth.signOut();
		return { ok: true };
	},

	listIdeas: async (): Promise<IdeaSummary[]> => {
		const { ideas } = await BoardPlugin.listIdeas();
		// Position is the order the files already sort in — by rank, which is
		// what the board's own ordering key means.
		return ideas.map((tile, index) => ({ ...toSummary(tile), position: index }));
	},

	getIdea: async (id: number): Promise<Idea> =>
		toIdea(await BoardPlugin.readIdea({ slug: await slugFor(id) })),

	createIdea: async (data: Partial<Idea>): Promise<Idea> =>
		toIdea(
			await BoardPlugin.createIdea({
				title: data.title ?? 'Untitled',
				color: data.color
			})
		),

	updateIdea: async (id: number, data: Partial<Idea>): Promise<Idea> => {
		const slug = await slugFor(id);
		return toIdea(
			await BoardPlugin.writeIdea({
				slug,
				title: data.title,
				notes: data.notes,
				status: data.status,
				progress: data.progress,
				color: data.color,
				repo: data.github_repo
			})
		);
	},

	deleteIdea: async (id: number): Promise<void> => {
		await BoardPlugin.deleteIdea({ slug: await slugFor(id) });
	},

	reorderIdeas: async (items: { id: number; position: number }[]): Promise<void> => {
		const ordered = [...items].sort((a, b) => a.position - b.position);
		const wanted = await Promise.all(ordered.map((item) => slugFor(item.id)));
		await BoardPlugin.reorder({ slugs: wanted });
	},

	createTodo: async (ideaId: number, text: string): Promise<Todo> => {
		const slug = await slugFor(ideaId);
		const todos = await readTodos(slug);
		const next: Todo[] = [
			...todos,
			{
				id: todoId(slug, todos.length),
				text,
				done: false,
				position: todos.length,
				github_issue_number: null,
				github_issue_url: null,
				github_issue_labels: null,
				github_issue_assignee: null,
				github_issue_comments: null
			}
		];
		const written = toTodos(await writeTodos(slug, next));
		return written[written.length - 1];
	},

	updateTodo: async (id: number, data: Partial<Todo>): Promise<Todo> => {
		const at = todoLocations.get(id);
		if (!at) throw new Error('That to-do is no longer on this board');
		const todos = await readTodos(at.slug);
		todos[at.index] = { ...todos[at.index], ...data };
		return toTodos(await writeTodos(at.slug, todos))[at.index];
	},

	deleteTodo: async (id: number): Promise<void> => {
		const at = todoLocations.get(id);
		if (!at) return;
		const todos = await readTodos(at.slug);
		todos.splice(at.index, 1);
		// Positions are the identity, so renumber before writing.
		await writeTodos(
			at.slug,
			todos.map((todo, position) => ({ ...todo, position }))
		);
	},

	/** Open an issue for a to-do. The click is the opt-in, as on the server. */
	promoteTodo: async (id: number): Promise<Todo> => {
		const at = todoLocations.get(id);
		if (!at) throw new Error('That to-do is no longer on this board');
		const todos = toTodos(await BoardPlugin.promoteTodo({ slug: at.slug, index: at.index }));
		return todos[at.index];
	},

	importIssues: async (ideaId: number): Promise<ImportedIssues> => {
		const slug = await slugFor(ideaId);
		const result = await BoardPlugin.importIssues({ slug });
		return { imported: result.imported, todos: toTodos(result.idea) };
	},

	boardOwners: async (): Promise<BoardOwners> => {
		const found = await Auth.owners();
		// A short list means the token predates the read:org scope, not that
		// the account has no organisations.
		return { owners: found.owners, orgs_visible: found.owners.length > 1 };
	},

	giveIdeaRepo: async (
		ideaId: number,
		name: string,
		org: string | null,
		isPrivate: boolean
	): Promise<Idea> =>
		toIdea(
			await BoardPlugin.createRepoForIdea({
				slug: await slugFor(ideaId),
				name,
				org,
				private: isPrivate
			})
		),

	/** Fetch the repository an idea lives in — the tile is a pointer until then. */
	syncIdea: async (id: number): Promise<Idea> =>
		toIdea(await BoardPlugin.fetchLinked({ slug: await slugFor(id) })),
	initIdeaSync: async (id: number): Promise<Idea> =>
		toIdea(await BoardPlugin.fetchLinked({ slug: await slugFor(id) })),

	board: async (): Promise<Board> => {
		const status = await BoardPlugin.status();
		return {
			board_repo: status.repo,
			board_branch: status.branch,
			board_commit_sha: null,
			board_published_at: null,
			sync: {
				pending: (status.unsynced ?? 0) > 0,
				last_error: null,
				last_commit_sha: null
			}
		};
	},

	setBoardRepo: async (repo: string | null): Promise<Board> => {
		if (!repo) throw new Error('The app needs a board repo to read from');
		await BoardPlugin.configure({ repo });
		return nativeApi.board();
	},

	/** Publishing on the device is syncing: commit, merge, push. */
	publishBoard: async (): Promise<PublishResult> => {
		const result = await BoardPlugin.sync();
		return {
			committed: true,
			commit_sha: null,
			written: result.merged,
			removed: [],
			needs_opt_in: false,
			moved: false,
			head_sha: null,
			error: null
		};
	},

	boardStatus: async (): Promise<PublishResult> => {
		const status = await BoardPlugin.status();
		return {
			committed: false,
			commit_sha: null,
			written: [],
			removed: [],
			needs_opt_in: false,
			moved: false,
			head_sha: null,
			error: (status.unsynced ?? 0) > 0 ? `${status.unsynced} commits not pushed yet` : null
		};
	},

	// Server features with no meaning on a git-only board.
	github: unavailable,
	pulls: unavailable,
	uploadLogo: unavailable,
	deleteLogo: unavailable,
	initBoard: unavailable,
	reconcileBoard: unavailable,
	listCollaborators: unavailable,
	invite: unavailable,
	removeCollaborator: unavailable,
	cancelInvite: unavailable
};
