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
