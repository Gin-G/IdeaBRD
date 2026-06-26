<script lang="ts">
	import type { IdeaSummary } from '$lib/types';
	import ProgressBar from './ProgressBar.svelte';
	import StatusBadge from './StatusBadge.svelte';
	import TileLogo from './TileLogo.svelte';

	let { idea }: { idea: IdeaSummary } = $props();
</script>

<a
	href="/ideas/{idea.id}"
	class="card group flex h-full flex-col gap-4 p-5 transition-all hover:-translate-y-0.5 hover:border-white/20 hover:bg-white/[0.06]"
>
	<div class="flex items-start gap-3">
		<TileLogo logo={idea.logo_url} title={idea.title} color={idea.color} />
		<div class="min-w-0 flex-1">
			<h3 class="truncate text-base font-semibold text-slate-100">{idea.title}</h3>
			<div class="mt-1.5 flex items-center gap-2">
				<StatusBadge status={idea.status} />
				{#if idea.github_repo}
					<span
						class="inline-flex items-center gap-1 text-xs text-slate-400"
						title={idea.github_repo}
					>
						<svg viewBox="0 0 16 16" class="h-3.5 w-3.5 fill-current" aria-hidden="true">
							<path
								d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"
							/>
						</svg>
						<span class="max-w-[7rem] truncate">{idea.github_repo}</span>
					</span>
				{/if}
			</div>
		</div>
	</div>

	<div class="mt-auto">
		<div class="mb-1.5 flex items-center justify-between text-xs text-slate-400">
			<span>Progress</span>
			<span class="font-medium text-slate-300">{idea.progress}%</span>
		</div>
		<ProgressBar value={idea.progress} color={idea.color} />
	</div>
</a>
