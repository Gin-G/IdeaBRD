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
	let token = $state('');
	let needsClientId = $state(false);
	let busy = $state(false);
	let error = $state('');
	let copied = $state(false);

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
			// Finishing the device flow means leaving the app, and Android is
			// free to reclaim the app while you are gone. Coming back to the
			// sign-in screen would strand a code you had already authorised,
			// so an unfinished one is put back on screen and waited on again.
			if (status.pendingUserCode) {
				code = {
					deviceCode: '',
					userCode: status.pendingUserCode,
					verificationUri: 'https://github.com/login/device',
					interval: 5,
					expiresIn: status.pendingExpiresIn ?? 900
				};
				step = 'code';
				void waitForCode();
				return;
			}
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
			await waitForCode({
				deviceCode: code.deviceCode,
				interval: code.interval,
				expiresIn: code.expiresIn
			});
		} catch (e) {
			error = e instanceof Error ? e.message : 'Sign-in failed';
			step = 'signin';
		} finally {
			busy = false;
		}
	}

	/**
	 * Wait for the code to be authorised. With no argument this resumes
	 * whatever the native side already has, which is how a sign-in survives
	 * the app being reclaimed mid-flow.
	 */
	async function waitForCode(started?: {
		deviceCode: string;
		interval: number;
		expiresIn: number;
	}) {
		try {
			const status = await Auth.poll({ ...(started ?? {}), ...(clientId ? { clientId } : {}) });
			login = status.login;
			await refresh();
		} catch (e) {
			// A newer sign-in replaced this one; whoever started that is now in
			// charge of the screen, so this should say nothing.
			if ((e as { code?: string })?.code === 'SUPERSEDED') return;
			error = e instanceof Error ? e.message : 'Sign-in failed';
			step = 'signin';
		}
	}

	async function copyCode() {
		if (!code) return;
		try {
			await Auth.copyToClipboard({ text: code.userCode });
			copied = true;
			setTimeout(() => (copied = false), 2000);
		} catch {
			/* the code is on screen to select by hand either way */
		}
	}

	/** Give up on this code and go back, rather than waiting out its 15 minutes. */
	async function startOver() {
		await Auth.cancelSignIn();
		code = null;
		error = '';
		step = 'signin';
	}

	/**
	 * The other way in: a token the person made themselves.
	 *
	 * The device flow needs an OAuth app, and an OAuth app belongs to whoever
	 * registered it — their name is on the consent screen every person sees.
	 * A token they make on their own account skips all of that, and gives the
	 * app exactly the same thing at the end of it.
	 */
	async function useToken() {
		busy = true;
		error = '';
		try {
			const status = await Auth.signInWithToken({ token: token.trim() });
			login = status.login;
			token = '';
			await refresh();
		} catch (e) {
			error = e instanceof Error ? e.message : 'That token was not accepted';
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

	async function openVerification() {
		if (!code) return;
		// Copy first: whether or not GitHub prefills the field, one paste beats
		// long-pressing eight characters out of a web page on a phone.
		await copyCode();
		const url = `${code.verificationUri}?user_code=${encodeURIComponent(code.userCode)}`;
		window.open(url, '_blank');
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
		{#if !needsClientId}
			<button class="btn-primary mt-6 w-full justify-center" onclick={signIn} disabled={busy}>
				{busy ? 'Asking GitHub…' : 'Sign in with GitHub'}
			</button>
			<p class="my-4 text-xs uppercase tracking-widest text-slate-600">or</p>
		{/if}

		<div class="mt-6 rounded-lg border border-white/10 bg-white/5 p-4 text-left">
			<p class="text-sm font-semibold text-slate-200">Use an access token</p>
			<p class="mt-1 text-xs text-slate-400">
				Make one at <span class="font-mono text-slate-300">github.com/settings/tokens</span> with
				the <span class="font-mono text-slate-300">repo</span> scope. It is yours, it stays on this
				device, and no OAuth app or other account is involved.
			</p>
			<input
				class="input mt-3 w-full font-mono text-sm"
				type="password"
				bind:value={token}
				placeholder="ghp_… or github_pat_…"
				spellcheck="false"
				autocomplete="off"
			/>
			<button
				class="btn-primary mt-3 w-full justify-center"
				onclick={useToken}
				disabled={busy || !token.trim()}
			>
				{busy ? 'Checking…' : 'Use this token'}
			</button>
		</div>

		{#if needsClientId}
			<details class="mt-4 text-left">
				<summary class="cursor-pointer text-xs text-slate-500">
					Sign in with an OAuth app instead
				</summary>
				<p class="mt-2 text-xs text-slate-400">
					This build has no GitHub client id compiled in. Paste one from an OAuth app or GitHub
					App with the device flow enabled.
				</p>
				<input
					class="input mt-2 w-full font-mono text-sm"
					bind:value={clientId}
					onchange={saveClientId}
					placeholder="Ov23li… or Iv23li…"
					spellcheck="false"
				/>
				<button
					class="btn-ghost mt-2 w-full justify-center"
					onclick={signIn}
					disabled={busy || !clientId.trim()}
				>
					{busy ? 'Asking GitHub…' : 'Sign in with GitHub'}
				</button>
			</details>
		{/if}
	{:else if step === 'code' && code}
		<h1 class="text-2xl font-bold">Type this code</h1>
		<p class="mt-2 text-sm text-slate-400">
			Open <span class="font-mono text-slate-300">{code.verificationUri}</span> on any device and
			enter:
		</p>
		<button
			class="my-6 w-full select-all rounded-lg border border-white/10 bg-white/5 py-4 font-mono text-3xl font-bold tracking-[0.3em] text-indigo-300"
			onclick={copyCode}
			title="Copy the code"
		>
			{code.userCode}
		</button>
		<button class="btn-primary w-full justify-center" onclick={openVerification}>
			Copy code and open GitHub
		</button>
		<button class="btn-ghost mt-2 w-full justify-center" onclick={copyCode}>
			{copied ? 'Copied' : 'Copy code'}
		</button>
		<p class="mt-4 text-xs text-slate-500">
			Waiting for you to authorise the code… you can leave the app and come back.
		</p>
		<button class="mt-4 text-xs text-slate-500 underline" onclick={startOver}>
			Start again with a new code
		</button>
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
