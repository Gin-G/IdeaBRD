<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { auth, loadUser } from '$lib/auth.svelte';
	import { api, redirectToLogin, redirectToGithubLogin } from '$lib/api';
	import AccountPanel from '$lib/components/AccountPanel.svelte';

	let { children } = $props();
	let showAccount = $state(false);

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
					<button
						class="flex items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-white/5"
						onclick={() => (showAccount = true)}
						title="Account"
					>
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
					</button>
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
			<div class="mx-auto max-w-sm py-24 text-center">
				<h1 class="text-2xl font-bold">Welcome to IdeaBRD</h1>
				<p class="mt-2 text-slate-400">Sign in to see your idea board.</p>
				<div class="mt-6 flex flex-col gap-3">
					<button class="btn-primary" onclick={redirectToLogin}>
						<span class="grid h-5 w-5 place-items-center rounded-full bg-white text-xs font-bold text-slate-900"
							>G</span
						>
						Sign in with Google
					</button>
					{#if auth.providers.github}
						<button class="btn-ghost" onclick={redirectToGithubLogin}>
							<svg viewBox="0 0 16 16" class="h-5 w-5 fill-current" aria-hidden="true"
								><path
									d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.6 7.6 0 014 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"
								/></svg
							>
							Sign in with GitHub
						</button>
					{/if}
				</div>
			</div>
		{:else}
			{@render children()}
		{/if}
	</main>

	{#if showAccount}
		<AccountPanel onclose={() => (showAccount = false)} />
	{/if}
</div>
