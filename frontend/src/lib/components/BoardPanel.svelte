<script lang="ts">
	import { onMount } from 'svelte';
	import { api, connectGithub, ApiError } from '$lib/api';
	import type { Board, BoardOwner, PublishResult } from '$lib/types';

	let { onclose, oninit }: { onclose: () => void; oninit?: () => void } = $props();

	let board = $state<Board | null>(null);
	let owners = $state<BoardOwner[]>([]);
	let orgsVisible = $state(true);
	let loading = $state(true);
	let busy = $state(false);
	let error = $state('');
	let result = $state<PublishResult | null>(null);
	// What a publish would change right now. Null while unknown.
	let pending = $state<PublishResult | null>(null);
	let checking = $state(false);

	// Creation form. The board is private by default: it is someone's notes.
	let name = $state('ideabrd-board');
	let owner = $state('');
	let isPrivate = $state(true);
	let linkExisting = $state('');
	let mode = $state<'create' | 'link'>('create');

	onMount(load);

	async function load() {
		loading = true;
		error = '';
		try {
			board = await api.board();
			if (board.board_repo) {
				checkPending();
			}
			if (!board.board_repo) {
				const found = await api.boardOwners();
				owners = found.owners;
				orgsVisible = found.orgs_visible;
				owner = owners[0]?.login ?? '';
			}
		} catch (e) {
			// No GitHub account yet is a prompt, not a failure.
			error = e instanceof ApiError ? e.message : 'Could not load board settings';
		} finally {
			loading = false;
		}
	}

	/** Ask the repo what is out of date. Never fatal: it is a nicety, not the board. */
	async function checkPending() {
		checking = true;
		try {
			pending = await api.boardStatus();
		} catch {
			pending = null;
		} finally {
			checking = false;
		}
	}

	async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
		busy = true;
		error = '';
		try {
			return await fn();
		} catch (e) {
			error = e instanceof ApiError ? e.message : 'Something went wrong';
		} finally {
			busy = false;
		}
	}

	async function create() {
		const personal = owners.find((o) => o.login === owner)?.kind !== 'org';
		const done = await run(() => api.initBoard(name.trim(), personal ? null : owner, isPrivate));
		if (done) {
			board = done.board;
			result = done.publish;
			oninit?.();
			await checkPending();
		}
	}

	async function link() {
		const linked = await run(() => api.setBoardRepo(linkExisting.trim()));
		if (linked) {
			board = linked;
			result = null;
			await checkPending();
		}
	}

	async function publish(optIn = false) {
		const done = await run(() => api.publishBoard(optIn));
		if (done) {
			result = done;
			if (done.committed) board = await api.board();
			await checkPending();
		}
	}

	async function unlink() {
		const cleared = await run(() => api.setBoardRepo(null));
		if (cleared) {
			board = cleared;
			result = null;
			pending = null;
			await load();
		}
	}

	const needsGithub = $derived(error.includes('GitHub account'));
	const changed = $derived((result?.written.length ?? 0) + (result?.removed.length ?? 0));
	const outstanding = $derived((pending?.written.length ?? 0) + (pending?.removed.length ?? 0));
	// Publishing is manual while the database is the source of truth, so the
	// board drifts from the repo as soon as it is edited. Say so, rather than
	// offering a button with no hint whether pressing it does anything.
	const upToDate = $derived(pending !== null && outstanding === 0);
</script>

<div
	class="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-sm"
	role="presentation"
	onclick={(e) => e.target === e.currentTarget && onclose()}
