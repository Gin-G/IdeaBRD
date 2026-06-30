import { api } from './api';
import type { Providers, User } from './types';

// Small reactive auth holder (Svelte 5 runes in a module).
export const auth = $state<{
	user: User | null;
	loading: boolean;
	providers: Providers;
}>({
	user: null,
	loading: true,
	providers: { google: true, github: false, dev: false }
});

export async function loadUser() {
	auth.loading = true;
	try {
		auth.providers = await api.providers();
	} catch {
		/* keep defaults */
	}
	try {
		auth.user = await api.me();
	} catch {
		auth.user = null;
	} finally {
		auth.loading = false;
	}
}
