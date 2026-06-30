// Outbound relay client. Dials OUT to the Cloudflare Worker, holds the
// WebSocket open, and replays each pushed Linear webhook (with its original
// headers, so HMAC still verifies) to the local handler. No inbound port.
// Uses Node 22's built-in global WebSocket — no dependencies.
const http = require("http");

const WORKER_WS = process.env.WORKER_WS;           // wss://<name>.<sub>.workers.dev/connect
const TARGET = process.env.TARGET || "http://127.0.0.1:8645/";

if (!WORKER_WS) { console.error("set WORKER_WS"); process.exit(1); }

function connect() {
  const ws = new WebSocket(WORKER_WS);
  let ping;
  ws.addEventListener("open", () => {
    console.log("connected to relay");
    ping = setInterval(() => { try { ws.send("ping"); } catch (_) {} }, 30000);
  });
  ws.addEventListener("message", (event) => {
    let msg;
    try { msg = JSON.parse(typeof event.data === "string" ? event.data : event.data.toString()); }
    catch (_) { return; } // skip pong / non-JSON
    if (!msg || !msg.body) return;
    const u = new URL(TARGET);
    const req = http.request({
      hostname: u.hostname, port: u.port || 80, path: u.pathname, method: "POST",
      headers: { ...msg.headers, "Content-Length": Buffer.byteLength(msg.body) },
    }, (res) => res.resume());
    req.on("error", (e) => console.log("forward error:", e.message));
    req.write(msg.body);
    req.end();
  });
  ws.addEventListener("close", () => {
    clearInterval(ping);
    console.log("disconnected; retrying in 3s");
    setTimeout(connect, 3000);
  });
  ws.addEventListener("error", (e) => console.log("ws error:", e.message || "error"));
}

connect();
