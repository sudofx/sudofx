/**
 * SUDOFX OWNER CONTROL SERVICE
 * ============================
 *
 * This Cloudflare Worker is the confidential half of the phone controls. The
 * public GitHub Pages document can request authentication, but only this service
 * holds the GitHub App client secret and only GitHub can establish identity.
 *
 * Authority is deliberately narrow:
 *
 *   GitHub OAuth -> proves the current user is the repository owner
 *   encrypted envelope -> carries one short-lived browser session
 *   Actions API -> enables, disables, dispatches, or cancels prove-model.yml
 *
 * The Worker never edits source, durable SQLite state, secrets, or arbitrary
 * workflows. A successful Stop disables the workflow before cancellation so a
 * concurrently finishing run cannot create another successor. Start performs
 * the reverse transition: enable first, then dispatch exactly one bootstrap.
 */

const API_VERSION = "2026-03-10";
const WORKFLOW = "prove-model.yml";
const OPERATIONS_WORKFLOW = "sudofx.yml";
const SESSION_SECONDS = 60 * 60 * 7;
const OAUTH_SECONDS = 60 * 10;

function base64url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function fromBase64url(value) {
  const normalized = value.replaceAll("-", "+").replaceAll("_", "/");
  const binary = atob(normalized + "=".repeat((4 - (normalized.length % 4)) % 4));
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function randomToken(size = 32) {
  const bytes = new Uint8Array(size);
  crypto.getRandomValues(bytes);
  return base64url(bytes);
}

async function sessionKey(secret) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(secret));
  return crypto.subtle.importKey("raw", digest, "AES-GCM", false, ["encrypt", "decrypt"]);
}

async function seal(payload, secret) {
  const iv = new Uint8Array(12);
  crypto.getRandomValues(iv);
  const plaintext = new TextEncoder().encode(JSON.stringify(payload));
  const ciphertext = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await sessionKey(secret), plaintext);
  return `${base64url(iv)}.${base64url(new Uint8Array(ciphertext))}`;
}

async function open(envelope, secret, expectedKind) {
  const [ivPart, ciphertextPart, extra] = String(envelope || "").split(".");
  if (!ivPart || !ciphertextPart || extra) throw new Error("invalid session envelope");
  const plaintext = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: fromBase64url(ivPart) },
    await sessionKey(secret),
    fromBase64url(ciphertextPart),
  );
  const payload = JSON.parse(new TextDecoder().decode(plaintext));
  if (payload.kind !== expectedKind || !Number.isFinite(payload.exp) || payload.exp <= Date.now()) {
    throw new Error("expired or mismatched session envelope");
  }
  return payload;
}

function configured(env) {
  const required = ["GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET", "SESSION_SECRET", "OWNER_GITHUB_ID", "PAGES_URL", "REPOSITORY"];
  return required.every((name) => typeof env[name] === "string" && env[name].length > 0);
}

function pagesOrigin(env) {
  return new URL(env.PAGES_URL).origin;
}

function cors(env) {
  return {
    "Access-Control-Allow-Origin": pagesOrigin(env),
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Cache-Control": "no-store",
    Vary: "Origin",
  };
}

function json(env, body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...cors(env), "Content-Type": "application/json; charset=utf-8" },
  });
}

async function github(path, token, init = {}, githubFetch = fetch) {
  const response = await githubFetch(`https://api.github.com${path}`, {
    ...init,
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "X-GitHub-Api-Version": API_VERSION,
      "User-Agent": "sudofx-owner-control",
      ...(init.headers || {}),
    },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`GitHub ${response.status}: ${detail.slice(0, 240)}`);
  }
  return response;
}

async function authorizedSession(request, env) {
  const authorization = request.headers.get("Authorization") || "";
  if (!authorization.startsWith("Bearer ")) throw new Error("missing owner session");
  const session = await open(authorization.slice(7), env.SESSION_SECRET, "session");
  if (String(session.ownerId) !== String(env.OWNER_GITHUB_ID)) throw new Error("owner mismatch");
  return session;
}

async function workflowStatus(env, token, githubFetch) {
  const workflowResponse = await github(
    `/repos/${env.REPOSITORY}/actions/workflows/${WORKFLOW}`,
    token,
    {},
    githubFetch,
  );
  const workflow = await workflowResponse.json();
  const runsResponse = await github(
    `/repos/${env.REPOSITORY}/actions/workflows/${WORKFLOW}/runs?per_page=20`,
    token,
    {},
    githubFetch,
  );
  const runs = (await runsResponse.json()).workflow_runs || [];
  const active = runs.filter((run) => run.status !== "completed");
  return {
    enabled: workflow.state === "active",
    activeRuns: active.map((run) => ({ id: run.id, status: run.status, url: run.html_url })),
  };
}

