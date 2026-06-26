// Lightweight WebSocket client for live updates. Components subscribe via onRealtime();
// the socket auto-connects on first subscription and reconnects if dropped.

export type RealtimeEvent =
	| { type: 'idea'; action: 'updated' | 'deleted'; id: number }
	| { type: 'board' };

type Handler = (e: RealtimeEvent) => void;

const handlers = new Set<Handler>();
let socket: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

function wsUrl(): string {
	const base = import.meta.env.VITE_API_BASE ?? '';
	if (base.startsWith('http')) return base.replace(/^http/, 'ws') + '/api/ws';
	const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
	return `${proto}//${location.host}/api/ws`;
}

function connect() {
	if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING))
		return;
	socket = new WebSocket(wsUrl());
	socket.onmessage = (ev) => {
		try {
			const data = JSON.parse(ev.data) as RealtimeEvent;
			handlers.forEach((h) => h(data));
		} catch {
			/* ignore malformed */
		}
	};
	socket.onclose = () => {
		socket = null;
		if (handlers.size > 0) scheduleReconnect();
	};
	socket.onerror = () => socket?.close();
}

function scheduleReconnect() {
	if (reconnectTimer) clearTimeout(reconnectTimer);
	reconnectTimer = setTimeout(connect, 3000);
}

/** Subscribe to live events. Returns an unsubscribe function. */
export function onRealtime(handler: Handler): () => void {
	handlers.add(handler);
	connect();
	return () => {
		handlers.delete(handler);
	};
}
