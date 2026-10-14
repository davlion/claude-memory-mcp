# claude-memory-cloud — Quickstart

> **Draft.** Parts 1–4 can be done now. Parts 5–8 describe steps that depend on the server, which isn't built yet; they'll be checked when it is. This file moves to the `claude-memory-cloud` repo once that repo exists.

claude-memory-cloud gives Claude one set of memories everywhere: Claude Code on any machine, Claude Code cloud sessions, and claude.ai chat on web, Desktop, and mobile. The memories are Markdown files in a private GitHub repo that you own. A small server, which you deploy to your own Cloudflare account, connects that repo to Claude as a custom connector.

You'll set up four things:

| What | Where | Cost | Time |
|---|---|---|---|
| A private memory repo | your GitHub account | free | 1 min |
| A Cloudflare account | cloudflare.com | free plan | 10 min |
| A GitHub App (lets the server use your memory repo, and nothing else) | your GitHub account | free | 10 min |
| The server, deployed as a Cloudflare Worker | your Cloudflare account | free plan | 10 min |

Then you connect it to Claude and run a setup script on each machine.

**Placeholders used below:** `<you>` is your GitHub username. `<sub>` is your Cloudflare `workers.dev` subdomain (chosen in Part 2). `<slug>` is your GitHub App's URL name (Part 3).

---

## Before you start

- A GitHub account.
- A claude.ai account (Pro, Max, Team, or Enterprise; custom connectors are needed).
- Node.js 20 or later on your Mac, for `npx`. Check with `node --version`.
- A password manager or other safe place for two secrets (a client secret and an encryption key). You'll paste them into a terminal once; they're never stored in a repo.

---

## Part 1 — Create your memory repo

1. On github.com, click **+** → **New repository**.
2. **Owner:** you. **Name:** `claude-memory`.
3. **Private.** ✅
4. Leave it **empty**: no README, no .gitignore, no license. The server initializes it on the first save.
5. Click **Create repository**.

✔ You now have `https://github.com/<you>/claude-memory`.

> Never put secrets in this repo. The server rejects saves that look like credentials, but don't rely on that alone.

---

## Part 2 — Create a Cloudflare account

1. Sign up at <https://dash.cloudflare.com/sign-up> and verify your email.
2. **Turn on two-factor authentication:** click the profile icon (top right) → **My Profile** → **Authentication** → set up two-factor authentication. Your server will hold access to your memory repo, so protect this account.
3. In the left sidebar, open **Workers & Pages** (under Compute). Cloudflare asks you to choose a **workers.dev subdomain** the first time. Pick something short. If it doesn't ask, find it on the Workers & Pages overview under **Subdomain**.
4. Write down the subdomain: `<sub>`. Your server's address will be `https://claude-memory.<sub>.workers.dev`.
5. Log the command-line tool in. In a terminal:

   ```bash
   npx wrangler@4.150.0 login
   ```

   A browser window opens; click **Allow**.
6. Check it worked:

   ```bash
   npx wrangler@4.150.0 whoami
   ```

   It prints your account name and ID.

✔ You have a Cloudflare account with 2FA, a subdomain, and `wrangler` logged in.

---

## Part 3 — Create the GitHub App

The GitHub App is how the server gets access to your memory repo, **and only that repo**. It acts as you, so it can never do more than you can, and commits show up under your name.

1. Go to github.com → your profile picture → **Settings** → **Developer settings** (bottom of the sidebar) → **GitHub Apps** → **New GitHub App**.
2. Fill in:

   | Field | Value |
   |---|---|
   | GitHub App name | `<you>-claude-memory` (must be unique on GitHub) |
   | Homepage URL | `https://claude-memory.<sub>.workers.dev` |
   | Callback URL | `https://claude-memory.<sub>.workers.dev/callback` |
   | Expire user authorization tokens | ✅ checked (the default) |
   | Request user authorization (OAuth) during installation | ☐ unchecked |
   | Enable Device Flow | ☐ unchecked |
   | Webhook → Active | ☐ **unchecked** |

3. **Permissions → Repository permissions:**
   - **Contents:** Read and write
   - **Metadata:** Read-only (GitHub sets this automatically)
   - Everything else: No access

   **Account permissions:** leave all at No access.
4. **Where can this GitHub App be installed?** → **Any account**. This lets a client organization install it on their own memory repo later. It does *not* list your app publicly.
5. Click **Create GitHub App**.
6. On the app's page, write down:
   - **Client ID** (starts with `Iv`)
   - the **slug**: the last part of the app's public URL, `https://github.com/apps/<slug>`
7. Click **Generate a new client secret**. Copy it into your password manager **now**; GitHub shows it only once.
8. **Do not** generate a private key. The server doesn't need one.

✔ You have a GitHub App with a Client ID, a slug, and a client secret saved safely.

---

## Part 4 — Install the app on your memory repo

1. Go to `https://github.com/apps/<slug>/installations/new`.
2. Choose your personal account.
3. Select **Only select repositories** → `claude-memory`.
4. Click **Install**.

