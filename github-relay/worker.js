// Whispera GitHub hooks relay.
//
// GitHub App webhooks land on POST /github; a poller on the agent box drains
// them via GET /drain (outbound-only from the box — nothing inbound ever
// reaches it). Events are held in KV for at most 24h.
//
// Request path for /github: per-IP rate limit -> body-size cap -> HMAC
// signature -> event-type filter -> author allowlist -> queue. The allowlist
// runs before queueing so a comment from anyone else never even reaches the
// agent, let alone its LLM.

const MAX_BODY_BYTES = 512 * 1024;
const EVENT_TTL_SECONDS = 24 * 60 * 60;

function csvSet(value, fallback) {
  return new Set(
    (value || fallback)
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean),
  );
}

async function hmacHex(secret, body) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, body);
  return [...new Uint8Array(sig)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let out = 0;
  for (let i = 0; i < a.length; i++) out |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return out === 0;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "POST" && url.pathname === "/github") {
      const ip = request.headers.get("cf-connecting-ip") || "unknown";
      const { success } = await env.GITHUB_RL.limit({ key: ip });
      if (!success) {
        return new Response("rate limited", { status: 429 });
      }

      const body = await request.arrayBuffer();
      if (body.byteLength > MAX_BODY_BYTES) {
        return new Response("too large", { status: 413 });
      }
      const theirSig = request.headers.get("x-hub-signature-256") || "";
      const ourSig = "sha256=" + (await hmacHex(env.WEBHOOK_SECRET, body));
      if (!timingSafeEqual(theirSig, ourSig)) {
        return new Response("bad signature", { status: 401 });
      }

      const event = request.headers.get("x-github-event") || "unknown";
      if (event === "ping") return new Response("pong", { status: 200 });
      const allowedEvents = csvSet(
        env.ALLOWED_EVENTS,
        "issue_comment,pull_request_review_comment",
      );
      if (!allowedEvents.has(event)) {
        return new Response("ignored", { status: 202 });
      }

      const text = new TextDecoder().decode(body);
      let author = "";
      try {
        const payload = JSON.parse(text);
        author = (payload?.comment?.user?.login || "").toLowerCase();
      } catch {
        return new Response("bad json", { status: 400 });
      }
      const allowedAuthors = csvSet(env.ALLOWED_AUTHORS, "sapoepsilon");
      if (!allowedAuthors.has(author)) {
        return new Response("author not allowed", { status: 202 });
      }

      const delivery =
        request.headers.get("x-github-delivery") || crypto.randomUUID();
      const key = `evt:${Date.now().toString().padStart(14, "0")}:${delivery}`;
      await env.EVENTS.put(
        key,
        JSON.stringify({ event, delivery, signature: theirSig, body: text }),
        { expirationTtl: EVENT_TTL_SECONDS },
      );
      // Flag key lets /drain skip the expensive KV list when the queue is
      // empty (KV free tier allows only 1k list ops/day vs 100k gets).
      await env.EVENTS.put("pending", "1", {
        expirationTtl: EVENT_TTL_SECONDS,
      });
      return new Response("queued", { status: 202 });
    }

    if (request.method === "GET" && url.pathname === "/drain") {
      const auth = request.headers.get("authorization") || "";
      if (!timingSafeEqual(auth, `Bearer ${env.POLL_TOKEN}`)) {
        return new Response("unauthorized", { status: 401 });
      }
      // Cheap read first: no flag -> nothing queued -> no list operation.
      const pending = await env.EVENTS.get("pending");
      if (pending === null) {
        return Response.json({ events: [] });
      }
      const list = await env.EVENTS.list({ prefix: "evt:", limit: 20 });
      const events = [];
      for (const entry of list.keys) {
        const value = await env.EVENTS.get(entry.name);
        if (value !== null) {
          events.push(JSON.parse(value));
          await env.EVENTS.delete(entry.name);
        }
      }
      // Clear the flag only when this page drained the whole queue.
      if (list.list_complete) {
        await env.EVENTS.delete("pending");
      }
      return Response.json({ events });
    }

    return new Response("not found", { status: 404 });
  },
};