async function maintenanceStatus(env, token, githubFetch) {
  /**
   * Read repository-backed storage risk without downloading SQLite contents.
   *
   * GitHub metadata is operational evidence, not database authority. Keeping
   * this behind the owner session avoids advertising storage topology on the
   * public page while giving the operator a truthful privacy/protection signal.
   */
  const [repositoryResponse, branchResponse, databaseResponse] = await Promise.all([
    github(`/repos/${env.REPOSITORY}`, token, {}, githubFetch),
    github(`/repos/${env.REPOSITORY}/branches/sudofx-state`, token, {}, githubFetch),
    github(`/repos/${env.REPOSITORY}/contents/sudofx.sqlite?ref=sudofx-state`, token, {}, githubFetch),
  ]);
  const repository = await repositoryResponse.json();
  const branch = await branchResponse.json();
  const database = await databaseResponse.json();
  return {
    repositoryVisibility: repository.visibility || (repository.private ? "private" : "public"),
    stateBranchProtected: Boolean(branch.protected),
    stateBranchHead: String(branch.commit?.sha || ""),
    databaseBytes: Number(database.size || 0),
    databaseBlob: String(database.sha || ""),
  };
}

async function login(request, env) {
  const verifier = randomToken(48);
  const challengeBytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  const state = await seal(
    { kind: "oauth", verifier, nonce: randomToken(), exp: Date.now() + OAUTH_SECONDS * 1000 },
    env.SESSION_SECRET,
  );
  const callback = `${new URL(request.url).origin}/auth/callback`;
  const target = new URL("https://github.com/login/oauth/authorize");
  target.searchParams.set("client_id", env.GITHUB_CLIENT_ID);
  target.searchParams.set("redirect_uri", callback);
  target.searchParams.set("state", state);
  target.searchParams.set("code_challenge", base64url(new Uint8Array(challengeBytes)));
  target.searchParams.set("code_challenge_method", "S256");
  target.searchParams.set("allow_signup", "false");
  return Response.redirect(target.toString(), 302);
}

async function callback(request, env, githubFetch) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const state = await open(url.searchParams.get("state"), env.SESSION_SECRET, "oauth");
  if (!code) throw new Error("GitHub did not return an authorization code");

  // Client-secret and token exchange remain server-side. PKCE binds the returned
  // code to the exact browser flow even if an authorization URL is intercepted.
  const tokenResponse = await githubFetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify({
      client_id: env.GITHUB_CLIENT_ID,
      client_secret: env.GITHUB_CLIENT_SECRET,
      code,
      redirect_uri: `${url.origin}/auth/callback`,
      code_verifier: state.verifier,
    }),
  });
  if (!tokenResponse.ok) throw new Error("GitHub token exchange failed");
  const token = await tokenResponse.json();
  if (!token.access_token) throw new Error(token.error_description || "GitHub returned no access token");

  const userResponse = await github("/user", token.access_token, {}, githubFetch);
  const user = await userResponse.json();
  if (String(user.id) !== String(env.OWNER_GITHUB_ID)) {
    return new Response("This GitHub account is not authorized to control sudofx.", { status: 403 });
  }

  // The browser receives only authenticated ciphertext in the URL fragment.
  // Fragments are not sent to Pages, referrers, proxies, or server logs. The
  // public script keeps it in sessionStorage and cannot recover the GitHub token.
  const lifetime = Math.min(Number(token.expires_in || SESSION_SECONDS), SESSION_SECONDS);
  const envelope = await seal(
    {
      kind: "session",
      ownerId: user.id,
      login: user.login,
      accessToken: token.access_token,
      exp: Date.now() + lifetime * 1000,
    },
    env.SESSION_SECRET,
  );
  const destination = new URL(env.PAGES_URL);
  destination.hash = `sudofx-control=${encodeURIComponent(envelope)}`;
  return Response.redirect(destination.toString(), 302);
}

