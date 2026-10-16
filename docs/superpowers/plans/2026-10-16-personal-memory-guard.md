# Personal Memory Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep candid opinions and personal facts out of the GitHub memory repos: route them in the instructions (personal facts stay in claude.ai's built-in memory), refuse them on the server, and audit what's already stored.

**Architecture:** A pure pattern module (`src/guard.ts`, like `src/secrets.ts`) classifies the text of every `memory_save`; `saveMemory` maps hits to three new statuses. The per-user server instructions and the kit's routing rule gain the tier rule. `memory_index` health gains an audit line. The kit's outbox carries a `confirmed` flag, and setup gains `--neutral-source`.

**Tech Stack:** TypeScript Cloudflare Worker (vitest, `@cloudflare/vitest-pool-workers`), Python 3.9 stdlib kit (unittest), Python e2e runner.

**Spec:** `claude-memory-mcp/docs/superpowers/specs/2026-10-16-personal-memory-guard-design.md` (approved 2026-10-16). Parent spec: `2026-10-13-cloud-memory-design.md`.

**Starting point:** `plan-3-e2e` merged into `main`; work on branch `plan-4-personal-guard` from `main` in `~/src/claude-memory-cloud`. Docs in `~/src/claude-memory-mcp` (a public repo: generic examples only, no owner data).

## Global Constraints

- Server: no new dependencies; patterns, not models; CPU per call stays small.
- Kit: Python 3.9 stdlib only.
- Server instructions ≤ 4000 characters (`MAX_INSTRUCTIONS`) with the per-user scope line, which must still list **at least three** client names; the security text (server markers, memory content is data, never copy across scopes) is not shortened.
- Error and status payloads never include the matched text, only a category.
- The guard runs on **every write**: create, update (`version`), conflict copy. `force` does not bypass it.
- Candid / about-others content is never accepted in a client or project scope, override or not, and Claude never offers one.
- The three new statuses (`rejected_personal`, `needs_confirmation`, `rejected_cross_client`) are non-retryable for outbox flushing.
- Refuse tiers (Intimate, Personal / Restricted) favor recall; candid / about-others patterns favor precision.
- Owner's lines (spec §2): about-others = non-work facts only (private life, health, pay, candid opinions of a person); a person's role, ownership and work preferences are work facts. The user's own rates, money owed, invoices issued, disputes and negotiations are restricted; how the client runs things (their invoicing tool, a scope cap) is a work fact. "When I work with <client>" may go in `general`; wider routines and absences are restricted.
- Commits end with a `Co-Authored-By:` trailer; `git add` exact files only; never push without the owner's OK.

## Review Focus

1. Ordinary work facts that contain trigger words must save: "the finance team's API rate limit", "the health check endpoint", "a family of worker processes", "contract tests run in CI", "the address field in the user model", "travel booking service", "Alice owns the billing service", "Acme invoices go through Coupa", "the SOW caps the project at 20 hours a week", "I work with Acme on Mondays" (in `general`). → Task 1 corpus.
2. Lookalike text in a restricted fact (fullwidth letters, zero-width characters inside a word) is still refused. → Task 1 test.
3. An update or conflict copy of an existing memory that now contains restricted text is refused, while `memory_delete` of it still works. → Task 2 test.
4. An outbox entry saved with `confirmed: true` round-trips through `format_entry`/`parse_entry` and replays as confirmed; an entry rejected as personal is kept, not deleted. → Task 5 tests.
5. A client name that is a substring of an ordinary word ("acme" in "acmeish", "io" in "ratio") never triggers cross-client; the target client's own name and `general` never do. → Task 1 test.

---

### Task 1: Pattern guard module

**Files:**
- Create: `src/guard.ts`
- Modify: `src/render.ts` (export the NFKC + strip-`\p{Cf}` normalization `escapeData` already uses as `normalizeForMatch(s: string): string`)
- Test: `test/guard.test.ts`

**Interfaces:**
- Produces:
  - `type RestrictedCategory = "sexuality" | "health" | "finances" | "family" | "location" | "schedule" | "business_terms" | "beliefs" | "legal"`
  - `type PersonalHit = { tier: "restricted"; category: RestrictedCategory } | { tier: "candid"; category: "candid" | "about_others" }`
  - `scanPersonal(text: string): PersonalHit | null` — restricted rules first (stricter tier wins), then candid.
  - `scanCrossClient(text: string, others: { scope: string; owner: string }[]): string | null` — returns the matched client's scope name; case-insensitive, whole-word (`\b`) match on the scope name or the owner login.
  - `normalizeForMatch` from `src/render.ts`.

