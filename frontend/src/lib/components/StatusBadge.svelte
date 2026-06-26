<script lang="ts">
	import { STATUS_STYLES, type Status } from '$lib/types';
	let { status }: { status: Status } = $props();
</script>

<span
	class="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize {STATUS_STYLES[
		status
	]}"
>
	{status}
</span>
