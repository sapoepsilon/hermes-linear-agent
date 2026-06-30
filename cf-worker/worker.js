// Hermes Linear relay — a public webhook ingress that pushes events down a
// held-open WebSocket dialed OUT by the agent box. Nothing on your network is
// exposed. The relay is dumb transport: the handler HMAC-verifies, so the
// Worker (and Cloudflare) cannot forge a valid event.
//
// Routes:
//   POST /linear   <- Linear posts webhooks here (set this as the Linear webhook URL)
//   GET  /connect  <- the agent-box client dials in here (WebSocket), holds it open
//
// One Durable Object instance bridges the two.

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const id = env.RELAY.idFromName("relay");
    const stub = env.RELAY.get(id);
    if (url.pathname === "/linear" || url.pathname === "/connect") {
      return stub.fetch(request);
    }
    return new Response("hermes-linear-relay", { status: 200 });
  },
};

export class Relay {
  constructor(state) {
    this.state = state;
  }

  async fetch(request) {
    const url = new URL(request.url);

    if (url.pathname === "/connect") {
      if (request.headers.get("Upgrade") !== "websocket") {
        return new Response("expected websocket", { status: 426 });
      }
      const pair = new WebSocketPair();
      // hibernation API: survives the DO being evicted between events
      this.state.acceptWebSocket(pair[1]);
      return new Response(null, { status: 101, webSocket: pair[0] });
    }

    if (url.pathname === "/linear" && request.method === "POST") {
      const body = await request.text();
      const payload = JSON.stringify({
        headers: {
          "Linear-Signature": request.headers.get("Linear-Signature") || "",
          "Linear-Delivery": request.headers.get("Linear-Delivery") || "",
          "Content-Type": request.headers.get("Content-Type") || "application/json",
        },
        body,
      });
      const sockets = this.state.getWebSockets();
      for (const ws of sockets) {
        try { ws.send(payload); } catch (_) { /* drop dead sockets */ }
      }
      // ack Linear immediately; the home box processes async
      return new Response(JSON.stringify({ ok: true, delivered: sockets.length }), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }

    return new Response("not found", { status: 404 });
  }

  async webSocketMessage(ws, message) {
    // home client may send "ping"; reply so it can detect liveness
    if (message === "ping") { try { ws.send("pong"); } catch (_) {} }
  }

  async webSocketClose(ws) {
    try { ws.close(); } catch (_) {}
  }
}
