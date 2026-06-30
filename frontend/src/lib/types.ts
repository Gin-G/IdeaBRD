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
