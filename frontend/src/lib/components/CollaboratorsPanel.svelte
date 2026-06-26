<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError } from '$lib/api';
	import type { Collaborator, Role } from '$lib/types';

	let {
		ideaId,
		canManage,
		onclose
	}: { ideaId: number; canManage: boolean; onclose: () => void } = $props();

	let people = $state<Collaborator[]>([]);
	let loading = $state(true);
	let email = $state('');
	let role = $state<Role>('editor');
	let busy = $state(false);
	let error = $state('');

	onMount(load);

	async function load() {
		loading = true;
		try {
			people = await api.listCollaborators(ideaId);
		} finally {
			loading = false;
		}
	}

	async function invite(e: SubmitEvent) {
		e.preventDefault();
		const addr = email.trim();
		if (!addr) return;
		busy = true;
		error = '';
		try {
			await api.invite(ideaId, addr, role);
			email = '';
			await load();
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Failed to invite';
		} finally {
			busy = false;
		}
	}

	async function remove(c: Collaborator) {
		if (c.status === 'pending' && c.invite_id != null) {
			await api.cancelInvite(ideaId, c.invite_id);
		} else if (c.user_id != null) {
			await api.removeCollaborator(ideaId, c.user_id);
		}
		await load();
	}

	function label(c: Collaborator): string {
		return c.name || c.email;
	}
</script>

<div
	class="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-sm"
	role="presentation"
	onclick={(e) => e.target === e.currentTarget && onclose()}
>
	<div class="card w-full max-w-lg p-6">
		<div class="mb-4 flex items-center justify-between">
			<h2 class="text-lg font-bold">Share this idea</h2>
			<button class="text-slate-400 hover:text-slate-200" onclick={onclose} aria-label="close"
				>✕</button
			>
		</div>

		{#if canManage}
			<form class="mb-4 space-y-3" onsubmit={invite}>
				<div class="flex gap-2">
					<input
						class="input"
						type="email"
						bind:value={email}
						placeholder="collaborator@email.com"
					/>
					<select class="input w-28 shrink-0" bind:value={role}>
						<option value="editor">Editor</option>
						<option value="viewer">Viewer</option>
					</select>
					<button class="btn-primary shrink-0" disabled={busy || !email.trim()}>Invite</button>
				</div>
				{#if error}<p class="text-sm text-rose-300">{error}</p>{/if}
				<p class="text-xs text-slate-500">
					They'll see this idea on their board. People without an account yet get a pending invite
					that activates when they sign in.
				</p>
			</form>
		{/if}

		{#if loading}
			<div class="h-20 animate-pulse rounded-lg bg-white/5"></div>
		{:else}
			<ul class="space-y-1.5">
				{#each people as c (c.email)}
					<li class="flex items-center gap-3 rounded-lg px-2 py-2 hover:bg-white/5">
						{#if c.avatar_url}
							<img src={c.avatar_url} alt="" class="h-8 w-8 rounded-full ring-1 ring-white/10" />
						{:else}
							<div
								class="grid h-8 w-8 place-items-center rounded-full bg-white/10 text-sm font-semibold uppercase"
							>
								{label(c).charAt(0)}
							</div>
						{/if}
						<div class="min-w-0 flex-1">
							<div class="truncate text-sm text-slate-200">{label(c)}</div>
							<div class="truncate text-xs text-slate-500">{c.email}</div>
						</div>
						<span
							class="rounded-full px-2 py-0.5 text-xs font-medium capitalize {c.status ===
							'pending'
								? 'bg-amber-500/15 text-amber-300'
								: 'bg-white/5 text-slate-300'}"
						>
							{c.is_owner ? 'owner' : c.status === 'pending' ? `${c.role} · pending` : c.role}
						</span>
						{#if canManage && !c.is_owner}
							<button
								class="text-slate-500 hover:text-rose-400"
								aria-label="remove"
								onclick={() => remove(c)}>✕</button
							>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</div>
</div>
