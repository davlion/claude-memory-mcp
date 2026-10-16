# Build rulings — Plan 1 and Plan 1b (claude-memory-cloud)

Decisions the build controller made on your behalf while executing the plans, in order. Each: what was decided — why — what it costs if wrong.

## 2026-10-13-cloud-memory-worker

- F1 mockFetch now prefers a matching regex, else the longest string prefix — fixes every route-order bug at once instead of reordering ~6 tests — if wrong, a test that relied on first-match order breaks visibly.
- F2 empty-repo snapshot expectation includes isPrivate: true — follows the Snapshot change — none.
- F3 indexAfter spreads snap — type correctness — none.
- F4 Task 12 deletes the smoke probe test (stub hook removed); auth.test covers interception — if wrong, interception loses a cheap direct test.
- F5 live-test mem() passes force: true — generated descriptions are Jaccard-similar by design — live suite no longer exercises similarity (unit tests do).
- F6 cookie parsing splits on first "=" — correctness — none.
- F7 stub comment says Task 12 — none.
- F8 env.ts augments Cloudflare.Env so `env` from cloudflare:workers is typed — implementer verifies with tsc — if the plugin uses a different interface, implementer adapts.
- F9 hoisted the duplicated github_api Check into githubApiFail(); kept the two small r() result closures (different captured names, 1 line each) — a reviewer may still flag them as Minor.
- F10 file structure lists auth-helpers.test.ts — none.
- F11 Task 15 also updates memory_scopes reason values in the spec — none.
- F12 split into "ignores unknown keys" and a real "failing check never fails the call" test — none.
- batch Tasks 2–4 (remote.ts, memory.ts, secrets.ts) into one implementer + one review — independent pure modules, complete code in plan, no shared files — if wrong, a defect in one delays the other two's completion.
- .gitignore gains `.dev.vars*` + `!.dev.vars.example` in Task 5's dispatch — editor backup .dev.vars~ (likely holds the secret) is untracked but not ignored — if skipped, a later `git add -A` could commit a secret.
- fix all three plan-mandated secrets.ts findings — spec §6 makes the scanner the guard against committing credentials; correctness beats plan text — cost if wrong: a slightly broader/narrower rule set than planned.
- also fold in two Minors cheaply: buildIndex collapses whitespace/newlines in descriptions (index corruption / forged headings); remote.ts tightens owner to [A-Za-z0-9-] and rejects "."/".." repos (API path interpolation) — security-adjacent and small — cost if wrong: a few extra lines.
- keep per-commit Co-Authored-By naming whichever model actually wrote the commit; no amends — attribution accuracy, harmless — cost if wrong: cosmetic trailer inconsistency on a feature branch.
- carry three Task 7 minors into Task 8's dispatch as extra items — (1) FakeStore snapshot uses GitHubStore's MEMORY.md + single-level memories/ filter (Task 8 tests lean on the fake), (3) a 422 from the README-init PUT returns ref_moved (concurrent first saves), (4) KV blob cache entries get expirationTtl 30 days (limits retention of plaintext memory content) — cost if wrong: small extra diff in Task 8.
- carry two Task 8 minors into Task 10's dispatch — (1) sanitize `source` in operations message() (collapse whitespace, cap 100 chars) to prevent trailer forging; (2) searchMemories matches name + description + body only, not YAML keys (spec §6) — cost if wrong: small extra diff in Task 10.
- fix round 1 also folds in security/robustness minors #1 (only bad_refresh_token = revoked; others transient), #2 (fetch/JSON failures in token calls → temporarily_unavailable on refresh, local error page at /callback), #4 (keep old refresh token if none returned), #7 (negative allowlist tests), #8 (formData in test, no console warning) — auth code; cheap now, costly later — cost if wrong: slightly larger fix diff.
- carry two Task 12 minors into Task 13's dispatch — host pin compares full origin (rejects http:// on the public host); open-redirect test asserts status 400 / null location — cheap hardening before deploy — cost if wrong: tiny extra diff.
- hold the final-fix dispatch until the threat-model review returns, then send ONE fix wave covering both — skill requires one fix dispatch; avoids two waves — cost if wrong: a short delay.
- final-review + threat-model fixes become Plan 1b (hardening & multi-user) via spec update + plan, instead of a single fix dispatch — scope is architectural (per-user scopes, per-context loading, injection framing) — cost if wrong: plan-writing time before fixes land.

