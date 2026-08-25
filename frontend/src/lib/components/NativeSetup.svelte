<script lang="ts">
	import { onMount } from 'svelte';
	import { Auth, Board, type DeviceCode } from '$lib/native/plugins';

	/**
	 * Getting the Android app to a working board: sign in, then say where the
	 * board lives.
	 *
	 * There is no server here to redirect to, so signing in is GitHub's device
	 * flow — the app shows a short code, the person types it at
	 * github.com/login/device on whatever device is handy, and the app waits.
	 * That is the flow for exactly this situation: an app that cannot keep a
	 * client secret, because everyone who installs it has a copy.
	 */
	let { oncomplete }: { oncomplete: () => void } = $props();

	let step = $state<'checking' | 'signin' | 'code' | 'repo'>('checking');
	let code = $state<DeviceCode | null>(null);
	let login = $state<string | null>(null);
	let repo = $state('');
	let clientId = $state('');
	let needsClientId = $state(false);
	let busy = $state(false);
	let error = $state('');

	const CLIENT_ID_KEY = 'ideabrd.clientId';

	onMount(async () => {
		try {
			clientId = localStorage.getItem(CLIENT_ID_KEY) ?? '';
		} catch {
			/* a browser with storage disabled still gets a working app */
		}
		await refresh();
	});

	async function refresh() {
		const status = await Auth.status();
		login = status.login;
		needsClientId = status.clientIdConfigured === false && !clientId;
		if (!status.authenticated) {
			step = 'signin';
			return;
		}
		const board = await Board.status();
		if (!board.repo || !board.cloned) {
			repo = board.repo ?? '';
			step = 'repo';
			return;
		}
		oncomplete();
	}

	async function signIn() {
		busy = true;
		error = '';
		try {
			code = await Auth.start(clientId ? { clientId } : undefined);
			step = 'code';
			// Polling blocks until the person authorises the code or it expires,
			// which is the whole of the waiting in this flow.
			const status = await Auth.poll({
				deviceCode: code.deviceCode,
				interval: code.interval,
				expiresIn: code.expiresIn,
				...(clientId ? { clientId } : {})
			});
			login = status.login;
			await refresh();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Sign-in failed';
			step = 'signin';
		} finally {
			busy = false;
		}
	}

	async function useRepo() {
		busy = true;
		error = '';
		try {
			await Board.configure({ repo: repo.trim() });
			oncomplete();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Could not clone that repository';
		} finally {
			busy = false;
		}
	}

	function saveClientId() {
		try {
			localStorage.setItem(CLIENT_ID_KEY, clientId.trim());
		} catch {
			/* not fatal: it is passed to the plugin from memory either way */
		}
		needsClientId = !clientId.trim();
	}

	function openVerification() {
		if (code) window.open(code.verificationUri, '_blank');
	}
</script>

<div class="mx-auto max-w-sm py-16 text-center">
	{#if step === 'checking'}
		<div class="flex justify-center py-16">
			<div class="h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-indigo-400"></div>
		</div>
	{:else if step === 'signin'}
		<h1 class="text-2xl font-bold">Your board, in your repo</h1>
		<p class="mt-2 text-sm text-slate-400">
			This app reads and writes the board straight from git. Sign in to GitHub to give it access
			to your repositories — the token stays on this device, encrypted by Android's keystore.
		</p>
		{#if needsClientId}
			<div class="mt-6 rounded-lg border border-white/10 bg-white/5 p-4 text-left">
				<p class="text-xs text-slate-400">
					This build has no GitHub client id compiled in. Paste one from an OAuth app with the
					device flow enabled.
				</p>
				<input
					class="input mt-2 w-full font-mono text-sm"
					bind:value={clientId}
					onchange={saveClientId}
					placeholder="Iv1.xxxxxxxxxxxx"
					spellcheck="false"
				/>
			</div>
		{/if}
		<button class="btn-primary mt-6 w-full justify-center" onclick={signIn} disabled={busy || needsClientId}>
			{busy ? 'Asking GitHub…' : 'Sign in with GitHub'}
		</button>
	{:else if step === 'code' && code}
		<h1 class="text-2xl font-bold">Type this code</h1>
		<p class="mt-2 text-sm text-slate-400">
			Open <span class="font-mono text-slate-300">{code.verificationUri}</span> on any device and
			enter:
		</p>
		<p class="my-6 select-all font-mono text-3xl font-bold tracking-[0.3em] text-indigo-300">
			{code.userCode}
		</p>
		<button class="btn-ghost w-full justify-center" onclick={openVerification}>
			Open GitHub
		</button>
		<p class="mt-4 text-xs text-slate-500">Waiting for you to authorise the code…</p>
	{:else if step === 'repo'}
		<h1 class="text-2xl font-bold">Which board?</h1>
		<p class="mt-2 text-sm text-slate-400">
			{#if login}Signed in as <span class="text-slate-300">{login}</span>.{/if}
			Name the repository your board lives in. It is cloned to this device and every change is
			committed there.
		</p>
		<input
			class="input mt-6 w-full text-center font-mono"
			bind:value={repo}
			placeholder="owner/ideabrd-board"
			spellcheck="false"
		/>
		<button
			class="btn-primary mt-3 w-full justify-center"
			onclick={useRepo}
			disabled={busy || !repo.trim()}
		>
			{busy ? 'Cloning…' : 'Use this board'}
		</button>
	{/if}

	{#if error}
		<p class="mt-4 rounded-lg bg-rose-500/10 px-3 py-2 text-sm text-rose-300">{error}</p>
	{/if}
</div>
