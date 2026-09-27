/**
 * Contract tests for the confidential control boundary.
 *
 * These tests use synthetic tokens and an in-memory GitHub surface. They prove
 * identity rejection and operation ordering; they do not claim that production
 * OAuth credentials or Cloudflare deployment exist.
 */

import assert from "node:assert/strict";
import test from "node:test";
import worker, { handleRequest } from "./worker.mjs";

const env = {
  GITHUB_CLIENT_ID: "client",
  GITHUB_CLIENT_SECRET: "secret",
  SESSION_SECRET: "test-only-session-secret",
  OWNER_GITHUB_ID: "14032554",
  PAGES_URL: "https://sudofx.github.io/sudofx/",
  REPOSITORY: "sudofx/sudofx",
};

async function ownerSession() {
  const loginResponse = await handleRequest(new Request("https://control.example/auth/login"), env);
  const authorization = new URL(loginResponse.headers.get("Location"));
  const callback = new URL("https://control.example/auth/callback");
  callback.searchParams.set("code", "authorized-code");
  callback.searchParams.set("state", authorization.searchParams.get("state"));
  const callbackResponse = await handleRequest(
    new Request(callback),
    env,
    async (url) => {
      if (url === "https://github.com/login/oauth/access_token") {
        return Response.json({ access_token: "owner-token", expires_in: 3600 });
      }
      if (url === "https://api.github.com/user") {
        return Response.json({ id: 14032554, login: "sudofx" });
      }
      throw new Error(`unexpected OAuth request: ${url}`);
    },
  );
  assert.equal(callbackResponse.status, 302);
  const fragment = new URL(callbackResponse.headers.get("Location")).hash;
  return decodeURIComponent(fragment.slice("#sudofx-control=".length));
}

test("unauthenticated API calls never reveal owner controls", async () => {
  const response = await handleRequest(
    new Request("https://control.example/api/session", {
      headers: { Origin: "https://sudofx.github.io" },
    }),
    env,
  );
  assert.equal(response.status, 401);
});

test("an unrelated web origin is rejected before GitHub is contacted", async () => {
  let contacted = false;
  const response = await handleRequest(
    new Request("https://control.example/api/session", {
      headers: { Origin: "https://attacker.example", Authorization: "Bearer invalid" },
    }),
    env,
    async () => { contacted = true; return new Response(); },
  );
  assert.equal(response.status, 403);
  assert.equal(contacted, false);
});

test("login uses GitHub OAuth with PKCE and the exact callback", async () => {
  const response = await handleRequest(new Request("https://control.example/auth/login"), env);
  assert.equal(response.status, 302);
  const target = new URL(response.headers.get("Location"));
  assert.equal(target.origin, "https://github.com");
  assert.equal(target.pathname, "/login/oauth/authorize");
  assert.equal(target.searchParams.get("client_id"), "client");
  assert.equal(target.searchParams.get("redirect_uri"), "https://control.example/auth/callback");
  assert.equal(target.searchParams.get("code_challenge_method"), "S256");
  assert.ok(target.searchParams.get("state"));
  assert.ok(target.searchParams.get("code_challenge"));
});

test("Cloudflare execution context never becomes the GitHub transport", async () => {
  // Cloudflare always supplies a third execution-context argument. The public
  // adapter must ignore it here; only direct handleRequest tests may inject a
  // synthetic GitHub transport into the confidential provider boundary.
  const context = { waitUntil() { throw new Error("context must stay lifecycle-only"); } };
  const response = await worker.fetch(
    new Request("https://control.example/auth/login"),
    env,
    context,
  );
  assert.equal(response.status, 302);
  assert.equal(new URL(response.headers.get("Location")).origin, "https://github.com");
});

test("OAuth provider failures stay inside the Worker error boundary", async () => {
  // Provider rejection is expected operational evidence, not a Worker crash.
  // Preserving the JSON boundary gives the operator a diagnosis and prevents
  // Cloudflare's opaque Error 1101 page from replacing the product interface.
  const loginResponse = await handleRequest(new Request("https://control.example/auth/login"), env);
  const authorization = new URL(loginResponse.headers.get("Location"));
  const callback = new URL("https://control.example/auth/callback");
  callback.searchParams.set("code", "rejected-code");
  callback.searchParams.set("state", authorization.searchParams.get("state"));
  const response = await handleRequest(
    new Request(callback),
    env,
    async () => { throw new Error("simulated provider rejection"); },
  );
  assert.equal(response.status, 502);
  assert.deepEqual(await response.json(), { error: "simulated provider rejection" });
});

