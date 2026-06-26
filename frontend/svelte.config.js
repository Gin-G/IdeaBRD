import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		// Pure SPA: build static assets with a catch-all fallback served by nginx.
		adapter: adapter({
			fallback: 'index.html',
			strict: false
		})
	}
};

export default config;