>
	<div class="card w-full max-w-lg p-6">
		<div class="mb-4 flex items-center justify-between">
			<h2 class="text-lg font-bold">Board repo</h2>
			<button class="text-slate-400 hover:text-slate-200" onclick={onclose} aria-label="close"
				>✕</button
			>
		</div>

		<p class="mb-4 text-sm text-slate-400">
			Your whole board, published to a git repo as files — one directory per idea. The board keeps
			working from the database either way; this is a second copy you own.
		</p>

		{#if loading}
			<div class="h-32 animate-pulse rounded-lg bg-white/5"></div>
		{:else if needsGithub}
			<div class="rounded-lg border border-white/10 bg-white/5 p-4 text-sm">
				<p class="mb-3 text-slate-300">Connect GitHub to give your board a repo.</p>
				<button class="btn-primary" onclick={connectGithub}>Connect GitHub</button>
			</div>
		{:else if board?.board_repo}
			<div class="mb-4 rounded-lg border border-white/10 bg-white/5 p-4">
				<div class="flex items-center justify-between gap-3">
					<div class="min-w-0">
						<a
							class="truncate font-mono text-sm text-sky-300 hover:underline"
							href={`https://github.com/${board.board_repo}`}
							target="_blank"
							rel="noreferrer">{board.board_repo}</a
						>
						<p class="mt-1 text-xs text-slate-500">
							{#if board.board_published_at}
								Published {new Date(board.board_published_at).toLocaleString()}
							{:else}
								Never published
							{/if}
						</p>
					</div>
					<button class="btn-ghost" onclick={unlink} disabled={busy}>Unlink</button>
				</div>
			</div>

			<div class="mb-3 flex items-center justify-between gap-3 text-sm">
				<span class="text-slate-400">
					{#if checking}
						Checking the repo…
					{:else if upToDate}
						Up to date with the board
					{:else if pending}
						{outstanding}
						{outstanding === 1 ? 'file' : 'files'} out of date
					{:else}
						Couldn't reach the repo
					{/if}
				</span>
				<button
					class="text-xs text-slate-500 hover:text-slate-300"
					onclick={checkPending}
					disabled={checking || busy}>Re-check</button
				>
			</div>

			<button
				class="btn-primary w-full"
				onclick={() => publish()}
				disabled={busy || checking || upToDate}
			>
				{#if busy}
					Publishing…
				{:else if upToDate}
					Nothing to publish
				{:else if pending}
					Publish {outstanding}
					{outstanding === 1 ? 'change' : 'changes'}
				{:else}
					Publish board
				{/if}
			</button>

			<p class="mt-2 text-xs text-slate-500">
				Publishing is manual for now — the board is edited in the app and copied here
				when you ask.
			</p>

			{#if result?.needs_opt_in}
				<div class="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm">
					<p class="mb-2 text-amber-200">
						That repo already holds files and isn't a board yet. Publishing adds
						<code class="font-mono text-xs">.ideabrd</code> and
						<code class="font-mono text-xs">ideas/</code> and leaves everything else alone.
					</p>
					<button class="btn-ghost" onclick={() => publish(true)} disabled={busy}>
						Publish into it anyway
					</button>
				</div>
			{:else if result?.error}
				<p class="mt-3 text-sm text-rose-400">{result.error}</p>
			{:else if result && !result.committed}
				<p class="mt-3 text-sm text-slate-400">Already up to date — nothing to commit.</p>
			{:else if result?.committed}
				<p class="mt-3 text-sm text-emerald-400">
					Published {changed}
					{changed === 1 ? 'file' : 'files'}.
				</p>
			{/if}
		{:else}
			<div class="mb-4 flex gap-2 text-sm">
				<button
					class={mode === 'create' ? 'btn-primary' : 'btn-ghost'}
					onclick={() => (mode = 'create')}>Create a repo</button
				>
				<button class={mode === 'link' ? 'btn-primary' : 'btn-ghost'} onclick={() => (mode = 'link')}
					>Use an existing one</button
				>
			</div>

			{#if mode === 'create'}
				<div class="space-y-3">
					<label class="block text-sm">
						<span class="mb-1 block text-slate-400">Owner</span>
						<select class="input w-full" bind:value={owner}>
							{#each owners as o (o.login)}
								<option value={o.login}>{o.login}{o.kind === 'org' ? ' (org)' : ''}</option>
							{/each}
						</select>
					</label>
					{#if !orgsVisible}
						<p class="text-xs text-slate-500">
							Only your account is listed — reconnect GitHub to grant organisation access.
							<button class="text-sky-400 hover:underline" onclick={connectGithub}>Reconnect</button>
						</p>
					{/if}
					<label class="block text-sm">
						<span class="mb-1 block text-slate-400">Repository name</span>
						<input class="input w-full font-mono" bind:value={name} spellcheck="false" />
					</label>
					<label class="flex items-center gap-2 text-sm text-slate-300">
						<input type="checkbox" bind:checked={isPrivate} />
						Private
					</label>
					<button
						class="btn-primary w-full"
						onclick={create}
						disabled={busy || !name.trim() || !owner}
					>
						{busy ? 'Creating…' : 'Create and publish'}
					</button>
				</div>
			{:else}
				<div class="space-y-3">
					<label class="block text-sm">
						<span class="mb-1 block text-slate-400">Repository</span>
						<input
							class="input w-full font-mono"
							bind:value={linkExisting}
							placeholder="owner/name"
							spellcheck="false"
						/>
					</label>
					<button class="btn-primary w-full" onclick={link} disabled={busy || !linkExisting.trim()}>
						{busy ? 'Linking…' : 'Link repo'}
					</button>
				</div>
			{/if}
		{/if}

		{#if error && !needsGithub}
			<p class="mt-3 text-sm text-rose-400">{error}</p>
		{/if}
	</div>
</div>
