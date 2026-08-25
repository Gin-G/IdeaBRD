import type { CapacitorConfig } from '@capacitor/cli';

/**
 * The Android app is this same SvelteKit board, loaded from the APK instead of
 * over the network.
 *
 * `webDir` is the static build adapter-static already produces, so there is no
 * second front end to keep in step — `npm run build && npx cap copy android`
 * is the whole packaging step. The Gradle project in ../android holds the two
 * native plugins (git, and a Keystore-backed token) that a web page cannot do
 * for itself.
 */
const config: CapacitorConfig = {
	appId: 'net.nickknows.ideabrd',
	appName: 'IdeaBRD',
	webDir: 'build',
	android: {
		path: '../android'
	},
	server: {
		// https rather than the default capacitor:// scheme: the board stores
		// things in localStorage and talks to GitHub, and a non-standard scheme
		// makes both of those behave differently from the browser build.
		androidScheme: 'https'
	}
};

export default config;
