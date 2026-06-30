<script lang="ts">
	import { onMount } from 'svelte';
	import { api, connectGithub, ApiError } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import type { Identity } from '$lib/types';

	let { onclose }: { onclose: () => void } = $props();

	let identities = $state<Identity[]>([]);
	let loading = $state(true);
	let error = $state('');

	onMount(load);

	async function load() {
		loading = true;
		try {
			identities = await api.identities();
		} finally {
			loading = false;
		}
	}

	function has(provider: string): Identity | undefined {
		return identities.find((i) => i.provider === provider);
	}

	async function unlink(provider: string) {
		error = '';
		try {
			await api.unlinkIdentity(provider);
			await load();
		} catch (e) {
			error = e instanceof ApiError ? e.message : 'Failed to unlink';
		}
	}

	const github = $derived(has('github'));
	const google = $derived(has('google'));
</script>

<div
	class="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-sm"
	role="presentation"
	onclick={(e) => e.target === e.currentTarget && onclose()}
>
	<div class="card w-full max-w-md p-6">
		<div class="mb-4 flex items-center justify-between">
			<h2 class="text-lg font-bold">Account</h2>
			<button class="text-slate-400 hover:text-slate-200" onclick={onclose} aria-label="close"
				>✕</button
			>
		</div>

		<p class="mb-4 text-sm text-slate-400">
			Sign-in methods linked to your board. Link both to log in with either.
		</p>

		{#if loading}
			<div class="h-24 animate-pulse rounded-lg bg-white/5"></div>
		{:else}
			<div class="space-y-2">
				<!-- Google -->
				<div class="flex items-center gap-3 rounded-lg bg-white/5 px-3 py-2.5">
					<span class="grid h-8 w-8 place-items-center rounded-full bg-white text-sm font-bold text-slate-900"
						>G</span
					>
					<div class="min-w-0 flex-1">
						<div class="text-sm font-medium">Google</div>
						<div class="truncate text-xs text-slate-400">
							{google ? google.email : 'Not linked'}
						</div>
					</div>
					{#if google}
						<span class="text-xs text-emerald-400">Linked</span>
						{#if identities.length > 1}
							<button class="text-xs text-slate-500 hover:text-rose-400" onclick={() => unlink('google')}
								>Unlink</button
							>
						{/if}
					{/if}
				</div>

				<!-- GitHub -->
				<div class="flex items-center gap-3 rounded-lg bg-white/5 px-3 py-2.5">
					<svg viewBox="0 0 16 16" class="h-8 w-8 fill-slate-200" aria-hidden="true">
						<path
							d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"
						/>
					</svg>
					<div class="min-w-0 flex-1">
						<div class="text-sm font-medium">GitHub</div>
						<div class="truncate text-xs text-slate-400">
							{#if github}
								@{github.github_login}{github.has_repo_token ? ' · repo access' : ''}
							{:else}
								Not linked
							{/if}
						</div>
					</div>
					{#if github}
						<span class="text-xs text-emerald-400">Linked</span>
						{#if identities.length > 1}
							<button class="text-xs text-slate-500 hover:text-rose-400" onclick={() => unlink('github')}
								>Unlink</button
							>
						{/if}
					{:else if auth.providers.github}
						<button class="btn-ghost py-1 text-xs" onclick={connectGithub}>Connect</button>
					{/if}
				</div>
			</div>
			{#if error}<p class="mt-3 text-sm text-rose-300">{error}</p>{/if}
			<p class="mt-4 text-xs text-slate-500">
				Linking GitHub also lets repo-linked ideas sync their <code>.ideabrd/</code> files.
			</p>
		{/if}
	</div>
</div>
