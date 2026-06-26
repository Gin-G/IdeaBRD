import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		// In dev the SPA runs on :5173 and proxies API calls to the FastAPI backend.
		proxy: {
			'/api': {
				target: process.env.VITE_API_PROXY || 'http://localhost:8000',
				changeOrigin: true
			}
		}
	}
});