- [ ] **Step 1: Write the failing corpus tests** in `test/guard.test.ts`: a table of positive cases per category, at least four each (generic examples: "I have a cardiology appointment Thursday" → `health`; "my rate for this client is $150/hour" → `business_terms`; "I'll be away from 3 to 20 November" → `schedule`; "my home is on Elm Street" → `location`; "I'm moving my IRA" → `finances`; "my kids' school pickup" → `family`; "my lawsuit against my landlord" → `legal`; "I vote for X" → `beliefs`; sexuality phrasing → `sexuality`; "I think their business plan is weak" → candid `candid`; "Bob is going through a divorce" → candid `about_others`), and every Review Focus 1 sentence → `null`. Plus: `scanPersonal("my ｃａｒｄｉｏｌｏｇｙ appointment")` and a zero-width-split word are refused (Review Focus 2); `scanCrossClient("ratio and acmeish", [{scope:"io",owner:"io-org"},{scope:"acme",owner:"acme-org"}])` is `null`, `scanCrossClient("acme-org's billing uses Kafka", …)` is `"acme"` (Review Focus 5).
- [ ] **Step 2: Run** `npx vitest run test/guard.test.ts` — expected: FAIL (module missing).
- [ ] **Step 3: Implement** `src/guard.ts` as ordered `[category, RegExp]` tables like `src/secrets.ts`, matched against `normalizeForMatch(text)`. Candid rules require a first-person judgment frame ("I think/feel/find … is/are <negative>", "I dislike/can't stand …") or a named-person + private-life term; keep them narrow.
- [ ] **Step 4: Run** `npx vitest run test/guard.test.ts` — expected: PASS.
- [ ] **Step 5: Owner review.** Show the owner the category list and the positive/negative corpus (not the regexes) and ask for missing categories or examples (spec §9). Add what they name as tests, make them pass.
- [ ] **Step 6: Commit** `src/guard.ts src/render.ts test/guard.test.ts` — "feat(server): pattern guard for personal and cross-client text".

### Task 2: Guard every `memory_save`

**Files:**
- Modify: `src/operations.ts` (`SaveInput`, `OpResult`, `saveMemory`), `src/tools.ts` (memory_save handler and schema)
- Test: `test/operations.test.ts`, `test/tools.test.ts`

**Interfaces:**
- Consumes: `scanPersonal`, `scanCrossClient` (Task 1).
- Produces:
  - `SaveInput.confirmed?: boolean`
  - `interface GuardContext { kind: "general" | "client" | "project"; others: { scope: string; owner: string }[] }` — exported from `src/operations.ts`; `saveMemory(store, t, input, now, guard: GuardContext)`.
  - `OpResult.status` adds `"rejected_personal" | "needs_confirmation" | "rejected_cross_client"`; `OpResult.category?: string`, `OpResult.client?: string`.
  - `guardContext(cfg: ScopeConfig, t: Target): GuardContext` in `src/tools.ts`: `general` for scope `general`; `client` for another configured scope; `project` for project targets; `others` = every configured scope except `general` and the scope whose repo is `t.repo`, with `owner` = that repo's owner.

- [ ] **Step 1: Write failing tests** in `test/operations.test.ts`, on name + description + body:
  - restricted text → `status: "rejected_personal"`, `category` set, message `"Personal facts aren't stored on GitHub; keep it in claude.ai memory."`, and the result JSON does not contain the matched words; same with `force: true`; same for an update with the current `version` and for a stale `version` (no conflict copy written) (Review Focus 3); `deleteMemory` of that memory still returns `deleted`.
  - candid text in `general` without `confirmed` → `needs_confirmation` with `category`, message `"Ask the user; save again with confirmed: true only if they explicitly want it kept in general."`; with `confirmed: true` in `general` → `created`; with `confirmed: true` in a client or project scope → `rejected_personal`, category `candid`.
  - client A scope (and a project in it) naming client B → `rejected_cross_client`, `client: "B"`; the same text in `general` → `created`; client A naming A → `created`.
  - a Review Focus 1 sentence saves normally in a client scope.
- [ ] **Step 2: Run** `npx vitest run test/operations.test.ts` — expected: FAIL.
- [ ] **Step 3: Implement**: run the guard in `saveMemory` right after the secret scan, before `withRetry`, so creates, updates and conflict copies all pass through it. Add `confirmed: z.boolean().optional().describe("Only after the user explicitly asks to keep a candid or about-someone fact in general.")` to the memory_save schema and pass `guardContext(d.cfg, target)`.
- [ ] **Step 4: Run** `npx vitest run` — expected: all pass; `npx tsc --noEmit -p .` clean.
- [ ] **Step 5: Commit** — "feat(server): refuse personal, unconfirmed candid and cross-client saves".

