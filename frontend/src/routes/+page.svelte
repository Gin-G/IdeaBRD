<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { api } from '$lib/api';
	import { onRealtime } from '$lib/realtime';
	import type { Idea, IdeaSummary } from '$lib/types';
	import Tile from '$lib/components/Tile.svelte';
	import IdeaModal from '$lib/components/IdeaModal.svelte';

	let ideas = $state<IdeaSummary[]>([]);
	let loading = $state(true);
	let error = $state('');
	let showModal = $state(false);

	let dragIndex = $state<number | null>(null);
	let savingOrder = $state(false);

	async function load() {
		try {
			ideas = await api.listIdeas();
			error = '';
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load ideas';
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		load();
		// Any live event may affect the board (shares, edits, deletes); just refetch.
		return onRealtime(() => {
			// Refetching mid-drag, or before the new order is saved, snaps tiles back.
			if (dragIndex !== null || savingOrder) return;
			load();
		});
	});

	function moveTile(from: number, to: number) {
		if (from === to || to < 0 || to >= ideas.length) return;
		const next = [...ideas];
		const [moved] = next.splice(from, 1);
		next.splice(to, 0, moved);
		ideas = next;
	}

	/** Persist the current order as positions 0..n-1 (the board sorts by position). */
	async function persistOrder() {
		savingOrder = true;
		try {
			await api.reorderIdeas(ideas.map((idea, i) => ({ id: idea.id, position: i })));
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to save the new order';
			await load(); // fall back to whatever the server still has
		} finally {
			savingOrder = false;
		}
	}

	function dragStart(e: DragEvent, i: number) {
		dragIndex = i;
		if (e.dataTransfer) {
			e.dataTransfer.effectAllowed = 'move';
			// Firefox refuses to start a drag unless dataTransfer carries something.
			e.dataTransfer.setData('text/plain', String(ideas[i].id));
		}
	}

	function dragOver(e: DragEvent, i: number) {
		if (dragIndex === null) return;
		e.preventDefault(); // marks this a valid drop target
		if (dragIndex === i) return;
		moveTile(dragIndex, i);
		dragIndex = i; // the dragged tile now lives here
	}

	async function dragEnd() {
		if (dragIndex === null) return;
		dragIndex = null;
		await persistOrder();
	}

	/** Keyboard equivalent of a drag, for anyone not using a pointer. */
	async function nudge(e: KeyboardEvent, i: number) {
		if (!e.altKey || (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight')) return;
		const to = e.key === 'ArrowLeft' ? i - 1 : i + 1;
		if (to < 0 || to >= ideas.length) return;
		e.preventDefault();
		moveTile(i, to);
		await persistOrder();
	}

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
			{#if ideas.length > 1}
				<span class="text-slate-500"
					>· drag to reorder, or <kbd class="font-sans">Alt</kbd> +
					<kbd class="font-sans">←</kbd>/<kbd class="font-sans">→</kbd></span
				>
			{/if}
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
		{#each ideas as idea, i (idea.id)}
			<Tile
				{idea}
				draggable
				dragging={dragIndex === i}
				ondragstart={(e) => dragStart(e, i)}
				ondragover={(e) => dragOver(e, i)}
				ondragend={dragEnd}
				ondrop={(e) => e.preventDefault()}
				onkeydown={(e) => nudge(e, i)}
			/>
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