## 2026-10-14-cloud-memory-hardening

- F1 (T1) replace starting at `let res: Response;`, not `try {` — avoids redeclaring res — none.
- F5 (T3) Since version = SHA-1 of the REBUILT index text (not the stored MEMORY.md blob sha) — index is rebuilt from files, so hand edits must change the version — cost if wrong: extra hash per scope (cheap).
- F4 (T4) remove `parseScopes` if unused in src after T4 (move its tests to parseScopeMap); fix comment — dead code — none.
- F3 (T4) export `esc` from consent.ts and reuse instead of copying escHtml — DRY — none.
- F6 (T3/T5) rename stale operations.test title; drop the T5 duplicate since-map assertion — none.
- F2 (T6) when replacing tools.test, keep T5's "memory_search defaults to the same context" test — otherwise T6 silently deletes T5 coverage — none.
- carry into Task 2 — health.ts githubApiFail must classify via toOpError (server_limit/internal get their own detail+action; never echo raw exception text) — same no-echo rule as Task 1 — tiny diff.
- carry T3 minor #1 into Task 9 (request isBinary/isTruncated; mark such memories unreadable instead of "" so they can't be overwritten blind) and #3 into Task 8 (size guard before KV put so >25MiB isn't reported as write-quota) — data-safety/accuracy — small diffs.
- carry T4 minors — into Task 5: parseScopeMap throws on duplicate logins differing only in case; resolveTarget uses Object.hasOwn (no prototype keys); into Task 7: add githubId to Props and refuse at /mcp when a pin exists and differs — cheap defense-in-depth — small diffs.
- carry into Task 6 — INSTRUCTIONS tells Claude to pass `scopes: ["<client>"]` when the user names a client in chat (spec "client scopes load when the user names the client") — reliability — one line.
- fix round 1 also folds minors #3 (cleanDescription in search), #4 (nonce in closing tag), #6 (memory_health preamble), #7 (nonce-consistency test), #5 (document provenance limits in THREAT-MODEL §3) — security layer; cheap now.
- carry into Task 9 — escapeData normalizes NFKC and strips \p{Cf} before matching (zero-width / fullwidth lookalikes); drop framedResult's unused scope/project params — defense in depth — tiny diff.
- carry into Task 8 — wiring tests assert toBe(415) for allowed /mcp cases; test that /callback stores githubId + authorizedAt in props; /mcp KV read failure → shaped `unavailable` response not raw 500. Into Task 10 — FAQ/self-hosting note: rare double failure (transient GitHub error during a refresh race, or rotated tokens + failed grant write) can leave a grant serving 503s for ≤2h then requiring reconnect.
- carry into Task 10 (as a small code commit) — bump KV snapshot key snap:v1 → snap:v2 (pre-deploy cache entries lack the unreadable flag); repo_public wording when visibility unknown ("couldn't confirm private") — cheap correctness.
- defer Steps 8–9 (seed script + CPU measurement) — informational only on Workers Paid; user didn't opt in — cost: Free-plan self-hosters lack a measured CPU number until run.
- ONE fix wave covering Important #1 (+suspended_at, index-404 action, tokenBad narrowed) and Minors #2–#7, #9; defer #8 — skill: one fix dispatch; all pre-production items — cost: larger single diff.

## 2026-10-15-cloud-memory-e2e

Plan 3 (Level 4 end-to-end), 2026-10-15 to 2026-10-16. Full ledger: `claude-memory-cloud/docs/plan-3/build-ledger.md`.

