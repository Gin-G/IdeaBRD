<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { api } from '$lib/api';
	import type { Idea, IdeaSummary } from '$lib/types';
	import Tile from '$lib/components/Tile.svelte';
	import IdeaModal from '$lib/components/IdeaModal.svelte';

	let ideas = $state<IdeaSummary[]>([]);
	let loading = $state(true);
	let error = $state('');
	let showModal = $state(false);

	async function load() {
		loading = true;
		try {
			ideas = await api.listIdeas();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load ideas';
		} finally {
			loading = false;
		}
	}

	onMount(load);

	async function create(data: Partial<Idea>) {
		const created = await api.createIdea(data);
		showModal = false;
		goto(`/ideas/${created.id}`);
	}
</script>

<div class="mb-6 flex items-end justify-between">
	<div>
		<h1 class="text-2xl font-extrabold tracking-tight">Your board</h1>
		<p class="mt-1 text-sm text-slate-400">
			{ideas.length}
			{ideas.length === 1 ? 'idea' : 'ideas'} in flight
		</p>
	</div>
	<button class="btn-primary" onclick={() => (showModal = true)}>
		<span class="text-base leading-none">+</span> New idea
	</button>
</div>

{#if loading}
	<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
		{#each Array(4) as _}
			<div class="card h-40 animate-pulse bg-white/[0.04]"></div>
		{/each}
	</div>
{:else if error}
	<div class="card p-6 text-rose-300">{error}</div>
{:else if ideas.length === 0}
	<div class="card flex flex-col items-center justify-center gap-3 py-20 text-center">
		<div class="text-5xl">💡</div>
		<h2 class="text-lg font-semibold">No ideas yet</h2>
		<p class="max-w-sm text-sm text-slate-400">
			Capture your first idea — link a GitHub repo or just start taking notes.
		</p>
		<button class="btn-primary mt-2" onclick={() => (showModal = true)}>Add your first idea</button>
	</div>
{:else}
	<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
		{#each ideas as idea (idea.id)}
			<Tile {idea} />
		{/each}
		<button
			class="card grid min-h-40 place-items-center border-dashed text-slate-400 transition-colors hover:border-white/30 hover:text-slate-200"
			onclick={() => (showModal = true)}
		>
			<span class="flex flex-col items-center gap-2">
				<span class="text-3xl">+</span>
				<span class="text-sm font-medium">New idea</span>
			</span>
		</button>
	</div>
{/if}

{#if showModal}
	<IdeaModal onsave={create} oncancel={() => (showModal = false)} />
{/if}
