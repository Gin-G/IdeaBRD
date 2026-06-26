<script lang="ts">
	let { value = 0, color = '#6366f1' }: { value?: number; color?: string } = $props();
	const clamped = $derived(Math.max(0, Math.min(100, value)));
</script>

<div class="h-1.5 w-full overflow-hidden rounded-full bg-white/10">
	<div
		class="h-full rounded-full transition-all duration-300"
		style="width: {clamped}%; background-color: {color};"
	></div>
</div>
