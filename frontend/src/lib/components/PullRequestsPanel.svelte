<script lang="ts">
	import { api } from '$lib/api';
	import type { PullRequest } from '$lib/types';

	let { ideaId, repo }: { ideaId: number; repo: string } = $props();

	let pulls = $state<PullRequest[] | null>(null);
	let loading = $state(true);
	let error = $state('');

	$effect(() => {
		repo; // re-fetch when the linked repo changes
		load();
	});

	async function load() {
		loading = true;
		error = '';
		try {
			pulls = await api.pulls(ideaId);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load pull requests';
		} finally {
			loading = false;
		}
	}

	function ago(iso: string | null): string {
		if (!iso) return '';
		const d = (Date.now() - new Date(iso).getTime()) / 1000;
		if (d < 3600) return `${Math.floor(d / 60)}m`;
		if (d < 86400) return `${Math.floor(d / 3600)}h`;
		return `${Math.floor(d / 86400)}d`;
	}
</script>

<div class="card p-5">
	<div class="mb-3 flex items-center gap-2">
		<svg viewBox="0 0 16 16" class="h-4 w-4 fill-slate-300" aria-hidden="true">
			<path
				d="M1.5 3.25a2.25 2.25 0 113 2.122v5.256a2.251 2.251 0 11-1.5 0V5.372A2.25 2.25 0 011.5 3.25zm5.677-.177L9.573.677A.25.25 0 0110 .854V2.5h1A2.5 2.5 0 0113.5 5v5.628a2.251 2.251 0 11-1.5 0V5a1 1 0 00-1-1h-1v1.646a.25.25 0 01-.427.177L7.177 3.427a.25.25 0 010-.354zM3.75 2.5a.75.75 0 100 1.5.75.75 0 000-1.5zm0 9.5a.75.75 0 100 1.5.75.75 0 000-1.5zm8.25.75a.75.75 0 101.5 0 .75.75 0 00-1.5 0z"
			/>
		</svg>
		<h3 class="font-semibold">Pull requests</h3>
		{#if pulls?.length}
			<span class="ml-auto text-xs text-slate-400">{pulls.length} open</span>
		{/if}
	</div>

	{#if loading}
		<div class="h-12 animate-pulse rounded-lg bg-white/5"></div>
	{:else if error}
		<p class="text-sm text-rose-300">{error}</p>
	{:else if pulls && pulls.length > 0}
		<ul class="space-y-2">
			{#each pulls as pr (pr.number)}
				<li>
					<a
						href={pr.html_url}
						target="_blank"
						rel="noreferrer noopener"
						class="block rounded-lg px-2 py-1.5 transition hover:bg-white/5"
					>
						<span class="flex items-baseline gap-1.5">
							<span class="font-mono text-xs text-slate-500">#{pr.number}</span>
							<span class="min-w-0 flex-1 break-words text-sm text-slate-200">{pr.title}</span>
							{#if pr.draft}
								<span
									class="shrink-0 rounded-full bg-white/10 px-1.5 py-0.5 text-[10px] leading-none text-slate-400"
									>draft</span
								>
							{/if}
						</span>
						<span class="mt-0.5 block text-xs text-slate-500">
							{pr.author ?? 'someone'}{#if pr.updated_at}&nbsp;· {ago(pr.updated_at)} ago{/if}
						</span>
					</a>
				</li>
			{/each}
		</ul>
	{:else}
		<p class="text-xs leading-relaxed text-slate-500">
			No open pull requests. This is where collaboration on the idea shows up once someone opens
			one — the repo is what people are added to, not the tile.
		</p>
	{/if}
</div>
