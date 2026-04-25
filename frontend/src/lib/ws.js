/**
 * TARGET WebSocket client.
 * Maintains state_version and ensures every outbound action carries it.
 * Auto-reconnect with backoff. Idempotent action_ids.
 */
import { wsUrl } from "./api";

export function createGameSocket({ tableId, token, onState, onReject, onClose }) {
  let ws = null;
  let stateVersion = 0;
  let closed = false;
  let pingTimer = null;

  const connect = () => {
    ws = new WebSocket(wsUrl(tableId, token));
    ws.onopen = () => {
      pingTimer = setInterval(() => {
        try { ws.send(JSON.stringify({ type: "PING" })); } catch (e) {}
      }, 25000);
    };
    ws.onmessage = (ev) => {
      let data;
      try { data = JSON.parse(ev.data); } catch { return; }
      if (data.type === "PONG") return;
      if (data.type === "STATE_UPDATE") {
        if (typeof data.state_version === "number" && data.state_version >= stateVersion) {
          stateVersion = data.state_version;
          onState && onState(data);
        }
        return;
      }
      if (data.type === "ACTION_REJECTED") {
        if (typeof data.expected_state_version === "number") {
          stateVersion = data.expected_state_version;
        }
        if (data.fresh_state) {
          onState && onState({ view: data.fresh_state, events: [], state_version: data.state_version ?? stateVersion });
        }
        onReject && onReject(data);
        return;
      }
    };
    ws.onclose = () => {
      if (pingTimer) clearInterval(pingTimer);
      pingTimer = null;
      onClose && onClose();
      if (!closed) setTimeout(connect, 1500);
    };
    ws.onerror = () => {
      try { ws.close(); } catch {}
    };
  };

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
    if (pingTimer) clearInterval(pingTimer);
    try { ws && ws.close(); } catch {}
  };

  connect();
  return { send, close };
}
