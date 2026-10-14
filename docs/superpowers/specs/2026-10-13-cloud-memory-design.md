# Cloud Memory — Design Spec

**Date:** 2026-10-13
**Status:** Approved in brainstorming; pending spec review
**Implementation repo:** `claude-memory-cloud` (new). This repo (`claude-memory-mcp`) stays in place. Its local cache is the source for the one-time migration of existing project memories (§10); after that it is legacy.

## 1. Goal

A standard memory context that follows the user across every Claude surface:

- Claude Code — local CLI and Desktop app on the Mac, and on the VMs (`earsvm`, `lume-claude-sandbox`)
- Claude Code cloud sessions (claude.ai/code)
- claude.ai chat — web, Desktop, mobile

Any session can read and add memories. Three kinds of memory live in the cloud, each kept separate:

- **General**: about the user and how they work.
- **Client**: about a client org as a whole.
- **Project**: about one codebase, identified by its git remote, so the same project on any machine or in a cloud session sees the same memories.

Claude Code's built-in auto-memory is turned off (§7) so it doesn't compete with the cloud store.

The same mechanism must work for a client whose code lives in private GitHub repos, with access governed by the permissions that client grants the user.

### Non-goals (v1)

- Project memories for directories without a git remote. Those sessions get general memories only.
- Staleness/decay scoring, contradiction linting, scheduled consolidation. Consolidation is a candidate for a later scheduled Claude routine.
- Embeddings / semantic search.
- Non-Claude AI tools.

## 2. Key facts the design rests on

Verified during research on 2026-10-13 (see brainstorming transcript for sources):

