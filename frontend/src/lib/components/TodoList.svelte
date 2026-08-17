<script lang="ts">
	import { api } from '$lib/api';
	import type { Todo } from '$lib/types';

	let {
		ideaId,
		todos = $bindable([]),
		canEdit = true,
		repo = null,
		onchange
	}: {
		ideaId: number;
		todos: Todo[];
		canEdit?: boolean;
		/** Linked repo ("owner/name"), or null — promoting to an issue needs one. */
		repo?: string | null;
		onchange?: () => void;
	} = $props();

	let newText = $state('');
	let adding = $state(false);
	let promoting = $state<number | null>(null);
	let error = $state('');

	const done = $derived(todos.filter((t) => t.done).length);

	async function add(e: SubmitEvent) {
		e.preventDefault();
		const text = newText.trim();
		if (!text) return;
		adding = true;
		try {
			const todo = await api.createTodo(ideaId, text);
			todos = [...todos, todo];
			newText = '';
			onchange?.();
		} finally {
			adding = false;
		}
	}

	async function toggle(todo: Todo) {
		if (!canEdit) return;
		const updated = await api.updateTodo(todo.id, { done: !todo.done });
		todos = todos.map((t) => (t.id === todo.id ? updated : t));
		onchange?.();
	}

	async function remove(todo: Todo) {
		await api.deleteTodo(todo.id);
		todos = todos.filter((t) => t.id !== todo.id);
		onchange?.();
	}

	/** Promoting is an explicit action, so its failure is shown rather than swallowed. */
	async function promote(todo: Todo) {
		promoting = todo.id;
		error = '';
		try {
			const updated = await api.promoteTodo(todo.id);
			todos = todos.map((t) => (t.id === todo.id ? updated : t));
			onchange?.();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Could not open the issue';
		} finally {
			promoting = null;
		}
	}
</script>

<div>
	<div class="mb-3 flex items-center justify-between">
		<h3 class="font-semibold">To-do</h3>
		{#if todos.length}
			<span class="text-xs text-slate-400">{done}/{todos.length} done</span>
		{/if}
	</div>

	<ul class="space-y-1.5">
		{#each todos as todo (todo.id)}
			<li class="group flex items-start gap-3 rounded-lg px-2 py-1.5 hover:bg-white/5">
				<button
					type="button"
					role="checkbox"
					aria-checked={todo.done}
					aria-label="toggle {todo.text}"
					disabled={!canEdit}
					class="grid h-5 w-5 shrink-0 place-items-center rounded-md border transition-colors {todo.done
						? 'border-indigo-400 bg-indigo-500 text-white'
						: 'border-white/20 hover:border-white/40'} {canEdit ? '' : 'cursor-default'}"
					onclick={() => toggle(todo)}
				>
					{#if todo.done}
						<svg viewBox="0 0 20 20" class="h-3.5 w-3.5 fill-current"
							><path
								d="M16.7 5.3a1 1 0 010 1.4l-7 7a1 1 0 01-1.4 0l-3-3a1 1 0 011.4-1.4l2.3 2.3 6.3-6.3a1 1 0 011.4 0z"
							/></svg
						>
					{/if}
				</button>
				<!-- min-w-0 lets the item shrink (flex defaults to min-width:auto) so that
				     break-words can wrap a long URL instead of overflowing the card. -->
				<span
					class="min-w-0 flex-1 break-words text-sm {todo.done
						? 'text-slate-500 line-through'
						: 'text-slate-200'}"
					>{todo.text}{#if todo.github_issue_url}&nbsp;<a
							href={todo.github_issue_url}
							target="_blank"
							rel="noreferrer noopener"
							title="Tracked as issue #{todo.github_issue_number} — the issue owns this item's text and state"
							class="whitespace-nowrap text-xs text-indigo-300 no-underline hover:text-indigo-200"
							>#{todo.github_issue_number}</a
						>{/if}</span
				>
				{#if canEdit && repo && !todo.github_issue_number}
					<button
						type="button"
						title="Open a GitHub issue for this to-do"
						disabled={promoting === todo.id}
						class="shrink-0 text-xs text-slate-500 transition hover:text-indigo-300 disabled:cursor-wait {promoting ===
						todo.id
							? 'opacity-100'
							: 'opacity-0 group-hover:opacity-100'}"
						onclick={() => promote(todo)}>{promoting === todo.id ? '…' : 'issue'}</button
					>
				{/if}
				{#if canEdit}
					<button
						type="button"
						aria-label="delete todo"
						class="shrink-0 text-slate-500 opacity-0 transition hover:text-rose-400 group-hover:opacity-100"
						onclick={() => remove(todo)}>✕</button
					>
				{/if}
			</li>
		{/each}
		{#if todos.length === 0}
			<li class="px-2 py-1.5 text-sm text-slate-500">No tasks yet.</li>
		{/if}
	</ul>

	{#if error}
		<p class="mt-2 px-2 text-xs text-rose-300">{error}</p>
	{/if}

	{#if canEdit}
		<form class="mt-3 flex gap-2" onsubmit={add}>
			<input class="input" bind:value={newText} placeholder="Add a task…" />
			<button class="btn-ghost shrink-0" disabled={adding || !newText.trim()}>Add</button>
		</form>
	{/if}
</div>