async function start(env, session, githubFetch) {
  await github(
    `/repos/${env.REPOSITORY}/actions/workflows/${WORKFLOW}/enable`,
    session.accessToken,
    { method: "PUT" },
    githubFetch,
  );
  await github(
    `/repos/${env.REPOSITORY}/actions/workflows/${WORKFLOW}/dispatches`,
    session.accessToken,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ref: "master", inputs: { dispatch_token: `owner-${Date.now()}` } }),
    },
    githubFetch,
  );
  return { enabled: true, message: "Continuous operation is starting." };
}

async function stop(env, session, githubFetch) {
  // Disable first. A run that reaches its continuation step during cancellation
  // can no longer dispatch a successor, closing the only race that could make a
  // Stop appear successful while another cycle escaped into the queue.
  await github(
    `/repos/${env.REPOSITORY}/actions/workflows/${WORKFLOW}/disable`,
    session.accessToken,
    { method: "PUT" },
    githubFetch,
  );
  const status = await workflowStatus(env, session.accessToken, githubFetch);
  const cancellations = status.activeRuns.map((run) =>
    github(
      `/repos/${env.REPOSITORY}/actions/runs/${run.id}/cancel`,
      session.accessToken,
      { method: "POST" },
      githubFetch,
    ).catch(() => null),
  );
  await Promise.all(cancellations);
  return { enabled: false, cancelledRuns: status.activeRuns.length, message: "Continuous operation is stopped." };
}

async function backup(env, session, githubFetch) {
  /**Request one verified, finite-retention recovery artifact.
   *
   * The Worker only dispatches the named maintenance action. The workflow and
   * storage adapter own restore, verification, snapshotting, and retention, so
   * browser authentication never becomes database authority.
   */
  await github(
    `/repos/${env.REPOSITORY}/actions/workflows/${OPERATIONS_WORKFLOW}/dispatches`,
    session.accessToken,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ref: "master", inputs: { action: "backup" } }),
    },
    githubFetch,
  );
  return { message: "Verified recovery backup requested." };
}

export async function handleRequest(request, env, githubFetch = fetch) {
  if (!configured(env)) return new Response("Control service is not configured.", { status: 503 });
  const url = new URL(request.url);
  if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(env) });

  try {
    // Await every asynchronous route inside this boundary. Returning a pending
    // promise would let its later rejection escape this catch block, turning a
    // useful OAuth or GitHub error into Cloudflare's opaque Worker Error 1101.
    // The request still completes asynchronously; ownership here means failures
    // are translated before control leaves the service's public interface.
    if (url.pathname === "/auth/login" && request.method === "GET") return await login(request, env);
    if (url.pathname === "/auth/callback" && request.method === "GET") return await callback(request, env, githubFetch);

    // API calls must originate from the published interface and carry the
    // encrypted owner session. CORS is not treated as authorization; identity
    // is still re-established by decrypting and checking the signed envelope.
    if (request.headers.get("Origin") !== pagesOrigin(env)) return json(env, { error: "origin rejected" }, 403);
    const session = await authorizedSession(request, env);
    if (url.pathname === "/api/session" && request.method === "GET") {
      const [workflow, maintenance] = await Promise.all([
        workflowStatus(env, session.accessToken, githubFetch),
        // Storage diagnostics require Contents read permission added after the
        // original control deployment. Missing optional evidence must not take
        // Start/Stop authority offline during that permission rollout.
        maintenanceStatus(env, session.accessToken, githubFetch).catch((error) => ({
          unavailable: true,
          error: error instanceof Error ? error.message : "storage diagnostics unavailable",
        })),
      ]);
      return json(env, { authorized: true, login: session.login, ...workflow, maintenance });
    }
    if (url.pathname === "/api/start" && request.method === "POST") return json(env, await start(env, session, githubFetch));
    if (url.pathname === "/api/stop" && request.method === "POST") return json(env, await stop(env, session, githubFetch));
    if (url.pathname === "/api/backup" && request.method === "POST") return json(env, await backup(env, session, githubFetch));
    return json(env, { error: "not found" }, 404);
  } catch (error) {
    const message = error instanceof Error ? error.message : "control request failed";
    const status = message.includes("session") || message.includes("owner") ? 401 : 502;
    return json(env, { error: message }, status);
  }
}

export default {
  /**
   * Cloudflare owns this three-argument interface: request, environment, then
   * execution context. The context is lifecycle authority, not a fetch client.
   * Keep it outside handleRequest's test seam so production can never mistake
   * ctx for the injected GitHub transport used by contract tests.
   */
  fetch(request, env) {
    return handleRequest(request, env);
  },
};
