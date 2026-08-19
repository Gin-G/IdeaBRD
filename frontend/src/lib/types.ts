export type Status = 'idea' | 'active' | 'paused' | 'done';
export type Role = 'owner' | 'editor' | 'viewer';

export interface User {
	id: number;
	email: string;
	name: string | null;
	avatar_url: string | null;
}

export interface Providers {
	google: boolean;
	github: boolean;
	dev: boolean;
}

export interface Identity {
	provider: 'google' | 'github';
	email: string | null;
	github_login: string | null;
	has_repo_token: boolean;
}

export interface OwnerInfo {
	name: string | null;
	email: string;
	avatar_url: string | null;
}

export interface Collaborator {
	status: 'active' | 'pending';
	role: Role;
	email: string;
	user_id: number | null;
	name: string | null;
	avatar_url: string | null;
	invite_id: number | null;
	is_owner: boolean;
}

export interface Todo {
	id: number;
	text: string;
	done: boolean;
	position: number;
	/** Issue backing this to-do, once promoted. While set, the issue owns its text and state. */
	github_issue_number: number | null;
	github_issue_url: string | null;
}

export interface IdeaSummary {
	id: number;
	title: string;
	status: Status;
	progress: number;
	color: string;
	logo_url: string | null;
	github_repo: string | null;
	position: number;
	role: Role;
	shared: boolean;
	has_collaborators: boolean;
	owner: OwnerInfo | null;
}

export interface Idea extends IdeaSummary {
	notes: string;
	created_at: string;
	updated_at: string;
	todos: Todo[];
	role: Role;
	owner: OwnerInfo | null;
	/** Last successful IDEA.md sync with the linked repo (git is the source of truth). */
	git_synced_at: string | null;
	/** Error from the most recent sync attempt, if it failed. */
	git_sync_error: string | null;
	/** True when the linked repo has no IDEA.md yet — tracking awaits the user's opt-in. */
	git_file_missing: boolean;
}

export interface GitHubRepo {
	full_name: string;
	html_url: string;
	description: string | null;
	stars: number;
	open_issues: number;
	forks: number;
	language: string | null;
	default_branch: string;
	pushed_at: string | null;
	last_commit_message: string | null;
}

/** Where a board is published as files, and what happened last time. */
export interface Board {
	board_repo: string | null;
	board_branch: string | null;
	board_commit_sha: string | null;
	board_published_at: string | null;
}

export interface BoardOwner {
	login: string;
	kind: 'user' | 'org';
}

export interface BoardOwners {
	owners: BoardOwner[];
	/** False when the GitHub login predates the read:org scope. */
	orgs_visible: boolean;
}

export interface PublishResult {
	committed: boolean;
	commit_sha: string | null;
	written: string[];
	removed: string[];
	/** The repo holds files but isn't a board yet; publishing needs opting in. */
	needs_opt_in: boolean;
	error: string | null;
}

export const STATUSES: { value: Status; label: string }[] = [
	{ value: 'idea', label: 'Idea' },
	{ value: 'active', label: 'Active' },
	{ value: 'paused', label: 'Paused' },
	{ value: 'done', label: 'Done' }
];

export const STATUS_STYLES: Record<Status, string> = {
	idea: 'bg-sky-500/15 text-sky-300 ring-1 ring-sky-500/30',
	active: 'bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30',
	paused: 'bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30',
	done: 'bg-violet-500/15 text-violet-300 ring-1 ring-violet-500/30'
};