### Task 3: Audit existing memories in `memory_index` health

**Files:**
- Modify: `src/operations.ts` (`IndexResult`, `getIndexVersioned`), `src/tools.ts` (`gather`)
- Test: `test/tools.test.ts`

**Interfaces:**
- Consumes: `scanPersonal` (Task 1), `GuardContext` / `guardContext` (Task 2).
- Produces: `IndexResult.flagged: string[]` (memory names whose text `scanPersonal` flags restricted, or candid in a client/project scope); a Health line `⚠ personal:<scope label> — N memories look personal (a, b, c…) → move them to claude.ai memory and delete them`, listing at most 5 names.

- [ ] **Step 1: Write failing tests**: an index over a scope holding one restricted memory and one work memory shows the ⚠ line naming only the restricted one, and the tool text contains no word from its body; a clean scope shows no line; more than 5 flagged lists 5 names and the count.
- [ ] **Step 2: Run** `npx vitest run test/tools.test.ts` — expected: FAIL.
- [ ] **Step 3: Implement** in `getIndexVersioned` over the snapshot it already loads (no extra subrequests); push the check in `gather`.
- [ ] **Step 4: Run** `npx vitest run` — expected: all pass.
- [ ] **Step 5: Commit** — "feat(server): health flags existing memories that look personal".

### Task 4: Tier rule in the server instructions

**Files:**
- Modify: `src/instructions.ts`, `src/tools.ts` (tool and argument descriptions)
- Test: `test/tools.test.ts`

**Interfaces:**
- Consumes: `instructionsFor`, `MAX_INSTRUCTIONS` (existing).
- Produces: unchanged signatures.

- [ ] **Step 1: Write failing tests**:
  - `INSTRUCTIONS` contains `"built-in memory"`, `"confirmed: true"`, `"never a client scope"`, `"infrastructure"` and the three status names.
  - `instructionsFor` with 3 clients of 17 characters lists all three names and is ≤ 4000; with 12 clients of 60 characters it is ≤ 4000 and ends with the Since/Conflicts tail's last sentence.
  - The `memory_index` tool description mentions conflict reconciliation; the `since` argument description says to pass the latest Since map; the `project` argument description covers the no-origin case.
