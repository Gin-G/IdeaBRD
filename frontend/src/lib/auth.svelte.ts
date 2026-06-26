import { api } from './api';
import type { User } from './types';

// Small reactive auth holder (Svelte 5 runes in a module).
export const auth = $state<{ user: User | null; loading: boolean }>({
	user: null,
	loading: true
});

export async function loadUser() {
	auth.loading = true;
	try {
		auth.user = await api.me();
	} catch {
		auth.user = null;
	} finally {
		auth.loading = false;
	}
}
