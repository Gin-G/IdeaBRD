import type {
	Board,
	BoardOwners,
	Collaborator,
	GitHubRepo,
	Idea,
	IdeaSummary,
	Identity,
	ImportedIssues,
	Providers,
	PublishResult,
	PullRequest,
	Reconcile,
	Role,
	Todo,
	User
} from './types';

import { isNative } from './native/plugins';
import { nativeApi } from './native/api';

// Same-origin in production (nginx proxies /api). Override with VITE_API_BASE if needed.
const BASE = import.meta.env.VITE_API_BASE ?? '';

/**
 * Whether this tab has already been sent to sign in and come back.
 *
 * Kept in sessionStorage rather than memory: the redirect reloads the page, so
 * anything in memory is gone by the time the answer is needed. Cleared once a
 * request succeeds, so the next expiry redirects again.
 */
const SIGN_IN_TRIED = 'ideabrd.signInTried';

function signInAlreadyTried(): boolean {
	try {
		return sessionStorage.getItem(SIGN_IN_TRIED) === '1';
	} catch {
		// Storage disabled: better to redirect once too often than to refuse
		// to sign somebody in at all.
		return false;
	}
}

function markSignInTried() {
	try {
		sessionStorage.setItem(SIGN_IN_TRIED, '1');
	} catch {
		/* see above */
	}
}

function clearSignInTried() {
	try {
		sessionStorage.removeItem(SIGN_IN_TRIED);
	} catch {
		/* see above */
	}
}

export class ApiError extends Error {
	status: number;
	constructor(status: number, message: string) {
		super(message);
		this.status = status;
	}
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
	// A FormData body must set its own multipart boundary, so don't force JSON on it.
	const isForm = init.body instanceof FormData;
	const res = await fetch(`${BASE}${path}`, {
		credentials: 'include',
		headers: {
			...(isForm ? {} : { 'Content-Type': 'application/json' }),
			...(init.headers ?? {})
		},
		...init
	});

	if (res.status === 401) {
		// Sessions live in the server's memory, so a restart signs everyone
		// out. Bouncing through GitHub costs a redirect and no interaction —
		// the app is already authorised — which is what makes that acceptable.
		// Once, though: if the round trip comes back still unauthenticated the
		// problem is the sign-in itself, and a page that redirects for ever
		// tells nobody anything.
		if (!signInAlreadyTried()) {
			markSignInTried();
			redirectToLogin();
		}
		throw new ApiError(401, 'Not authenticated');
	}
	if (!res.ok) {
		let detail = res.statusText;
		try {
			detail = (await res.json()).detail ?? detail;
		} catch {
			/* ignore */
		}
		throw new ApiError(res.status, detail);
	}
	clearSignInTried();
	if (res.status === 204) return undefined as T;
	return res.json() as Promise<T>;
}

export function redirectToLogin() {
	window.location.href = `${BASE}/api/auth/login`;
}

export function redirectToGithubLogin() {
	window.location.href = `${BASE}/api/auth/github/login`;
}

/** Link a GitHub account to the currently logged-in user. */
export function connectGithub() {
	window.location.href = `${BASE}/api/auth/github/login?connect=1`;
}

