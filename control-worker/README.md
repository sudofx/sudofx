# sudofx owner control

This Cloudflare Worker is the confidential authentication and control boundary
for the public GitHub Pages observer.

It is intentionally independent from sudofx durable state.

The Worker can control only `prove-model.yml`. It cannot edit source, work
items, receipts, SQLite state, repository secrets, or arbitrary workflows. It
may dispatch the exact `backup` action in `sudofx.yml`; that workflow produces a
verified, finite-retention recovery artifact without mutating the record.

## Authority

```text
GitHub OAuth
  -> proves configured owner identity

encrypted browser envelope
  -> carries one short-lived owner session

GitHub Actions API
  -> inspect / enable / disable / dispatch / cancel prove-model.yml
```

SQLite remains authoritative for sudofx work.

## Start

Start performs two ordered actions:

1. enable `prove-model.yml`
2. dispatch exactly one bootstrap run

The workflow itself owns success-only continuation after that bootstrap.

## Stop

Stop performs the inverse boundary safely:

1. disable `prove-model.yml`
2. inspect active runs
3. cancel active runs

Disabling first prevents a currently finishing run from creating a successor
after the owner has asked the system to stop.

## Live status

For an authenticated owner, `/api/session` returns the workflow enabled state,
current active runs, and storage-maintenance metadata: repository visibility,
state-branch protection, state head, and database blob size. It never downloads
or exposes database contents. The Pages observer treats that authenticated
evidence as stronger than anonymous GitHub telemetry or an older static artifact.

Provider and OAuth failures are translated inside the Worker request boundary so
the browser receives an explicit error instead of an escaped runtime failure.

## GitHub App configuration

The GitHub App must be owned by `sudofx`, installed only on the `sudofx`
repository, and configured with:

- Homepage: `https://sudofx.github.io/sudofx/`
- Callback: `https://<worker-host>/auth/callback`
- Repository permission: Actions — read and write
- Repository permission: Contents — read (for authenticated storage diagnostics)
- Webhooks: disabled

## Worker configuration

Encrypted secrets:

- `GITHUB_CLIENT_ID`
- `GITHUB_CLIENT_SECRET`
- `SESSION_SECRET` (at least 32 random bytes)

Non-secret deployment configuration in `wrangler.jsonc`:

- `OWNER_GITHUB_ID`
- `PAGES_URL`
- `REPOSITORY`

Identity is bound to the configured immutable numeric GitHub user ID rather than
a renameable login.

After deployment, repository variable `SUDOFX_CONTROL_URL` must contain the
Worker origin. The next successful Pages publication reveals the Owner sign-in
link; Start and Stop remain hidden until the Worker validates an owner session.

## Security boundary

The public Pages artifact never receives:

- GitHub client secret
- GitHub OAuth access token
- session encryption secret
- SQLite mutation authority

The browser receives only a short-lived encrypted session envelope. GitHub
provider credentials stay inside the Worker environment.
