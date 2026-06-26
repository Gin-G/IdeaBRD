<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { auth, loadUser } from '$lib/auth.svelte';
	import { api, redirectToLogin } from '$lib/api';

	let { children } = $props();

	onMount(loadUser);

	async function logout() {
		await api.logout();
		auth.user = null;
		redirectToLogin();
	}
</script>

<div class="min-h-full bg-gradient-to-b from-slate-950 via-slate-950 to-slate-900">
	<header class="sticky top-0 z-20 border-b border-white/10 bg-slate-950/70 backdrop-blur">
		<div class="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6">
			<a href="/" class="flex items-center gap-2.5">
				<span
					class="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-indigo-500 to-fuchsia-500 text-lg font-black text-white shadow-lg shadow-indigo-500/30"
					>◆</span
				>
				<span class="text-lg font-extrabold tracking-tight">IdeaBRD</span>
			</a>

			{#if auth.user}
				<div class="flex items-center gap-3">
					{#if auth.user.avatar_url}
						<img
							src={auth.user.avatar_url}
							alt=""
							class="h-8 w-8 rounded-full ring-1 ring-white/20"
						/>
					{/if}
					<span class="hidden text-sm text-slate-300 sm:block"
						>{auth.user.name ?? auth.user.email}</span
					>
					<button class="btn-ghost" onclick={logout}>Sign out</button>
				</div>
			{/if}
		</div>
	</header>

	<main class="mx-auto max-w-7xl px-4 py-8 sm:px-6">
		{#if auth.loading}
			<div class="flex items-center justify-center py-32 text-slate-400">
				<div
					class="h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-indigo-400"
				></div>
			</div>
		{:else if !auth.user}
			<div class="mx-auto max-w-md py-24 text-center">
				<h1 class="text-2xl font-bold">Welcome to IdeaBRD</h1>
				<p class="mt-2 text-slate-400">Sign in to see your idea board.</p>
				<button class="btn-primary mt-6" onclick={redirectToLogin}>Sign in with Google</button>
			</div>
		{:else}
			{@render children()}
		{/if}
	</main>
</div>
