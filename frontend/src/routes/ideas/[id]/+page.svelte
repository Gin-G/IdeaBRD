<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { api } from '$lib/api';
	import { STATUSES, type Idea } from '$lib/types';
	import TileLogo from '$lib/components/TileLogo.svelte';
	import ProgressBar from '$lib/components/ProgressBar.svelte';
	import TodoList from '$lib/components/TodoList.svelte';
	import GitHubPanel from '$lib/components/GitHubPanel.svelte';
	import IdeaModal from '$lib/components/IdeaModal.svelte';

	const id = $derived(Number($page.params.id));

	let idea = $state<Idea | null>(null);
	let loading = $state(true);
	let error = $state('');
	let editing = $state(false);
	let savedAt = $state(0);

	onMount(load);

	async function load() {
		loading = true;
		try {
			idea = await api.getIdea(id);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load idea';
		} finally {
			loading = false;
		}
	}

	async function patch(data: Partial<Idea>) {
		if (!idea) return;
		idea = await api.updateIdea(idea.id, data);
		savedAt = Date.now();
	}

	async function saveMeta(data: Partial<Idea>) {
		await patch(data);
		editing = false;
	}

	async function remove() {
		if (!idea) return;
		if (!confirm(`Delete "${idea.title}"? This cannot be undone.`)) return;
		await api.deleteIdea(idea.id);
		goto('/');
	}

	// Derive progress from completed todos.
	function autoProgress() {
		if (!idea || idea.todos.length === 0) return;
		const pct = Math.round((idea.todos.filter((t) => t.done).length / idea.todos.length) * 100);
		patch({ progress: pct });
	}
</script>

<a href="/" class="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-400 hover:text-slate-200">
	← Back to board
</a>

{#if loading}
	<div class="card h-64 animate-pulse bg-white/[0.04]"></div>
{:else if error}
	<div class="card p-6 text-rose-300">{error}</div>
{:else if idea}
	<div class="grid gap-6 lg:grid-cols-[1fr,20rem]">
		<!-- Main column -->
		<div class="space-y-6">
			<div class="card p-6">
				<div class="flex items-start gap-4">
					<TileLogo logo={idea.logo_url} title={idea.title} color={idea.color} size="lg" />
					<div class="min-w-0 flex-1">
						<input
							class="w-full bg-transparent text-2xl font-extrabold tracking-tight text-slate-100 focus:outline-none"
							bind:value={idea.title}
							onblur={() => patch({ title: idea!.title })}
						/>
						<div class="mt-2 flex flex-wrap items-center gap-2">
							{#each STATUSES as s}
								<button
									class="rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize transition {idea
										.status === s.value
										? 'bg-indigo-500 text-white'
										: 'bg-white/5 text-slate-400 hover:bg-white/10'}"
									onclick={() => patch({ status: s.value })}>{s.label}</button
								>
							{/each}
						</div>
					</div>
					<div class="flex gap-2">
						<button class="btn-ghost" onclick={() => (editing = true)}>Edit</button>
						<button class="btn-danger" onclick={remove}>Delete</button>
					</div>
				</div>

				<div class="mt-5">
					<div class="mb-2 flex items-center justify-between text-sm">
						<span class="font-medium text-slate-300">Progress: {idea.progress}%</span>
						<button class="text-xs text-indigo-300 hover:text-indigo-200" onclick={autoProgress}
							>Set from to-dos</button
						>
					</div>
					<input
						type="range"
						min="0"
						max="100"
						step="5"
						class="w-full accent-indigo-500"
						bind:value={idea.progress}
						onchange={() => patch({ progress: idea!.progress })}
					/>
					<ProgressBar value={idea.progress} color={idea.color} />
				</div>
			</div>

			<div class="card p-6">
				<h3 class="mb-3 font-semibold">Notes</h3>
				<textarea
					class="input min-h-[12rem] resize-y font-mono text-sm leading-relaxed"
					bind:value={idea.notes}
					placeholder="Jot down anything — context, links, plans… (markdown welcome)"
					onblur={() => patch({ notes: idea!.notes })}
				></textarea>
				{#if savedAt}
					<p class="mt-2 text-xs text-slate-500">Saved</p>
				{/if}
			</div>
		</div>

		<!-- Side column -->
		<div class="space-y-6">
			<div class="card p-6">
				<TodoList ideaId={idea.id} bind:todos={idea.todos} />
			</div>

			{#if idea.github_repo}
				<GitHubPanel ideaId={idea.id} repo={idea.github_repo} />
			{/if}
		</div>
	</div>

	{#if editing}
		<IdeaModal {idea} onsave={saveMeta} oncancel={() => (editing = false)} />
	{/if}
{/if}