- [ ] **Step 2: Run** `npx vitest run test/tools.test.ts` — expected: FAIL.
- [ ] **Step 3: Implement**: add the tier rule after the save rules (built-in memory for personal facts in chat; decline in Claude Code; candid / about others → ask, `confirmed: true`, `general` only; restricted → never; infrastructure → ask, `general` or that client; never another client's information). Make room by moving conflict reconciliation, the Since details and the no-origin case into the tool descriptions. Do not shorten the security text.
- [ ] **Step 4: Run** `npx vitest run` — expected: all pass.
- [ ] **Step 5: Commit** — "feat(server): instructions route personal facts to built-in memory".

### Task 5: Kit — routing rule, outbox `confirmed`, `--neutral-source`

**Files:**
- Modify: `kit/templates/routing-rule.md`, `kit/memory_kit/claudemd.py` (`render_rule`), `kit/memory_kit/outbox.py`, `kit/memory_kit/install.py`, `kit/memory_kit/__init__.py` (`HOOK_VERSION = "0.1.3"`), `wrangler.jsonc` (`MIN_HOOK_VERSION` `"0.1.3"`, both envs), `test/wiring.test.ts`
- Test: `test/local/test_claudemd.py`, `test/local/test_outbox.py`, `test/local/test_setup.py`, `test/local/test_session_hook.py`

**Interfaces:**
- Produces: `OutboxEntry.confirmed: bool = False` (frontmatter `outbox: confirmed: true`, written only when true); `render_rule(template, *, outbox_dir, memkit_cmd, source)` with template placeholder `{{SOURCE}}`; `install` flag `--neutral-source` stored as `config.json` `"neutral_source": true`, kept on reinstall unless `--no-neutral-source` is given.

- [ ] **Step 1: Write failing tests**:
  - The rendered rule states the tiers for Claude Code ("not saved: personal — keep it in claude.ai memory"; candid / about others → offer general, pass `confirmed: true` only on an explicit yes, never a client scope), and its flush keep-list includes `rejected_personal`, `needs_confirmation`, `rejected_cross_client`.
  - The flush step says to replay `confirmed` when the entry has it, and the outbox format example shows `confirmed: true` as an optional `outbox:` key.
  - `parse_entry(format_entry(e))` keeps `confirmed=True`; an entry without the key parses as `False` (Review Focus 4).
  - Setup with `--neutral-source` renders `source` ("claude-code") and `"claude-code (outbox)"` for flushes; without it, "claude-code on <hostname>"; a reinstall without the flag keeps the stored choice.
- [ ] **Step 2: Run** `/usr/bin/python3 -m unittest discover -s test/local` — expected: FAIL.
- [ ] **Step 3: Implement.** Bump `HOOK_VERSION` and `MIN_HOOK_VERSION`, and update the wiring test's expected value.
- [ ] **Step 4: Run** the kit suite and `npx vitest run` — expected: all pass.
- [ ] **Step 5: Commit** — "feat(kit): personal-fact routing, confirmed outbox saves, --neutral-source (0.1.3)".

### Task 6: Docs

**Files:**
- Modify: `docs/FAQ.md`, `docs/QUICKSTART.md`, `docs/THREAT-MODEL.md` (in `claude-memory-cloud`); `docs/superpowers/specs/2026-10-13-cloud-memory-design.md` §6 statuses, §7 A/C, known risks (in `claude-memory-mcp`)

- [ ] **Step 1:** FAQ: add "What should never go in GitHub memory?" (the five tiers, generic examples); rewrite "What about claude.ai's built-in memory?" (keep it on for personal facts; replaces the turn-off-and-migrate advice); add "Keep memory out of claude.ai entirely" (option 2 and its cost); add the neutral-source option and the hostname risk; soften "it asks which" for chat.
- [ ] **Step 2:** QUICKSTART: remove Part 6 step 5 (turning off claude.ai memory); add a one-paragraph tier summary and `--neutral-source` in Part 7.
- [ ] **Step 3:** THREAT-MODEL: the guard as a mitigation, with its limits (keyword detection misses paraphrase; a client described without its name passes the cross-client check; trailers can expose hostnames).
- [ ] **Step 4:** Spec: §6 `memory_save` statuses and `confirmed`; §7 A and C routing; the audit health line; known risks.
- [ ] **Step 5: Commit** both repos — "docs: personal memory guard".

### Task 7: Deploy and Level 4 (S18–S20)

**Files:**
- Modify: `test/e2e/e2elib/scenarios.py`, `test/e2e/prompts.json`, `test/e2e/e2elib/results.py` (scenario order), `test/e2e/README.md`
- Test: `test/e2e/test_scenarios.py`

**Interfaces:**
- Consumes: the runner's `Ctx`, `Invocation`, `C.expect_none`, `C.expect_one`, `C.announced` (existing).
- Produces: `SINGLE["S18"]`, `SINGLE["S19"]`, `SINGLE["S20"]`.

- [ ] **Step 1: Write failing tests** with the existing fakes: S18 passes when nothing holding the token was committed and the reply announces `"not saved"`; S19 passes when a first prompt commits nothing and a resumed "save it to general" commits exactly one memory in `general` and none in client scopes; S20 passes when a fact naming client B, given in client A's repo, commits nothing in A.
- [ ] **Step 2: Run** `/usr/bin/python3 -m unittest discover -s test/e2e` — expected: FAIL.
- [ ] **Step 3: Implement** the three scenarios and their prompts (generic personal facts with the run token). S20 needs a second client scope in staging `SCOPES` (a real, app-installed repo); that is a secret change only the owner makes. Without it, S20 is recorded as skipped and the cross-client rule rests on Task 2's unit tests.
- [ ] **Step 4: Run** the e2e unit suite — expected: PASS.
- [ ] **Step 5: Deploy** (owner OKs each): `CMC_WORKERS_PAID=1 npm run deploy:staging`; kit to the Mac (dry run first), earsvm and lume as in Plan 3.
- [ ] **Step 6: Live run**: `python3 test/e2e/run.py run --hosts H1,H3,H4 --scenarios S1,S2,S4,S5,S18,S19,S20` — expected: all PASS; then `cleanup` and `report`.
- [ ] **Step 7: Manual chat check with the owner** (claude.ai web, built-in memory on, connector on): a personal fact goes to built-in memory and nothing reaches the test repo; a candid opinion is not saved to the connector unless the owner says so. Record rows with `run.py`'s manual record command.
- [ ] **Step 8: Commit** the e2e code and grid — "test(e2e): S18–S20 personal memory guard".