- Work on branch `plan-3-e2e` in the main checkout, no worktree — the plan's starting point says so — none.
- Code tasks 2–6 before Task 1 (VMs were off); Task 2's kit redeploy moved into Task 1 — no task consumed Task 1's results except two small follow-ups — a follow-up commit.
- VMs get `sample-app` by rsync of the Mac's clone (origin intact) instead of adding GitHub credentials — the runner never pulls — the VM checkouts can't pull.
- The runner and probe scrub every `ANTHROPIC_*`, `CLAUDE_CODE_*`, `CLAUDECODE`, `CLAUDE_PID`, `CLAUDE_EFFORT` variable (the plan listed a subset; more leak) — none.
- H5 cloud stays manual — new cloud sessions are interactive-only (V7) — H5 rows done by hand.
- U1's prompt-hook check replaced by a settings.json kit-hook check — stream-json never shows UserPromptSubmit output, so the old check was vacuous — none.
- Dropped H4's partial rows from run `xdgroe` and reran H4 in full — the crash was GitHub connectivity — none.
- S5 phrasing 3 ("the linter runs before tests") kept for both compared runs, then replaced with "we tag releases with a v prefix" — in a repo it's a project fact, not ambiguous — S5 still not ambiguous enough.
- Cleanup deletes test files with `gh api`, and the resulting provenance ⚠ is documented in `test/e2e/README.md` — fast and deterministic; it clears at the next server write — a stale ⚠ line in staging after runs.
- S15 (repo made public) skipped — it would expose the test repo's history; the alternative needed a SCOPES change — `repo_public` is verified only by unit tests.
- "Remove the user from the test org" skipped — the user is its only owner — that health line unverified live.
- Layer B (prompt hook) kept — A + C and A + B + C grids were identical, but the hook demonstrably fires (user's call) — none.
- Snapshot written by a `PostToolUse` hook instead of Claude (kit 0.1.2) — the Write call showed in every transcript; the hook gets the full result silently — none found (18/18 regression).
- `Edit(~/.claude-memory-cloud/cache/**)` dropped from new installs' allow rules — Claude no longer writes there — one prompt if Claude ever writes the cache by hand.
- Server instructions built per user with the user's scope names, plus a no-remote rule and `readOnlyHint` annotations — Level 4 findings (S5, cloud) — S5 9/9 in Claude Code after.
- Instructions held to ≤ 4000 characters by a test — Claude Code truncates server instructions at 4096 (found live: the new scope line was cut off) — any new instruction must fit.
- The "use these tools, not a host's built-in memory" instruction was removed before going live — it conflicts with the user's open question about keeping personal memories in claude.ai — chat keeps routing some saves to built-in memory until the final review decides.
- `memory_move` tool not built; S17 shows the read → save → delete recourse works — optional Plan 4 item — a prompt per move.

## Known follow-ups (deferred minor findings still worth doing)

Triaged by the Plan 1 and Plan 1b final reviews; everything not listed was judged stay-deferred or closed.

**Before production (Plan 4)**
- memory_search drops the project target silently when its owner scope is unreachable for reasons other than an error (app not installed, not_reachable, suspended, public): add a problem line.
- Pin hygiene when removing a friend whose login may be reused: also `wrangler kv key delete --remote "allowlist:github-id:<login>"` (documented in the Quickstart).
- Production checklist: production KV ids; public production app with "Only select repositories"; set the SCOPES secret before first sign-in (pins the owner's ID on first connect); run `node scripts/check-scopes.mjs` before every `secret put SCOPES`.
- Health shows `✓ project … → <client repo>` even when that client scope fails (seen with `app_not_installed`, Plan 3 Task 10): mark the project line failed or omit it.
- Decide chat routing between claude.ai's built-in memory and the connector (final review of Plan 3: the user may keep personal memories out of GitHub). Chat never calls `memory_index` at start, never asked the S5 scope question, and doesn't use the exact "saved to / not saved" line.
- Optional: `memory_move` (atomic move between scopes; today read → save → delete, which prompts for the delete).
- Optional: e2e cleanup through `memory_delete` instead of `gh api`, so runs don't leave a provenance ⚠ in staging.
- Optional: cut per-call CPU overhead (~30 ms fixed: build the MCP server and schemas once per isolate, cache health results briefly) if Workers Free support is wanted.

**Later / cleanup**
- `Snapshot.indexSha` is dead (version is the SHA-1 of the rebuilt index); remove at the next cache-key bump.
- `gather` calls reachability twice per memory_index (cached; a few extra subrequests).
- Rate limiter `.limit()` throwing → 500 (fail open arguably better); limiter is approximate by Cloudflare design.
- Pin get/put not atomic and the write fails open (low risk; commented).
- A refused sign-in leaves the stranger's own `ghu_` token unrevoked.
- Legacy grants without `githubId` skip the pin check until they age out (production starts with fresh grants).
- `lastRateLimit` may hold the GraphQL quota after a snapshot.
- Truncated-tree error reports `internal` rather than a size message.
- Live tests leave stamped artifacts in the test repo; trailer test checks only the last 5 commits.
- ~~Spec §7 B/H still describes a local scope-map copy; reword in Plan 2 for the per-user map.~~ Done in Plan 2 Task 15.