test("authenticated session reports storage maintenance metadata without database contents", async () => {
  /**
   * Owner diagnostics may reveal size and protection posture, but the Worker
   * must never download or return the authoritative SQLite payload itself.
   */
  const session = await ownerSession();
  const response = await handleRequest(
    new Request("https://control.example/api/session", {
      headers: { Origin: "https://sudofx.github.io", Authorization: `Bearer ${session}` },
    }),
    env,
    async (url) => {
      const parsed = new URL(url);
      if (parsed.pathname.endsWith("/actions/workflows/prove-model.yml")) {
        return Response.json({ state: "disabled_manually" });
      }
      if (parsed.pathname.endsWith("/actions/workflows/prove-model.yml/runs")) {
        return Response.json({ workflow_runs: [] });
      }
      if (parsed.pathname === "/repos/sudofx/sudofx") {
        return Response.json({ visibility: "public", private: false });
      }
      if (parsed.pathname.endsWith("/branches/sudofx-state")) {
        return Response.json({ protected: false, commit: { sha: "state-head" } });
      }
      if (parsed.pathname.endsWith("/contents/sudofx.sqlite")) {
        assert.equal(parsed.searchParams.get("ref"), "sudofx-state");
        return Response.json({ size: 24576, sha: "database-blob" });
      }
      throw new Error(`unexpected session request: ${url}`);
    },
  );
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.deepEqual(body.capabilities, ["backup", "storage-diagnostics"]);
  assert.deepEqual(body.maintenance, {
    repositoryVisibility: "public",
    stateBranchProtected: false,
    stateBranchHead: "state-head",
    databaseBytes: 24576,
    databaseBlob: "database-blob",
  });
  assert.equal(JSON.stringify(body).includes("content"), false);
});

test("missing diagnostics permission does not disable authenticated workflow controls", async () => {
  const session = await ownerSession();
  const response = await handleRequest(
    new Request("https://control.example/api/session", {
      headers: { Origin: "https://sudofx.github.io", Authorization: `Bearer ${session}` },
    }),
    env,
    async (url) => {
      const path = new URL(url).pathname;
      if (path.endsWith("/actions/workflows/prove-model.yml")) {
        return Response.json({ state: "active" });
      }
      if (path.endsWith("/actions/workflows/prove-model.yml/runs")) {
        return Response.json({ workflow_runs: [] });
      }
      return new Response("permission missing", { status: 403 });
    },
  );
  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.enabled, true);
  assert.equal(body.maintenance.unavailable, true);
});

test("Start enables the workflow before dispatching one bootstrap", async () => {
  const session = await ownerSession();
  const operations = [];
  const response = await handleRequest(
    new Request("https://control.example/api/start", {
      method: "POST",
      headers: { Origin: "https://sudofx.github.io", Authorization: `Bearer ${session}` },
    }),
    env,
    async (url, init) => {
      operations.push([url, init.method]);
      return new Response(null, { status: 204 });
    },
  );
  assert.equal(response.status, 200);
  assert.deepEqual(operations.map(([url, method]) => [new URL(url).pathname, method]), [
    ["/repos/sudofx/sudofx/actions/workflows/prove-model.yml/enable", "PUT"],
    ["/repos/sudofx/sudofx/actions/workflows/prove-model.yml/dispatches", "POST"],
  ]);
});

test("Backup dispatches only the named verified recovery action", async () => {
  const session = await ownerSession();
  const operations = [];
  const response = await handleRequest(
    new Request("https://control.example/api/backup", {
      method: "POST",
      headers: { Origin: "https://sudofx.github.io", Authorization: `Bearer ${session}` },
    }),
    env,
    async (url, init) => {
      operations.push([new URL(url).pathname, init.method, JSON.parse(init.body)]);
      return new Response(null, { status: 204 });
    },
  );
  assert.equal(response.status, 200);
  assert.deepEqual(operations, [[
    "/repos/sudofx/sudofx/actions/workflows/sudofx.yml/dispatches",
    "POST",
    { ref: "master", inputs: { action: "backup" } },
  ]]);
});

test("Stop disables the workflow before discovering and cancelling active runs", async () => {
  const session = await ownerSession();
  const operations = [];
  const response = await handleRequest(
    new Request("https://control.example/api/stop", {
      method: "POST",
      headers: { Origin: "https://sudofx.github.io", Authorization: `Bearer ${session}` },
    }),
    env,
    async (url, init) => {
      const path = new URL(url).pathname;
      operations.push([path, init.method || "GET"]);
      if (path.endsWith("/prove-model.yml")) return Response.json({ state: "disabled_manually" });
      if (path.endsWith("/runs")) return Response.json({ workflow_runs: [{ id: 42, status: "in_progress", html_url: "https://example/run/42" }] });
      return new Response(null, { status: 204 });
    },
  );
  assert.equal(response.status, 200);
  assert.deepEqual(operations, [
    ["/repos/sudofx/sudofx/actions/workflows/prove-model.yml/disable", "PUT"],
    ["/repos/sudofx/sudofx/actions/workflows/prove-model.yml", "GET"],
    ["/repos/sudofx/sudofx/actions/workflows/prove-model.yml/runs", "GET"],
    ["/repos/sudofx/sudofx/actions/runs/42/cancel", "POST"],
  ]);
});
