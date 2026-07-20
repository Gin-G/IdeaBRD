import type {
	Collaborator,
	GitHubRepo,
	Idea,
	IdeaSummary,
	Identity,
	Providers,
	Role,
	Todo,
	User
} from './types';

// Same-origin in production (nginx proxies /api). Override with VITE_API_BASE if needed.
const BASE = import.meta.env.VITE_API_BASE ?? '';

export class ApiError extends Error {
	status: number;
	constructor(status: number, message: string) {
		super(message);
		this.status = status;
	}
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
	const res = await fetch(`${BASE}${path}`, {
		credentials: 'include',
		headers: { 'Content-Type': 'application/json', ...(init.headers ?? {}) },
		...init
	});

	if (res.status === 401) {
		// Not logged in: bounce the browser to the backend login flow.
		redirectToLogin();
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

export const api = {
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

	github: (ideaId: number) => request<GitHubRepo>(`/api/ideas/${ideaId}/github`),

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
