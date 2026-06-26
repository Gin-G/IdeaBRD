<script lang="ts">
	import { api } from '$lib/api';
	import type { Todo } from '$lib/types';

	let {
		ideaId,
		todos = $bindable([]),
		onchange
	}: { ideaId: number; todos: Todo[]; onchange?: () => void } = $props();

	let newText = $state('');
	let adding = $state(false);

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
		const updated = await api.updateTodo(todo.id, { done: !todo.done });
		todos = todos.map((t) => (t.id === todo.id ? updated : t));
		onchange?.();
	}

	async function remove(todo: Todo) {
		await api.deleteTodo(todo.id);
		todos = todos.filter((t) => t.id !== todo.id);
		onchange?.();
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
			<li class="group flex items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-white/5">
				<button
					type="button"
					role="checkbox"
					aria-checked={todo.done}
					aria-label="toggle {todo.text}"
					class="grid h-5 w-5 shrink-0 place-items-center rounded-md border transition-colors {todo.done
						? 'border-indigo-400 bg-indigo-500 text-white'
						: 'border-white/20 hover:border-white/40'}"
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
				<span class="flex-1 text-sm {todo.done ? 'text-slate-500 line-through' : 'text-slate-200'}"
					>{todo.text}</span
				>
				<button
					type="button"
					aria-label="delete todo"
					class="text-slate-500 opacity-0 transition hover:text-rose-400 group-hover:opacity-100"
					onclick={() => remove(todo)}>✕</button
				>
			</li>
		{/each}
	</ul>

	<form class="mt-3 flex gap-2" onsubmit={add}>
		<input class="input" bind:value={newText} placeholder="Add a task…" />
		<button class="btn-ghost shrink-0" disabled={adding || !newText.trim()}>Add</button>
	</form>
</div>
