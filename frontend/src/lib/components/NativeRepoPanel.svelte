<script lang="ts">
	import { api } from '$lib/api';
	import type { Idea } from '$lib/types';

	/**
	 * A repo-linked idea, on the device.
	 *
	 * The board repo records only *where* such an idea lives — its notes and
	 * to-dos are tracked in that repository, under its own history. So until
	 * this device has a checkout of it, the tile is a pointer and nothing more,
	 * and fetching it is a deliberate act rather than something an opened tile
	 * does on somebody's mobile data.
	 */
	let {
		idea,
		onsynced
	}: { idea: Idea; onsynced: (updated: Idea) => void } = $props();

	let busy = $state(false);
	let error = $state('');

	const cloned = $derived(!idea.git_file_missing);

	async function fetchIt() {
		busy = true;
		error = '';
		try {
			onsynced(await api.syncIdea(idea.id));
		} catch (e) {
			error = e instanceof Error ? e.message : 'Could not reach the repository';
		} finally {
			busy = false;
		}
	}
</script>

<div class="card p-5">
	<div class="mb-2 flex items-center gap-2">
		<h3 class="font-semibold">Its own repo</h3>
		{#if cloned}
			<button
				class="ml-auto text-xs text-indigo-300 hover:text-indigo-200 disabled:opacity-50"
				onclick={fetchIt}
				disabled={busy}>{busy ? 'Fetching…' : 'Fetch'}</button
			>
		{/if}
	</div>

	<a
		href="https://github.com/{idea.github_repo}"
		target="_blank"
		rel="noreferrer noopener"
		class="font-mono text-sm text-sky-300 hover:underline">{idea.github_repo}</a
	>

	{#if cloned}
		<p class="mt-2 text-xs leading-relaxed text-slate-400">
			This idea is checked out on this device. Edits are committed to that repository, and
			<em>Sync</em> pushes them along with the board. To-dos ending in
			<span class="font-mono text-slate-300">(#12)</span> follow their issue.
		</p>
	{:else}
		<p class="mt-2 text-xs leading-relaxed text-slate-400">
			The board records that this idea lives there; its notes and to-dos are in that repo's
			<span class="font-mono text-slate-300">IDEA.md</span>. Fetch it to read and edit it here —
			it is cloned once and then works offline.
		</p>
		<button class="btn-ghost mt-3 w-full justify-center" onclick={fetchIt} disabled={busy}>
			{busy ? 'Cloning…' : 'Fetch this idea'}
		</button>
	{/if}

	{#if error}
		<p class="mt-2 rounded-lg bg-rose-500/10 px-3 py-2 text-xs text-rose-300">{error}</p>
	{/if}
</div>