- A custom connector added on claude.ai is available in claude.ai chat (web/Desktop/mobile), in local Claude Code when logged in with a claude.ai account, and in cloud Claude Code sessions. Connector traffic goes through Anthropic's servers, so it is not limited by the cloud session's GitHub proxy, which only allows repos attached to the session.
- claude.ai custom connectors support OAuth through Dynamic Client Registration (DCR), CIMD (Claude's published client identity), or a user-supplied client. They support custom static headers only as a limited org beta.
- GitHub's hosted MCP server does not support DCR. GitHub's own docs say it can't currently be added as a Claude connector, and a general GitHub connector would expose all of a client's code repos anyway. So we run our own server.
- No native Anthropic feature bridges claude.ai memory and Claude Code memory. Chat and Cowork memory were merged on 2026-08-25; Claude Code is explicitly separate "for now". **Watch item:** if Anthropic syncs Claude Code memory, revisit this project. Client-owned repos and per-client scopes would remain differentiators.
- Claude Code auto-memory is machine-local. Folders are named from each machine's path. In cloud sessions it is lost when the session ends.
- Auto-memory can be turned off:
  - with `autoMemoryEnabled: false` in user, project, local, or managed settings
  - with the env var `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`
  - When off, Claude neither creates nor loads auto-memory files.
- There is no hook event for memory writes. Mirroring auto-memory would need a `PostToolUse` path filter that misses writes made through Bash. That makes it unreliable, so it was rejected in favor of turning auto-memory off.
- In cloud sessions, hooks and settings from the repo run, but user-level `~/.claude` settings and hooks do not.
- Prior art: nothing suitable to adopt. `hippocampus` (Cloudflare + GitHub App + private repo) is the closest architectural reference. Borrowed ideas are credited in the sections below.

## 3. Architecture

```
claude.ai connector (chat · Desktop · mobile · Code local · Code cloud)
        │  MCP over Streamable HTTP, OAuth
        ▼
Cloudflare Worker  "claude-memory"
  ├─ workers-oauth-provider   — OAuth server facing claude.ai; grants in KV
  ├─ GitHub App user auth     — obtains user-to-server token
  └─ MCP server (/mcp)        — memory tools → GitHub REST API
        │  user's GitHub token
        ▼
GitHub:  dav/claude-memory            (scope: general;  projects/<repo>/ for dav/* projects)
         <client-org>/claude-memory   (scope: <client>; projects/<repo>/ for <client-org>/* projects)
```

### Components

| Unit | Responsibility | Depends on |
|---|---|---|
| `src/index.ts` | Wires OAuthProvider, auth handler, and MCP server | everything below |
| `src/github-auth.ts` | GitHub App authorize/callback; token refresh | GitHub OAuth endpoints, KV |
| `src/scopes.ts` | Resolves a scope (`general`, `<client>`, or `project` + remote) to `{repo, path}`; reports reachability per user | config, GitHub API |
| `src/remote.ts` | Normalizes git remote URLs (`git@github.com:o/r.git`, `https://github.com/o/r`, `ssh://…`) → `o/r` | none (pure) |
| `src/store.ts` | Reads tree/files at a commit; atomic multi-file commit with ref compare-and-swap | GitHub Git Data API |
| `src/memory.ts` | Frontmatter parse/serialize; index rebuild; similarity check | none (pure) |
| `src/secrets.ts` | Secret-pattern scanner | none (pure) |
| `src/tools.ts` | MCP tool definitions; maps results and errors | memory, store, scopes, secrets |
| `src/instructions.ts` | Server instructions text (includes routing rule) | none |

The pure units (`memory`, `secrets`, `remote`) contain no I/O. `store` is the only unit that talks to the Git Data API.

### Languages

- **Worker: TypeScript.** Cloudflare's OAuth provider, MCP transport (`agents`), and Workers test pool are JavaScript-only, and they cover the security-sensitive auth code. Python Workers lack the OAuth library.
- **Everything local: Python and shell.** That covers the hooks, `setup.sh`, the migration script, and the e2e test runner, matching this repo. Hooks are kept light so they start fast.

### Infrastructure

- **Cloudflare:** a free account with 2FA. Workers on the free plan, KV for OAuth grants and the search cache, deployed with `wrangler`. Default URL `*.workers.dev`; no custom domain needed.
- **Two deployments:**
  - `claude-memory-staging`, mapped to test repos
  - `claude-memory`, mapped to real repos
- **Secrets** (`wrangler secret put`): `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `COOKIE_ENCRYPTION_KEY`.
- **Config** (a `wrangler.jsonc` var): `SCOPES`, a JSON map from scope name to repo, e.g. `{"general":"dav/claude-memory","acme":"acme-org/claude-memory"}`. Adding a client means installing the app on their repo, adding one line here, and redeploying.
- **Project scope resolution:** a normalized remote `o/r` maps to the scope whose repo owner is `o`, with path `projects/<r>/`. Example: `acme-org/billing` → `acme-org/claude-memory` at `projects/billing/`. If no scope's repo is owned by `o` → error `no_memory_repo_for_owner`. Non-GitHub remotes → error `unsupported_remote`.
- **Starting point:** built directly on `@cloudflare/workers-oauth-provider`'s consent and upstream sign-in helpers and the stateless `createMcpHandler` from `agents`. Cloudflare's GitHub-OAuth demo was stale (it predates those helpers and uses the deprecated `McpAgent`).

## 4. Authentication and access

### GitHub App

- Registered under the user's personal account as "dav-claude-memory" (name TBD at creation). Installable by "Any account", but not listed in the Marketplace.
- **Permissions:** Repository contents read & write; Metadata read (mandatory). Nothing else.
- **Webhooks:** disabled.
- **Callback URL:** `https://<worker>/callback`.
- **Installed on:**
  - the user's account, on `dav/claude-memory` only
  - each client org, on `<client-org>/claude-memory` only. An org owner does this; it takes about a minute and involves no secrets.
- **User-to-server tokens only.** Effective access is the intersection of the app's permissions, the repos the installation covers, and the user's own access. Commits are attributed to the user. Tokens expire after 8 hours and are refreshed with the refresh token. The app's private key is not needed and is not stored.
- **Revocation:** if the client uninstalls the app or removes the user from the org, access ends immediately.

### Flow

1. The user adds the connector in claude.ai. claude.ai registers via DCR or CIMD, whichever `workers-oauth-provider` supports, and starts OAuth with PKCE S256.
2. The Worker's `/authorize` redirects to GitHub. The user approves once. `/callback` exchanges the code for user and refresh tokens.
3. The Worker stores the GitHub tokens in the grant props. `workers-oauth-provider` encrypts props using the issued access token. **Verify this property** before describing it to a client.
4. On each tool call, the Worker resolves scope → repo, calls the GitHub API with the user's token, and refreshes the token if it has expired.

### Hardening (borrowed from memoria_mcp)

- Pinned public base URL. Reject requests whose origin (scheme + host) doesn't match, so the OAuth issuer can't be spoofed. Plain `http://` requests get 421.
- Redirect URI allowlist: `https://claude.ai/api/mcp/auth_callback`, `https://claude.com/api/mcp/auth_callback`, plus `localhost` callbacks for Claude Code CLI OAuth.
- Error responses from the authorization endpoint redirect only to allowlisted redirect URIs. This closes an open redirect that DCR would otherwise allow.
- Only GitHub's `bad_refresh_token` revokes a grant. Other refresh errors are treated as transient.
- The Worker logs no memory content and no tokens.

### Data handling

Memory text passes through the Worker in plaintext, because TLS ends at Cloudflare, and it reaches Anthropic whenever Claude reads it. The rule is **no secrets in memories**, enforced by the scanner in §6. Every write is a commit in the owner's repo, which gives a full audit trail. The KV blob cache (used by search) also holds memory text, keyed by blob SHA, with a 30-day expiry.

Client-hosted deployment is possible, since the code is small and self-contained, but it is not needed for the current client: a small shop that trusts the user.

## 5. Repo layout and memory format

One `claude-memory` repo per owner (the user, each client org). It holds that owner's general or client memories plus a folder per project:

```
claude-memory/
├── README.md        # what this is; rules (no secrets; format)
├── MEMORY.md        # index — maintained by the server
├── memories/
│   ├── <name>.md
│   └── <name>.conflict-<UTC timestamp>.md   # only when a conflict occurred
└── projects/
    └── <repo>/
        ├── MEMORY.md
        └── memories/
            └── <name>.md
```

Every **memory set** (the root set, or one project's) has the same structure: a `MEMORY.md` plus a `memories/` folder. The rules below apply to each set independently. Names are unique per set.

### Memory file

The format is identical to Claude Code auto-memory, so memories can move between local and cloud without conversion:

```markdown
---
name: debugging-discipline
description: Measure first; question failed theories before trying another fix
metadata:
  type: feedback        # user | feedback | project | reference
---

<the fact>
**Why:** ...
**How to apply:** ...
```

- `name` must be kebab-case, match `^[a-z0-9][a-z0-9-]{0,63}$`, and be unique per scope. The filename is `memories/<name>.md`.
- `[[name]]` links to other memories in the same scope are allowed. Dangling links are fine.

### Index (`MEMORY.md`)

Rebuilt from frontmatter on every write and committed **in the same commit** as the memory change. Format:

```markdown
# Memory index — <scope>

- [<name>](memories/<name>.md) — <description>
...

## Conflicts
- memories/<name>.conflict-<ts>.md — reconcile with <name>.md
```

The `## Conflicts` section is omitted when there are no conflicts. If someone edits a memory by hand on github.com, the next server write corrects the index.

### Commits

- Message: `<op>: <name>`. Trailers: `Memory-Source: <source>` and `Memory-Scope: <scope>`, where a project scope is written `project:<owner>/<repo>`.
- `Memory-Source` comes from the optional `source` tool argument (Claude states where it runs, e.g. `claude-code on earsvm`, `claude.ai chat`); `unknown` if absent. Reason: connectors reach every surface through claude.ai, so the OAuth client is the same everywhere, and stateless MCP only carries clientInfo on `initialize`. The value is sanitized so it can't forge trailers: whitespace collapsed, max 100 chars, `unknown` if empty.
- Mechanism: Git Data API. Create blobs, then a tree, then a commit, then update the ref with `force: false`. If the ref update fails because the branch moved, re-read and re-apply. That is always safe for a different-file change; a same-file change follows the conflict rule in §6. GitHub reports a racing ref update as HTTP 422 "Reference cannot be updated" or "not a fast forward"; both are treated as a ref race and retried.

## 6. Tools

All tools take `scope`: `general`, a client name (a key in `SCOPES`), or `project`. When `scope` is `project`, the parameter `project` is required. It takes a git remote URL or `owner/repo` and is resolved as described in §3. Where noted, `scope` defaults to `general`.

`memory_index` additionally takes `project?`. When given, the project's index is included alongside the indexes for the requested scopes.

`memory_read`, `memory_search`, `memory_save`, and `memory_delete` also take `since?` (§6 Freshness); it is omitted from the table below.

| Tool | Parameters | Returns |
|---|---|---|
| `memory_scopes` | — | `[{scope, repo, reachable, writable, private, reason?}]`, where `reason` is `app_not_installed`, `not_reachable`, or `repo_public`. `writable` is false for a public repo |
| `memory_index` | `scopes?: string[]` (default: all configured), `project?` | A `health` block (§7 F) followed by, per reachable scope (and the project, if given), the `MEMORY.md` content including the Conflicts section, then the `Since` map (§6 Freshness). An unknown project with no folder yet → empty index, not an error |
| `memory_health` | `project?` | The `health` block only. Used on demand ("is memory working?") |
| `memory_read` | `scope`, `names: string[]` (max 20) | Per name, `{name, content, version}` or `{name, error:"not_found"}`. `version` is the file's blob SHA |
| `memory_search` | `query`, `scopes?` | `[{scope, name, description, snippet}]`, max 20. Case-insensitive substring/term match over name, description, and body (not frontmatter keys) |
| `memory_save` | `scope` (default `general`), `name`, `description`, `type`, `body`, `version?`, `force?: boolean`, `source?` | `{status, name, commit_url?, similar?, conflict_file?, pattern?}` |
| `memory_delete` | `scope`, `name`, `version?`, `source?` | `{status: deleted|conflict|not_found, commit_url?}` |

### `memory_save` semantics

Checks run in this order:

1. **Validate:** name format, type enum, required fields. Failure → `status: invalid` with a message.
2. **Secret scan** of all fields. A hit → `status: rejected_secret` with `pattern` (the rule name, never the matched text). Nothing is written.
3. **Visibility:** if the scope's repo is public → error `repo_public`, naming the repo and the fix. Nothing is written. The `private` flag comes from the `GET /repos/{repo}` call the store already makes to find the default branch, so this costs no extra request. `memory_delete` applies the same check; reads don't.
4. **No `version` (create):**
   - If `<name>.md` exists → `status: exists`, with its `version`. Claude should read it and update instead.
   - If similar memories exist and `force` is not set → `status: similar_found`, with `similar: [{name, description}]` (max 3). Nothing is written.
   - Otherwise write → `created`.
5. **With `version` (update):**
   - If the current blob SHA equals `version` → write → `updated`.
   - If it differs → write the new content to `memories/<name>.conflict-<ts>.md` (with the Conflicts index entry) → `status: conflict`, with `conflict_file`. The original is untouched.
   - If the file is missing → `not_found`.

`memory_delete` with a stale `version` → `conflict`, and nothing is deleted. Without `version` → unconditional delete. Claude is instructed to pass a version.

### Freshness: changes made by other surfaces

Nothing is pushed to running sessions. A session sees another surface's changes in two ways:

- **New sessions** call `memory_index`, which returns the latest state.
- **Running sessions** learn of changes on their next memory tool call:
  - `memory_index` ends with a `Since` map, `{scopeLabel: indexVersion}`, with one entry per index it returned (e.g. `general`, `acme`, `project:acme-org/billing`). `indexVersion` is the blob SHA of that scope's `MEMORY.md`, or `none` if there isn't one. Each save and delete rewrites the index in the same commit, so the version changes exactly when that scope's memories change.
  - `memory_read`, `memory_search`, `memory_save`, and `memory_delete` take `since?`. After the operation, the Worker re-checks each scope in the map. For any that changed, it adds a second content item, "Memory changed since your index", containing that scope's current index and a new `Since` map. The tool's own result stays unchanged.
  - Unknown keys are ignored. If the check itself fails, the result still returns, without the notice.
  - A session's own save also changes the version, so the notice follows it. That's correct, because the session's copy of the index is stale too.

This stays stateless: the Worker stores nothing per session. Claude carries the map. Duplicates and concurrent edits are already handled by the save path (similarity check, conflict copies), whether or not the notice was seen.

### Similarity check (borrowed from memoria_mcp)

Normalized tokens of name and description are compared with Jaccard similarity; ≥ 0.5 counts as similar. Threshold to be tuned during build with real memories. Pure function in `memory.ts`.

### Secret scanner

Pure function in `secrets.ts`, with rules for:

- GitHub tokens (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_`)
- AWS access keys (`AKIA…`/`ASIA…`)
- PEM private-key blocks
- Slack tokens (`xox[abprs]-`)
- Anthropic keys (`sk-ant-`)
- OpenAI keys (`sk-`, `sk-proj-`, `sk-svcacct-`, `sk-admin-`), with `-` and `_` allowed in the body
- Google API keys (`AIza`)
- JWTs
- generic `key|token|secret|password = <long value>` assignments. They match quoted JSON/YAML keys too. Values that look like code references or URLs are not flagged: starting with `$`, `${`, `process.`, `os.`, `env.`, `http://`, `https://`, or containing `(`

Every rule needs a true-positive and a false-positive test.

### Search

The Worker fetches the tree and the files for the scope's current commit and searches in memory. The result is cached in KV, keyed by commit SHA. GitHub code search is not used because its index lags behind recent writes.

### Resources

- `memory://{scope}/index`: the same content as `memory_index` for that scope.
- `memory://project/{owner}/{repo}/index`: the same for a project.

### Conflict reconciliation

No dedicated tool. Claude reads both files, saves the merged content to `<name>.md` with its current `version`, then deletes the conflict file. Each conflict file appears in the index until it is resolved.

## 7. Routing and triggering

**Problem:**
- In Claude Code, "save a memory…" naturally goes to the built-in auto-memory, whose instructions are in the system prompt.
- Connector tools are often deferred.
- Claude has to decide whether a fact is general, client, or project.

Turning auto-memory off removes the first problem. Layers A–D below handle the rest. E covers saves made while the connector is unavailable, and G covers reads.

### Auto-memory off

- **Mac and VMs:** `"autoMemoryEnabled": false` in `~/.claude/settings.json`, distributed to the VMs as part of setup.
- **Cloud sessions:** `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` in the cloud environment's environment variables. User settings are not read in cloud sessions.
- When off, the built-in "write memories to `~/.claude/projects/…/memory/`" instruction and the startup `MEMORY.md` load should both disappear. **Verify with `/context`** (§11).
- Reversible: one setting.

### Determining the project

In Claude Code, the project is the `origin` remote of the session's working directory, from `git remote get-url origin`. That works locally and in cloud sessions, which clone the repo. With no git repo or no `origin` there is no project scope, and only general and client memories apply. claude.ai chat has no project; there, Claude uses a project scope only when the user names a repo.

### A. Routing rule in `~/.claude/CLAUDE.md`

Covers local Code on the Mac and VMs. Distributed to the VMs as part of setup.

> **Memory.** Memories live in the claude-memory connector. Auto-memory is off.
>
> At session start, call `memory_index` with `project` = this repo's `git remote get-url origin` (omit it if there is none).
>
> When saving a memory:
> - About me or how we work in general → scope `general`.
> - About the client org as a whole → scope `<client>`.
> - About this codebase → scope `project` with `project` = the origin remote.
>
> If it's unclear, ask in one line ("general, <client>, or this project?"). With no git remote, project-specific facts can't be saved; say so. After saving, state the scope it went to.
>
> After context compaction (the session-start hook says so), call `memory_index` again, as at session start.
>
> After each successful `memory_index`, write its result to `~/.claude/memory-cache/<owner__repo or _none>.md` (§7 G). If `memory_index` fails, use the session-start snapshot, say it is stale and give its date, and don't save, update, or delete from it.
>
> If `memory_save` fails because the connector is unavailable (unreachable, auth expired, upstream error, or the tools aren't loaded), write the memory to the outbox (`~/.claude/memory-outbox/`, format in §7 E) and say "queued in outbox for <scope>". Never drop it silently. If the session-start hook reports queued memories and the connector works, flush them.

### B. `UserPromptSubmit` hook

A user-level script in `~/.claude/hooks/`, installed on the Mac and the VMs.

- It matches memory-intent phrases, case-insensitive:
  - `save (a |this )?memory`
  - `remember (this|that)`
  - `don't (do|let) .* again`
  - `note for (the )?future`
  - `add (this )?to (your )?memory`
- On a match, it emits `additionalContext` with:
  - a two-line reminder of the routing rule
  - **the origin remote**, if any, so Claude doesn't have to look it up
  - **the inferred client scope**: the remote's owner looked up in a local copy of the scope map (`~/.claude/memory-scopes.json`). If the owner is unknown, there is no client hint.
- If the phrases don't match, it outputs nothing. It must run in under 100 ms and needs no network; `git remote` is local.
- Whether B is needed is decided by the S2/S4/S5 results with A + C alone (§9). It is built regardless, because it is small, and it can be disabled.

### C. Server instructions

Sent by the Worker wherever the connector is enabled, so they reach cloud sessions and chat:

> At the start of a conversation, call `memory_index`. In Claude Code, pass `project` = the working directory's `git remote get-url origin`, if there is one. Read individual memories when relevant.
>
> Save lasting facts to one of three scopes:
> - the user (`general`)
> - a client org as a whole (client scope)
> - one codebase (`project`, with its origin remote)
>
> If the scope is unclear, ask in one line. Never save secrets. Prefer updating an existing memory (pass its `version`) over creating a new one. After saving, tell the user the scope. If `memory_index` lists conflicts, offer to reconcile them.
>
> If the memory index is no longer in your context (for example after the conversation was summarized), call `memory_index` again.
>
> `memory_index` ends with a `Since` map. Pass it as `since` on later memory tool calls. If a result says "Memory changed since your index", replace your copy of that scope's index with the one given and use the new map.
>
> If a save fails with a retryable error (`unavailable`, `reauth_required`), tell the user plainly. In local Claude Code, follow the outbox rule in the user's CLAUDE.md. Elsewhere, there is no outbox: tell the user the memory was not saved.

### D. Save announcement

Included in A and C. Every save attempt ends with exactly one of:

- "saved to **<scope>**" (for a project: "saved to **project billing**")
- "**queued in outbox** for <scope>"
- "**not saved**: <reason>"

Misroutes and unsaved memories are visible right away.

### E. Outbox (local Claude Code only)

For when Claude works but the memory connector doesn't: the Worker or GitHub is down or rate-limited, the token has expired, or the connector isn't loaded in this session. (With no internet at all, Claude Code itself doesn't run.)

- **Location:** `~/.claude/memory-outbox/` on the Mac and VMs.
- **Entry:** one file per queued save, named `<UTC timestamp>-<name>.md`. It holds the normal memory file plus an `outbox:` frontmatter block:

  ```yaml
  outbox:
    op: save            # save | delete
    scope: project      # general | <client> | project
    project: acme-org/billing   # when scope is project
    version: <blob sha> # the version the edit was based on; absent for create
    queued_at: 2026-10-13T18:04:00Z
    host: earsvm
  ```

- **Marker:** a non-empty outbox is the dirty flag. Entries carry their project, so the state is visible per project; no separate flag file.
- **`SessionStart` hook** (user-level, Mac and VMs): counts entries. If there are any, it emits `additionalContext`: "N memories queued in outbox (M for this project). Once `memory_index` succeeds, flush them with `memory_save`/`memory_delete`, oldest first, and delete each entry only after a successful result." It outputs nothing when the outbox is empty. The same hook runs the local preflight checks (§7 F).
- **Flush:** Claude replays each entry through the normal tools, so secret scanning, the similarity check, and conflict handling all apply. A stale `version` produces a conflict copy rather than overwriting. An entry that gets a non-retryable result (`rejected_secret`, `repo_public`, `invalid`, `no_memory_repo_for_owner`) is kept and reported to the user rather than deleted.
- **Why Claude flushes rather than a script:** the connector authenticates through claude.ai, and writing to GitHub directly would bypass the server's checks.
- **Not covered:**
  - Cloud sessions: the outbox would be lost with the VM; the save is reported as not saved.
  - claude.ai chat: there is no local disk.
  - Reads while the connector is unavailable: only the stale snapshot (§7 G) is available. `memory_read` and `memory_search` fail visibly.
- **Precedent:** the `claude-memory-mcp` pending-shares queue, which retries unreachable VMs on the next `sync_now`.

### F. Preflight health check

At session start, two halves check everything. **Every failed check reports the action the user should take**, not just what's wrong.

Authentication lives in claude.ai, not in the local shell. A local hook therefore cannot check the GitHub token; the server does. `gh` login in the shell is **not** needed for memory to work. It is only needed for the migration and e2e test scripts, which check it themselves.

#### Server half: `health` block in `memory_index` / `memory_health`

Each check returns `{check, status: ok|warn|fail, detail, action?}`. `action` is required whenever status isn't `ok`.

| Check | Fail / warn condition | Action reported to the user |
|---|---|---|
| `github_token` | refresh failed / revoked | "Reconnect: claude.ai → Settings → Connectors → claude-memory → Disconnect, then Connect, and approve on GitHub." |
| `github_token` (warn) | expires within 15 min and no refresh token | "Memory sign-in expires soon; reconnect the claude-memory connector in claude.ai Settings → Connectors." |
| `rate_limit` (warn) | < 10% remaining | "GitHub rate limit low (N left, resets HH:MM). Saves may be queued until then; no action needed." |
| `scope:<name>` | `app_not_installed` | General: "Install the GitHub App on `<repo>`: <install link> → Only select repositories → `claude-memory`." Client: "Ask an owner of `<org>` to install the app: <install link>." |
| `scope:<name>` | `not_reachable`: the repo isn't in the user's installation list. GitHub App user tokens return 404 for "repo missing", "app not on this repo", and "no user access" alike, so the three can't be told apart | Lists all three fixes, most likely first: "Install the app on `<repo>`; create the private repo `<repo>` if it doesn't exist (it can be empty; the server initializes it on first write); or, if you're not a member, ask an owner of `<org>` to add you, and check you're signed in to the right GitHub account (`<login>`)." |
| `scope:<name>` | `repo_public`: the repo's `private` flag is false (taken from the installation repository list the check already fetches) | "⚠ `<repo>` is **public**, so anyone can read these memories. Make it private: repo Settings → General → Danger Zone → Change visibility. Saves to this scope are blocked until then." |
| `project` | `no_memory_repo_for_owner` | "No memory repo is configured for `<owner>`. Project memories for this repo can't be saved. To enable: create `<owner>/claude-memory`, install the app on it, and add a scope for `<owner>`." |
| `project` | `unsupported_remote` | "This repo's origin isn't on GitHub; project memories aren't available here." |
| `github_api` | 5xx / timeout | "GitHub is having problems (status page: githubstatus.com). Saves will be queued in the outbox; nothing to do." |

#### Local half: added to the `SessionStart` hook (Mac and VMs)

| Check | Fail condition | Action reported to the user |
|---|---|---|
| Worker reachable | `GET <worker>/health` fails within 1 s | "Can't reach the memory server `<url>`. Check this machine's network/DNS (`curl -sS <url>/health`). Saves will be queued in the outbox." |
| Auto-memory off | `autoMemoryEnabled` not `false` in effective settings, and `CLAUDE_CODE_DISABLE_AUTO_MEMORY` unset | "Built-in auto-memory is on, so memories may go to the local folder. Add `\"autoMemoryEnabled\": false` to `~/.claude/settings.json`." |
| Routing rule present | marker line missing from `~/.claude/CLAUDE.md` | "The memory routing rule is missing from `~/.claude/CLAUDE.md`; rerun the claude-memory-cloud setup script." |
| Scope map | `~/.claude/memory-scopes.json` missing or invalid | "Scope map missing or invalid; rerun the setup script (or fix `~/.claude/memory-scopes.json`)." |
| Outbox | entries present (as §7 E) | "N memories queued; they'll be flushed once the server responds." If any entry is older than 7 days: "Oldest queued memory is D days old; check the server health above." |
| Hook version | installed hook older than the version the Worker reports at `/health` | "Memory hooks are out of date; rerun the setup script." |

The hook's network budget is one `GET` with a 1 s timeout. Its total runtime must stay under 1.5 s. The Worker's `/health` is unauthenticated and returns only `{ok, version, min_hook_version}`.

| Local memory files private | `~/.claude/memory-outbox/` or `~/.claude/memory-cache/` not mode `700`, or a file in them not `600` | "Memory files on this machine are readable by other users. Run `chmod 700 ~/.claude/memory-outbox ~/.claude/memory-cache && chmod 600 ~/.claude/memory-outbox/* ~/.claude/memory-cache/*`." The hook also creates both directories with these modes. |

#### Reporting rule

- **Healthy → silent.**
- **Otherwise →** at session start, Claude says one line per problem, each with its action, e.g.:
  > ⚠ memory: `acme` unreachable — ask an owner of acme-org to install the app: <link>. Saves to `acme` will be queued.
- After that, Claude doesn't bring up health again unless asked or unless the status changes.
- If `memory_index` returns no result at all (the connector isn't loaded or can't be reached), Claude reports: "⚠ memory connector unavailable — check claude.ai → Settings → Connectors → claude-memory is connected, and run `/mcp` to see if it's enabled in this session. Saves will be queued."

### G. Last-known-good snapshot (local Claude Code only)

Gives a session some memories when the connector is unavailable, or when Claude skips the session-start `memory_index` call. It is read-only and always labeled stale.

- **Location:** `~/.claude/memory-cache/<key>.md`, mode `0600`. `<key>` is the origin remote as `owner__repo`, or `_none` outside a git repo.
- **Content:** the `memory_index` result (the general, client, and project indexes, which are one line per memory), with an `as_of` timestamp and the scope commit SHAs. It holds the index only, not memory bodies.
- **Writer:** Claude. After each successful `memory_index`, it overwrites the snapshot for the current key. Layer A includes this rule. Nothing else writes to the cache. The hook can't, because only the connector holds GitHub credentials.
- **Reader:** the `SessionStart` hook. When a snapshot exists for the current key, the hook always injects it as `additionalContext`, headed: "Memory snapshot from <as_of> (stale; read-only). A successful `memory_index` supersedes it." It is capped at 8 KB; if truncated, it says so.
- **Rules:**
  - Claude never saves, updates, or deletes based on the snapshot alone. A save still goes through `memory_save` or the outbox. An update based on a snapshot line has no `version`, so it is treated as a create and the similarity check catches it.
  - If `memory_index` fails, Claude says the memories shown are from the snapshot, with its date.
- **Not covered:** cloud sessions and claude.ai chat, which have no persistent local disk.

### H. Compaction counts as a session start

When a long session is compacted, the summary may drop the memory index and the `Since` map. Claude then knows less than a new session would, and nothing tells it so. Compaction is therefore treated as a second session start.

- **Local Claude Code (Mac and VMs):** the `SessionStart` hook is registered for all sources (`startup`, `resume`, `clear`, `compact`), with no matcher. On source `compact` it does everything it does at startup (outbox count, preflight, snapshot) and adds: "Context was compacted. Call `memory_index` again (with `project` as at session start) and use its result and `Since` map from now on."
- **Cloud sessions and chat:** there are no local hooks, so the rule is in the server instructions (C): if you no longer have the memory index in context (for example after the conversation was summarized), call `memory_index` again.
- **Layer A** includes the same rule.
- `PreCompact` isn't used. Nothing needs saving before compaction, because memories are already saved when they're made.

## 8. Error handling

| Condition | Behavior |
|---|---|
| GitHub 404/403 on scope repo | Distinguish `app_not_installed` (owner-level installation lookup) from `not_reachable` (repo missing, app not on the repo, or no user access: indistinguishable); message names the fixes |
| Token refresh fails | `reauth_required`: "reconnect the claude-memory connector in claude.ai settings". Retryable: local Code queues the save in the outbox (§7 E) |
| GitHub 5xx / rate limit | `unavailable`, with the retry-after if known. Retryable: local Code queues the save in the outbox; elsewhere it is reported as not saved. Never dropped silently. |
| Connector unreachable or not loaded | No tool result at all. Local Code queues the save in the outbox; elsewhere it is reported as not saved. |
| Ref update race | Re-read and re-apply. After 3 attempts → error |
| Unknown scope | List valid scopes |
| `scope: project` without `project` | `invalid`: "pass the git origin remote" |
| Project owner has no memory repo | `no_memory_repo_for_owner` naming the owner; Claude tells the user (memory not saved) |
| Non-GitHub remote | `unsupported_remote` |
| Secret detected | `rejected_secret` + rule name |
| Scope repo is public | `repo_public`: save and delete refused, reads allowed; the action says how to make it private. Not retryable on its own: an outbox entry stays queued until the repo is private |
| Same-file concurrent edit | Conflict file (§6) |

## 9. Testing

### Level 1 — Worker unit tests

vitest, run inside the actual Worker runtime via `@cloudflare/vitest-pool-workers`, with the GitHub API mocked. Covers:

- frontmatter parse and serialize round-trip
- index rebuild, with and without conflicts
- every secret rule (true and false positives)
- similarity threshold cases
- `memory_save` decision table: create / exists / similar / force / update / stale version → conflict / not_found
- delete paths
- scope resolution, including project → `{repo, projects/<r>/}` and unknown owner
- remote normalization: SSH, HTTPS, `ssh://`, with and without `.git`, trailing slashes, case of the owner
- error mapping
- Host and redirect allowlist checks

### Level 2 — Integration against staging

Uses the real throwaway repo `dav/claude-memory-test`. A scripted MCP client (TypeScript SDK) authenticates with a test grant and exercises every tool:

- create, similar_found, force create
- update, then a stale version → conflict file appears in the index
- reconcile, then delete
- search finds a just-written memory
- secret rejected, with no commit
- `Memory-Source` and `Memory-Scope` trailers present
- `health` block for each server-side check: ok, and each fail/warn condition (expired token, app not installed, no user access, missing repo, unconfigured project owner, low rate limit via mocked headers), each with a non-empty `action`
- `/health` endpoint returns `{ok, version, min_hook_version}` with no auth
- **Concurrency:** two simultaneous updates with the same `version` → exactly one `updated` and one `conflict`
- Two simultaneous creates of different names → both land; the index contains both
- Project scope: save, read, and index for `dav/<test-repo>` land under `projects/<test-repo>/` with their own `MEMORY.md`; the root index is unchanged
- `memory_index` with an unknown project → empty project index, no error

### Level 3 — Hook tests

Shell-level tests of the `UserPromptSubmit` script:

- trigger and non-trigger phrase tables
- remote → scope mapping: client org, personal repo, no remote, non-git directory
- the origin remote is included when present and omitted otherwise
- no output on a non-match
- runs under 100 ms

Shell-level tests of the `SessionStart` outbox hook:

- source `compact` → the same output as `startup`, plus the re-index line; source `startup` → no re-index line

- empty or missing outbox → no output
- entries counted overall and for the current project (by origin remote)
- non-git directory → total only
- malformed entry → counted and flagged, not crashing
- each local preflight check broken in turn (Worker unreachable via a bad URL, auto-memory on, routing marker missing, scope map missing or invalid, stale outbox entry, hook older than `min_hook_version`) → one line with the expected action
- all healthy → no output
- total runtime under 1.5 s with the Worker unreachable (timeout respected)

Snapshot (§7 G):

- no snapshot for the current key → no snapshot output
- snapshot present → injected with the stale header and its `as_of` date
- snapshot over 8 KB → truncated, with a truncation note
- non-git directory → the `_none` snapshot is used

Outbox entry format: a fixture-based round-trip test (memory frontmatter + `outbox:` block) shared with the flush instructions.

### Level 4 — Surface matrix (end-to-end)

**Prerequisites:**

- A test client org (free GitHub org, e.g. `dav-test-client`) with the app installed on `dav-test-client/claude-memory`. Never experiment on the real client first.
- A test code repo in that org (`dav-test-client/sample-app`), cloned on H1, H3, H4 and used in H5, for S3 and the project scenarios.
- Staging connector added in claude.ai.
- Auto-memory off on the hosts (settings on H1–H4, env var on H5).
- VMs powered on.

**Hosts:**

| ID | Host | Execution |
|---|---|---|
| H1 | Mac — Claude Code CLI | scripted (`claude -p`) |
| H2 | Mac — Desktop app Code session | manual checklist |
| H3 | earsvm | scripted over SSH |
| H4 | lume-claude-sandbox | scripted over SSH |
| H5 | Cloud Code session | scripted if CLI cloud launch is supported, else manual |
| H6 | claude.ai web chat | manual checklist |
| H7 | Claude mobile | manual spot check |

**Scenarios:**

| ID | Scenario | Hosts | Pass criterion |
|---|---|---|---|
| S1 | Connector present; index read at session start unprompted | all | index content appears without being asked |
| S2 | "Save a memory so we don't do X again" (general fact) | all | commit in `general` repo; scope announced |
| S3 | Client-wide fact, session in a client-org repo | H1–H5 | commit in `dav-test-client` scope |
| S0 | Auto-memory off takes effect | H1–H5 | `/context` shows no auto-memory instruction and no `MEMORY.md` load; no files written under `~/.claude/projects/*/memory/` during the run |
| S4 | Project-only fact, session in `sample-app` | H1–H5 | commit under `dav-test-client/claude-memory/projects/sample-app/`; no local auto-memory file |
| S4n | Project-only fact in a directory with no git remote | H1 | Claude says it can't be saved as a project memory; nothing committed |
| S5 | Ambiguous fact | H1, H5, H6 | one-line scope question before saving |
| S6 | Save on host A, new session on host B reads it (general **and** project) | H1→H3, H3→H5, H5→H6 (general only), H4→H1 (project) | memory available on B; the project memory appears in B's session-start index |
| S7 | S2 issued deep in a long session (after compaction) | H1, H5 | routes correctly |
| S8 | Memory containing a secret | H1, H6 | refused; no commit |
| S9 | Same memory edited concurrently from two hosts | H1 + H3 | conflict file appears; reconciled on next session start |
| S10 | App uninstalled from test org | H1 | clear `app_not_installed` message |
| S11 | Connector unavailable (disable the staging connector with `/mcp`, or block the Worker), then save | H1, H3 | entry in `~/.claude/memory-outbox/`; "queued in outbox for <scope>" announced; no commit |
| S11b | S11 continued: restore the connector, start a new session | H1, H3 | hook reports the queued count; Claude flushes; commit lands; outbox empty |
| S11c | Queued update whose `version` went stale (memory edited from another host before the flush) | H1 + H3 | flush produces a conflict copy, not an overwrite; outbox entry removed |
| S11e | S11 continued: with the connector still unavailable, start a new session in a repo that has a snapshot | H1, H3 | the snapshot's memories appear, labeled stale with their date; Claude says the connector is unavailable |
| S11f | Connector healthy, new session | H1 | `~/.claude/memory-cache/<key>.md` is rewritten with a newer `as_of` |
| S13 | Two running sessions: H1 saves a memory; H3 (already running) then makes any memory tool call | H1 + H3 | H3's result includes the change notice with the new memory, and Claude mentions or uses it |
| S14 | Long session: force compaction (`/compact`), then ask about a memory saved at the start | H1, H5 | Claude calls `memory_index` again after compaction (H1: prompted by the hook; H5: by the server instructions) and answers correctly |
| S15 | Make `claude-memory-test` public, then start a session and save to it | H1 | health reports `repo_public` with the visibility action; the save is refused with "not saved: repo is public"; switching the repo back to private clears the warning and the save then succeeds |
| S11d | Connector unavailable in a cloud session and in chat | H5, H6 | "not saved: <reason>" announced; nothing queued |
| S12 | Preflight: break one thing at a time — revoke the GitHub token, uninstall the app from the test org, remove the user from the test org, point to a missing repo, block the Worker URL, turn auto-memory on, delete the routing rule, corrupt the scope map | H1 (all), H5 (server-side ones) | exactly one warning line per broken item, naming the right action; silent once fixed |
| S12h | Preflight with everything healthy | all | no health output at all |

**Verification:** pass/fail is decided by checking the repos with `gh api`: expected commit, file, and trailers. For S0 and S4, also confirm that no local auto-memory files appeared. For S4n and S8, confirm no commit. **Test runner** (`tests/e2e/run.py`): for each scripted host and scenario, it:

1. runs `claude -p "<prompt>"` once, locally or over SSH, in the right directory
2. checks the outcome with `gh api` (which repo and path, trailers, no local memory file, outbox state)
3. writes a PASS/FAIL row

It checks **outcomes, never Claude's wording**, because replies vary from run to run. Routing prompts (S2/S4/S5) run 3× each per host, and a scenario passes only if all runs pass.

Manual hosts follow a checklist, verified the same way.

**Fixed prompt set:** ~10 phrasings covering S2, S4, and S5, kept in the repo (`tests/e2e/prompts.json`) so results are comparable across hosts and runs. The first run uses layers A + C only, to decide whether layer B is needed. The second run adds B.

**Results:** recorded per run in `tests/e2e/results/<date>.md` as a host × scenario grid.

## 10. Rollout

1. User creates the Cloudflare account (2FA) and the GitHub App (guided). User creates `dav/claude-memory`, `dav/claude-memory-test`, and the test org.
2. Build the Worker. Levels 1 and 2 green on staging.
3. Add the staging connector in claude.ai. On the Mac and VMs, run the **setup script** (`claude-memory-cloud/setup.sh`, idempotent). It:
   - turns auto-memory off
   - adds the routing rule to `~/.claude/CLAUDE.md`, with a marker line
   - installs the `UserPromptSubmit` hook (B) and the `SessionStart` outbox + snapshot + preflight hook (E, F, G, H), registered for all sources including `compact`
   - writes `~/.claude/memory-scopes.json` and the Worker URL
   - runs the local preflight once and prints the result In the cloud environment: set the auto-memory env var. Run Level 3, then Level 4.
4. Deploy production.
5. **One-time migration** of existing local memories:
   - Source: the `claude-memory-mcp` cache (`~/.claude-memories/<vm>/<project-slug>/memory/`), which holds the Mac's and the VMs' memories.
   - For each project folder, find its git remote by locating the repo on that host. Present the mapping table `slug → owner/repo` for the user to confirm or correct.
   - The user picks which memories are general (→ `general`) and which are project memories (→ `project`). Merge duplicates of the same project across hosts with `memory_save`'s similar/exists handling.
   - Done with a script that calls the production tools, so secret scanning and indexing apply.
   - Local auto-memory folders are left in place (not deleted) as a backup.
6. Onboard the client: an org owner installs the app on their `claude-memory` repo; add the scope; redeploy.
7. **Bootstrap script for other developers** (Plan 4, after production works). `claude-memory-cloud/bootstrap.py` uses only the Python standard library and is idempotent. It replaces most of the manual Quickstart Parts 1–5. Part 2 (Cloudflare signup, 2FA, `wrangler login`) stays manual, and so does adding the connector in claude.ai.
   - **Preflight:** it checks `gh auth status`, `npx wrangler whoami`, and `node --version`. Each failure names its fix, e.g. "run `gh auth login`".
   - **Memory repo:** `gh repo create <you>/claude-memory --private`, skipped if the repo already exists.
   - **GitHub App, via GitHub's App Manifest flow:**
     - The script serves a one-page form on `127.0.0.1:<random port>`. The form posts a manifest to `https://github.com/settings/apps/new?state=<random>` with every field from Quickstart Part 3 prefilled: name `<you>-claude-memory`, callback `https://claude-memory.<sub>.workers.dev/callback`, Contents read/write, webhook inactive, no OAuth on install, installable by any account.
     - The user clicks **Create**. GitHub redirects to `127.0.0.1:<port>/done?code=…&state=…`. The script checks `state` and exchanges the code (`POST /app-manifests/{code}/conversions`, within the hour it's valid) for the client ID, client secret, and slug.
     - The flow also returns a private key, which isn't needed. The script discards it without writing it anywhere, and shows the app-settings link where the user deletes it.
   - **Install:** opens `https://github.com/apps/<slug>/installations/select_target`, tells the user to select only `claude-memory`, and waits for Enter.
   - **Cloudflare:** creates the KV namespaces, writes the ids, `PUBLIC_URL`, `GITHUB_APP_SLUG`, and `SCOPES` into `wrangler.jsonc`, sets the three secrets by piping them to `wrangler secret put … --env production` on stdin, deploys, and checks `/health`.
   - **Secrets** (client secret, encryption key) go only to `wrangler`. They are never printed, logged, or written to disk. Non-secret state (slug, client ID, subdomain, KV ids) is kept in `.bootstrap.json` (gitignored) so a rerun resumes where it stopped.
   - **Ends** by printing the connector URL and the remaining manual steps: add the connector in claude.ai, then run `./setup.sh` on each machine.
   - **Tests:** unit tests for the manifest contents and the `wrangler.jsonc` edit; the redirect and code exchange are tested against a local fake GitHub. Plus one real run on a fresh GitHub account and Cloudflare account, following the updated Quickstart.
   - **Quickstart:** the main path becomes "Cloudflare signup → `wrangler login` → `./bootstrap.py` → add the connector → `./setup.sh`". The manual Parts 1, 3, 4, and 5 move to an appendix.

8. **Security self-check: `npm run doctor`** in `claude-memory-cloud` (Plan 4, Python, standard library only). It runs automatically before `deploy:staging` and `deploy:production` (as an npm `pre` script, and a failure stops the deploy), and at the end of `bootstrap.py`. It prints one line per check, and every failure prints its fix:
   - `.dev.vars`: mode `600`, ignored by git, no placeholder values left. Values are never printed.
   - no editor or backup copies of it (`.dev.vars~`, `.dev.vars.bak`, `.dev.vars.swp`, …), which hold the same secrets
   - no secrets in tracked files or in git history (the server's secret-scanner rules, run over `git log -p`)
   - the three Worker secrets exist in the target environment (`wrangler secret list` names only)
   - the GitHub App's permissions are exactly contents:write and metadata:read, and it subscribes to no webhook events (from the app's public API listing)
   - every repo in `SCOPES` is private (via `GET /repos/{repo}` with the developer's `gh` token)

   Checks that can't be automated (2FA on GitHub and Cloudflare; the client secret only in a password manager; no private key generated for the app) are listed at the end as a manual checklist. The Quickstart gets a short "Check your security setup" section built around this command.

### Documentation

Shipped in the `claude-memory-cloud` repo, written for other developers as well as the current setup:

- **`docs/QUICKSTART.md`:** step-by-step setup: memory repo, Cloudflare account, GitHub App, deploy, connect, per-machine setup, verification, adding a client org, and a development/test appendix.
- **`docs/FAQ.md`:** what it is, security and privacy, day-to-day behavior, operations.

Drafts live in this repo at `docs/cloud-memory/` until `claude-memory-cloud` exists. Plan 1 Task 1 moves them there. Each later plan updates them when it changes user-visible behavior, and Plan 4 checks every step against the real deployment.

## 11. Open items to resolve during build

- ~~Confirm that `workers-oauth-provider` encrypts grant props with the issued token (§4).~~ Resolved: verified in 1.2.3. Props are AES-GCM encrypted with key material from the token.
- ~~Confirm that each surface reports a distinct MCP clientInfo name, for the `Memory-Source` trailer (§5).~~ Resolved: replaced by the `source` tool argument.
- ~~Confirm the current state of Cloudflare's GitHub-OAuth MCP demo as a starting point (§3).~~ Resolved: the demo was stale. The Worker uses `workers-oauth-provider` 1.2.3's own consent and upstream helpers instead.
- Resolved: `McpAgent` is deprecated. The Worker uses MCP SDK v2 (`@modelcontextprotocol/server`) and stateless `createMcpHandler`.
- Confirm cloud sessions can be launched from the CLI, for scripting H5 (§9).
- Tune the similarity threshold (§6).
- Confirm that turning auto-memory off removes the built-in memory instruction from the system prompt, not just the file loading (§7, test S0).
- Confirm `CLAUDE_CODE_DISABLE_AUTO_MEMORY` set as a cloud environment variable takes effect in cloud sessions (§7, test S0 on H5).
