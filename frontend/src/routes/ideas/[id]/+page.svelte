<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { api } from '$lib/api';
	import { onRealtime } from '$lib/realtime';
	import { STATUSES, type Idea } from '$lib/types';
	import TileLogo from '$lib/components/TileLogo.svelte';
	import ProgressBar from '$lib/components/ProgressBar.svelte';
	import TodoList from '$lib/components/TodoList.svelte';
	import GitHubPanel from '$lib/components/GitHubPanel.svelte';
	import IdeaModal from '$lib/components/IdeaModal.svelte';
	import CollaboratorsPanel from '$lib/components/CollaboratorsPanel.svelte';

	const id = $derived(Number($page.params.id));

	let idea = $state<Idea | null>(null);
	let loading = $state(true);
	let error = $state('');
	let editing = $state(false);
	let sharing = $state(false);
	let savedAt = $state(0);

	// Avoid clobbering an in-progress text edit when a live update arrives.
	let typing = $state(false);
	let pendingReload = $state(false);

	const canEdit = $derived(idea?.role === 'owner' || idea?.role === 'editor');
	const isOwner = $derived(idea?.role === 'owner');

	onMount(() => {
		load();
		return onRealtime((e) => {
			if (e.type === 'idea' && e.id !== id) return;
			if (e.type === 'idea' && e.action === 'deleted') {
				goto('/');
				return;
			}
			if (typing) pendingReload = true;
			else load();
		});
	});

	async function load() {
		try {
			idea = await api.getIdea(id);
			error = '';
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

	function startTyping() {
		typing = true;
	}
	async function stopTyping(data: Partial<Idea>) {
		await patch(data);
		typing = false;
		if (pendingReload) {
			pendingReload = false;
			load();
		}
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

	async function leave() {
		if (!idea) return;
		const me = await api.me();
		await api.removeCollaborator(idea.id, me.id);
		goto('/');
	}

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
	{#if idea.shared && idea.owner}
		<div
			class="mb-4 flex items-center gap-2 rounded-xl border border-indigo-500/20 bg-indigo-500/10 px-4 py-2.5 text-sm text-indigo-200"
		>
			{#if idea.owner.avatar_url}
				<img src={idea.owner.avatar_url} alt="" class="h-5 w-5 rounded-full" />
			{/if}
			Shared with you by {idea.owner.name || idea.owner.email}
			<span class="rounded-full bg-white/10 px-2 py-0.5 text-xs capitalize">{idea.role}</span>
		</div>
	{/if}

	<div class="grid gap-6 lg:grid-cols-[1fr,20rem]">
		<!-- Main column -->
		<div class="space-y-6">
			<div class="card p-6">
				<div class="flex items-start gap-4">
					<TileLogo logo={idea.logo_url} title={idea.title} color={idea.color} size="lg" />
					<div class="min-w-0 flex-1">
						<input
							class="w-full bg-transparent text-2xl font-extrabold tracking-tight text-slate-100 focus:outline-none disabled:opacity-100"
							bind:value={idea.title}
							disabled={!canEdit}
							onfocus={startTyping}
							onblur={() => stopTyping({ title: idea!.title })}
						/>
						<div class="mt-2 flex flex-wrap items-center gap-2">
							{#each STATUSES as s}
								<button
									disabled={!canEdit}
									class="rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize transition {idea
										.status === s.value
										? 'bg-indigo-500 text-white'
										: 'bg-white/5 text-slate-400 hover:bg-white/10'} {canEdit
										? ''
										: 'cursor-default'}"
									onclick={() => canEdit && patch({ status: s.value })}>{s.label}</button
								>
							{/each}
						</div>
					</div>
					<div class="flex shrink-0 gap-2">
						<button class="btn-ghost" onclick={() => (sharing = true)}>
							<svg viewBox="0 0 20 20" class="h-4 w-4 fill-current" aria-hidden="true"
								><path
									d="M13 8a3 3 0 100-6 3 3 0 000 6zM7 8a3 3 0 100-6 3 3 0 000 6zM7 10c-2.7 0-5 1.3-5 3.5V16h10v-2.5C12 11.3 9.7 10 7 10zM13.5 10c-.4 0-.8 0-1.2.1 1 .9 1.7 2 1.7 3.4V16h4v-2.5c0-2.2-2-3.5-4.5-3.5z"
								/></svg
							>
							Share
						</button>
						{#if canEdit}
							<button class="btn-ghost" onclick={() => (editing = true)}>Edit</button>
						{/if}
						{#if isOwner}
							<button class="btn-danger" onclick={remove}>Delete</button>
						{:else}
							<button class="btn-ghost" onclick={leave}>Leave</button>
						{/if}
					</div>
				</div>

				<div class="mt-5">
					<div class="mb-2 flex items-center justify-between text-sm">
						<span class="font-medium text-slate-300">Progress: {idea.progress}%</span>
						{#if canEdit}
							<button class="text-xs text-indigo-300 hover:text-indigo-200" onclick={autoProgress}
								>Set from to-dos</button
							>
						{/if}
					</div>
					{#if canEdit}
						<input
							type="range"
							min="0"
							max="100"
							step="5"
							class="w-full accent-indigo-500"
							bind:value={idea.progress}
							onchange={() => patch({ progress: idea!.progress })}
						/>
					{/if}
					<ProgressBar value={idea.progress} color={idea.color} />
				</div>
			</div>

			<div class="card p-6">
				<h3 class="mb-3 font-semibold">Notes</h3>
				<textarea
					class="input min-h-[12rem] resize-y font-mono text-sm leading-relaxed disabled:opacity-100"
					bind:value={idea.notes}
					disabled={!canEdit}
					placeholder={canEdit ? 'Jot down anything — context, links, plans…' : 'No notes.'}
					onfocus={startTyping}
					onblur={() => stopTyping({ notes: idea!.notes })}
				></textarea>
				{#if savedAt}
					<p class="mt-2 text-xs text-slate-500">Saved · syncs live</p>
				{/if}
			</div>
		</div>

		<!-- Side column -->
		<div class="space-y-6">
			<div class="card p-6">
				<TodoList ideaId={idea.id} bind:todos={idea.todos} {canEdit} />
			</div>

			{#if idea.github_repo}
				<GitHubPanel ideaId={idea.id} repo={idea.github_repo} />
			{/if}
		</div>
	</div>

	{#if editing}
		<IdeaModal {idea} onsave={saveMeta} oncancel={() => (editing = false)} />
	{/if}
	{#if sharing}
		<CollaboratorsPanel ideaId={idea.id} canManage={isOwner} onclose={() => (sharing = false)} />
	{/if}
{/if}
