<script lang="ts">
	let {
		logo = null,
		title = '',
		color = '#6366f1',
		size = 'md'
	}: { logo?: string | null; title?: string; color?: string; size?: 'md' | 'lg' } = $props();

	const isUrl = $derived(!!logo && /^https?:\/\//.test(logo));
	const fallback = $derived(title.trim().charAt(0).toUpperCase() || '◆');
	const box = $derived(size === 'lg' ? 'h-14 w-14 text-2xl' : 'h-11 w-11 text-xl');
</script>

{#if isUrl}
	<img
		src={logo}
		alt=""
		class="{box} shrink-0 rounded-xl object-cover ring-1 ring-white/10"
	/>
{:else}
	<div
		class="{box} grid shrink-0 place-items-center rounded-xl font-bold text-white ring-1 ring-white/10"
		style="background: linear-gradient(135deg, {color}, {color}aa);"
	>
		{logo || fallback}
	</div>
{/if}
