<script lang="ts">
	import { api, connectGithub, ApiError } from '$lib/api';
	import { isNative } from '$lib/native/plugins';
	import { nativeApi } from '$lib/native/api';
	import type { BoardOwner, Idea } from '$lib/types';

	let {
		idea,
		oncreated
	}: { idea: Idea; oncreated: (updated: Idea) => void } = $props();

	let open = $state(false);
	// Pointing an idea at a repo that already exists is the device's own path:
	// in the browser the same thing is the repo field in the edit dialog, where
	// the server handles the opt-in.
	const canLinkExisting = isNative();
	let mode = $state<'create' | 'link'>('create');
	let existing = $state('');
	// Set when the named repo has no IDEA.md, so linking would mean writing one
	// into it. Nothing has been changed at that point.
	let confirmSeed = $state(false);
	let owners = $state<BoardOwner[]>([]);
	let owner = $state('');
	let name = $state('');
	let isPrivate = $state(true);
	let busy = $state(false);
	let error = $state('');
	let needsGithub = $state(false);

	/** The repo name this idea would suggest for itself. */
	function suggest(title: string): string {
		return (
			title
				.toLowerCase()
				.normalize('NFKD')
				.replace(/[^a-z0-9]+/g, '-')
				.replace(/^-+|-+$/g, '')
				.slice(0, 60) || 'idea'
		);
	}

	async function start() {
		open = true;
		name = suggest(idea.title);
		error = '';
		try {
			const found = await api.boardOwners();
			owners = found.owners;
			owner = owners[0]?.login ?? '';
		} catch (e) {
			needsGithub = e instanceof ApiError && e.status === 400;
			if (!needsGithub) error = e instanceof Error ? e.message : 'Could not reach GitHub';
		}
	}

	async function link(seed = false) {
		busy = true;
		error = '';
		try {
			const result = await nativeApi.linkIdeaRepo(idea.id, existing.trim(), seed);
			if (result.needsSeed) {
				confirmSeed = true;
			} else if (result.idea) {
				oncreated(result.idea);
				open = false;
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'Could not link that repository';
		} finally {
			busy = false;
		}
	}

	async function create() {
		busy = true;
		error = '';
		try {
			const isOrg = owners.find((o) => o.login === owner)?.kind === 'org';
			oncreated(await api.giveIdeaRepo(idea.id, name.trim(), isOrg ? owner : null, isPrivate));
			open = false;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Could not create the repository';
		} finally {
			busy = false;
		}
	}
</script>

<div class="card p-5">
	<h3 class="mb-2 font-semibold">Give this idea a repo</h3>
	<p class="text-xs leading-relaxed text-slate-400">
		An idea kept on a board has nowhere for anyone else to link. Its own repository is what
		sharing means: people are added there, work happens in branches and pull requests, and every
		board that carries this idea records a pointer to it instead of a copy.
	</p>

	{#if needsGithub}
		<button class="btn-primary mt-3 w-full justify-center" onclick={connectGithub}>
			Connect GitHub
		</button>
	{:else if !open}
		<button class="btn-ghost mt-3 w-full justify-center" onclick={start}>Create a repository</button
		>
	{:else if mode === 'link'}
		<div class="mt-3 space-y-3">
			<label class="block text-sm">
				<span class="mb-1 block text-xs text-slate-400">Repository</span>
				<input
					class="input w-full font-mono text-sm"
					bind:value={existing}
					placeholder="owner/name"
					spellcheck="false"
				/>
			</label>
			{#if confirmSeed}
				<div class="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200">
					That repository has no <span class="font-mono">IDEA.md</span>. Linking it means
					committing one there from this idea. Nothing has been written yet.
				</div>
				<button
					class="btn-primary w-full justify-center"
					onclick={() => link(true)}
					disabled={busy}
				>
					{busy ? 'Committing…' : 'Add IDEA.md and link'}
				</button>
			{:else}
				<button
					class="btn-primary w-full justify-center"
					onclick={() => link()}
					disabled={busy || !existing.trim()}
				>
					{busy ? 'Cloning…' : 'Link this repo'}
				</button>
			{/if}
			<button
				class="btn-ghost w-full justify-center"
				onclick={() => {
					mode = 'create';
					confirmSeed = false;
				}}>Create one instead</button
			>
		</div>
	{:else}
		<div class="mt-3 space-y-3">
			{#if owners.length > 1}
				<label class="block text-sm">
					<span class="mb-1 block text-xs text-slate-400">Owner</span>
					<select class="input w-full" bind:value={owner}>
						{#each owners as o (o.login)}
							<option value={o.login}>{o.login}{o.kind === 'org' ? ' (org)' : ''}</option>
						{/each}
					</select>
				</label>
			{/if}
			<label class="block text-sm">
				<span class="mb-1 block text-xs text-slate-400">Repository name</span>
				<input class="input w-full font-mono text-sm" bind:value={name} spellcheck="false" />
			</label>
			<label class="flex items-center gap-2 text-sm text-slate-300">
				<input type="checkbox" bind:checked={isPrivate} />
				Private
			</label>
			<p class="text-xs text-slate-500">
				The notes, to-dos and tile image move into
				<span class="font-mono">IDEA.md</span> in the new repo, which then becomes the source of truth
				for them.
			</p>
			<div class="flex gap-2">
				<button class="btn-ghost flex-1 justify-center" onclick={() => (open = false)}>
					Cancel
				</button>
				<button
					class="btn-primary flex-1 justify-center"
					onclick={create}
					disabled={busy || !name.trim()}
				>
					{busy ? 'Creating…' : 'Create'}
				</button>
			</div>
			{#if canLinkExisting}
				<button
					class="w-full text-xs text-slate-500 hover:text-slate-300"
					onclick={() => (mode = 'link')}>Use a repository I already have</button
				>
			{/if}
		</div>
	{/if}

	{#if error}<p class="mt-3 text-sm text-rose-300">{error}</p>{/if}
</div>
