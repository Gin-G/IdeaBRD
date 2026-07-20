<script lang="ts">
	import { api } from '$lib/api';
	import type { Idea } from '$lib/types';

	let {
		idea,
		canEdit,
		onsynced
	}: { idea: Idea; canEdit: boolean; onsynced: (updated: Idea) => void } = $props();

	let busy = $state(false);
	let error = $state('');

	async function run(call: () => Promise<Idea>) {
		busy = true;
		error = '';
		try {
			onsynced(await call());
		} catch (e) {
			error = e instanceof Error ? e.message : 'Sync failed';
		} finally {
			busy = false;
		}
	}

	const sync = () => run(() => api.syncIdea(idea.id));
	const startTracking = () => run(() => api.initIdeaSync(idea.id));

	function ago(iso: string | null): string {
		if (!iso) return 'never';
		const d = (Date.now() - new Date(iso).getTime()) / 1000;
		if (d < 60) return 'just now';
		if (d < 3600) return `${Math.floor(d / 60)}m ago`;
		if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
		return `${Math.floor(d / 86400)}d ago`;
	}

	const syncError = $derived(error || idea.git_sync_error || '');
</script>

<div class="card p-5">
	<div class="mb-2 flex items-center gap-2">
		<svg viewBox="0 0 16 16" class="h-4 w-4 fill-slate-300" aria-hidden="true">
			<path
				d="M11.93 8.5a4.002 4.002 0 01-7.86 0H.75a.75.75 0 010-1.5h3.32a4.002 4.002 0 017.86 0h3.32a.75.75 0 010 1.5h-3.32zM10.5 7.75a2.5 2.5 0 10-5 0 2.5 2.5 0 005 0z"
			/>
		</svg>
		<h3 class="font-semibold">Git sync</h3>
		{#if !idea.git_file_missing}
			<button
				class="ml-auto text-xs text-indigo-300 hover:text-indigo-200 disabled:opacity-50"
				onclick={sync}
				disabled={busy}>{busy ? 'Syncing…' : 'Sync now'}</button
			>
		{/if}
	</div>

	{#if idea.git_file_missing}
		<p class="text-xs leading-relaxed text-slate-400">
			This repo has no <span class="font-mono text-slate-300">IDEA.md</span> yet. Add one to track
			this idea's notes, to-dos and status in git? The file is committed to
			<span class="font-mono text-slate-300">{idea.github_repo}</span> and becomes the source of truth.
		</p>
		{#if canEdit}
			<button class="btn-ghost mt-3 w-full justify-center" onclick={startTracking} disabled={busy}>
				{busy ? 'Committing…' : 'Add IDEA.md to repo'}
			</button>
		{/if}
		{#if syncError}
			<p class="mt-2 rounded-lg bg-rose-500/10 px-3 py-2 text-xs text-rose-300">{syncError}</p>
		{/if}
	{:else}
		<p class="text-xs leading-relaxed text-slate-400">
			Details live in
			<a
				href="https://github.com/{idea.github_repo}/blob/HEAD/IDEA.md"
				target="_blank"
				rel="noreferrer noopener"
				class="font-mono text-indigo-300 hover:text-indigo-200">IDEA.md</a
			>
			— git is the source of truth. Edits here commit to the repo; edits in the repo show up here.
		</p>
		{#if syncError}
			<p class="mt-2 rounded-lg bg-rose-500/10 px-3 py-2 text-xs text-rose-300">{syncError}</p>
		{:else}
			<p class="mt-2 text-xs text-slate-500">Synced {ago(idea.git_synced_at)}</p>
		{/if}
	{/if}
</div>
