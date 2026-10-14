# Cloud Memory — Design Spec

**Date:** 2026-10-13
**Status:** Approved in brainstorming; pending spec review
**Implementation repo:** `claude-memory-cloud` (new). This repo (`claude-memory-mcp`) is unchanged and keeps syncing project memories from VMs.

## 1. Goal

A standard memory context that follows the user across every Claude surface:

- Claude Code — local CLI and Desktop app on the Mac, and on the VMs (`earsvm`, `lume-claude-sandbox`)
- Claude Code cloud sessions (claude.ai/code)
- claude.ai chat — web, Desktop, mobile

Any session can read and add memories. **General** memories (about the user and how they work) and **client** memories (about a client org as a whole) live in the cloud. **Project** memories stay local in Claude Code auto-memory and are never mixed in.

The same mechanism must work for a client whose code lives in private GitHub repos, with access governed by the permissions that client grants the user.

### Non-goals (v1)

- Syncing project memories (the existing `claude-memory-mcp` covers this).
- Staleness/decay scoring, contradiction linting, scheduled consolidation. Consolidation is a candidate for a later scheduled Claude routine.
- Embeddings / semantic search.
- Non-Claude AI tools.

## 2. Key facts the design rests on

Verified during research on 2026-10-13 (see brainstorming transcript for sources):

