<script lang="ts">
	import { untrack } from 'svelte';
	import { api, ApiError } from '$lib/api';
	import { isNative } from '$lib/native/plugins';
	import { STATUSES, type Idea, type Status, type Todo } from '$lib/types';
	import TileLogo from './TileLogo.svelte';
	import TodoList from './TodoList.svelte';

	let {
		idea = null,
		onsave,
		oncancel,
		onlogo,
		ontodos
	}: {
		idea?: Idea | null;
		onsave: (data: Partial<Idea>) => void;
		oncancel: () => void;
		/** Uploads persist immediately (they need an id), so the parent is told directly. */
		onlogo?: (idea: Idea) => void;
		/** So does every to-do edit, for the same reason. */
		ontodos?: (todos: Todo[]) => void;
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
	let uploading = $state(false);
	let uploadError = $state('');

	const uploaded = $derived(logo.startsWith('/api/'));

	// Linking a repo means seeding it with the idea's IDEA.md, which is the
	// server's job. Offering the field on the device would let someone turn a
	// held idea into a pointer to a repo that doesn't have it yet.
	const canLinkRepo = !isNative();

	// The to-do list writes through to the API as it is edited, so it keeps its
	// own copy rather than waiting for Save like the fields above it.
	let todos = $state<Todo[]>(init?.todos ?? []);
	$effect(() => ontodos?.(todos));

	async function pickLogo(e: Event) {
		const input = e.currentTarget as HTMLInputElement;
		const file = input.files?.[0];
		input.value = ''; // so the same file can be re-picked after a failure
		if (!file || !idea) return;
		uploading = true;
		uploadError = '';
		try {
			const updated = await api.uploadLogo(idea.id, file);
			logo = updated.logo_url ?? '';
			onlogo?.(updated);
		} catch (err) {
			uploadError = err instanceof ApiError ? err.message : 'Upload failed';
		} finally {
			uploading = false;
		}
	}

	async function clearLogo() {
		if (!idea) return;
		uploading = true;
		uploadError = '';
		try {
			const updated = await api.deleteLogo(idea.id);
			logo = '';
			onlogo?.(updated);
		} catch (err) {
			uploadError = err instanceof ApiError ? err.message : 'Could not remove the image';
		} finally {
			uploading = false;
		}
	}

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
	<div class="card max-h-[88vh] w-full max-w-lg overflow-y-auto p-6">
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
					>Logo (emoji, image URL, or an upload)</label
				>
				<input id="logo" class="input" bind:value={logo} placeholder="🚀  or  https://…/logo.png" />
				{#if idea}
					<div class="mt-2 flex flex-wrap items-center gap-3">
						<label class="btn-ghost cursor-pointer py-1 text-xs">
							<input
								type="file"
								accept="image/png,image/jpeg,image/gif,image/webp"
								class="hidden"
								disabled={uploading}
								onchange={pickLogo}
							/>
							{uploading ? 'Uploading…' : uploaded ? 'Replace image' : 'Upload image'}
						</label>
						{#if uploaded}
							<button
								type="button"
								class="text-xs text-slate-500 hover:text-rose-400"
								onclick={clearLogo}>Remove</button
							>
						{/if}
						<span class="text-xs text-slate-500">PNG, JPEG, GIF or WebP · up to 1MB</span>
					</div>
					{#if idea.github_repo && !idea.git_file_missing}
						<p class="mt-1.5 text-xs text-slate-500">
							Committed to <span class="font-mono text-slate-400">{idea.github_repo}</span> as
							<span class="font-mono text-slate-400">idea_logo.*</span>, so the tile is rebuilt from
							the repo wherever it's linked.
						</p>
					{/if}
				{:else}
					<p class="mt-1.5 text-xs text-slate-500">
						Create the idea first to upload an image.
					</p>
				{/if}
				{#if uploadError}<p class="mt-1.5 text-xs text-rose-300">{uploadError}</p>{/if}
			</div>

			{#if canLinkRepo}
				<div>
					<label class="mb-1 block text-xs font-medium text-slate-400" for="repo"
						>GitHub repo (optional)</label
					>
					<input id="repo" class="input" bind:value={repo} placeholder="owner/name" />
				</div>
			{:else if repo}
				<div>
					<span class="mb-1 block text-xs font-medium text-slate-400">GitHub repo</span>
					<p class="font-mono text-sm text-slate-300">{repo}</p>
					<p class="mt-1 text-xs text-slate-500">
						This idea lives in that repository; its notes and to-dos are committed there.
					</p>
				</div>
			{/if}

			{#if idea}
				<!-- The to-do list, here as well as on the full page: promoting an item
				     to an issue was reachable from one screen only, which made it look
				     like a feature of that page rather than of the idea. -->
				<div class="border-t border-white/10 pt-4">
					<TodoList
						ideaId={idea.id}
						bind:todos
						canEdit={idea.role !== 'viewer'}
						repo={idea.github_repo}
					/>
				</div>
			{/if}

			<div class="flex justify-end gap-2 pt-2">
				<button type="button" class="btn-ghost" onclick={oncancel}>Cancel</button>
				<button type="submit" class="btn-primary" disabled={saving || !title.trim()}>
					{idea ? 'Save' : 'Create idea'}
				</button>
			</div>
		</form>
	</div>
</div>
