/**
 * TARGET WebSocket client.
 * Maintains state_version and ensures every outbound action carries it.
 * Auto-reconnect with backoff. Idempotent action_ids.
 *
 * The connection lifecycle hooks (onopen/onmessage/onclose/onerror) are kept
 * thin — they delegate to the small, named helpers declared above `connect()`.
 * That keeps cyclomatic complexity low and behaviour identical to the
 * single-function form.
 */
import { wsUrl } from "./api";

const PING_INTERVAL_MS = 25000;
const RECONNECT_DELAY_MS = 1500;

export function createGameSocket({ tableId, token, onState, onReject, onClose }) {
  let ws = null;
  let stateVersion = 0;
  let closed = false;
  let pingTimer = null;

  // ---- message-type handlers (no side effects on the socket itself) ----

  const handleStateUpdate = (data) => {
    if (typeof data.state_version === "number" && data.state_version >= stateVersion) {
      stateVersion = data.state_version;
      onState && onState(data);
    }
  };

  const handleActionRejected = (data) => {
    if (typeof data.expected_state_version === "number") {
      stateVersion = data.expected_state_version;
    }
    if (data.fresh_state) {
      onState && onState({
        view: data.fresh_state,
        events: [],
        state_version: data.state_version ?? stateVersion,
      });
    }
    onReject && onReject(data);
  };

  const dispatch = (data) => {
    switch (data.type) {
      case "PONG":
        return;
      case "STATE_UPDATE":
        handleStateUpdate(data);
        return;
      case "ACTION_REJECTED":
        handleActionRejected(data);
        return;
      default:
        // Unknown message types are dropped silently to keep forward-compat.
        return;
    }
  };

  // ---- socket lifecycle helpers ----

  const startPings = () => {
    pingTimer = setInterval(() => {
      try {
        ws.send(JSON.stringify({ type: "PING" }));
      } catch (e) {
        console.warn("ws: PING send failed", e);
      }
    }, PING_INTERVAL_MS);
  };

  const stopPings = () => {
    if (pingTimer) clearInterval(pingTimer);
    pingTimer = null;
  };

  const onMessage = (ev) => {
    let data;
    try {
      data = JSON.parse(ev.data);
    } catch (e) {
      console.warn("ws: malformed message dropped", e);
      return;
    }
    dispatch(data);
  };

  const onSocketClose = () => {
    stopPings();
    onClose && onClose();
    if (!closed) setTimeout(connect, RECONNECT_DELAY_MS);
  };

  const onSocketError = (e) => {
    console.warn("ws: socket error", e);
    try {
      ws.close();
    } catch (closeErr) {
      console.warn("ws: error while closing after socket error", closeErr);
    }
  };

  // ---- connect ----

  const connect = () => {
    ws = new WebSocket(wsUrl(tableId, token));
    ws.onopen = startPings;
    ws.onmessage = onMessage;
    ws.onclose = onSocketClose;
    ws.onerror = onSocketError;
  };

  // ---- public API ----

  const send = (type, payload = {}) => {
    if (!ws || ws.readyState !== 1) return false;
    const intent = {
      type,
      client_action_id: crypto.randomUUID(),
      state_version: stateVersion,
      payload,
    };
    ws.send(JSON.stringify(intent));
    return true;
  };

  const close = () => {
    closed = true;
    stopPings();
    try {
      ws && ws.close();
    } catch (e) {
      console.warn("ws: error while closing socket", e);
    }
  };

  connect();
  return { send, close };
}