- A custom connector added on claude.ai is available in claude.ai chat (web/Desktop/mobile), in local Claude Code when logged in with a claude.ai account, and in cloud Claude Code sessions. Connector traffic goes through Anthropic's servers, so it is not limited by the cloud session's GitHub proxy, which only allows repos attached to the session.
- claude.ai custom connectors support OAuth through Dynamic Client Registration (DCR), CIMD (Claude's published client identity), or a user-supplied client. They support custom static headers only as a limited org beta.
- GitHub's hosted MCP server does not support DCR. GitHub's own docs say it can't currently be added as a Claude connector, and a general GitHub connector would expose all of a client's code repos anyway. So we run our own server.
- No native Anthropic feature bridges claude.ai memory and Claude Code memory. Chat and Cowork memory were merged on 2026-08-25; Claude Code is explicitly separate "for now". **Watch item:** if Anthropic syncs Claude Code memory, revisit this project. Client-owned repos and per-client scopes would remain differentiators.
- Claude Code auto-memory in cloud sessions is local to the VM and is lost when the session ends.
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
GitHub:  dav/claude-memory            (scope: general)
         <client-org>/claude-memory   (scope: <client>)
```

### Components

| Unit | Responsibility | Depends on |
|---|---|---|
| `src/index.ts` | Wires OAuthProvider, auth handler, and MCP server | everything below |
| `src/github-auth.ts` | GitHub App authorize/callback; token refresh | GitHub OAuth endpoints, KV |
| `src/scopes.ts` | Maps scope name → repo; reports reachability per user | config, GitHub API |
| `src/store.ts` | Reads tree/files at a commit; atomic multi-file commit with ref compare-and-swap | GitHub Git Data API |
| `src/memory.ts` | Frontmatter parse/serialize; index rebuild; similarity check | none (pure) |
| `src/secrets.ts` | Secret-pattern scanner | none (pure) |
| `src/tools.ts` | MCP tool definitions; maps results and errors | memory, store, scopes, secrets |
| `src/instructions.ts` | Server instructions text (includes routing rule) | none |

The pure units (`memory`, `secrets`) contain no I/O. `store` is the only unit that talks to the Git Data API.

### Infrastructure

- **Cloudflare:** a free account with 2FA. Workers on the free plan, KV for OAuth grants and the search cache, deployed with `wrangler`. Default URL `*.workers.dev`; no custom domain needed.
- **Two deployments:**
  - `claude-memory-staging`, mapped to test repos
  - `claude-memory`, mapped to real repos
- **Secrets** (`wrangler secret put`): `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `COOKIE_ENCRYPTION_KEY`.
- **Config** (a `wrangler.jsonc` var): `SCOPES`, a JSON map from scope name to repo, e.g. `{"general":"dav/claude-memory","acme":"acme-org/claude-memory"}`. Adding a client means installing the app on their repo, adding one line here, and redeploying.
- **Starting point:** Cloudflare's "remote MCP server with GitHub OAuth" demo. Check its current state before adopting it.

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

- Pinned public base URL. Reject requests whose Host doesn't match, so the OAuth issuer can't be spoofed.
- Redirect URI allowlist: `https://claude.ai/api/mcp/auth_callback`, `https://claude.com/api/mcp/auth_callback`, plus `localhost` callbacks for Claude Code CLI OAuth.
- The Worker logs no memory content and no tokens.

### Data handling

Memory text passes through the Worker in plaintext, because TLS ends at Cloudflare, and it reaches Anthropic whenever Claude reads it. The rule is **no secrets in memories**, enforced by the scanner in §6. Every write is a commit in the owner's repo, which gives a full audit trail.

Client-hosted deployment is possible, since the code is small and self-contained, but it is not needed for the current client: a small shop that trusts the user.

## 5. Repo layout and memory format

One `claude-memory` repo per scope:

```
claude-memory/
├── README.md        # what this is; rules (no secrets; format)
├── MEMORY.md        # index — maintained by the server
└── memories/
    ├── <name>.md
    └── <name>.conflict-<UTC timestamp>.md   # only when a conflict occurred
```

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

- Message: `<op>: <name>`. Trailers: `Memory-Source: <client>` (from the MCP `initialize` clientInfo name; record verbatim, and **verify during build** that surfaces report distinct names) and `Memory-Scope: <scope>`.
- Mechanism: Git Data API. Create blobs, then a tree, then a commit, then update the ref with `force: false`. If the ref update fails because the branch moved, re-read and re-apply. That is always safe for a different-file change; a same-file change follows the conflict rule in §6.

## 6. Tools

All tools take `scope`, the name of a key in `SCOPES`. Where noted, it defaults to `general`.

| Tool | Parameters | Returns |
|---|---|---|
| `memory_scopes` | — | `[{scope, repo, reachable, writable, reason?}]`, where `reason` is `app_not_installed` or `no_user_access` |
| `memory_index` | `scopes?: string[]` (default: all reachable) | Per scope, the `MEMORY.md` content, including the Conflicts section |
| `memory_read` | `scope`, `names: string[]` (max 20) | Per name, `{name, content, version}` or `{name, error:"not_found"}`. `version` is the file's blob SHA |
| `memory_search` | `query`, `scopes?` | `[{scope, name, description, snippet}]`, max 20. Case-insensitive substring/term match over name, description, and body |
| `memory_save` | `scope` (default `general`), `name`, `description`, `type`, `body`, `version?`, `force?: boolean` | `{status, name, commit_url?, similar?, conflict_file?, pattern?}` |
| `memory_delete` | `scope`, `name`, `version?` | `{status: deleted|conflict|not_found, commit_url?}` |

### `memory_save` semantics

Checks run in this order:

1. **Validate:** name format, type enum, required fields. Failure → `status: invalid` with a message.
2. **Secret scan** of all fields. A hit → `status: rejected_secret` with `pattern` (the rule name, never the matched text). Nothing is written.
3. **No `version` (create):**
   - If `<name>.md` exists → `status: exists`, with its `version`. Claude should read it and update instead.
   - If similar memories exist and `force` is not set → `status: similar_found`, with `similar: [{name, description}]` (max 3). Nothing is written.
   - Otherwise write → `created`.
4. **With `version` (update):**
   - If the current blob SHA equals `version` → write → `updated`.
   - If it differs → write the new content to `memories/<name>.conflict-<ts>.md` (with the Conflicts index entry) → `status: conflict`, with `conflict_file`. The original is untouched.
   - If the file is missing → `not_found`.

`memory_delete` with a stale `version` → `conflict`, and nothing is deleted. Without `version` → unconditional delete. Claude is instructed to pass a version.

### Similarity check (borrowed from memoria_mcp)

Normalized tokens of name and description are compared with Jaccard similarity; ≥ 0.5 counts as similar. Threshold to be tuned during build with real memories. Pure function in `memory.ts`.

### Secret scanner

Pure function in `secrets.ts`, with rules for:

- GitHub tokens (`ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`, `github_pat_`)
- AWS access keys (`AKIA…`/`ASIA…`)
- PEM private-key blocks
- Slack tokens (`xox[abprs]-`)
- Anthropic/OpenAI-style keys (`sk-ant-`, `sk-`)
- Google API keys (`AIza`)
- JWTs
- generic `password|secret|token\s*[:=]\s*<long value>`

Every rule needs a true-positive and a false-positive test.

### Search

The Worker fetches the tree and the files for the scope's current commit and searches in memory. The result is cached in KV, keyed by commit SHA. GitHub code search is not used because its index lags behind recent writes.

### Resource

`memory://{scope}/index`, with the same content as `memory_index` for that scope.

### Conflict reconciliation

No dedicated tool. Claude reads both files, saves the merged content to `<name>.md` with its current `version`, then deletes the conflict file. Each conflict file appears in the index until it is resolved.

## 7. Routing and triggering

**Problem:** in Claude Code, "save a memory…" naturally goes to the built-in local auto-memory, whose instructions are in the system prompt. Connector tools are often deferred, and Claude has to decide whether a fact is general, client, or project. Four layers address this.

### A. Routing rule in `~/.claude/CLAUDE.md`

Covers local Code on the Mac and VMs. Distributed to the VMs as part of setup.

> **Where memories go.** When saving a memory:
> - About me or how we work in general → `memory_save` scope `general` (claude-memory connector).
> - About the client org as a whole → `memory_save` scope `<client>`.
> - About this codebase only → local auto-memory.
>
> If it's unclear, ask in one line ("general, <client>, or this project?"). After saving, state the scope it went to. At session start, call `memory_index`.

### B. `UserPromptSubmit` hook

A user-level script in `~/.claude/hooks/`, installed on the Mac and the VMs.

- It matches memory-intent phrases, case-insensitive: `save (a |this )?memory`, `remember (this|that)`, `don't (do|let) .* again`, `note for (the )?future`, `add (this )?to (your )?memory`.
- On a match, it emits `additionalContext` containing a two-line reminder of the routing rule, plus the **inferred client scope**: the `origin` remote's owner, looked up in a local copy of the scope map (`~/.claude/memory-scopes.json`). If the owner is unknown, it injects no scope hint.
- If the phrases don't match, it outputs nothing. It must run in under 100 ms and needs no network.
- Whether B is needed is decided by test S2/S4/S5 results with A + C alone (§9). It is built regardless, because it is small, and it can be disabled.

### C. Server instructions

Sent by the Worker wherever the connector is enabled, so they reach cloud sessions and chat:

> At the start of a conversation, call `memory_index`. Read individual memories when relevant. Save lasting facts about the user (scope `general`) or about a client org as a whole (client scope). Never save secrets or project-specific details here. Prefer updating an existing memory (pass its `version`) over creating a new one. After saving, tell the user the scope. In Claude Code cloud sessions, local auto-memory is lost when the session ends: for project-only facts, say so and offer to add the fact to the repo's `CLAUDE.md` instead. If `memory_index` lists conflicts, offer to reconcile them.

### D. Scope announcement

Included in A and C: every save ends with "saved to **<scope>**", so misroutes are visible right away.

## 8. Error handling

| Condition | Behavior |
|---|---|
| GitHub 404/403 on scope repo | Distinguish `app_not_installed` (installation lookup) from `no_user_access`; message names the fix |
| Token refresh fails | Message: "reconnect the claude-memory connector in claude.ai settings" |
| GitHub 5xx / rate limit | Fail clearly with the retry-after if known. **No silent local fallback.** |
| Ref update race | Re-read and re-apply. After 3 attempts → error |
| Unknown scope | List valid scopes |
| Secret detected | `rejected_secret` + rule name |
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
- scope resolution
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
- **Concurrency:** two simultaneous updates with the same `version` → exactly one `updated` and one `conflict`
- Two simultaneous creates of different names → both land; the index contains both

### Level 3 — Hook tests

Shell-level tests of the `UserPromptSubmit` script:

- trigger and non-trigger phrase tables
- remote → scope mapping: client org, personal repo, no remote, non-git directory
- no output on a non-match
- runs under 100 ms

### Level 4 — Surface matrix (end-to-end)

**Prerequisites:**

- A test client org (free GitHub org, e.g. `dav-test-client`) with the app installed on `dav-test-client/claude-memory`. Never experiment on the real client first.
- A test code repo in that org, used for S3.
- Staging connector added in claude.ai.
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
| S4 | Project-only fact | H1–H4 | written to local auto-memory; no connector commit |
| S4c | Project-only fact in cloud | H5 | Claude warns it won't persist and offers repo `CLAUDE.md` |
| S5 | Ambiguous fact | H1, H5, H6 | one-line scope question before saving |
| S6 | Save on host A, new session on host B reads it | H1→H3, H3→H5, H5→H6, H6→H1 | memory available on B |
| S7 | S2 issued deep in a long session (after compaction) | H1, H5 | routes correctly |
| S8 | Memory containing a secret | H1, H6 | refused; no commit |
| S9 | Same memory edited concurrently from two hosts | H1 + H3 | conflict file appears; reconciled on next session start |
| S10 | App uninstalled from test org | H1 | clear `app_not_installed` message |

**Verification:** pass/fail is decided by checking the repos with `gh api`: expected commit, file, and trailers; for S4, the local auto-memory files; for S8, no commit. Scripted hosts run a driver script that issues the prompt and then checks. Manual hosts follow a checklist, verified the same way.

**Fixed prompt set:** ~10 phrasings covering S2, S4, and S5, kept in the repo (`tests/e2e/prompts.json`) so results are comparable across hosts and runs. The first run uses layers A + C only, to decide whether layer B is needed. The second run adds B.

**Results:** recorded per run in `tests/e2e/results/<date>.md` as a host × scenario grid.

## 10. Rollout

1. User creates the Cloudflare account (2FA) and the GitHub App (guided). User creates `dav/claude-memory`, `dav/claude-memory-test`, and the test org.
2. Build the Worker. Levels 1 and 2 green on staging.
3. Add the staging connector in claude.ai. Install layers A and B on the Mac and VMs. Run Level 3, then Level 4.
4. Deploy production. Seed `general` by promoting existing general-purpose local memories, with the user choosing which ones.
5. Onboard the client: an org owner installs the app on their `claude-memory` repo; add the scope; redeploy.

## 11. Open items to resolve during build

- Confirm that `workers-oauth-provider` encrypts grant props with the issued token (§4).
- Confirm that each surface reports a distinct MCP clientInfo name, for the `Memory-Source` trailer (§5).
- Confirm cloud sessions can be launched from the CLI, for scripting H5 (§9).
- Tune the similarity threshold (§6).
- Confirm the current state of Cloudflare's GitHub-OAuth MCP demo as a starting point (§3).
