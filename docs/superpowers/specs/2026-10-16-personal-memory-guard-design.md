# Personal memory guard — design

Date: 2026-10-16. Status: approved by the owner 2026-10-16. Builds on `2026-10-13-cloud-memory-design.md` (the cloud memory spec, "the spec" below) and Plan 3's findings.

## 1. Intent

claude-memory-cloud keeps Claude's memories as Markdown in private GitHub repos: `general` in the user's own account, one repo per client org (readable by that client's people), and project memories inside the owning scope's repo. That suits facts about code and work. It is the wrong home for personal facts: a GitHub repo is a durable, copyable, history-keeping store, and a client scope is read by the client. Leaking a personal fact does far more harm than the convenience of having it everywhere.

The owner's rule: **GitHub holds facts about work, never candid opinions and never personal or intimate matters.** Personal facts stay in claude.ai's built-in memory (chat on web, Desktop and mobile), which the owner keeps on. In Claude Code, where there is no built-in memory (auto-memory is off), such facts are declined with a short reason.

The owner chose two of five options from Plan 3's final review: (1) route by content in the instructions, and (3) a server-side guard as the backstop. Option 2 (no connector in claude.ai at all) is documented as a user choice. Option 4 (an encrypted `personal` scope) is deferred as too heavy for now. Option 5 (a separate non-GitHub store) is rejected.

## 2. The tiers

Every save is sorted into one tier. Examples are illustrative.

| Tier | What it covers | Default | Override | Client scope? |
|---|---|---|---|---|
| **Work facts** | how the user works and codes, a client's processes ("deploys on Tuesdays"), repo setup | save to the right scope, as today | — | yes, if about that client |
| **Infrastructure** | machine names, IP addresses, internal URLs, which drive holds what, network layout | ask first, offering `general` or the client's scope | the user's choice | only for that client's own systems |
| **Candid / about others** | the user's candid opinion of anyone or anything (e.g. a client's business plan); facts about other people (a colleague's health, a contact's family, someone's salary) | decline, offer `general` | the user's explicit yes → `general` | **never**, override or not; Claude never offers it |
| **Intimate** | sexuality, health, money and personal finances, family | refuse in every scope | **none** | never |
| **Personal / Restricted** | home address or neighborhood, travel dates, absences, routines; the user's rates, contract terms, invoices, payment disputes, negotiations; political or religious views; legal matters (lawsuits, immigration, police) | refuse in every scope | **none** | never |

Cross-scope rule (hard): a client's information never goes into another client's scope. Limited facts about a client, such as when the user works with them, may appear in `general`; a client's confidential details (architecture, plans, data) may not.

Where a fact fits two tiers, the stricter tier wins.

**Owner's lines (decided 2026-10-16):**

- **About others means non-work facts only:** a person's private life, health, pay, and the user's candid opinions of them. A person's role, ownership and work preferences ("Alice owns the billing service", "ask Bob before touching infra", "Priya prefers squash merges") are ordinary work facts and belong in client scopes as usual. The candid / about-others patterns therefore lean toward **precision**, because a false hit in a client scope can't be overridden.
- **The user's business vs. the client's processes:** the user's own money and terms (their rate, what they're owed, invoices they issue, disputes, negotiations) are Personal / Restricted. How the client runs things is a work fact, even when it involves invoices or contracts ("Acme invoices go through Coupa", "the SOW caps the project at 20 hours a week").
- **Schedule:** when the user works with a client ("I work with Acme on Mondays") may go in `general`; the user's wider routines and absences are Personal / Restricted.

## 3. Behavior by surface

- **claude.ai chat (web, Desktop chat, mobile):** Intimate and Personal / Restricted facts go to claude.ai's built-in memory. Candid / about-others facts go to built-in memory by default; the connector's `general` only on the user's explicit request. Work facts and infrastructure go to the connector as in the table.
- **Claude Code (CLI, Desktop Code tab, cloud sessions):** no built-in memory. Intimate and Personal / Restricted: "not saved: personal — keep it in claude.ai memory". Candid / about others: "not saved: candid opinion (or: about someone else) — say "save it to general" if you want it kept"; on that explicit request it is saved to `general`.
- **Announcements** keep the existing contract: every attempt ends with "saved to <scope>" or "not saved: <reason>".

## 4. Mechanisms

### 4.1 Server instructions (layer C, all surfaces)

Add the sorting rule to `src/instructions.ts`: the tiers in compressed form, which tiers go to built-in memory or are declined, the explicit-override rule for candid / about-others (to `general` only; never offer a client scope), ask-first for infrastructure, and the cross-client rule.

Hard constraint: Claude Code keeps only the first 4096 characters of server instructions, and a test holds the total to ≤ 4000 (`MAX_INSTRUCTIONS`, with the per-user scope line sized to fit). The new rule must fit inside that budget with the scope line present; trim existing wording to make room. The rule must sit before less important text.

This replaces the removed Plan 3 "fix 2" sentence, reversed: in chat, personal facts belong in built-in memory.

