<script lang="ts">
	import { page } from '$app/state';
	import { ApiError, fetchPublicBoard } from '$lib/api';
	import type { PublicBoard } from '$lib/types';
	import ProgressBar from '$lib/components/ProgressBar.svelte';
	import StatusBadge from '$lib/components/StatusBadge.svelte';
	import TileLogo from '$lib/components/TileLogo.svelte';

	const login = $derived(page.params.login ?? '');

	let board = $state<PublicBoard | null>(null);
	let error = $state('');

	$effect(() => {
		const who = login;
		board = null;
		error = '';
		fetchPublicBoard(who)
			.then((b) => {
				board = b;
				document.title = `${b.name ?? b.login} · IdeaBRD`;
			})
			.catch((err) => {
				error =
					err instanceof ApiError && err.status === 404
						? 'There is no public page here.'
						: 'This page could not be loaded right now. Try again in a minute.';
			});
	});

	function host(url: string): string {
		try {
			return new URL(url).host.replace(/^www\./, '');
		} catch {
			return url;
		}
	}
</script>

<svelte:head>
	<title>{login} · IdeaBRD</title>
</svelte:head>

{#if error}
	<div class="mx-auto max-w-md py-24 text-center text-slate-400">{error}</div>
{:else if !board}
	<div class="flex items-center justify-center py-32 text-slate-400">
		<div class="h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-indigo-400"></div>
	</div>
{:else}
	<header class="mb-8">
		<h1 class="text-3xl font-extrabold tracking-tight">{board.name ?? board.login}</h1>
		<p class="mt-1 text-slate-400">
			{board.ideas.length}
			{board.ideas.length === 1 ? 'project' : 'projects'} · @{board.login}
		</p>
	</header>

	{#if board.ideas.length === 0}
		<p class="py-16 text-center text-slate-400">Nothing public yet.</p>
	{:else}
		<div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
			{#each board.ideas as idea (idea.slug)}
				<article class="card flex flex-col gap-3 p-5">
					<div class="flex items-start gap-3">
						<TileLogo logo={idea.logo_url} title={idea.title} color={idea.color ?? undefined} />
						<div class="min-w-0 flex-1">
							<h2 class="truncate font-semibold">{idea.title}</h2>
							<div class="mt-1"><StatusBadge status={idea.status} /></div>
						</div>
					</div>

					{#if idea.summary}
						<p class="flex-1 text-sm leading-relaxed text-slate-300">{idea.summary}</p>
					{/if}

					<div>
						<div class="mb-1 flex justify-between text-xs text-slate-400">
							<span>
								{#if idea.todos_total}{idea.todos_done}/{idea.todos_total} to-dos{/if}
							</span>
							<span class="tabular-nums">{idea.progress}%</span>
						</div>
						<ProgressBar value={idea.progress} color={idea.color ?? undefined} />
					</div>

					{#if idea.site_url || idea.repo_url}
						<div class="flex flex-wrap gap-4 border-t border-white/10 pt-3 text-sm">
							{#if idea.site_url}
								<a class="text-indigo-300 hover:underline" href={idea.site_url} target="_blank" rel="noopener"
									>{host(idea.site_url)} ↗</a
								>
							{/if}
							{#if idea.repo_url}
								<a class="text-slate-300 hover:underline" href={idea.repo_url} target="_blank" rel="noopener"
									>Code ↗</a
								>
							{/if}
						</div>
					{/if}
				</article>
			{/each}
		</div>
	{/if}
{/if}
