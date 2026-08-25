import { Capacitor, registerPlugin } from '@capacitor/core';

/**
 * The two native plugins, and the one question that decides which board the app
 * is looking at: is this running inside the Android app, or in a browser?
 *
 * In a browser the board comes from the API and the server owns everything. On
 * the device there is no server — the board is a git checkout in the app's own
 * storage, and these plugins are how the page reaches it.
 */

export interface DeviceCode {
	deviceCode: string;
	userCode: string;
	verificationUri: string;
	interval: number;
	expiresIn: number;
}

export interface AuthStatus {
	authenticated: boolean;
	login: string | null;
	clientIdConfigured?: boolean;
}

export interface AuthPlugin {
	status(): Promise<AuthStatus>;
	/** Accounts a repository could be created under: the user, plus their orgs. */
	owners(): Promise<{ owners: { login: string; kind: 'user' | 'org' }[] }>;
	/** Ask GitHub for a code for the person to type. Nothing is authorised yet. */
	start(options?: { clientId?: string }): Promise<DeviceCode>;
	/** Resolves once they have authorised it; the token stays on the native side. */
	poll(options: {
		deviceCode: string;
		interval: number;
		expiresIn: number;
		clientId?: string;
	}): Promise<AuthStatus>;
	signOut(): Promise<void>;
}

/** A to-do, plus whatever the issue behind it last said. */
export interface NativeTodo {
	/** Position in the file — the only identity a to-do has in git. */
	index: number;
	text: string;
	done: boolean;
	issue: number | null;
	issueUrl: string | null;
	labels: string[];
	assignee: string | null;
	comments: number;
}

/** One idea, as the files say it. Ids are a web idea; git has slugs. */
export interface NativeTile {
	slug: string;
	title: string | null;
	status: string;
	progress: number;
	color: string;
	rank: string | null;
	repo: string | null;
	logo: string | null;
	notes: string;
	/** True when the idea lives in a repository of its own. */
	linked: boolean;
	/** ...and true once this device has a checkout of it. */
	linkedCloned: boolean;
	/** Commits in that checkout the remote hasn't seen. */
	unsynced: number;
	todos?: NativeTodo[];
}

export interface BoardStatus {
	repo: string | null;
	branch: string;
	cloned: boolean;
	authenticated: boolean;
	login: string | null;
	/** Commits made here that the remote hasn't seen. */
	unsynced?: number;
	dirty?: boolean;
}

export interface BoardPlugin {
	configure(options: { repo: string; branch?: string }): Promise<BoardStatus>;
	status(): Promise<BoardStatus>;
	listIdeas(): Promise<{ ideas: NativeTile[] }>;
	readIdea(options: { slug: string }): Promise<NativeTile>;
	createIdea(options: { title: string; color?: string }): Promise<NativeTile>;
	writeIdea(options: Partial<NativeTile> & { slug: string }): Promise<NativeTile>;
	deleteIdea(options: { slug: string }): Promise<{ deleted: string }>;
	reorder(options: { slugs: string[] }): Promise<{ rewritten: string[] }>;
	/** Fetch, merge by meaning, push — the board and every idea repo it holds. */
	sync(): Promise<{ merged: string[]; unsynced: number }>;
	/** Clone or pull the repository an idea lives in, and refresh its issues. */
	fetchLinked(options: { slug: string }): Promise<NativeTile>;
	/** Open an issue for one to-do; the issue then owns its text and state. */
	promoteTodo(options: { slug: string; index: number }): Promise<NativeTile>;
	/** Adopt the repo's open issues as to-dos. */
	importIssues(options: { slug: string }): Promise<{ imported: number; idea: NativeTile }>;
	/** Create a repository for a held idea and move the idea into it. */
	createRepoForIdea(options: {
		slug: string;
		name: string;
		org?: string | null;
		private?: boolean;
	}): Promise<NativeTile>;
	/**
	 * Point a held idea at a repository that already exists.
	 *
	 * Answers `needsSeed` and changes nothing when that repo has no IDEA.md:
	 * writing one into somebody's repository is never done unprompted.
	 */
	linkRepo(options: {
		slug: string;
		repo: string;
		seed?: boolean;
	}): Promise<{ needsSeed: boolean; repo?: string; idea?: NativeTile }>;
}

export const Auth = registerPlugin<AuthPlugin>('Auth');
export const Board = registerPlugin<BoardPlugin>('Board');

/** True inside the Android app, false in any browser. */
export function isNative(): boolean {
	return Capacitor.isNativePlatform();
}
