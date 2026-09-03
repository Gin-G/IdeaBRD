/**
 * What a 401 does.
 *
 * Sessions live in the server's memory, so a restart signs everyone out and
 * the page has to send the browser back through GitHub — which returns
 * without asking anything, because the app is already authorised. That is
 * what makes an in-memory session store acceptable.
 *
 * It has to happen exactly once. A page that redirects on every 401 spins for
 * ever when the sign-in itself is what is broken, and shows nobody an error.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const LOGIN_URL = '/api/auth/login';

async function loadApi() {
	vi.resetModules();
	return await import('../api');
}

function respondWith(status: number, body: unknown = {}) {
	vi.stubGlobal(
		'fetch',
		vi.fn(async () => ({
			ok: status >= 200 && status < 300,
			status,
			statusText: String(status),
			json: async () => body
		}))
	);
}

describe('a 401 from the API', () => {
	beforeEach(() => {
		sessionStorage.clear();
		// jsdom refuses real navigation; watch the assignment instead.
		Object.defineProperty(window, 'location', {
			configurable: true,
			value: { href: '' }
		});
	});

	it('sends the browser to sign in', async () => {
		respondWith(401);
		const { httpApi } = await loadApi();

		await expect(httpApi.me()).rejects.toMatchObject({ status: 401 });

		expect(window.location.href).toContain(LOGIN_URL);
	});

	it('does not send it a second time', async () => {
		respondWith(401);
		const { httpApi } = await loadApi();

		await expect(httpApi.me()).rejects.toMatchObject({ status: 401 });
		window.location.href = '';
		await expect(httpApi.me()).rejects.toMatchObject({ status: 401 });

		expect(window.location.href).toBe('');
	});

	it('arms itself again once a request succeeds', async () => {
		respondWith(401);
		const { httpApi } = await loadApi();
		await expect(httpApi.me()).rejects.toMatchObject({ status: 401 });

		respondWith(200, { id: 1, email: 'a@example.com' });
		await httpApi.me();

		respondWith(401);
		window.location.href = '';
		await expect(httpApi.me()).rejects.toMatchObject({ status: 401 });
		expect(window.location.href).toContain(LOGIN_URL);
	});
});