const httpApi = {
	providers: () => request<Providers>('/api/auth/providers'),
	me: () => request<User>('/api/auth/me'),
	identities: () => request<Identity[]>('/api/auth/identities'),
	unlinkIdentity: (provider: string) =>
		request<void>(`/api/auth/identities/${provider}`, { method: 'DELETE' }),
	logout: () => request<{ ok: boolean }>('/api/auth/logout', { method: 'POST' }),

	listIdeas: () => request<IdeaSummary[]>('/api/ideas'),
	getIdea: (id: number) => request<Idea>(`/api/ideas/${id}`),
	syncIdea: (id: number) => request<Idea>(`/api/ideas/${id}/sync`, { method: 'POST' }),
	/** User-confirmed opt-in: commit IDEA.md to the linked repo to start tracking. */
	initIdeaSync: (id: number) =>
		request<Idea>(`/api/ideas/${id}/sync?init=true`, { method: 'POST' }),
	createIdea: (data: Partial<Idea>) =>
		request<Idea>('/api/ideas', { method: 'POST', body: JSON.stringify(data) }),
	updateIdea: (id: number, data: Partial<Idea>) =>
		request<Idea>(`/api/ideas/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
	deleteIdea: (id: number) =>
		request<void>(`/api/ideas/${id}`, { method: 'DELETE' }),
	reorderIdeas: (items: { id: number; position: number }[]) =>
		request<void>('/api/ideas/reorder', { method: 'PATCH', body: JSON.stringify(items) }),

	createTodo: (ideaId: number, text: string) =>
		request<Todo>(`/api/ideas/${ideaId}/todos`, {
			method: 'POST',
			body: JSON.stringify({ text })
		}),
	updateTodo: (todoId: number, data: Partial<Todo>) =>
		request<Todo>(`/api/todos/${todoId}`, { method: 'PATCH', body: JSON.stringify(data) }),
	deleteTodo: (todoId: number) =>
		request<void>(`/api/todos/${todoId}`, { method: 'DELETE' }),
	/** Open a GitHub issue for this to-do; the issue then owns its text and state. */
	promoteTodo: (todoId: number) =>
		request<Todo>(`/api/todos/${todoId}/issue`, { method: 'POST' }),
	/** Adopt the repo's issues as to-dos — the opposite direction to promoting. */
	importIssues: (ideaId: number, state: 'open' | 'closed' | 'all' = 'open') =>
		request<ImportedIssues>(`/api/ideas/${ideaId}/todos/import?state=${state}`, {
			method: 'POST'
		}),

	github: (ideaId: number) => request<GitHubRepo>(`/api/ideas/${ideaId}/github`),
	pulls: (ideaId: number) => request<PullRequest[]>(`/api/ideas/${ideaId}/pulls`),
	/** Create a repo for a note-only idea and move the idea into it. */
	giveIdeaRepo: (ideaId: number, name: string, org: string | null, isPrivate: boolean) =>
		request<Idea>(`/api/ideas/${ideaId}/repo`, {
			method: 'POST',
			body: JSON.stringify({ name, org, private: isPrivate })
		}),

	/** Upload a tile logo. No Content-Type header: the browser sets the multipart boundary. */
	uploadLogo: (ideaId: number, file: File) => {
		const body = new FormData();
		body.append('file', file);
		return request<Idea>(`/api/ideas/${ideaId}/logo`, { method: 'PUT', body });
	},
	deleteLogo: (ideaId: number) =>
		request<Idea>(`/api/ideas/${ideaId}/logo`, { method: 'DELETE' }),

	board: () => request<Board>('/api/board'),
	boardOwners: () => request<BoardOwners>('/api/board/owners'),
	/** Create a fresh repo for this board and publish into it. */
	initBoard: (name: string, org: string | null, isPrivate: boolean) =>
		request<{ board: Board; publish: PublishResult }>('/api/board/init', {
			method: 'POST',
			body: JSON.stringify({ name, org, private: isPrivate })
		}),
	setBoardRepo: (repo: string | null) =>
		request<Board>('/api/board', { method: 'PUT', body: JSON.stringify({ board_repo: repo }) }),
	/** What a publish would change, without changing anything. */
	boardStatus: () => request<PublishResult>('/api/board/status'),
	/** Write the board to its repo. optIn accepts a repo that holds other files;
	 *  force accepts one that has moved since the last publish. */
	publishBoard: (optIn = false, force = false) =>
		request<PublishResult>(`/api/board/publish?opt_in=${optIn}&force=${force}`, {
			method: 'POST'
		}),
	/** Every idea, as the database and the repo each have it. Read-only. */
	reconcileBoard: () => request<Reconcile>('/api/board/reconcile'),

	listCollaborators: (ideaId: number) =>
		request<Collaborator[]>(`/api/ideas/${ideaId}/collaborators`),
	invite: (ideaId: number, email: string, role: Role) =>
		request<Collaborator>(`/api/ideas/${ideaId}/collaborators`, {
			method: 'POST',
			body: JSON.stringify({ email, role })
		}),
	removeCollaborator: (ideaId: number, userId: number) =>
		request<void>(`/api/ideas/${ideaId}/collaborators/${userId}`, { method: 'DELETE' }),
	cancelInvite: (ideaId: number, inviteId: number) =>
		request<void>(`/api/ideas/${ideaId}/invitations/${inviteId}`, { method: 'DELETE' })
};

/**
 * The board, from wherever this build reads it.
 *
 * In a browser that is the API. Inside the Android app there is no server at
 * all: the board is a git checkout on the device, and `nativeApi` implements
 * this same surface over it. Components call `api` either way and never find
 * out which — the alternative is every page carrying two code paths for the
 * rest of its life.
 */
export const api: typeof httpApi = isNative()
	? (nativeApi as unknown as typeof httpApi)
	: httpApi;

export { httpApi };