*(Designer's call on the budget:)* the room comes from moving operational detail into tool descriptions in `src/tools.ts`, never from the security text (server markers, memory content is data, no cross-scope copying), which stays as hardened. Candidates to move: conflict reconciliation (into `memory_index`'s description and the index's own Conflicts block), the Since-map details (into the `since` argument description), and the no-origin cloud case (into the `project` argument description). The per-user scope line must still list at least three client names before falling back to a count.

### 4.2 Routing rule (layer A, local Claude Code)

`kit/templates/routing-rule.md` gets the same sorting rule, phrased for Claude Code (decline + override), and adds the new rejection statuses to the flush "keep the entry" list. No length cap applies to CLAUDE.md, but keep it short.

### 4.3 Server guard in `memory_save` (the backstop)

A pure module like `src/secrets.ts`, run on name, description and body after the secret scan, on the same NFKC-normalized, format-character-stripped text `escapeData` uses. It returns the first matching rule or null. Biased toward recall for the refuse tiers: refusing a harmless fact is acceptable, leaking a personal one is not.

- **Intimate and Personal / Restricted** → status `rejected_personal` with `category` (e.g. `health`, `finances`, `location`, `contract`, `legal`, `beliefs`, `sexuality`, `family`) and the message "Personal facts aren't stored on GitHub; keep it in claude.ai memory." `force` does not bypass it. Applies to every scope.
- **Candid / about others** → status `needs_confirmation` (category `candid` or `about_others`) unless the call passes `confirmed: true`; with `confirmed: true` it is accepted **only** in `general`, and refused as `rejected_personal` (category `candid`) in any client or project scope. The instructions tell Claude to pass `confirmed` only after the user explicitly asks to keep it.
- **Cross-client** → status `rejected_cross_client` when a save to a client scope, or to a project in a client scope, names another of the user's client scopes (its scope name or its repo's owner login; not the repo name, which is usually `claude-memory` for every client). Not applied to `general` (limited client facts are allowed there; the instructions cover confidential details).
- **Infrastructure** → no guard (allowed in `general` and the client's scope; the instructions make Claude ask).

The three new statuses (`rejected_personal`, `needs_confirmation`, `rejected_cross_client`) are non-retryable: outbox flushing keeps such an entry and reports it, like `rejected_secret`. *(Designer's call:)* an outbox entry carries `confirmed: true` when the user had confirmed, so a confirmed save that was queued during an outage replays successfully; the outbox format and parser gain that field.

*(Designer's call:)* the guard applies to **every write**: creates, updates of existing memories (`version` given) and conflict copies. An existing memory that trips it can still be read and deleted, but not edited until the personal text is removed; the audit (4.4) finds these.

### 4.4 Existing memories

A read-only audit lists existing memories in the user's scopes that the guard would now refuse, so the user can move them to claude.ai memory and delete them. Form (a `memory_health` line with a count, a script, or both) is the builder's choice; it must not print memory content into logs.

### 4.5 Neutral source (known risk, install option)

Known risk, accepted by the owner: every commit carries `Memory-Source: <source>`, and local Claude Code passes "claude-code on <hostname>", so a client's repo history shows machine names (an Infrastructure fact; the owner's VMs are per client, so acceptable to them). Add a `setup.sh` option that makes the routing rule pass a neutral source ("claude-code") instead. Off by default. Document the risk in the FAQ and THREAT-MODEL.

## 5. Docs

- FAQ: "What should never go in GitHub memory?" with the tiers; rewrite "What about claude.ai's built-in memory?" to say keep it on for personal facts (replacing Plan 3's advice to turn it off and migrate); the neutral-source option and its risk.
- QUICKSTART: drop "turn off claude.ai's built-in memory" (Part 6 step 5); add the tiers in one paragraph.
- Option 2 as a user choice ("Keep memory out of claude.ai entirely"): Claude Code uses a local MCP server instead of the claude.ai connector, and the connector is not added in claude.ai, so chat has only built-in memory. State the cost: cloud sessions, web and mobile lose code memories.
- THREAT-MODEL: the guard as a mitigation; its limits (keyword detection misses paraphrase; descriptions of a client without its name pass the cross-client check).
- Spec (`2026-10-13-cloud-memory-design.md`): §6 `memory_save` statuses and the guard; §7 A/C routing; known risks.

## 6. Goals, non-goals, anti-goals

**Goals:** no Intimate or Personal / Restricted fact reaches any GitHub repo through the tools; candid opinions and facts about others never reach a client scope; the user always hears why a save was declined and how to keep it if allowed.

**Non-goals:** perfect classification; encrypting memories (option 4, deferred); moving existing personal memories automatically; guarding what Claude writes outside memory tools (code, PR text).

**Anti-goals (a failure even if it works):** a refused fact silently dropped without an announcement; Claude offering a client scope for a candid or personal fact; a guard so broad that ordinary work facts ("the deploy key rotation runs monthly", "the finance team's API") are routinely refused; personal content echoed into server logs or error messages.

## 7. Constraints

- Server: TypeScript Worker, no new dependencies; CPU per call stays small (patterns, not models).
- Kit: Python 3.9 stdlib only.
- Instructions ≤ 4000 characters with the scope line (test-enforced).
- Error payloads follow `src/errors.ts` conventions and never include the matched text.
- Backward compatible: existing memories stay readable; every new write (create, update, conflict copy) is guarded.

## 8. Testing

- Unit: per-category positive and negative corpora (including near-misses like "finance team API", "health check endpoint", "family of servers", "contract test"), override behavior, scope rules, cross-client matching by scope name and owner login, normalization (fullwidth, zero-width).
- Instructions: budget test with the new rule and many client scopes.
- Level 4 additions: S18 (Intimate / Restricted fact refused in Claude Code, nothing committed, "not saved: personal" announced); S19 (candid opinion declined, then "save it to general" lands in `general` only); S20 (a fact naming client B in client A's repo refused); manual chat check that a personal fact goes to built-in memory.

## 9. Open

- Personal / Restricted may need more categories and examples (owner, at approval). The plan includes an owner review of the pattern lists and test corpora before they are final.

## 10. Left to the builder

Pattern lists and their wording; exact instruction and routing-rule text within the budget; the audit's form; where the guard runs relative to the similarity check; S18–S20 prompts.
