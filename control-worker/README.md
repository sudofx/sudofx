# sudofx owner control

This Cloudflare Worker is the confidential authentication and control boundary
for the public GitHub Pages observer. It is intentionally independent from the
SQLite authority: Start and Stop operate only on `prove-model.yml` and never
modify a work item or receipt.

The GitHub App must be owned by `sudofx`, installed only on the `sudofx`
repository, and configured with:

- Homepage: `https://sudofx.github.io/sudofx/`
- Callback: `https://<worker-host>/auth/callback`
- Repository permission: Actions — read and write
- Webhooks: disabled

The Worker requires these encrypted secrets:

- `GITHUB_CLIENT_ID`
- `GITHUB_CLIENT_SECRET`
- `SESSION_SECRET` (at least 32 random bytes)

`OWNER_GITHUB_ID`, `PAGES_URL`, and `REPOSITORY` are non-secret deployment
configuration in `wrangler.jsonc`. Identity is bound to immutable numeric user
ID `14032554`, not the renameable `sudofx` login.

After deployment, repository variable `SUDOFX_CONTROL_URL` must contain the
Worker origin. The next successful Pages publication will then reveal the Owner
sign-in link; Start and Stop remain hidden until the Worker validates a signed-in
owner session.