✔ The app can reach `<you>/claude-memory` and nothing else.

---

## Part 5 — Deploy the server *(not yet available)*

1. Get the code and install dependencies:

   ```bash
   git clone https://github.com/<owner>/claude-memory-cloud
   cd claude-memory-cloud
   npm install
   ```

2. Create the two storage namespaces, and paste each printed `id` into the `env.production` section of `wrangler.jsonc`:

   ```bash
   npx wrangler kv namespace create OAUTH_KV
   npx wrangler kv namespace create CACHE_KV
   ```

3. In the `env.production` section of `wrangler.jsonc`, set:
   - `PUBLIC_URL` → `https://claude-memory.<sub>.workers.dev`
   - `GITHUB_APP_SLUG` → `<slug>`
   - `SCOPES` → `{"general": "<you>/claude-memory"}`
4. Set the secrets. Each command prompts for a value; paste it there, not on the command line:

   ```bash
   npx wrangler secret put GITHUB_CLIENT_ID --env production        # the Client ID from Part 3
   npx wrangler secret put GITHUB_CLIENT_SECRET --env production    # the client secret from Part 3
   openssl rand -hex 32                                             # generates an encryption key...
   npx wrangler secret put COOKIE_ENCRYPTION_KEY --env production   # ...paste it here
   ```

5. Deploy and check:

   ```bash
   npm run deploy:production
   curl -sS https://claude-memory.<sub>.workers.dev/health
   ```

   Expected: `{"ok":true,...}`.

---

## Part 6 — Connect it to Claude *(not yet available)*

1. On claude.ai: **Settings** → **Connectors** → **Add custom connector**.
   - **Name:** `claude-memory`
   - **URL:** `https://claude-memory.<sub>.workers.dev/mcp`
2. Click **Connect**. Approve the consent page, then approve on GitHub.
3. Test it: in a new chat, ask *"What's in my memory index?"* You should see a health line and an empty index.

The connector now works in claude.ai chat (web, Desktop, mobile), in Claude Code cloud sessions, and in local Claude Code when you're logged in with your claude.ai account.

---

## Part 7 — Set up each machine *(not yet available)*

On every Mac or VM where you use Claude Code:

```bash
cd claude-memory-cloud && ./setup.sh
```

The script:
- turns off Claude Code's built-in local memory, so every memory goes to the cloud
- adds the memory routing rule to `~/.claude/CLAUDE.md`
- installs the hooks that queue saves while offline, check health at session start, and keep a stale read-only copy of your memory index
- prints a health report, each problem listed with what to do about it

It's safe to run again.

**For cloud sessions:** in your Claude Code cloud environment settings, add the environment variable `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`.

---

## Part 8 — Check it works *(not yet available)*

1. Start `claude` in any git repo and say: *"Save a memory that I prefer small commits."*
   Claude should answer with **"saved to general"**.
2. Open `https://github.com/<you>/claude-memory` and confirm a new commit.
3. On your phone, in the Claude app, ask: *"What do you remember about how I like commits?"*

---

## Adding a client organization

To keep a client's memories in the client's own GitHub org:

1. **The client** (an org owner) creates a private, empty repo `<client-org>/claude-memory`. They add you to it if you don't already have access.
2. **The client** installs your app: `https://github.com/apps/<slug>/installations/new` → their org → **Only select repositories** → `claude-memory`. No secrets change hands.
3. **You** add the scope to `SCOPES` in `wrangler.jsonc`, e.g. `{"general": "<you>/claude-memory", "acme": "acme-org/claude-memory"}`, then run `npm run deploy:production`.
4. **You** add the scope to the local scope map by rerunning `./setup.sh` on each machine.

Memories about the client's codebases go to `<client-org>/claude-memory` under `projects/<repo>/`. If the client removes you from the org or uninstalls the app, access ends immediately.

---

## Appendix — Development and test setup

Only needed if you're working on claude-memory-cloud itself.

1. **Staging server:** also add the callback URL `https://claude-memory-staging.<sub>.workers.dev/callback` to the GitHub App (a GitHub App allows up to 10). Staging is the top-level config in `wrangler.jsonc`, deployed with `npm run deploy:staging`; its secrets are set without `--env`.
2. **Test memory repo:** create a private, empty repo `<you>/claude-memory-test`, and add it to the app installation on your account.
3. **Test client org:** create a free organization (github.com → **+** → **New organization** → **Free**), e.g. `<you>-test-client`. In it, create private repos `claude-memory` (empty) and `sample-app` (with a README). Install the app on that org, selecting only `claude-memory`.
4. **Local secrets:** in the repo, create `.dev.vars` (it's gitignored):

   ```
   GITHUB_CLIENT_ID=<client id>
   GITHUB_CLIENT_SECRET=<client secret>
   COOKIE_ENCRYPTION_KEY=<output of: openssl rand -hex 32>
   ```
