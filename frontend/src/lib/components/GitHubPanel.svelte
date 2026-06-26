<script lang="ts">
	import { api } from '$lib/api';
	import type { GitHubRepo } from '$lib/types';

	let { ideaId, repo }: { ideaId: number; repo: string } = $props();

	let data = $state<GitHubRepo | null>(null);
	let loading = $state(true);
	let error = $state('');

	$effect(() => {
		// Re-fetch whenever the linked repo changes.
		repo;
		load();
	});

	async function load() {
		loading = true;
		error = '';
		data = null;
		try {
			data = await api.github(ideaId);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load repo';
		} finally {
			loading = false;
		}
	}

	function ago(iso: string | null): string {
		if (!iso) return '—';
		const d = (Date.now() - new Date(iso).getTime()) / 1000;
		if (d < 3600) return `${Math.floor(d / 60)}m ago`;
		if (d < 86400) return `${Math.floor(d / 3600)}h ago`;
		return `${Math.floor(d / 86400)}d ago`;
	}
</script>

<div class="card p-5">
	<div class="mb-3 flex items-center gap-2">
		<svg viewBox="0 0 16 16" class="h-4 w-4 fill-slate-300" aria-hidden="true">
			<path
				d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"
			/>
		</svg>
		<h3 class="font-semibold">GitHub</h3>
		<a href="https://github.com/{repo}" target="_blank" rel="noreferrer noopener"
			class="ml-auto text-xs text-indigo-300 hover:text-indigo-200">{repo} ↗</a
		>
	</div>

	{#if loading}
		<div class="h-20 animate-pulse rounded-lg bg-white/5"></div>
	{:else if error}
		<p class="text-sm text-rose-300">{error}</p>
	{:else if data}
		{#if data.description}
			<p class="mb-3 text-sm text-slate-400">{data.description}</p>
		{/if}
		<div class="grid grid-cols-3 gap-3 text-center">
			<div class="rounded-lg bg-white/5 py-2">
				<div class="text-lg font-bold">{data.stars}</div>
				<div class="text-xs text-slate-400">stars</div>
			</div>
			<div class="rounded-lg bg-white/5 py-2">
				<div class="text-lg font-bold">{data.open_issues}</div>
				<div class="text-xs text-slate-400">open issues</div>
			</div>
			<div class="rounded-lg bg-white/5 py-2">
				<div class="text-lg font-bold">{data.forks}</div>
				<div class="text-xs text-slate-400">forks</div>
			</div>
		</div>
		<dl class="mt-3 space-y-1.5 text-sm">
			{#if data.language}
				<div class="flex justify-between">
					<dt class="text-slate-400">Language</dt>
					<dd class="text-slate-200">{data.language}</dd>
				</div>
			{/if}
			<div class="flex justify-between">
				<dt class="text-slate-400">Last push</dt>
				<dd class="text-slate-200">{ago(data.pushed_at)}</dd>
			</div>
			{#if data.last_commit_message}
				<div class="flex justify-between gap-4">
					<dt class="text-slate-400">Latest commit</dt>
					<dd class="truncate text-slate-200" title={data.last_commit_message}>
						{data.last_commit_message}
					</dd>
				</div>
			{/if}
		</dl>
	{/if}
</div>
