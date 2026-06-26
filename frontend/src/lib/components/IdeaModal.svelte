<script lang="ts">
	import { untrack } from 'svelte';
	import { STATUSES, type Idea, type Status } from '$lib/types';
	import TileLogo from './TileLogo.svelte';

	let {
		idea = null,
		onsave,
		oncancel
	}: {
		idea?: Idea | null;
		onsave: (data: Partial<Idea>) => void;
		oncancel: () => void;
	} = $props();

	const PALETTE = ['#6366f1', '#ec4899', '#f59e0b', '#10b981', '#06b6d4', '#ef4444', '#8b5cf6'];

	// Snapshot the incoming idea once to seed the form's editable local state.
	const init = untrack(() => idea);
	let title = $state(init?.title ?? '');
	let status = $state<Status>(init?.status ?? 'idea');
	let color = $state(init?.color ?? PALETTE[0]);
	let logo = $state(init?.logo_url ?? '');
	let repo = $state(init?.github_repo ?? '');
	let saving = $state(false);

	function submit(e: SubmitEvent) {
		e.preventDefault();
		if (!title.trim()) return;
		saving = true;
		onsave({
			title: title.trim(),
			status,
			color,
			logo_url: logo.trim() || null,
			github_repo: repo.trim() || null
		});
	}
</script>

<div
	class="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-sm"
	role="presentation"
	onclick={(e) => e.target === e.currentTarget && oncancel()}
>
	<div class="card w-full max-w-lg p-6">
		<h2 class="text-lg font-bold">{idea ? 'Edit idea' : 'New idea'}</h2>

		<form class="mt-5 space-y-4" onsubmit={submit}>
			<div class="flex items-center gap-3">
				<TileLogo {logo} {title} {color} size="lg" />
				<div class="flex-1">
					<label class="mb-1 block text-xs font-medium text-slate-400" for="title">Title</label>
					<input id="title" class="input" bind:value={title} placeholder="My next big thing" />
				</div>
			</div>

			<div class="grid grid-cols-2 gap-4">
				<div>
					<label class="mb-1 block text-xs font-medium text-slate-400" for="status">Status</label>
					<select id="status" class="input" bind:value={status}>
						{#each STATUSES as s}
							<option value={s.value}>{s.label}</option>
						{/each}
					</select>
				</div>
				<div>
					<span class="mb-1 block text-xs font-medium text-slate-400">Accent color</span>
					<div class="flex flex-wrap gap-2 pt-1.5">
						{#each PALETTE as c}
							<button
								type="button"
								aria-label="color {c}"
								class="h-6 w-6 rounded-full ring-2 ring-offset-2 ring-offset-slate-900 transition {color ===
								c
									? 'ring-white'
									: 'ring-transparent'}"
								style="background-color: {c};"
								onclick={() => (color = c)}
							></button>
						{/each}
					</div>
				</div>
			</div>

			<div>
				<label class="mb-1 block text-xs font-medium text-slate-400" for="logo"
					>Logo (emoji or image URL)</label
				>
				<input id="logo" class="input" bind:value={logo} placeholder="🚀  or  https://…/logo.png" />
			</div>

			<div>
				<label class="mb-1 block text-xs font-medium text-slate-400" for="repo"
					>GitHub repo (optional)</label
				>
				<input id="repo" class="input" bind:value={repo} placeholder="owner/name" />
			</div>

			<div class="flex justify-end gap-2 pt-2">
				<button type="button" class="btn-ghost" onclick={oncancel}>Cancel</button>
				<button type="submit" class="btn-primary" disabled={saving || !title.trim()}>
					{idea ? 'Save' : 'Create idea'}
				</button>
			</div>
		</form>
	</div>
</div>
