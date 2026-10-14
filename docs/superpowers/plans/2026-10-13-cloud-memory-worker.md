# Cloud Memory Worker Implementation Plan (Plan 1 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy to staging the Cloudflare Worker that serves memory tools over remote MCP. Memories are stored as markdown in GitHub repos, and authentication goes through a GitHub App with tokens that act on behalf of the user.

**Architecture:**
- One TypeScript Worker. Its parts:
  - `@cloudflare/workers-oauth-provider`: the OAuth server that claude.ai talks to.
  - A GitHub App sign-in flow, with PKCE.
  - A stateless MCP endpoint built with `createMcpHandler` from `agents`.
- The memory logic is pure functions over a `Store` interface:
  - a GitHub Git Data API implementation for production
  - an in-memory fake for tests
- Every write commits the memory file and the rebuilt `MEMORY.md` together, using a compare-and-swap ref update.

**Tech Stack:**
- TypeScript 6.0.3
- Cloudflare Workers (wrangler 4.150.0)
- @cloudflare/workers-oauth-provider 1.2.3
- agents 0.28.1 + @modelcontextprotocol/server 2.3.1
- zod 4.6.7
- yaml 2.9.1
- vitest 5.0.4 + @cloudflare/vitest-plugin 1.4.1

**Spec:** `docs/superpowers/specs/2026-10-13-cloud-memory-design.md` (in `claude-memory-mcp`). Read §3–§8 before starting.

**Plan series:**
- **Plan 1 (this):** the Worker
- **Plan 2:** local kit (setup.sh, hooks, CLAUDE.md rule)
- **Plan 3:** e2e test runner + surface matrix
- **Plan 4:** migration + production rollout + client onboarding

## Global Constraints

- **Code location:** a new repo at `~/src/claude-memory-cloud`. All paths below are relative to it unless prefixed with `claude-memory-mcp/`.
- **Pinned versions** (`package.json`): `@cloudflare/workers-oauth-provider@1.2.3`, `agents@0.28.1`, `@modelcontextprotocol/server@2.3.1`, `@modelcontextprotocol/sdk@1.32.1`, `@modelcontextprotocol/client@2.3.1`, `zod@4.6.7`, `yaml@2.9.1`. Dev: `wrangler@4.150.0`, `vitest@5.0.4`, `@cloudflare/vitest-plugin@1.4.1`, `typescript@6.0.3`, `@types/node@26.6.5`.
  - `agents@0.28.1` lists all three MCP packages as exact peers.
  - Do **not** use `@cloudflare/vitest-pool-workers`: it is deprecated and incompatible with vitest 5.
  - Do **not** use `McpAgent`: it is deprecated.
- **Compatibility:** `compatibility_date: "2026-01-28"`, `compatibility_flags: ["nodejs_compat", "global_fetch_strictly_public"]`.
- **Memory names:** `^[a-z0-9][a-z0-9-]{0,63}$`. Types: `user | feedback | project | reference`.
- **Similarity threshold:** 0.5 (Jaccard), max 3 results.
- **Write retries:** max 3 attempts on a ref race.
- **Tool result statuses** (exact strings): `created`, `updated`, `conflict`, `exists`, `similar_found`, `rejected_secret`, `invalid`, `not_found`, `deleted`.
- **Error codes** (exact strings): `invalid`, `unknown_scope`, `no_memory_repo_for_owner`, `unsupported_remote`, `not_reachable`, `reauth_required`, `unavailable`.
- **Redirect allowlist:**
  - `https://claude.ai/api/mcp/auth_callback`
  - `https://claude.com/api/mcp/auth_callback`
  - `http://localhost:<any>/…`
  - `http://127.0.0.1:<any>/…`
- **The Worker never logs** memory content or tokens.
- **Commit trailers:** `Memory-Source: <source>`, `Memory-Scope: <scope | project:owner/repo>`.

## Deviations from the spec (decided while planning; update the spec in Task 15)

1. **`Memory-Source` comes from an optional `source` tool argument.**
   - Connectors reach every surface through claude.ai, so the OAuth client is the same everywhere.
   - In the legacy stateless MCP mode, `clientInfo` is only present on the `initialize` request.
   - So the server cannot tell surfaces apart. Claude is instructed to pass `source` (e.g. `claude-code on earsvm`, `claude.ai chat`). If it doesn't, the value is `unknown`.
2. **Scope reachability is reported as `not_reachable` with a combined action** when the repo isn't in the user's installation list.
   - A GitHub App user token cannot tell "repo missing", "app not on this repo", and "no user access" apart: all three return 404.
   - The action lists all three fixes, most likely first.
   - "App not installed on this owner at all" *can* be detected, and keeps its own action text.

## File Structure

```
claude-memory-cloud/
├── package.json
├── tsconfig.json
├── wrangler.jsonc            # staging (top level) + env.production
├── vitest.config.ts
├── .dev.vars.example         # placeholder secrets for local dev/tests
├── .gitignore
├── README.md
├── src/
│   ├── index.ts              # entry: host pin, /health, lazy OAuthProvider, MCP api handler
│   ├── env.ts                # Env and Props types
│   ├── remote.ts             # pure: git remote URL → "owner/repo"
│   ├── memory.ts             # pure: frontmatter, names, index, similarity, conflict names
│   ├── secrets.ts            # pure: secret scanner
│   ├── scopes.ts             # pure: SCOPES config parse + target resolution
│   ├── errors.ts             # OpError + codes
│   ├── github.ts             # GitHub REST client + GitHubError mapping
│   ├── store.ts              # Store interface, GitHubStore, blob cache
│   ├── operations.ts         # save/delete/read/index/search over Store
│   ├── health.ts             # health checks with actions; scope reachability
│   ├── instructions.ts       # MCP server instructions text
│   ├── tools.ts              # createServer(): MCP tool/resource registration
│   ├── github-auth.ts        # /authorize, /callback, refresh, redirect allowlist
│   └── consent.ts            # consent page HTML
└── test/
    ├── setup.ts              # fetch mocking helper
    ├── fake-store.ts         # in-memory Store
    ├── smoke.test.ts
    ├── remote.test.ts
    ├── memory.test.ts
    ├── secrets.test.ts
    ├── scopes.test.ts
    ├── github.test.ts
    ├── store.test.ts
    ├── operations.test.ts
    ├── health.test.ts
    ├── tools.test.ts
    ├── auth.test.ts
    ├── wiring.test.ts
    └── integration/
        └── github-live.test.ts   # runs only with GITHUB_TEST_TOKEN
```

---

### Task 0: One-time setup (user, guided — no code)

The user does these steps; the agent walks them through and records the outputs. The user-facing version of these steps is `docs/cloud-memory/QUICKSTART.md` in `claude-memory-mcp` (Parts 2–4 and the Appendix); keep the two consistent, and fix the Quickstart wherever a step turns out to be wrong. **No later task can deploy or run integration tests without them.**

- [ ] **Step 1: Cloudflare account**
  1. Sign up at https://dash.cloudflare.com/sign-up and verify the email.
  2. Turn on 2FA: My Profile → Authentication.
  3. Workers & Pages → choose a `*.workers.dev` subdomain. Record it as `<sub>`.
  4. In a terminal: `npx wrangler@4.150.0 login`, which opens a browser.
  5. Verify: `npx wrangler@4.150.0 whoami` prints the account.

- [ ] **Step 2: GitHub repos and test org**
  1. Create the private repo `dav/claude-memory-test`. Leave it empty.
  2. Create the private repo `dav/claude-memory`. Leave it empty; it's used in Plan 4.
  3. Create a free org `dav-test-client` (github.com → + → New organization → Free).
  4. In that org, create the private repos `claude-memory` (empty) and `sample-app` (with a README).

- [ ] **Step 3: GitHub App** at github.com → Settings → Developer settings → GitHub Apps → New GitHub App
  - **Name:** `dav-claude-memory`. If the name is taken, choose another and record the slug.
  - **Homepage URL:** `https://claude-memory-staging.<sub>.workers.dev`
  - **Callback URL:** `https://claude-memory-staging.<sub>.workers.dev/callback`. Production gets added in Plan 4; a GitHub App allows up to 10 callback URLs.
  - **Expire user authorization tokens:** ✅ (the default)
  - **Request user authorization (OAuth) during installation:** ☐
  - **Enable Device Flow:** ☐
  - **Webhook → Active:** ☐ (unchecked)
  - **Repository permissions:** Contents → **Read and write**. Metadata → Read (mandatory). Everything else: No access.
  - **Account permissions:** none.
  - **Where can this GitHub App be installed:** Any account.
  - Create it, then on the app page: record the **Client ID** and **slug**, then click **Generate a new client secret** and record it.
  - **Do not** generate a private key; it isn't needed.

- [ ] **Step 4: Install the app**
  1. Go to `https://github.com/apps/<slug>/installations/new`.
  2. Install on **dav** → Only select repositories → `claude-memory-test`, `claude-memory`.
  3. Install on **dav-test-client** → Only select repositories → `claude-memory`.

- [ ] **Step 5: Record values** in `~/src/claude-memory-cloud/.dev.vars`, created in Task 1 and gitignored. The agent asks the user to paste the secret, never echoes it, and never commits it:

```
GITHUB_CLIENT_ID=<client id>
GITHUB_CLIENT_SECRET=<client secret>
COOKIE_ENCRYPTION_KEY=<output of: openssl rand -hex 32>
```

---

### Task 1: Scaffold the repo and confirm the test harness

**Files:**
- Create: `package.json`, `tsconfig.json`, `wrangler.jsonc`, `vitest.config.ts`, `.gitignore`, `.dev.vars.example`, `README.md`, `src/env.ts`, `src/index.ts` (stub), `test/setup.ts`, `test/smoke.test.ts`

**Interfaces:**
- Produces: `Env` and `Props` types (`src/env.ts`), and the `mockFetch(routes)` test helper (`test/setup.ts`), used by every later test that touches the network.

- [ ] **Step 1: Create the repo and install pinned dependencies**

```bash
mkdir -p ~/src/claude-memory-cloud && cd ~/src/claude-memory-cloud && git init -b main
npm init -y
npm i -E @cloudflare/workers-oauth-provider@1.2.3 agents@0.28.1 @modelcontextprotocol/server@2.3.1 @modelcontextprotocol/sdk@1.32.1 @modelcontextprotocol/client@2.3.1 zod@4.6.7 yaml@2.9.1
npm i -D -E wrangler@4.150.0 vitest@5.0.4 @cloudflare/vitest-plugin@1.4.1 typescript@6.0.3 @types/node@26.6.5
```

Then edit `package.json` so that it has `"type": "module"`, `"private": true`, and these scripts:

```json
"scripts": {
  "dev": "wrangler dev",
  "test": "vitest run",
  "test:watch": "vitest",
  "typecheck": "tsc --noEmit",
  "types": "wrangler types",
  "deploy:staging": "wrangler deploy",
  "deploy:production": "wrangler deploy --env production"
}
```

- [ ] **Step 2: Write `wrangler.jsonc`**

```jsonc
{
  "$schema": "node_modules/wrangler/config-schema.json",
  "name": "claude-memory-staging",
  "main": "src/index.ts",
  "compatibility_date": "2026-01-28",
  "compatibility_flags": ["nodejs_compat", "global_fetch_strictly_public"],
  "kv_namespaces": [
    { "binding": "OAUTH_KV", "id": "REPLACE_IN_TASK_14" },
    { "binding": "CACHE_KV", "id": "REPLACE_IN_TASK_14" }
  ],
  "vars": {
    "PUBLIC_URL": "https://claude-memory-staging.REPLACE_SUB.workers.dev",
    "SCOPES": "{\"general\":\"dav/claude-memory-test\",\"dav-test-client\":\"dav-test-client/claude-memory\"}",
    "GITHUB_APP_SLUG": "dav-claude-memory",
    "WORKER_VERSION": "0.1.0",
    "MIN_HOOK_VERSION": "0.1.0"
  },
  "env": {
    "production": {
      "name": "claude-memory",
      "kv_namespaces": [
        { "binding": "OAUTH_KV", "id": "REPLACE_IN_PLAN_4" },
        { "binding": "CACHE_KV", "id": "REPLACE_IN_PLAN_4" }
      ],
      "vars": {
        "PUBLIC_URL": "https://claude-memory.REPLACE_SUB.workers.dev",
        "SCOPES": "{\"general\":\"dav/claude-memory\"}",
        "GITHUB_APP_SLUG": "dav-claude-memory",
        "WORKER_VERSION": "0.1.0",
        "MIN_HOOK_VERSION": "0.1.0"
      }
    }
  }
}
```

- [ ] **Step 3: Write `src/env.ts`**

```ts
import type { OAuthHelpers } from "@cloudflare/workers-oauth-provider";

export interface Env {
  OAUTH_KV: KVNamespace;
  CACHE_KV: KVNamespace;
  OAUTH_PROVIDER: OAuthHelpers;
  GITHUB_CLIENT_ID: string;
  GITHUB_CLIENT_SECRET: string;
  COOKIE_ENCRYPTION_KEY: string;
  PUBLIC_URL: string;
  SCOPES: string;
  GITHUB_APP_SLUG: string;
  WORKER_VERSION: string;
  MIN_HOOK_VERSION: string;
}

/** Encrypted per-grant props set at sign-in (see github-auth.ts). */
export interface Props {
  login: string;
  githubToken: string;
  githubRefreshToken: string;
  /** epoch ms */
  githubTokenExpiresAt: number;
}
```

- [ ] **Step 4: Write `tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "es2022",
    "module": "es2022",
    "moduleResolution": "bundler",
    "lib": ["es2023"],
    "types": ["@cloudflare/workers-types/experimental", "@cloudflare/vitest-plugin/types", "node"],
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "skipLibCheck": true,
    "noEmit": true
  },
  "include": ["src", "test", "vitest.config.ts"]
}
```

Then install the workers types: `npm i -D -E @cloudflare/workers-types@5.20261014.1`.

- [ ] **Step 5: Write `vitest.config.ts`, `test/setup.ts`, `.dev.vars.example`, `.gitignore`, and the stub `src/index.ts`**

`vitest.config.ts`:
```ts
import { cloudflareTest } from "@cloudflare/vitest-plugin";
import { defineProject } from "vitest/config";

export default defineProject({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler.jsonc" },
      miniflare: {
        bindings: {
          PUBLIC_URL: "https://memory.test",
          SCOPES: JSON.stringify({ general: "dav/claude-memory-test", acme: "acme-org/claude-memory" }),
          GITHUB_CLIENT_ID: "Iv1.testclient",
          GITHUB_CLIENT_SECRET: "test-secret",
          COOKIE_ENCRYPTION_KEY: "0".repeat(64),
          GITHUB_TEST_TOKEN: process.env.GITHUB_TEST_TOKEN ?? "",
          GITHUB_TEST_REPO: process.env.GITHUB_TEST_REPO ?? "",
        },
      },
    }),
  ],
  test: { setupFiles: ["test/setup.ts"] },
});
```

`test/setup.ts`:
```ts
import { afterEach, vi } from "vitest";

export type Route = {
  method?: string;
  /** Matched against the full URL with startsWith, or a RegExp. */
  url: string | RegExp;
  respond: (req: Request) => Response | Promise<Response>;
};

/** Intercepts global fetch (including from Worker code in the same isolate). Unmatched requests throw. */
export function mockFetch(routes: Route[]) {
  const calls: Request[] = [];
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const req = new Request(input as RequestInfo, init);
    calls.push(req.clone());
    const route = routes.find(
      (r) =>
        (!r.method || r.method === req.method) &&
        (typeof r.url === "string" ? req.url.startsWith(r.url) : r.url.test(req.url)),
    );
    if (!route) throw new Error(`unmocked fetch: ${req.method} ${req.url}`);
    return route.respond(req);
  });
  return { calls, spy };
}

export const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });

afterEach(() => vi.restoreAllMocks());
```

`.dev.vars.example`:
```
GITHUB_CLIENT_ID=Iv1.xxxxxxxx
GITHUB_CLIENT_SECRET=xxxxxxxx
COOKIE_ENCRYPTION_KEY=generate-with-openssl-rand-hex-32
```

`.gitignore`:
```
node_modules/
.dev.vars
.wrangler/
dist/
```

`src/index.ts` (stub; replaced in Task 13):
```ts
import type { Env } from "./env";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      const probe = url.searchParams.get("probe");
      if (probe) {
        const r = await fetch(probe);
        return Response.json({ probed: r.status });
      }
      return Response.json({ ok: true, version: env.WORKER_VERSION });
    }
    return new Response("not found", { status: 404 });
  },
};
```

- [ ] **Step 6: Write the smoke test.** It confirms the Worker runs and that `mockFetch` intercepts fetches made *by Worker code*. If the second test fails, switch `test/setup.ts` to MSW (`npm i -D -E msw @msw/cloudflare`, then `setupNetwork` from `@msw/cloudflare`) and keep the same `mockFetch(routes)` signature.

`test/smoke.test.ts`:
```ts
import { exports } from "cloudflare:workers";
import { expect, it } from "vitest";
import { json, mockFetch } from "./setup";

it("serves /health", async () => {
  const res = await exports.default.fetch("https://memory.test/health");
  expect(res.status).toBe(200);
  expect(await res.json()).toMatchObject({ ok: true });
});

it("mockFetch intercepts outbound fetch from worker code", async () => {
  mockFetch([{ url: "https://api.github.com/zen", respond: () => json({}, 418) }]);
  const res = await exports.default.fetch("https://memory.test/health?probe=https://api.github.com/zen");
  expect(await res.json()).toEqual({ probed: 418 });
});
```

- [ ] **Step 7: Run the tests and typecheck**

Run: `cp .dev.vars.example .dev.vars` (skip this if Task 0 already created `.dev.vars`), then `npx vitest run test/smoke.test.ts && npx tsc --noEmit`
Expected: 2 passed, and no type errors.

- [ ] **Step 8: Move the docs drafts into this repo**

```bash
mkdir -p docs
cp ~/src/claude-memory-mcp/docs/cloud-memory/QUICKSTART.md ~/src/claude-memory-mcp/docs/cloud-memory/FAQ.md docs/
```
In both copies, delete the "This file moves to the `claude-memory-cloud` repo…" sentence from the Draft note. In `claude-memory-mcp`, replace each draft with a single line pointing to the new location, and commit that there.

- [ ] **Step 9: Write `README.md`** (short: what the repo is, a link to `docs/QUICKSTART.md` and `docs/FAQ.md`, `npm test`, deploy commands, and a pointer to the spec) **and commit**

```bash
git add -A && git commit -m "chore: scaffold claude-memory-cloud worker"
```

---

### Task 2: `remote.ts` — normalize git remotes

**Files:**
- Create: `src/remote.ts`
- Test: `test/remote.test.ts`

**Interfaces:**
- Produces: `normalizeRemote(input: string): { owner: string; repo: string } | null`. Returns `null` for non-GitHub or unparseable input. `owner` and `repo` are lowercased; `.git` and trailing slashes are stripped. Bare `owner/repo` is accepted.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest";
import { normalizeRemote } from "../src/remote";

describe("normalizeRemote", () => {
  it.each([
    ["git@github.com:Acme-Org/Billing.git", "acme-org", "billing"],
    ["https://github.com/acme-org/billing", "acme-org", "billing"],
    ["https://github.com/acme-org/billing.git/", "acme-org", "billing"],
    ["ssh://git@github.com/acme-org/billing.git", "acme-org", "billing"],
    ["https://user@github.com/acme-org/billing.git", "acme-org", "billing"],
    ["acme-org/billing", "acme-org", "billing"],
    ["  acme-org/billing  ", "acme-org", "billing"],
  ])("%s", (input, owner, repo) => {
    expect(normalizeRemote(input)).toEqual({ owner, repo });
  });

  it.each(["git@gitlab.com:a/b.git", "https://bitbucket.org/a/b", "not a remote", "", "a/b/c"])(
    "rejects %s",
    (input) => expect(normalizeRemote(input)).toBeNull(),
  );
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run test/remote.test.ts`
Expected: FAIL, "Failed to resolve import ../src/remote" (or similar)

- [ ] **Step 3: Implement**

```ts
const PART = "[A-Za-z0-9_.-]+";
const PATTERNS = [
  new RegExp(`^git@github\\.com:(${PART})/(${PART})$`),
  new RegExp(`^(?:https?|ssh|git)://(?:[^@/]+@)?github\\.com/(${PART})/(${PART})$`),
  new RegExp(`^(${PART})/(${PART})$`),
];

export function normalizeRemote(input: string): { owner: string; repo: string } | null {
  const s = input.trim().replace(/\/+$/, "").replace(/\.git$/, "");
  for (const re of PATTERNS) {
    const m = re.exec(s);
    if (m && m[1] && m[2]) return { owner: m[1].toLowerCase(), repo: m[2].toLowerCase() };
  }
  return null;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run test/remote.test.ts`
Expected: PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add src/remote.ts test/remote.test.ts && git commit -m "feat: normalize git remote URLs"
```

---

### Task 3: `memory.ts` — format, names, index, similarity

**Files:**
- Create: `src/memory.ts`
- Test: `test/memory.test.ts`

**Interfaces:**
- Produces:
  - `type MemoryType = "user" | "feedback" | "project" | "reference"`
  - `interface Memory { name: string; description: string; type: MemoryType; body: string }`
  - `class MemoryFormatError extends Error`
  - `isValidName(name: string): boolean`
  - `parseMemory(text: string): Memory`. Throws `MemoryFormatError`. Accepts `metadata.type` or a legacy top-level `type`; a missing type becomes `reference`; extra keys are ignored.
  - `serializeMemory(m: Memory): string`
  - `memoryPath(name: string): string` returns `memories/<name>.md`
  - `conflictPath(name: string, now: Date): string` returns `memories/<name>.conflict-YYYYMMDDTHHMMSSZ.md`
  - `parseMemoryPath(path: string): { name: string; conflict: boolean } | null`. Takes a path relative to the set root.
  - `interface IndexEntry { name: string; description: string }`
  - `buildIndex(label: string, entries: IndexEntry[], conflictPaths: string[]): string`
  - `findSimilar(c: IndexEntry, existing: IndexEntry[], threshold?: number, limit?: number): IndexEntry[]`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest";
import {
  buildIndex, conflictPath, findSimilar, isValidName, MemoryFormatError,
  memoryPath, parseMemory, parseMemoryPath, serializeMemory, type Memory,
} from "../src/memory";

const sample: Memory = {
  name: "debugging-discipline",
  description: "Measure first; question failed theories",
  type: "feedback",
  body: "Measure before theorizing.\n**Why:** wasted hours.\n",
};

describe("names", () => {
  it.each(["a", "debugging-discipline", "x1-2", "a".repeat(64)])("valid %s", (n) => expect(isValidName(n)).toBe(true));
  it.each(["", "-a", "A", "a_b", "a.b", "a".repeat(65), "a/b"])("invalid %s", (n) => expect(isValidName(n)).toBe(false));
});

describe("parse/serialize", () => {
  it("round-trips", () => {
    expect(parseMemory(serializeMemory(sample))).toEqual(sample);
  });

  it("serializes in the auto-memory layout", () => {
    expect(serializeMemory(sample)).toBe(
      "---\nname: debugging-discipline\ndescription: Measure first; question failed theories\nmetadata:\n  type: feedback\n---\n\nMeasure before theorizing.\n**Why:** wasted hours.\n",
    );
  });

  it("accepts legacy top-level type and ignores extra keys", () => {
    const text = "---\nname: old-one\ndescription: legacy\ntype: project\noriginSessionId: abc\n---\n\nbody\n";
    expect(parseMemory(text)).toEqual({ name: "old-one", description: "legacy", type: "project", body: "body\n" });
  });

  it("defaults missing type to reference", () => {
    expect(parseMemory("---\nname: x\ndescription: d\n---\nb").type).toBe("reference");
  });

  it.each([
    ["no frontmatter", "just text"],
    ["missing name", "---\ndescription: d\n---\nb"],
    ["bad name", "---\nname: Bad Name\ndescription: d\n---\nb"],
    ["missing description", "---\nname: x\n---\nb"],
    ["bad type", "---\nname: x\ndescription: d\nmetadata:\n  type: nope\n---\nb"],
  ])("rejects %s", (_label, text) => {
    expect(() => parseMemory(text)).toThrow(MemoryFormatError);
  });
});

describe("paths", () => {
  it("memoryPath", () => expect(memoryPath("abc")).toBe("memories/abc.md"));
  it("conflictPath", () =>
    expect(conflictPath("abc", new Date("2026-10-13T18:04:05.123Z"))).toBe("memories/abc.conflict-20261013T180405Z.md"));
  it("parseMemoryPath", () => {
    expect(parseMemoryPath("memories/abc.md")).toEqual({ name: "abc", conflict: false });
    expect(parseMemoryPath("memories/abc.conflict-20261013T180405Z.md")).toEqual({ name: "abc", conflict: true });
    expect(parseMemoryPath("MEMORY.md")).toBeNull();
    expect(parseMemoryPath("memories/sub/abc.md")).toBeNull();
    expect(parseMemoryPath("memories/Bad.md")).toBeNull();
  });
});

describe("buildIndex", () => {
  it("lists entries sorted by name, without a conflicts section when none", () => {
    const out = buildIndex("general", [
      { name: "zeta", description: "last" },
      { name: "alpha", description: "first" },
    ], []);
    expect(out).toBe(
      "# Memory index — general\n\n- [alpha](memories/alpha.md) — first\n- [zeta](memories/zeta.md) — last\n",
    );
  });

  it("adds a conflicts section", () => {
    const out = buildIndex("project billing", [{ name: "a", description: "d" }], ["memories/a.conflict-20261013T180405Z.md"]);
    expect(out).toContain("## Conflicts\n- memories/a.conflict-20261013T180405Z.md — reconcile with a.md\n");
  });

  it("handles empty sets", () => {
    expect(buildIndex("general", [], [])).toBe("# Memory index — general\n\n(no memories yet)\n");
  });
});

describe("findSimilar", () => {
  const existing = [
    { name: "debugging-discipline", description: "Measure first; question failed theories" },
    { name: "prefers-concise-answers", description: "User wants short answers" },
  ];
  it("finds near-duplicates", () => {
    const r = findSimilar({ name: "debugging-rules", description: "measure first, question failed theories" }, existing);
    expect(r.map((e) => e.name)).toEqual(["debugging-discipline"]);
  });
  it("ignores unrelated", () => {
    expect(findSimilar({ name: "deploy-tuesdays", description: "Acme deploys on Tuesdays" }, existing)).toEqual([]);
  });
  it("excludes an identical name (that is 'exists', not 'similar')", () => {
    expect(findSimilar({ name: "debugging-discipline", description: "x" }, existing)).toEqual([]);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run test/memory.test.ts`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement**

```ts
import { parse as parseYaml, stringify as stringifyYaml } from "yaml";

export type MemoryType = "user" | "feedback" | "project" | "reference";
const TYPES: readonly MemoryType[] = ["user", "feedback", "project", "reference"];

export interface Memory { name: string; description: string; type: MemoryType; body: string }
export interface IndexEntry { name: string; description: string }

export class MemoryFormatError extends Error {}

const NAME_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;
export const isValidName = (name: string) => NAME_RE.test(name);

export function parseMemory(text: string): Memory {
  const m = /^---\n([\s\S]*?)\n---\n?([\s\S]*)$/.exec(text.replace(/\r\n/g, "\n"));
  if (!m) throw new MemoryFormatError("missing frontmatter");
  let fm: Record<string, unknown>;
  try {
    fm = (parseYaml(m[1] ?? "") ?? {}) as Record<string, unknown>;
  } catch (e) {
    throw new MemoryFormatError(`invalid frontmatter: ${(e as Error).message}`);
  }
  const name = fm.name;
  const description = fm.description;
  if (typeof name !== "string" || !isValidName(name)) throw new MemoryFormatError("invalid or missing name");
  if (typeof description !== "string" || !description.trim()) throw new MemoryFormatError("missing description");
  const meta = fm.metadata as Record<string, unknown> | undefined;
  const rawType = meta?.type ?? fm.type ?? "reference";
  if (typeof rawType !== "string" || !TYPES.includes(rawType as MemoryType)) {
    throw new MemoryFormatError(`invalid type: ${String(rawType)}`);
  }
  return { name, description, type: rawType as MemoryType, body: (m[2] ?? "").replace(/^\n/, "") };
}

export function serializeMemory(mem: Memory): string {
  const fm = stringifyYaml(
    { name: mem.name, description: mem.description, metadata: { type: mem.type } },
    { lineWidth: 0 },
  );
  const body = mem.body.endsWith("\n") ? mem.body : `${mem.body}\n`;
  return `---\n${fm}---\n\n${body}`;
}

export const memoryPath = (name: string) => `memories/${name}.md`;

export function conflictPath(name: string, now: Date): string {
  const ts = now.toISOString().replace(/\.\d{3}Z$/, "Z").replace(/[-:]/g, "");
  return `memories/${name}.conflict-${ts}.md`;
}

const PATH_RE = /^memories\/([a-z0-9][a-z0-9-]{0,63})(\.conflict-\d{8}T\d{6}Z)?\.md$/;
export function parseMemoryPath(path: string): { name: string; conflict: boolean } | null {
  const m = PATH_RE.exec(path);
  return m && m[1] ? { name: m[1], conflict: Boolean(m[2]) } : null;
}

export function buildIndex(label: string, entries: IndexEntry[], conflictPaths: string[]): string {
  const lines = [`# Memory index — ${label}`, ""];
  const sorted = [...entries].sort((a, b) => a.name.localeCompare(b.name));
  if (sorted.length === 0) lines.push("(no memories yet)");
  for (const e of sorted) lines.push(`- [${e.name}](${memoryPath(e.name)}) — ${e.description}`);
  if (conflictPaths.length > 0) {
    lines.push("", "## Conflicts");
    for (const p of [...conflictPaths].sort()) {
      const parsed = parseMemoryPath(p);
      lines.push(`- ${p} — reconcile with ${parsed?.name ?? "?"}.md`);
    }
  }
  return `${lines.join("\n")}\n`;
}

const STOP = new Set(["the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "be", "with", "we", "i"]);
function tokens(e: IndexEntry): Set<string> {
  const words = `${e.name.replace(/-/g, " ")} ${e.description}`.toLowerCase().split(/[^a-z0-9]+/);
  return new Set(words.filter((w) => w.length > 1 && !STOP.has(w)));
}

export function findSimilar(c: IndexEntry, existing: IndexEntry[], threshold = 0.5, limit = 3): IndexEntry[] {
  const ct = tokens(c);
  return existing
    .filter((e) => e.name !== c.name)
    .map((e) => {
      const et = tokens(e);
      const inter = [...ct].filter((t) => et.has(t)).length;
      const union = new Set([...ct, ...et]).size;
      return { e, score: union === 0 ? 0 : inter / union };
    })
    .filter((x) => x.score >= threshold)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map((x) => x.e);
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run test/memory.test.ts`
Expected: PASS. If the "near-duplicates" case scores just under 0.5, print the score in the test, adjust the **test fixture wording** (not the threshold, which is fixed by the spec), and note the score in the commit message.

- [ ] **Step 5: Commit**

```bash
git add src/memory.ts test/memory.test.ts && git commit -m "feat: memory format, index builder, similarity"
```

---

### Task 4: `secrets.ts` — secret scanner

**Files:**
- Create: `src/secrets.ts`
- Test: `test/secrets.test.ts`

**Interfaces:**
- Produces: `scanForSecrets(text: string): string | null`. It returns the **rule name** of the first match, or `null`. It never returns the matched text.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest";
import { scanForSecrets } from "../src/secrets";

const POSITIVE: [string, string][] = [
  ["github-token", "token is ghp_" + "a".repeat(36)],
  ["github-token", "ghu_" + "B".repeat(36)],
  ["github-pat", "github_pat_" + "1".repeat(22) + "_" + "x".repeat(59)],
  ["aws-access-key", "AKIA" + "ABCDEFGHIJKLMNOP"],
  ["private-key", "-----BEGIN OPENSSH PRIVATE KEY-----\nabc"],
  ["slack-token", "xoxb-1234567890-abcdefghij"],
  ["anthropic-key", "sk-ant-api03-" + "z".repeat(40)],
  ["openai-key", "sk-" + "Q".repeat(40)],
  ["google-api-key", "AIza" + "S".repeat(35)],
  ["jwt", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJlLXZhbHVlLWhlcmU"],
  ["generic-assignment", "password = hunter2hunter2hunter2"],
  ["generic-assignment", "API_TOKEN: 'abcdEFGH1234abcdEFGH'"],
];

const NEGATIVE = [
  "Use the GitHub token from the connector, never paste it",
  "The password policy requires 12 characters",
  "sk-learn is a python library",
  "AKIA prefix identifies AWS keys",
  "token: <redacted>",
  "secret = short",
  "We store JWTs in cookies",
  "See https://github.com/acme-org/billing",
];

describe("scanForSecrets", () => {
  it.each(POSITIVE)("detects %s", (rule, text) => expect(scanForSecrets(text)).toBe(rule));
  it.each(NEGATIVE)("allows: %s", (text) => expect(scanForSecrets(text)).toBeNull());
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run test/secrets.test.ts`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement**

```ts
const RULES: [string, RegExp][] = [
  ["private-key", /-----BEGIN [A-Z ]*PRIVATE KEY-----/],
  ["github-pat", /\bgithub_pat_[A-Za-z0-9_]{50,}\b/],
  ["github-token", /\bgh[pousr]_[A-Za-z0-9]{36,}\b/],
  ["aws-access-key", /\b(?:AKIA|ASIA)[A-Z0-9]{16}\b/],
  ["slack-token", /\bxox[abprs]-[A-Za-z0-9-]{10,}\b/],
  ["anthropic-key", /\bsk-ant-[A-Za-z0-9_-]{20,}/],
  ["openai-key", /\bsk-(?:proj-)?[A-Za-z0-9]{32,}\b/],
  ["google-api-key", /\bAIza[0-9A-Za-z_-]{35}\b/],
  ["jwt", /\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{16,}\b/],
  [
    "generic-assignment",
    /\b[A-Za-z_]*(?:password|passwd|secret|token|api[_-]?key)[A-Za-z_]*\s*[:=]\s*['"]?(?![<\[])[^\s'"]{16,}/i,
  ],
];

export function scanForSecrets(text: string): string | null {
  for (const [rule, re] of RULES) if (re.test(text)) return rule;
  return null;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run test/secrets.test.ts`
Expected: PASS (20 tests). If a negative case trips a rule, tighten that rule's regex. Do not delete the test case.

- [ ] **Step 5: Commit**

```bash
git add src/secrets.ts test/secrets.test.ts && git commit -m "feat: secret scanner"
```

---

### Task 5: `errors.ts` + `scopes.ts` — config and target resolution

**Files:**
- Create: `src/errors.ts`, `src/scopes.ts`
- Test: `test/scopes.test.ts`

**Interfaces:**
- Consumes: `normalizeRemote` (Task 2).
- Produces:
  - `type ErrorCode = "invalid" | "unknown_scope" | "no_memory_repo_for_owner" | "unsupported_remote" | "not_reachable" | "reauth_required" | "unavailable"`
  - `class OpError extends Error { code: ErrorCode; action?: string; retryAfter?: number }`
  - `type ScopeConfig = Record<string, string>` (scope name → `"owner/repo"`)
  - `parseScopes(json: string): ScopeConfig`. Throws on invalid input. The `project` scope name is reserved and rejected.
  - `interface Target { scopeLabel: string; displayLabel: string; repo: string; prefix: string }`
    - `scopeLabel` is the commit trailer value: `general`, or `project:acme-org/billing`.
    - `displayLabel` is shown to the user: `general`, or `project billing`.
    - `prefix` is `""` or `projects/<repo>/`.
  - `resolveTarget(cfg: ScopeConfig, scope: string, project?: string): Target`. Throws `OpError`.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest";
import { OpError } from "../src/errors";
import { parseScopes, resolveTarget } from "../src/scopes";

const cfg = parseScopes(JSON.stringify({ general: "dav/claude-memory", acme: "Acme-Org/claude-memory" }));

describe("parseScopes", () => {
  it("parses", () => expect(cfg).toEqual({ general: "dav/claude-memory", acme: "Acme-Org/claude-memory" }));
  it.each([
    "not json",
    "[]",
    JSON.stringify({ general: "no-slash" }),
    JSON.stringify({ project: "a/b" }),
  ])("rejects %s", (j) => expect(() => parseScopes(j)).toThrow());
  it("does not require a general scope", () => expect(parseScopes(JSON.stringify({ acme: "a/b" }))).toEqual({ acme: "a/b" }));
});

describe("resolveTarget", () => {
  it("named scope", () =>
    expect(resolveTarget(cfg, "acme")).toEqual({ scopeLabel: "acme", displayLabel: "acme", repo: "Acme-Org/claude-memory", prefix: "" }));

  it("project via remote, owner matched case-insensitively", () =>
    expect(resolveTarget(cfg, "project", "git@github.com:acme-org/Billing.git")).toEqual({
      scopeLabel: "project:acme-org/billing",
      displayLabel: "project billing",
      repo: "Acme-Org/claude-memory",
      prefix: "projects/billing/",
    }));

  const code = (fn: () => unknown) => {
    try { fn(); } catch (e) { return (e as OpError).code; }
    return "no-throw";
  };
  it("unknown scope", () => expect(code(() => resolveTarget(cfg, "nope"))).toBe("unknown_scope"));
  it("project without remote", () => expect(code(() => resolveTarget(cfg, "project"))).toBe("invalid"));
  it("non-GitHub remote", () => expect(code(() => resolveTarget(cfg, "project", "git@gitlab.com:a/b.git"))).toBe("unsupported_remote"));
  it("owner without memory repo", () => expect(code(() => resolveTarget(cfg, "project", "someone/x"))).toBe("no_memory_repo_for_owner"));
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run test/scopes.test.ts`
Expected: FAIL (modules not found)

- [ ] **Step 3: Implement**

`src/errors.ts`:
```ts
export type ErrorCode =
  | "invalid" | "unknown_scope" | "no_memory_repo_for_owner" | "unsupported_remote"
  | "not_reachable" | "reauth_required" | "unavailable";

export class OpError extends Error {
  constructor(
    public code: ErrorCode,
    message: string,
    public action?: string,
    public retryAfter?: number,
  ) {
    super(message);
  }
}
```

`src/scopes.ts`:
```ts
import { OpError } from "./errors";
import { normalizeRemote } from "./remote";

export type ScopeConfig = Record<string, string>;
export interface Target { scopeLabel: string; displayLabel: string; repo: string; prefix: string }

const REPO_RE = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;

export function parseScopes(json: string): ScopeConfig {
  const v = JSON.parse(json) as unknown;
  if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error("SCOPES must be a JSON object");
  const out: ScopeConfig = {};
  for (const [k, repo] of Object.entries(v)) {
    if (k === "project") throw new Error('scope name "project" is reserved');
    if (typeof repo !== "string" || !REPO_RE.test(repo)) throw new Error(`invalid repo for scope ${k}`);
    out[k] = repo;
  }
  return out;
}

export function resolveTarget(cfg: ScopeConfig, scope: string, project?: string): Target {
  if (scope !== "project") {
    const repo = cfg[scope];
    if (!repo) throw new OpError("unknown_scope", `unknown scope "${scope}"; valid: ${[...Object.keys(cfg), "project"].join(", ")}`);
    return { scopeLabel: scope, displayLabel: scope, repo, prefix: "" };
  }
  if (!project) throw new OpError("invalid", "scope project requires `project` (the git origin remote)", "Pass the output of `git remote get-url origin`.");
  const r = normalizeRemote(project);
  if (!r) throw new OpError("unsupported_remote", `not a GitHub remote: ${project}`, "This repo's origin isn't on GitHub; project memories aren't available here.");
  const repo = Object.values(cfg).find((v) => v.split("/")[0]!.toLowerCase() === r.owner);
  if (!repo) {
    throw new OpError(
      "no_memory_repo_for_owner",
      `no memory repo configured for owner ${r.owner}`,
      `Project memories for this repo can't be saved. To enable: create ${r.owner}/claude-memory, install the app on it, and add a scope for ${r.owner}.`,
    );
  }
  return { scopeLabel: `project:${r.owner}/${r.repo}`, displayLabel: `project ${r.repo}`, repo, prefix: `projects/${r.repo}/` };
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run test/scopes.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/errors.ts src/scopes.ts test/scopes.test.ts && git commit -m "feat: scope config and target resolution"
```

---

### Task 6: `github.ts` — REST client with error mapping

**Files:**
- Create: `src/github.ts`
- Test: `test/github.test.ts`

**Interfaces:**
- Produces:
  - `type GitHubErrorKind = "unauthorized" | "not_found" | "forbidden" | "rate_limited" | "unavailable" | "conflict" | "empty_repo" | "unprocessable" | "other"`
  - `class GitHubError extends Error { status: number; kind: GitHubErrorKind; retryAfter?: number }`
  - `interface RateLimit { limit: number; remaining: number; reset: number /* epoch s */ }`
  - `class GitHub { constructor(token: string); lastRateLimit: RateLimit | null; request<T>(method: string, path: string, body?: unknown): Promise<T> }`. `path` starts with `/`, base `https://api.github.com`.
  - `toOpError(e: unknown): OpError` maps:
    - `unauthorized` → `reauth_required`, with the reconnect action
    - `rate_limited` / `unavailable` → `unavailable`
    - `not_found` / `forbidden` → `not_reachable`
    - everything else → `unavailable`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest";
import { GitHub, GitHubError, toOpError } from "../src/github";
import { json, mockFetch } from "./setup";

describe("GitHub.request", () => {
  it("sends auth headers and parses JSON; records rate limit", async () => {
    const { calls } = mockFetch([{ url: "https://api.github.com/user", respond: () =>
      json({ login: "dav" }, 200, { "x-ratelimit-limit": "5000", "x-ratelimit-remaining": "4999", "x-ratelimit-reset": "1700000000" }) }]);
    const gh = new GitHub("ghu_x");
    expect(await gh.request("GET", "/user")).toEqual({ login: "dav" });
    expect(calls[0]!.headers.get("authorization")).toBe("Bearer ghu_x");
    expect(calls[0]!.headers.get("accept")).toBe("application/vnd.github+json");
    expect(calls[0]!.headers.get("x-github-api-version")).toBe("2022-11-28");
    expect(calls[0]!.headers.get("user-agent")).toBe("claude-memory-cloud");
    expect(gh.lastRateLimit).toEqual({ limit: 5000, remaining: 4999, reset: 1700000000 });
  });

  it("returns null for 204", async () => {
    mockFetch([{ url: "https://api.github.com/x", respond: () => new Response(null, { status: 204 }) }]);
    expect(await new GitHub("t").request("DELETE", "/x")).toBeNull();
  });

  const cases: [number, Record<string, string>, unknown, string][] = [
    [401, {}, { message: "Bad credentials" }, "unauthorized"],
    [404, {}, { message: "Not Found" }, "not_found"],
    [403, { "x-ratelimit-remaining": "0", "x-ratelimit-reset": "1700000000" }, { message: "API rate limit exceeded" }, "rate_limited"],
    [429, { "retry-after": "30" }, {}, "rate_limited"],
    [403, {}, { message: "Resource not accessible by integration" }, "forbidden"],
    [409, {}, { message: "Git Repository is empty." }, "empty_repo"],
    [409, {}, { message: "conflict" }, "conflict"],
    [422, {}, { message: "Update is not a fast forward" }, "conflict"],
    [422, {}, { message: "Invalid request" }, "unprocessable"],
    [502, {}, {}, "unavailable"],
  ];
  it.each(cases)("maps %i %j %j → %s", async (status, headers, body, kind) => {
    mockFetch([{ url: "https://api.github.com/y", respond: () => json(body, status, headers) }]);
    const err = await new GitHub("t").request("GET", "/y").catch((e) => e);
    expect(err).toBeInstanceOf(GitHubError);
    expect((err as GitHubError).kind).toBe(kind);
  });

  it("maps network failure to unavailable", async () => {
    mockFetch([{ url: "https://api.github.com/z", respond: () => { throw new TypeError("network"); } }]);
    expect(((await new GitHub("t").request("GET", "/z").catch((e) => e)) as GitHubError).kind).toBe("unavailable");
  });
});

describe("toOpError", () => {
  it("unauthorized → reauth_required with action", () => {
    const e = toOpError(new GitHubError("x", 401, "unauthorized"));
    expect(e.code).toBe("reauth_required");
    expect(e.action).toMatch(/Settings → Connectors/);
  });
  it("rate_limited → unavailable with retryAfter", () => {
    const e = toOpError(new GitHubError("x", 429, "rate_limited", 30));
    expect([e.code, e.retryAfter]).toEqual(["unavailable", 30]);
  });
  it("not_found → not_reachable", () => expect(toOpError(new GitHubError("x", 404, "not_found")).code).toBe("not_reachable"));
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run test/github.test.ts`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement**

```ts
import { OpError } from "./errors";

export type GitHubErrorKind =
  | "unauthorized" | "not_found" | "forbidden" | "rate_limited" | "unavailable"
  | "conflict" | "empty_repo" | "unprocessable" | "other";

export class GitHubError extends Error {
  constructor(message: string, public status: number, public kind: GitHubErrorKind, public retryAfter?: number) {
    super(message);
  }
}

export interface RateLimit { limit: number; remaining: number; reset: number }

export const RECONNECT_ACTION =
  "Reconnect: claude.ai → Settings → Connectors → claude-memory → Disconnect, then Connect, and approve on GitHub.";

export class GitHub {
  lastRateLimit: RateLimit | null = null;
  constructor(private token: string) {}

  async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    let res: Response;
    try {
      res = await fetch(`https://api.github.com${path}`, {
        method,
        headers: {
          authorization: `Bearer ${this.token}`,
          accept: "application/vnd.github+json",
          "x-github-api-version": "2022-11-28",
          "user-agent": "claude-memory-cloud",
          ...(body === undefined ? {} : { "content-type": "application/json" }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (e) {
      throw new GitHubError(`network error: ${(e as Error).message}`, 0, "unavailable");
    }
    const limit = res.headers.get("x-ratelimit-limit");
    if (limit) {
      this.lastRateLimit = {
        limit: Number(limit),
        remaining: Number(res.headers.get("x-ratelimit-remaining")),
        reset: Number(res.headers.get("x-ratelimit-reset")),
      };
    }
    if (res.status === 204) return null as T;
    const text = await res.text();
    const data = text ? (JSON.parse(text) as Record<string, unknown>) : {};
    if (res.ok) return data as T;
    throw classify(res, String(data.message ?? res.statusText));
  }
}

function classify(res: Response, message: string): GitHubError {
  const s = res.status;
  const retryAfterHeader = res.headers.get("retry-after");
  const reset = res.headers.get("x-ratelimit-reset");
  const retryAfter = retryAfterHeader
    ? Number(retryAfterHeader)
    : reset ? Math.max(0, Number(reset) - Math.floor(Date.now() / 1000)) : undefined;
  if (s === 401) return new GitHubError(message, s, "unauthorized");
  if (s === 429 || (s === 403 && (res.headers.get("x-ratelimit-remaining") === "0" || /rate limit/i.test(message)))) {
    return new GitHubError(message, s, "rate_limited", retryAfter);
  }
  if (s === 403) return new GitHubError(message, s, "forbidden");
  if (s === 404) return new GitHubError(message, s, "not_found");
  if (s === 409) return new GitHubError(message, s, /empty/i.test(message) ? "empty_repo" : "conflict");
  if (s === 422) return new GitHubError(message, s, /fast.forward/i.test(message) ? "conflict" : "unprocessable");
  if (s >= 500) return new GitHubError(message, s, "unavailable");
  return new GitHubError(message, s, "other");
}

export function toOpError(e: unknown): OpError {
  if (e instanceof OpError) return e;
  if (!(e instanceof GitHubError)) return new OpError("unavailable", String(e));
  switch (e.kind) {
    case "unauthorized":
      return new OpError("reauth_required", "GitHub sign-in expired or was revoked", RECONNECT_ACTION);
    case "rate_limited":
      return new OpError("unavailable", "GitHub rate limit reached", "Saves may be queued until the limit resets; no action needed.", e.retryAfter);
    case "not_found":
    case "forbidden":
      return new OpError("not_reachable", e.message);
    default:
      return new OpError("unavailable", `GitHub error: ${e.message}`, "GitHub is having problems (githubstatus.com). Saves will be queued; nothing to do.");
  }
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run test/github.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/github.ts test/github.test.ts && git commit -m "feat: GitHub REST client with error classification"
```

---

### Task 7: `store.ts` — Store interface, GitHub implementation, fake

**Files:**
- Create: `src/store.ts`, `test/fake-store.ts`
- Test: `test/store.test.ts`

**Interfaces:**
- Consumes: `GitHub`, `GitHubError` (Task 6).
- Produces:
  - `interface FileEntry { path: string; sha: string; content: string }`
  - `interface Snapshot { commitSha: string | null; files: Map<string, FileEntry> }`
    - `commitSha === null` means the repo is empty.
    - Keys are paths **relative to the prefix**, e.g. `memories/a.md`, `MEMORY.md`.
    - For prefix `""`, anything under `projects/` is excluded.
  - `interface Change { path: string; content: string | null }`. The path is relative to the prefix; `null` means delete.
  - `type CommitResult = { ok: true; commitSha: string; url: string } | { ok: false; reason: "ref_moved" }`
  - `interface Store { snapshot(repo: string, prefix: string): Promise<Snapshot>; commit(repo: string, prefix: string, baseCommitSha: string | null, changes: Change[], message: string): Promise<CommitResult> }`
  - `class GitHubStore implements Store { constructor(gh: GitHub, cache?: KVNamespace) }`. Blobs are cached in KV under `blob:<sha>`; they're immutable.
  - `test/fake-store.ts`: `class FakeStore implements Store` with `files: Map<string, Map<string,string>>` keyed by repo, then full path; a `commits: {repo, message, changes}[]` log; and `failNextCommit: number` to simulate ref races.

- [ ] **Step 1: Write the fake store** (it's test infrastructure and has no tests of its own)

`test/fake-store.ts`:
```ts
import type { Change, CommitResult, Snapshot, Store } from "../src/store";

async function sha(s: string) {
  const d = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(s));
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export class FakeStore implements Store {
  files = new Map<string, Map<string, string>>();
  commits: { repo: string; message: string; changes: Change[] }[] = [];
  heads = new Map<string, number>();
  failNextCommit = 0;
  /** Called after a snapshot is taken and before the commit is applied: simulates a concurrent writer. */
  beforeCommit?: () => void;

  repo(repo: string) {
    let m = this.files.get(repo);
    if (!m) this.files.set(repo, (m = new Map()));
    return m;
  }
  /** Direct write that bumps the head, as if another client committed. */
  put(repo: string, path: string, content: string | null) {
    const m = this.repo(repo);
    if (content === null) m.delete(path);
    else m.set(path, content);
    this.heads.set(repo, (this.heads.get(repo) ?? 0) + 1);
  }

  async snapshot(repo: string, prefix: string): Promise<Snapshot> {
    const m = this.repo(repo);
    const head = this.heads.get(repo);
    const files = new Map<string, { path: string; sha: string; content: string }>();
    for (const [p, content] of m) {
      if (!p.startsWith(prefix)) continue;
      const rel = p.slice(prefix.length);
      if (prefix === "" && rel.startsWith("projects/")) continue;
      files.set(rel, { path: rel, sha: await sha(content), content });
    }
    return { commitSha: head === undefined ? null : `c${head}`, files };
  }

  async commit(repo: string, prefix: string, base: string | null, changes: Change[], message: string): Promise<CommitResult> {
    this.beforeCommit?.();
    this.beforeCommit = undefined;
    const head = this.heads.get(repo);
    const current = head === undefined ? null : `c${head}`;
    if (this.failNextCommit > 0 || current !== base) {
      if (this.failNextCommit > 0) this.failNextCommit--;
      return { ok: false, reason: "ref_moved" };
    }
    for (const c of changes) {
      const full = prefix + c.path;
      if (c.content === null) this.repo(repo).delete(full);
      else this.repo(repo).set(full, c.content);
    }
    const next = (head ?? 0) + 1;
    this.heads.set(repo, next);
    this.commits.push({ repo, message, changes });
    return { ok: true, commitSha: `c${next}`, url: `https://github.com/${repo}/commit/c${next}` };
  }
}
```

- [ ] **Step 2: Write the failing test for `GitHubStore`**

```ts
import { env } from "cloudflare:workers";
import { describe, expect, it } from "vitest";
import { GitHub } from "../src/github";
import { GitHubStore } from "../src/store";
import { json, mockFetch } from "./setup";

const R = "https://api.github.com/repos/dav/mem";
const b64 = (s: string) => btoa(unescape(encodeURIComponent(s)));

function repoRoutes(extra: Parameters<typeof mockFetch>[0] = []) {
  return [
    { method: "GET", url: `${R}/git/ref/heads/main`, respond: () => json({ object: { sha: "c1" } }) },
    { method: "GET", url: R, respond: () => json({ default_branch: "main" }) },
    { method: "GET", url: `${R}/git/commits/c1`, respond: () => json({ tree: { sha: "t1" } }) },
    { method: "GET", url: `${R}/git/trees/t1?recursive=1`, respond: () => json({ truncated: false, tree: [
      { path: "MEMORY.md", type: "blob", sha: "s0" },
      { path: "memories/a.md", type: "blob", sha: "s1" },
      { path: "projects/billing/memories/p.md", type: "blob", sha: "s2" },
      { path: "README.md", type: "blob", sha: "s3" },
    ] }) },
    { method: "GET", url: `${R}/git/blobs/s0`, respond: () => json({ content: b64("# idx\n"), encoding: "base64" }) },
    { method: "GET", url: `${R}/git/blobs/s1`, respond: () => json({ content: b64("A — é\n"), encoding: "base64" }) },
    { method: "GET", url: `${R}/git/blobs/s2`, respond: () => json({ content: b64("P\n"), encoding: "base64" }) },
    ...extra,
  ];
}

describe("GitHubStore.snapshot", () => {
  it("root prefix: MEMORY.md + memories/*, excludes projects/ and other files, decodes UTF-8", async () => {
    mockFetch(repoRoutes());
    const snap = await new GitHubStore(new GitHub("t"), env.CACHE_KV).snapshot("dav/mem", "");
    expect(snap.commitSha).toBe("c1");
    expect([...snap.files.keys()].sort()).toEqual(["MEMORY.md", "memories/a.md"]);
    expect(snap.files.get("memories/a.md")).toEqual({ path: "memories/a.md", sha: "s1", content: "A — é\n" });
  });

  it("project prefix: paths relative to the prefix", async () => {
    mockFetch(repoRoutes());
    const snap = await new GitHubStore(new GitHub("t"), env.CACHE_KV).snapshot("dav/mem", "projects/billing/");
    expect([...snap.files.keys()]).toEqual(["memories/p.md"]);
  });

  it("uses the blob cache on a second snapshot", async () => {
    mockFetch(repoRoutes());
    const store = new GitHubStore(new GitHub("t"), env.CACHE_KV);
    await store.snapshot("dav/mem", "");
    const { calls } = mockFetch(repoRoutes());
    await store.snapshot("dav/mem", "");
    expect(calls.some((c) => c.url.includes("/git/blobs/"))).toBe(false);
  });

  it("empty repo → commitSha null, no files", async () => {
    mockFetch([
      { method: "GET", url: R, respond: () => json({ default_branch: "main" }) },
      { method: "GET", url: `${R}/git/ref/heads/main`, respond: () => json({ message: "Git Repository is empty." }, 409) },
    ]);
    const snap = await new GitHubStore(new GitHub("t")).snapshot("dav/mem", "");
    expect(snap).toEqual({ commitSha: null, files: new Map() });
  });
});

describe("GitHubStore.commit", () => {
  it("creates tree (with deletes), commit, and fast-forwards the ref", async () => {
    const { calls } = mockFetch([
      { method: "GET", url: R, respond: () => json({ default_branch: "main" }) },
      { method: "GET", url: `${R}/git/commits/c1`, respond: () => json({ tree: { sha: "t1" } }) },
      { method: "POST", url: `${R}/git/trees`, respond: () => json({ sha: "t2" }) },
      { method: "POST", url: `${R}/git/commits`, respond: () => json({ sha: "c2", html_url: "https://github.com/dav/mem/commit/c2" }) },
      { method: "PATCH", url: `${R}/git/refs/heads/main`, respond: () => json({ object: { sha: "c2" } }) },
    ]);
    const res = await new GitHubStore(new GitHub("t")).commit("dav/mem", "projects/billing/", "c1",
      [{ path: "memories/x.md", content: "X" }, { path: "memories/y.md", content: null }], "save: x");
    expect(res).toEqual({ ok: true, commitSha: "c2", url: "https://github.com/dav/mem/commit/c2" });
    const tree = await calls.find((c) => c.url.endsWith("/git/trees") && c.method === "POST")!.json();
    expect(tree).toEqual({ base_tree: "t1", tree: [
      { path: "projects/billing/memories/x.md", mode: "100644", type: "blob", content: "X" },
      { path: "projects/billing/memories/y.md", mode: "100644", type: "blob", sha: null },
    ] });
    const patch = await calls.find((c) => c.method === "PATCH")!.json();
    expect(patch).toEqual({ sha: "c2", force: false });
  });

  it("non-fast-forward → ref_moved", async () => {
    mockFetch([
      { method: "GET", url: R, respond: () => json({ default_branch: "main" }) },
      { method: "GET", url: `${R}/git/commits/c1`, respond: () => json({ tree: { sha: "t1" } }) },
      { method: "POST", url: `${R}/git/trees`, respond: () => json({ sha: "t2" }) },
      { method: "POST", url: `${R}/git/commits`, respond: () => json({ sha: "c2", html_url: "u" }) },
      { method: "PATCH", url: `${R}/git/refs/heads/main`, respond: () => json({ message: "Update is not a fast forward" }, 422) },
    ]);
    expect(await new GitHubStore(new GitHub("t")).commit("dav/mem", "", "c1", [{ path: "MEMORY.md", content: "i" }], "m"))
      .toEqual({ ok: false, reason: "ref_moved" });
  });

  it("empty repo (base null) → initializes README via contents API, then reports ref_moved so the caller retries", async () => {
    const { calls } = mockFetch([
      { method: "GET", url: R, respond: () => json({ default_branch: "main" }) },
      { method: "PUT", url: `${R}/contents/README.md`, respond: () => json({ commit: { sha: "c1" } }, 201) },
    ]);
    expect(await new GitHubStore(new GitHub("t")).commit("dav/mem", "", null, [{ path: "MEMORY.md", content: "i" }], "m"))
      .toEqual({ ok: false, reason: "ref_moved" });
    const put = await calls.find((c) => c.method === "PUT")!.json() as { message: string; content: string };
    expect(put.message).toBe("init: claude-memory");
    expect(atob(put.content)).toMatch(/^# claude-memory/);
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `npx vitest run test/store.test.ts`
Expected: FAIL (module not found)

- [ ] **Step 4: Implement `src/store.ts`**

```ts
import { GitHub, GitHubError } from "./github";

export interface FileEntry { path: string; sha: string; content: string }
export interface Snapshot { commitSha: string | null; files: Map<string, FileEntry> }
export interface Change { path: string; content: string | null }
export type CommitResult = { ok: true; commitSha: string; url: string } | { ok: false; reason: "ref_moved" };

export interface Store {
  snapshot(repo: string, prefix: string): Promise<Snapshot>;
  commit(repo: string, prefix: string, baseCommitSha: string | null, changes: Change[], message: string): Promise<CommitResult>;
}

export const README = `# claude-memory

Memories for Claude, maintained by the claude-memory-cloud server.

- \`MEMORY.md\` is the index; \`memories/\` holds one file per memory; \`projects/<repo>/\` holds per-project sets.
- **Never put secrets here.** The server rejects anything that looks like a credential.
- Editing by hand is fine; the server rebuilds the index on its next write.
`;

const decode = (b64: string) =>
  new TextDecoder().decode(Uint8Array.from(atob(b64.replace(/\n/g, "")), (c) => c.charCodeAt(0)));
const encode = (s: string) => btoa(String.fromCharCode(...new TextEncoder().encode(s)));

export class GitHubStore implements Store {
  private branches = new Map<string, string>();
  constructor(private gh: GitHub, private cache?: KVNamespace) {}

  private async branch(repo: string) {
    let b = this.branches.get(repo);
    if (!b) {
      b = (await this.gh.request<{ default_branch: string }>("GET", `/repos/${repo}`)).default_branch;
      this.branches.set(repo, b);
    }
    return b;
  }

  private async blob(repo: string, sha: string): Promise<string> {
    const cached = await this.cache?.get(`blob:${sha}`);
    if (cached !== null && cached !== undefined) return cached;
    const b = await this.gh.request<{ content: string }>("GET", `/repos/${repo}/git/blobs/${sha}`);
    const text = decode(b.content);
    await this.cache?.put(`blob:${sha}`, text);
    return text;
  }

  async snapshot(repo: string, prefix: string): Promise<Snapshot> {
    const branch = await this.branch(repo);
    let commitSha: string;
    try {
      commitSha = (await this.gh.request<{ object: { sha: string } }>("GET", `/repos/${repo}/git/ref/heads/${branch}`)).object.sha;
    } catch (e) {
      if (e instanceof GitHubError && (e.kind === "empty_repo" || e.kind === "not_found" && /empty/i.test(e.message))) {
        return { commitSha: null, files: new Map() };
      }
      throw e;
    }
    const treeSha = (await this.gh.request<{ tree: { sha: string } }>("GET", `/repos/${repo}/git/commits/${commitSha}`)).tree.sha;
    const tree = await this.gh.request<{ tree: { path: string; type: string; sha: string }[]; truncated: boolean }>(
      "GET", `/repos/${repo}/git/trees/${treeSha}?recursive=1`,
    );
    if (tree.truncated) throw new GitHubError("memory repo tree too large (truncated)", 0, "other");
    const wanted = tree.tree.filter((t) => {
      if (t.type !== "blob" || !t.path.startsWith(prefix)) return false;
      const rel = t.path.slice(prefix.length);
      return rel === "MEMORY.md" || (rel.startsWith("memories/") && !rel.slice(9).includes("/"));
    });
    const files = new Map<string, FileEntry>();
    await Promise.all(wanted.map(async (t) => {
      const rel = t.path.slice(prefix.length);
      files.set(rel, { path: rel, sha: t.sha, content: await this.blob(repo, t.sha) });
    }));
    return { commitSha, files };
  }

  async commit(repo: string, prefix: string, base: string | null, changes: Change[], message: string): Promise<CommitResult> {
    const branch = await this.branch(repo);
    if (base === null) {
      // Git Data API can't write to an empty repo: create README via the contents API, then let the caller retry.
      await this.gh.request("PUT", `/repos/${repo}/contents/README.md`, { message: "init: claude-memory", content: encode(README), branch });
      return { ok: false, reason: "ref_moved" };
    }
    const baseTree = (await this.gh.request<{ tree: { sha: string } }>("GET", `/repos/${repo}/git/commits/${base}`)).tree.sha;
    const tree = await this.gh.request<{ sha: string }>("POST", `/repos/${repo}/git/trees`, {
      base_tree: baseTree,
      tree: changes.map((c) => c.content === null
        ? { path: prefix + c.path, mode: "100644", type: "blob", sha: null }
        : { path: prefix + c.path, mode: "100644", type: "blob", content: c.content }),
    });
    const commit = await this.gh.request<{ sha: string; html_url: string }>("POST", `/repos/${repo}/git/commits`, {
      message, tree: tree.sha, parents: [base],
    });
    try {
      await this.gh.request("PATCH", `/repos/${repo}/git/refs/heads/${branch}`, { sha: commit.sha, force: false });
    } catch (e) {
      if (e instanceof GitHubError && e.kind === "conflict") return { ok: false, reason: "ref_moved" };
      throw e;
    }
    return { ok: true, commitSha: commit.sha, url: commit.html_url };
  }
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `npx vitest run test/store.test.ts`
Expected: PASS. If the empty-repo ref lookup returns 404 instead of 409 in the live test (Task 14), the `not_found && /empty/` branch covers it. Keep both.

- [ ] **Step 6: Commit**

```bash
git add src/store.ts test/store.test.ts test/fake-store.ts && git commit -m "feat: GitHub-backed store with CAS commits and blob cache"
```

---

### Task 8: `operations.ts` — save, delete, read, index, search

**Files:**
- Create: `src/operations.ts`
- Test: `test/operations.test.ts`

**Interfaces:**
- Consumes: `Store` and `Snapshot` (Task 7); `Target` (Task 5); everything in `memory.ts` (Task 3); `scanForSecrets` (Task 4); `OpError` (Task 5).
- Produces:
  - `interface SaveInput { name: string; description: string; type: string; body: string; version?: string; force?: boolean; source?: string }`
  - `interface OpResult { status: "created"|"updated"|"conflict"|"exists"|"similar_found"|"rejected_secret"|"invalid"|"not_found"|"deleted"; name: string; scope: string; commit_url?: string; similar?: IndexEntry[]; conflict_file?: string; pattern?: string; version?: string; message?: string }`. `scope` is the `displayLabel`.
  - `saveMemory(store: Store, t: Target, input: SaveInput, now?: Date): Promise<OpResult>`
  - `deleteMemory(store: Store, t: Target, name: string, version?: string, source?: string, now?: Date): Promise<OpResult>`
  - `readMemories(store: Store, t: Target, names: string[]): Promise<({ name: string; content: string; version: string } | { name: string; error: "not_found" })[]>`
  - `getIndex(store: Store, t: Target): Promise<string>`. Returns the stored `MEMORY.md`, or one built from the files if it's missing (that path doesn't write).
  - `getIndexVersioned(store: Store, t: Target): Promise<{ text: string; version: string }>`. Same text as `getIndex`. `version` is the stored `MEMORY.md` blob SHA, or `"none"` when there is no stored index. Every save and delete rewrites the index in the same commit, so the version changes exactly when the scope's memories change. Used for the `since` map (Task 10).
  - `searchMemories(store: Store, targets: Target[], query: string): Promise<{ scope: string; name: string; description: string; snippet: string }[]>`. Max 20 results.
  - `MAX_ATTEMPTS = 3`

- [ ] **Step 1: Write the failing test**

```ts
import { beforeEach, describe, expect, it } from "vitest";
import { serializeMemory } from "../src/memory";
import { deleteMemory, getIndex, getIndexVersioned, readMemories, saveMemory, searchMemories } from "../src/operations";
import type { Target } from "../src/scopes";
import { FakeStore } from "./fake-store";

const T: Target = { scopeLabel: "general", displayLabel: "general", repo: "dav/mem", prefix: "" };
const P: Target = { scopeLabel: "project:dav/app", displayLabel: "project app", repo: "dav/mem", prefix: "projects/app/" };
const NOW = new Date("2026-10-13T18:04:05Z");
const base = { description: "Measure first; question failed theories", type: "feedback", body: "Measure.\n", source: "test" };

let store: FakeStore;
beforeEach(() => {
  store = new FakeStore();
  store.put("dav/mem", "README.md", "r"); // non-empty repo
});

describe("saveMemory: create", () => {
  it("creates file + index in one commit with trailers", async () => {
    const r = await saveMemory(store, T, { name: "debugging-discipline", ...base }, NOW);
    expect(r).toMatchObject({ status: "created", name: "debugging-discipline", scope: "general" });
    expect(r.commit_url).toMatch(/commit/);
    const c = store.commits.at(-1)!;
    expect(c.changes.map((x) => x.path).sort()).toEqual(["MEMORY.md", "memories/debugging-discipline.md"]);
    expect(c.message).toBe("save: debugging-discipline\n\nMemory-Source: test\nMemory-Scope: general\n");
    expect(store.repo("dav/mem").get("MEMORY.md")).toContain("- [debugging-discipline](memories/debugging-discipline.md)");
  });

  it("project target writes under the prefix with its own index", async () => {
    await saveMemory(store, P, { name: "no-generated-edits", ...base, description: "never edit generated/" }, NOW);
    expect(store.repo("dav/mem").has("projects/app/memories/no-generated-edits.md")).toBe(true);
    expect(store.repo("dav/mem").get("projects/app/MEMORY.md")).toMatch(/^# Memory index — project app/);
    expect(store.repo("dav/mem").has("MEMORY.md")).toBe(false);
    expect(store.commits.at(-1)!.message).toContain("Memory-Scope: project:dav/app");
  });

  it("exists → returns version, writes nothing", async () => {
    await saveMemory(store, T, { name: "a", ...base }, NOW);
    const n = store.commits.length;
    const r = await saveMemory(store, T, { name: "a", ...base, description: "other" }, NOW);
    expect(r.status).toBe("exists");
    expect(r.version).toMatch(/^[0-9a-f]{40}$/);
    expect(store.commits.length).toBe(n);
  });

  it("similar_found unless force", async () => {
    await saveMemory(store, T, { name: "debugging-discipline", ...base }, NOW);
    const r = await saveMemory(store, T, { name: "debugging-rules", ...base, description: "measure first, question failed theories" }, NOW);
    expect(r.status).toBe("similar_found");
    expect(r.similar?.map((s) => s.name)).toEqual(["debugging-discipline"]);
    const f = await saveMemory(store, T, { name: "debugging-rules", ...base, description: "measure first, question failed theories", force: true }, NOW);
    expect(f.status).toBe("created");
  });

  it("rejected_secret names the rule, never the value, writes nothing", async () => {
    const secret = "ghp_" + "a".repeat(36);
    const r = await saveMemory(store, T, { name: "x", ...base, body: `token ${secret}` }, NOW);
    expect(r).toMatchObject({ status: "rejected_secret", pattern: "github-token" });
    expect(JSON.stringify(r)).not.toContain(secret);
    expect(store.commits.length).toBe(0);
  });

  it.each([
    [{ name: "Bad Name" }],
    [{ type: "nope" }],
    [{ description: "" }],
  ])("invalid input %j", async (patch) => {
    const r = await saveMemory(store, T, { name: "ok", ...base, ...patch }, NOW);
    expect(r.status).toBe("invalid");
  });

  it("empty repo: initializes and retries", async () => {
    const empty = new FakeStore();
    // FakeStore treats a missing head as empty; emulate GitHubStore's init-then-ref_moved by bumping head on first commit
    empty.beforeCommit = () => empty.put("dav/new", "README.md", "r");
    const r = await saveMemory(empty, { ...T, repo: "dav/new" }, { name: "a", ...base }, NOW);
    expect(r.status).toBe("created");
  });
});

describe("saveMemory: update", () => {
  it("matching version → updated", async () => {
    await saveMemory(store, T, { name: "a", ...base }, NOW);
    const [read] = await readMemories(store, T, ["a"]);
    const r = await saveMemory(store, T, { name: "a", ...base, body: "new\n", version: (read as { version: string }).version }, NOW);
    expect(r.status).toBe("updated");
    expect(store.repo("dav/mem").get("memories/a.md")).toContain("new");
  });

  it("stale version → conflict file + index Conflicts entry, original untouched", async () => {
    await saveMemory(store, T, { name: "a", ...base }, NOW);
    const [read] = await readMemories(store, T, ["a"]);
    store.put("dav/mem", "memories/a.md", serializeMemory({ name: "a", description: "edited elsewhere", type: "feedback", body: "x\n" }));
    const r = await saveMemory(store, T, { name: "a", ...base, body: "mine\n", version: (read as { version: string }).version }, NOW);
    expect(r).toMatchObject({ status: "conflict", conflict_file: "memories/a.conflict-20261013T180405Z.md" });
    expect(store.repo("dav/mem").get("memories/a.md")).toContain("edited elsewhere");
    expect(store.repo("dav/mem").get("memories/a.conflict-20261013T180405Z.md")).toContain("mine");
    expect(store.repo("dav/mem").get("MEMORY.md")).toContain("## Conflicts");
  });

  it("missing file → not_found", async () => {
    expect((await saveMemory(store, T, { name: "zzz", ...base, version: "abc" }, NOW)).status).toBe("not_found");
  });
});

describe("races", () => {
  it("ref moved by a different-file write → retried and lands; both in index", async () => {
    store.beforeCommit = () => store.put("dav/mem", "memories/other.md", serializeMemory({ name: "other", description: "o", type: "user", body: "o\n" }));
    const r = await saveMemory(store, T, { name: "a", ...base }, NOW);
    expect(r.status).toBe("created");
    const idx = store.repo("dav/mem").get("MEMORY.md")!;
    expect(idx).toContain("[a]");
    expect(idx).toContain("[other]");
  });

  it("gives up after 3 attempts with unavailable", async () => {
    store.failNextCommit = 3;
    await expect(saveMemory(store, T, { name: "a", ...base }, NOW)).rejects.toMatchObject({ code: "unavailable" });
  });
});

describe("deleteMemory", () => {
  it("deletes with matching version and updates index", async () => {
    await saveMemory(store, T, { name: "a", ...base }, NOW);
    const [read] = await readMemories(store, T, ["a"]);
    const r = await deleteMemory(store, T, "a", (read as { version: string }).version, "test", NOW);
    expect(r.status).toBe("deleted");
    expect(store.repo("dav/mem").has("memories/a.md")).toBe(false);
    expect(store.repo("dav/mem").get("MEMORY.md")).toContain("(no memories yet)");
    expect(store.commits.at(-1)!.message.startsWith("delete: a\n")).toBe(true);
  });
  it("stale version → conflict, nothing deleted", async () => {
    await saveMemory(store, T, { name: "a", ...base }, NOW);
    expect((await deleteMemory(store, T, "a", "deadbeef", "test", NOW)).status).toBe("conflict");
    expect(store.repo("dav/mem").has("memories/a.md")).toBe(true);
  });
  it("can delete a conflict file by its name", async () => {
    store.put("dav/mem", "memories/a.conflict-20261013T180405Z.md", "x");
    const r = await deleteMemory(store, T, "a.conflict-20261013T180405Z", undefined, "test", NOW);
    expect(r.status).toBe("deleted");
  });
  it("missing → not_found", async () => {
    expect((await deleteMemory(store, T, "nope", undefined, "test", NOW)).status).toBe("not_found");
  });
});

describe("read / index / search", () => {
  beforeEach(async () => {
    await saveMemory(store, T, { name: "a", ...base, body: "The deploy window is Tuesday.\n" }, NOW);
    await saveMemory(store, P, { name: "b", ...base, description: "project thing", body: "Never edit generated/ by hand.\n" }, NOW);
  });
  it("readMemories mixes found and not_found", async () => {
    const r = await readMemories(store, T, ["a", "nope"]);
    expect(r[0]).toMatchObject({ name: "a" });
    expect((r[0] as { content: string }).content).toContain("Tuesday");
    expect(r[1]).toEqual({ name: "nope", error: "not_found" });
  });
  it("getIndex returns stored index; builds one when missing; empty project → empty index", async () => {
    expect(await getIndex(store, T)).toContain("[a]");
    store.put("dav/mem", "MEMORY.md", null);
    expect(await getIndex(store, T)).toContain("[a]");
    expect(await getIndex(store, { ...P, prefix: "projects/none/", displayLabel: "project none" }))
      .toBe("# Memory index — project none\n\n(no memories yet)\n");
  });
  it("getIndexVersioned: blob SHA of MEMORY.md, \"none\" when absent, changes on save", async () => {
    const before = await getIndexVersioned(store, T);
    expect(before.version).toMatch(/^[0-9a-f]{40}$/);
    expect(before.text).toBe(await getIndex(store, T));
    expect((await getIndexVersioned(store, { ...P, prefix: "projects/none/", displayLabel: "project none" })).version).toBe("none");
    await saveMemory(store, T, { name: "zz-new", ...base, description: "something unrelated entirely" }, NOW);
    const after = await getIndexVersioned(store, T);
    expect(after.version).not.toBe(before.version);
    expect(after.text).toContain("[zz-new]");
  });
  it("search matches all terms across body, case-insensitive, with snippet", async () => {
    const r = await searchMemories(store, [T, P], "GENERATED hand");
    expect(r).toEqual([{ scope: "project app", name: "b", description: "project thing", snippet: expect.stringContaining("generated/") }]);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run test/operations.test.ts`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement**

```ts
import { OpError } from "./errors";
import {
  buildIndex, conflictPath, findSimilar, isValidName, memoryPath, MemoryFormatError,
  parseMemory, parseMemoryPath, serializeMemory, type IndexEntry, type Memory,
} from "./memory";
import type { Target } from "./scopes";
import { scanForSecrets } from "./secrets";
import type { Change, Snapshot, Store } from "./store";

export const MAX_ATTEMPTS = 3;
const TYPES = ["user", "feedback", "project", "reference"];

export interface SaveInput { name: string; description: string; type: string; body: string; version?: string; force?: boolean; source?: string }
export interface OpResult {
  status: "created" | "updated" | "conflict" | "exists" | "similar_found" | "rejected_secret" | "invalid" | "not_found" | "deleted";
  name: string; scope: string; commit_url?: string; similar?: IndexEntry[]; conflict_file?: string; pattern?: string; version?: string; message?: string;
}

function entries(snap: Snapshot): { list: IndexEntry[]; conflicts: string[] } {
  const list: IndexEntry[] = [];
  const conflicts: string[] = [];
  for (const [path, f] of snap.files) {
    const p = parseMemoryPath(path);
    if (!p) continue;
    if (p.conflict) { conflicts.push(path); continue; }
    try {
      const m = parseMemory(f.content);
      list.push({ name: p.name, description: m.description });
    } catch {
      list.push({ name: p.name, description: "(unparseable frontmatter — fix by hand)" });
    }
  }
  return { list, conflicts };
}

/** Index after applying `changes` to `snap`. */
function indexAfter(t: Target, snap: Snapshot, changes: Change[]): string {
  const next = new Map(snap.files);
  for (const c of changes) {
    if (c.content === null) next.delete(c.path);
    else next.set(c.path, { path: c.path, sha: "", content: c.content });
  }
  const { list, conflicts } = entries({ commitSha: snap.commitSha, files: next });
  return buildIndex(t.displayLabel, list, conflicts);
}

const message = (op: string, name: string, t: Target, source?: string) =>
  `${op}: ${name}\n\nMemory-Source: ${source?.trim() || "unknown"}\nMemory-Scope: ${t.scopeLabel}\n`;

/** Runs `decide` against fresh snapshots, committing its changes; retries on ref races. */
async function withRetry(
  store: Store, t: Target,
  decide: (snap: Snapshot) => { result: OpResult; changes?: Change[]; op?: string; source?: string },
): Promise<OpResult> {
  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
    const snap = await store.snapshot(t.repo, t.prefix);
    const d = decide(snap);
    if (!d.changes) return d.result;
    const changes = [...d.changes, { path: "MEMORY.md", content: indexAfter(t, snap, d.changes) }];
    const res = await store.commit(t.repo, t.prefix, snap.commitSha, changes, message(d.op!, d.result.name, t, d.source));
    if (res.ok) return { ...d.result, commit_url: res.url };
  }
  throw new OpError("unavailable", `could not commit after ${MAX_ATTEMPTS} attempts (concurrent writes)`, "Try again in a moment.");
}

export async function saveMemory(store: Store, t: Target, input: SaveInput, now = new Date()): Promise<OpResult> {
  const r = (status: OpResult["status"], extra: Partial<OpResult> = {}): OpResult => ({ status, name: input.name, scope: t.displayLabel, ...extra });
  if (!isValidName(input.name)) return r("invalid", { message: "name must match ^[a-z0-9][a-z0-9-]{0,63}$" });
  if (!TYPES.includes(input.type)) return r("invalid", { message: `type must be one of ${TYPES.join(", ")}` });
  if (!input.description?.trim()) return r("invalid", { message: "description is required" });
  if (!input.body?.trim()) return r("invalid", { message: "body is required" });
  const pattern = scanForSecrets(`${input.name}\n${input.description}\n${input.body}`);
  if (pattern) return r("rejected_secret", { pattern, message: "Remove the credential and save again." });

  const mem: Memory = { name: input.name, description: input.description, type: input.type as Memory["type"], body: input.body };
  let content: string;
  try { content = serializeMemory(mem); parseMemory(content); }
  catch (e) { return r("invalid", { message: (e as MemoryFormatError).message }); }
  const path = memoryPath(input.name);

  return withRetry(store, t, (snap) => {
    const existing = snap.files.get(path);
    if (input.version === undefined) {
      if (existing) return { result: r("exists", { version: existing.sha, message: "Read it and update with its version instead." }) };
      if (!input.force) {
        const similar = findSimilar({ name: input.name, description: input.description }, entries(snap).list);
        if (similar.length) return { result: r("similar_found", { similar, message: "Update one of these, or save again with force: true." }) };
      }
      return { result: r("created"), changes: [{ path, content }], op: "save", source: input.source };
    }
    if (!existing) return { result: r("not_found") };
    if (existing.sha === input.version) return { result: r("updated"), changes: [{ path, content }], op: "update", source: input.source };
    const cpath = conflictPath(input.name, now);
    return { result: r("conflict", { conflict_file: cpath, message: "The memory changed since you read it; your version was saved as a conflict copy. Reconcile them." }),
      changes: [{ path: cpath, content }], op: "conflict", source: input.source };
  });
}

export async function deleteMemory(store: Store, t: Target, name: string, version?: string, source?: string, _now = new Date()): Promise<OpResult> {
  const path = `memories/${name}.md`;
  const r = (status: OpResult["status"], extra: Partial<OpResult> = {}): OpResult => ({ status, name, scope: t.displayLabel, ...extra });
  if (!parseMemoryPath(path)) return r("invalid", { message: "invalid memory name" });
  return withRetry(store, t, (snap) => {
    const existing = snap.files.get(path);
    if (!existing) return { result: r("not_found") };
    if (version !== undefined && existing.sha !== version) return { result: r("conflict", { version: existing.sha, message: "Changed since you read it; re-read before deleting." }) };
    return { result: r("deleted"), changes: [{ path, content: null }], op: "delete", source };
  });
}

export async function readMemories(store: Store, t: Target, names: string[]) {
  const snap = await store.snapshot(t.repo, t.prefix);
  return names.map((name) => {
    const f = snap.files.get(`memories/${name}.md`);
    return f ? { name, content: f.content, version: f.sha } : { name, error: "not_found" as const };
  });
}

export async function getIndexVersioned(store: Store, t: Target): Promise<{ text: string; version: string }> {
  const snap = await store.snapshot(t.repo, t.prefix);
  const stored = snap.files.get("MEMORY.md");
  if (stored) return { text: stored.content, version: stored.sha };
  const { list, conflicts } = entries(snap);
  return { text: buildIndex(t.displayLabel, list, conflicts), version: "none" };
}

export async function getIndex(store: Store, t: Target): Promise<string> {
  return (await getIndexVersioned(store, t)).text;
}

export async function searchMemories(store: Store, targets: Target[], query: string) {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  const out: { scope: string; name: string; description: string; snippet: string }[] = [];
  for (const t of targets) {
    const snap = await store.snapshot(t.repo, t.prefix);
    for (const [path, f] of snap.files) {
      const p = parseMemoryPath(path);
      if (!p || p.conflict) continue;
      const hay = f.content.toLowerCase();
      if (!terms.every((term) => hay.includes(term))) continue;
      let description = "";
      try { description = parseMemory(f.content).description; } catch { /* keep empty */ }
      const at = Math.max(0, hay.indexOf(terms[0] ?? "") - 40);
      out.push({ scope: t.displayLabel, name: p.name, description, snippet: f.content.slice(at, at + 120).replace(/\s+/g, " ").trim() });
      if (out.length >= 20) return out;
    }
  }
  return out;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run test/operations.test.ts`
Expected: PASS. In "empty repo: initializes and retries", the `beforeCommit` hook moves the head the way `GitHubStore`'s README init does. The first commit therefore reports `ref_moved`, and the retry lands as `created`.

- [ ] **Step 5: Commit**

```bash
git add src/operations.ts test/operations.test.ts && git commit -m "feat: memory operations with conflict copies, dedup, secret scan, retries"
```

---

### Task 9: `health.ts` — checks with user actions

**Files:**
- Create: `src/health.ts`
- Test: `test/health.test.ts`

**Interfaces:**
- Consumes: `GitHub`, `GitHubError`, `RECONNECT_ACTION` (Task 6); `ScopeConfig`, `resolveTarget` (Task 5); `OpError` (Task 5); `Props` (Task 1).
- Produces:
  - `interface Check { check: string; status: "ok" | "warn" | "fail"; detail: string; action?: string }`
  - `interface ScopeReach { scope: string; repo: string; reachable: boolean; writable: boolean; reason?: "app_not_installed" | "not_reachable" }`
  - `scopeReachability(gh: GitHub, cfg: ScopeConfig, appSlug: string): Promise<ScopeReach[]>`
  - `runHealth(o: { gh: GitHub; cfg: ScopeConfig; props: Props; appSlug: string; project?: string; now?: number }): Promise<Check[]>`
  - `formatHealth(checks: Check[]): string` gives one line per check: `✓ check — detail` or `⚠/✗ check — detail → action`.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest";
import { GitHub } from "../src/github";
import { formatHealth, runHealth, scopeReachability } from "../src/health";
import { json, mockFetch } from "./setup";

const cfg = { general: "dav/claude-memory", acme: "acme-org/claude-memory" };
const NOW = 1_800_000_000_000;
const props = { login: "dav", githubToken: "ghu_x", githubRefreshToken: "ghr_x", githubTokenExpiresAt: NOW + 6 * 3600_000 };
const RL = { "x-ratelimit-limit": "5000", "x-ratelimit-remaining": "4870", "x-ratelimit-reset": "1800003600" };

function routes(o: { installs?: unknown[]; repos?: Record<number, unknown[]>; user?: number; repoMeta?: Record<string, unknown> } = {}) {
  return [
    { url: "https://api.github.com/user/installations?", respond: () => json({ installations: o.installs ?? [
      { id: 1, account: { login: "dav" } }, { id: 2, account: { login: "acme-org" } } ] }, 200, RL) },
    { url: /\/user\/installations\/(\d+)\/repositories/, respond: (req: Request) => {
      const id = Number(/installations\/(\d+)/.exec(req.url)![1]);
      const repos = o.repos?.[id] ?? (id === 1 ? [{ full_name: "dav/claude-memory", permissions: { push: true } }]
        : [{ full_name: "acme-org/claude-memory", permissions: { push: true } }]);
      return json({ repositories: repos }, 200, RL);
    } },
    { url: "https://api.github.com/user", respond: () => o.user === 401 ? json({ message: "Bad credentials" }, 401) : json({ login: "dav" }, 200, RL) },
  ];
}

const byCheck = (cs: { check: string }[], name: string) => cs.find((c) => c.check === name)!;

describe("runHealth", () => {
  it("all ok", async () => {
    mockFetch(routes());
    const cs = await runHealth({ gh: new GitHub("t"), cfg, props, appSlug: "dav-claude-memory", now: NOW });
    expect(cs.every((c) => c.status === "ok")).toBe(true);
    expect(byCheck(cs, "github_token").detail).toMatch(/expires in 6h/);
    expect(byCheck(cs, "rate_limit").detail).toBe("4870 / 5000 remaining");
  });

  it("revoked token → fail with reconnect action, scopes skipped", async () => {
    mockFetch(routes({ user: 401 }));
    const cs = await runHealth({ gh: new GitHub("t"), cfg, props, appSlug: "s", now: NOW });
    expect(byCheck(cs, "github_token")).toMatchObject({ status: "fail", action: expect.stringContaining("Settings → Connectors") });
    expect(cs.find((c) => c.check.startsWith("scope:"))).toBeUndefined();
  });

  it("token expiring with no refresh token → warn", async () => {
    mockFetch(routes());
    const cs = await runHealth({ gh: new GitHub("t"), cfg, props: { ...props, githubRefreshToken: "", githubTokenExpiresAt: NOW + 10 * 60_000 }, appSlug: "s", now: NOW });
    expect(byCheck(cs, "github_token").status).toBe("warn");
  });

  it("app not installed on the client org → fail with 'ask an owner' + install link", async () => {
    mockFetch(routes({ installs: [{ id: 1, account: { login: "dav" } }] }));
    const cs = await runHealth({ gh: new GitHub("t"), cfg, props, appSlug: "dav-claude-memory", now: NOW });
    expect(byCheck(cs, "scope:acme")).toMatchObject({ status: "fail", detail: expect.stringContaining("app_not_installed") });
    expect(byCheck(cs, "scope:acme").action).toBe(
      "Ask an owner of acme-org to install the app on acme-org/claude-memory: https://github.com/apps/dav-claude-memory/installations/new");
  });

  it("app not installed on own account → install it yourself", async () => {
    mockFetch(routes({ installs: [{ id: 2, account: { login: "acme-org" } }] }));
    const cs = await runHealth({ gh: new GitHub("t"), cfg, props, appSlug: "dav-claude-memory", now: NOW });
    expect(byCheck(cs, "scope:general").action).toMatch(/^Install the GitHub App on dav\/claude-memory: https:\/\/github.com\/apps\/dav-claude-memory\/installations\/new/);
  });

  it("repo not in installation → not_reachable with combined action", async () => {
    mockFetch(routes({ repos: { 2: [] } }));
    const cs = await runHealth({ gh: new GitHub("t"), cfg, props, appSlug: "s", now: NOW });
    const c = byCheck(cs, "scope:acme");
    expect(c).toMatchObject({ status: "fail", detail: expect.stringContaining("not_reachable") });
    expect(c.action).toMatch(/add claude-memory to the app's repositories/);
    expect(c.action).toMatch(/create the private repo/i);
    expect(c.action).toMatch(/add your account/i);
  });

  it("read-only access → warn", async () => {
    mockFetch(routes({ repos: { 2: [{ full_name: "acme-org/claude-memory", permissions: { push: false } }] } }));
    const cs = await runHealth({ gh: new GitHub("t"), cfg, props, appSlug: "s", now: NOW });
    expect(byCheck(cs, "scope:acme")).toMatchObject({ status: "warn", action: expect.stringMatching(/write access/) });
  });

  it("project checks: ok, unconfigured owner, non-GitHub", async () => {
    mockFetch(routes());
    const ok = await runHealth({ gh: new GitHub("t"), cfg, props, appSlug: "s", project: "acme-org/billing", now: NOW });
    expect(byCheck(ok, "project")).toMatchObject({ status: "ok", detail: "acme-org/billing → acme-org/claude-memory/projects/billing/" });
    mockFetch(routes());
    const none = await runHealth({ gh: new GitHub("t"), cfg, props, appSlug: "s", project: "other/x", now: NOW });
    expect(byCheck(none, "project")).toMatchObject({ status: "fail", action: expect.stringContaining("create other/claude-memory") });
  });

  it("low rate limit → warn", async () => {
    mockFetch(routes().map((r) => ({ ...r, respond: async (req: Request) => {
      const res = await r.respond(req);
      return new Response(res.body, { status: res.status, headers: { ...Object.fromEntries(res.headers), "x-ratelimit-remaining": "100" } });
    } })));
    const cs = await runHealth({ gh: new GitHub("t"), cfg, props, appSlug: "s", now: NOW });
    expect(byCheck(cs, "rate_limit").status).toBe("warn");
  });

  it("GitHub 5xx → github_api fail with status-page action", async () => {
    mockFetch([{ url: "https://api.github.com/", respond: () => json({}, 503) }]);
    const cs = await runHealth({ gh: new GitHub("t"), cfg, props, appSlug: "s", now: NOW });
    expect(byCheck(cs, "github_api")).toMatchObject({ status: "fail", action: expect.stringContaining("githubstatus.com") });
  });
});

describe("scopeReachability", () => {
  it("reports per scope", async () => {
    mockFetch(routes({ installs: [{ id: 1, account: { login: "dav" } }] }));
    expect(await scopeReachability(new GitHub("t"), cfg, "s")).toEqual([
      { scope: "general", repo: "dav/claude-memory", reachable: true, writable: true },
      { scope: "acme", repo: "acme-org/claude-memory", reachable: false, writable: false, reason: "app_not_installed" },
    ]);
  });
});

describe("formatHealth", () => {
  it("one line per check with action", () => {
    expect(formatHealth([
      { check: "github_token", status: "ok", detail: "ok (expires in 6h 0m)" },
      { check: "scope:acme", status: "fail", detail: "app_not_installed", action: "Ask an owner…" },
    ])).toBe("✓ github_token — ok (expires in 6h 0m)\n✗ scope:acme — app_not_installed → Ask an owner…");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run test/health.test.ts`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement**

```ts
import type { Props } from "./env";
import { OpError } from "./errors";
import { GitHub, GitHubError, RECONNECT_ACTION } from "./github";
import { resolveTarget, type ScopeConfig } from "./scopes";

export interface Check { check: string; status: "ok" | "warn" | "fail"; detail: string; action?: string }
export interface ScopeReach { scope: string; repo: string; reachable: boolean; writable: boolean; reason?: "app_not_installed" | "not_reachable" }

type Installation = { id: number; account: { login: string } };
type InstRepo = { full_name: string; permissions?: { push?: boolean } };

async function listAll<T>(gh: GitHub, path: string, key: string): Promise<T[]> {
  const out: T[] = [];
  for (let page = 1; page <= 10; page++) {
    const sep = path.includes("?") ? "&" : "?";
    const res = await gh.request<Record<string, T[]>>("GET", `${path}${sep}per_page=100&page=${page}`);
    const items = res[key] ?? [];
    out.push(...items);
    if (items.length < 100) break;
  }
  return out;
}

export async function scopeReachability(gh: GitHub, cfg: ScopeConfig, _appSlug: string): Promise<ScopeReach[]> {
  const installs = await listAll<Installation>(gh, "/user/installations", "installations");
  const reposByInstall = new Map<number, InstRepo[]>();
  const out: ScopeReach[] = [];
  for (const [scope, repo] of Object.entries(cfg)) {
    const owner = repo.split("/")[0]!.toLowerCase();
    const inst = installs.find((i) => i.account.login.toLowerCase() === owner);
    if (!inst) { out.push({ scope, repo, reachable: false, writable: false, reason: "app_not_installed" }); continue; }
    if (!reposByInstall.has(inst.id)) {
      reposByInstall.set(inst.id, await listAll<InstRepo>(gh, `/user/installations/${inst.id}/repositories`, "repositories"));
    }
    const r = reposByInstall.get(inst.id)!.find((x) => x.full_name.toLowerCase() === repo.toLowerCase());
    if (!r) { out.push({ scope, repo, reachable: false, writable: false, reason: "not_reachable" }); continue; }
    out.push({ scope, repo, reachable: true, writable: Boolean(r.permissions?.push) });
  }
  return out;
}

function fmtDuration(ms: number) {
  const m = Math.max(0, Math.round(ms / 60_000));
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

export async function runHealth(o: { gh: GitHub; cfg: ScopeConfig; props: Props; appSlug: string; project?: string; now?: number }): Promise<Check[]> {
  const now = o.now ?? Date.now();
  const install = `https://github.com/apps/${o.appSlug}/installations/new`;
  const checks: Check[] = [];
  try {
    await o.gh.request("GET", "/user");
    const left = o.props.githubTokenExpiresAt - now;
    if (left < 15 * 60_000 && !o.props.githubRefreshToken) {
      checks.push({ check: "github_token", status: "warn", detail: `expires in ${fmtDuration(left)}, no refresh token`,
        action: "Memory sign-in expires soon; reconnect the claude-memory connector in claude.ai Settings → Connectors." });
    } else {
      checks.push({ check: "github_token", status: "ok", detail: `ok (expires in ${fmtDuration(left)})` });
    }
  } catch (e) {
    if (e instanceof GitHubError && e.kind === "unauthorized") {
      checks.push({ check: "github_token", status: "fail", detail: "reauth_required", action: RECONNECT_ACTION });
      return checks;
    }
    checks.push({ check: "github_api", status: "fail", detail: `unavailable (${(e as Error).message})`,
      action: "GitHub is having problems (status page: githubstatus.com). Saves will be queued in the outbox; nothing to do." });
    return checks;
  }

  try {
    for (const r of await scopeReachability(o.gh, o.cfg, o.appSlug)) {
      const [owner] = r.repo.split("/");
      const name = `scope:${r.scope}`;
      if (r.reachable && r.writable) checks.push({ check: name, status: "ok", detail: `ok ${r.repo}` });
      else if (r.reachable) checks.push({ check: name, status: "warn", detail: `read-only ${r.repo}`, action: `Ask an owner of ${owner} for write access to ${r.repo}.` });
      else if (r.reason === "app_not_installed") {
        const own = owner!.toLowerCase() === o.props.login.toLowerCase();
        checks.push({ check: name, status: "fail", detail: `app_not_installed ${r.repo}`, action: own
          ? `Install the GitHub App on ${r.repo}: ${install} → Only select repositories → ${r.repo.split("/")[1]}.`
          : `Ask an owner of ${owner} to install the app on ${r.repo}: ${install}` });
      } else {
        checks.push({ check: name, status: "fail", detail: `not_reachable ${r.repo}`, action:
          `The app is installed on ${owner} but can't see ${r.repo}. Likely fixes, in order: add claude-memory to the app's repositories (${owner} → Settings → GitHub Apps → ${o.appSlug} → Configure); create the private repo ${r.repo} if it doesn't exist; ask an owner of ${owner} to add your account (${o.props.login}) to it.` });
      }
    }
  } catch (e) {
    checks.push({ check: "github_api", status: "fail", detail: `unavailable (${(e as Error).message})`,
      action: "GitHub is having problems (status page: githubstatus.com). Saves will be queued in the outbox; nothing to do." });
  }

  if (o.project) {
    try {
      const t = resolveTarget(o.cfg, "project", o.project);
      checks.push({ check: "project", status: "ok", detail: `${t.scopeLabel.slice(8)} → ${t.repo}/${t.prefix}` });
    } catch (e) {
      const err = e as OpError;
      checks.push({ check: "project", status: "fail", detail: err.code, action: err.action });
    }
  }

  const rl = o.gh.lastRateLimit;
  if (rl) {
    const low = rl.remaining < rl.limit * 0.1;
    const resets = new Date(rl.reset * 1000).toISOString().slice(11, 16);
    checks.push(low
      ? { check: "rate_limit", status: "warn", detail: `${rl.remaining} / ${rl.limit} remaining`,
          action: `GitHub rate limit low (${rl.remaining} left, resets ${resets} UTC). Saves may be queued until then; no action needed.` }
      : { check: "rate_limit", status: "ok", detail: `${rl.remaining} / ${rl.limit} remaining` });
  }
  return checks;
}

export function formatHealth(checks: Check[]): string {
  const icon = { ok: "✓", warn: "⚠", fail: "✗" } as const;
  return checks.map((c) => `${icon[c.status]} ${c.check} — ${c.detail}${c.action ? ` → ${c.action}` : ""}`).join("\n");
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run test/health.test.ts`
Expected: PASS. Note: `mockFetch` matches by `startsWith`, so the route order in `routes()` matters. `/user/installations?` comes before `/user`. Keep that order.

- [ ] **Step 5: Commit**

```bash
git add src/health.ts test/health.test.ts && git commit -m "feat: health checks with user-facing actions"
```

---

### Task 10: `instructions.ts` + `tools.ts` — MCP surface

**Files:**
- Create: `src/instructions.ts`, `src/tools.ts`
- Test: `test/tools.test.ts`

**Interfaces:**
- Consumes: operations (Task 8), health (Task 9), scopes (Task 5), `toOpError` (Task 6), `Store` (Task 7), `GitHub` (Task 6), `Props` (Task 1).
- Produces:
  - `INSTRUCTIONS: string`
  - `interface ToolDeps { store: Store; gh: GitHub; cfg: ScopeConfig; props: Props; appSlug: string; now?: () => Date }`
  - `callTool(deps: ToolDeps, name: string, args: Record<string, unknown>): Promise<{ text: string; isError: boolean; notes?: string }>`. This is the transport-independent dispatcher, and it's what the tests exercise. `notes` carries the "changed since your index" block; `createServer` sends it as a second text content item so `text` stays plain JSON.
  - **`since` map** (spec §6 "Freshness"): `memory_index` ends with a `## Since` section holding a JSON object `{ [scopeLabel]: indexVersion }` for every index it returned (keys like `general`, `acme`, `project:acme-org/billing`). `memory_read`, `memory_search`, `memory_save`, and `memory_delete` accept `since?: Record<string, string>`. When given, the dispatcher re-checks each key after the operation; for any whose version differs it returns that scope's current index plus an updated map in `notes`. Unknown or unresolvable keys are ignored. A failure in this check never fails the tool call.
  - `createServer(deps: ToolDeps): McpServer`. It registers every tool through `callTool`, plus the resource templates.
  - Tool names: `memory_scopes`, `memory_index`, `memory_health`, `memory_read`, `memory_search`, `memory_save`, `memory_delete`.

- [ ] **Step 1: Write the failing test**

```ts
import { beforeEach, describe, expect, it } from "vitest";
import { GitHub } from "../src/github";
import { callTool, createServer, type ToolDeps } from "../src/tools";
import { saveMemory } from "../src/operations";
import { resolveTarget } from "../src/scopes";
import { INSTRUCTIONS } from "../src/instructions";
import { FakeStore } from "./fake-store";
import { json, mockFetch } from "./setup";

const cfg = { general: "dav/mem", acme: "acme-org/claude-memory" };
const props = { login: "dav", githubToken: "t", githubRefreshToken: "r", githubTokenExpiresAt: Date.now() + 8 * 3600_000 };
let deps: ToolDeps;
let store: FakeStore;

function healthyGitHub() {
  mockFetch([
    { url: "https://api.github.com/user/installations?", respond: () => json({ installations: [
      { id: 1, account: { login: "dav" } }, { id: 2, account: { login: "acme-org" } }] }) },
    { url: "https://api.github.com/user/installations/1/repositories", respond: () => json({ repositories: [{ full_name: "dav/mem", permissions: { push: true } }] }) },
    { url: "https://api.github.com/user/installations/2/repositories", respond: () => json({ repositories: [{ full_name: "acme-org/claude-memory", permissions: { push: true } }] }) },
    { url: "https://api.github.com/user", respond: () => json({ login: "dav" }) },
  ]);
}

beforeEach(() => {
  store = new FakeStore();
  store.put("dav/mem", "README.md", "r");
  store.put("acme-org/claude-memory", "README.md", "r");
  deps = { store, gh: new GitHub("t"), cfg, props, appSlug: "dav-claude-memory", now: () => new Date("2026-10-13T18:04:05Z") };
});

const save = (args: Record<string, unknown>) =>
  callTool(deps, "memory_save", { description: "Measure first", type: "feedback", body: "Measure.\n", source: "test", ...args });

describe("callTool", () => {
  it("memory_save defaults scope to general and returns JSON", async () => {
    const r = await save({ name: "a" });
    expect(r.isError).toBe(false);
    expect(JSON.parse(r.text)).toMatchObject({ status: "created", scope: "general" });
  });

  it("memory_save project scope", async () => {
    const r = await save({ name: "b", scope: "project", project: "git@github.com:acme-org/billing.git" });
    expect(JSON.parse(r.text)).toMatchObject({ status: "created", scope: "project billing" });
    expect(store.repo("acme-org/claude-memory").has("projects/billing/memories/b.md")).toBe(true);
  });

  it("memory_index includes health first, then each reachable scope, then the project", async () => {
    await save({ name: "a" });
    healthyGitHub();
    const r = await callTool(deps, "memory_index", { project: "acme-org/billing" });
    const t = r.text;
    expect(t.indexOf("## Health")).toBe(0);
    expect(t).toContain("# Memory index — general");
    expect(t).toContain("[a]");
    expect(t).toContain("# Memory index — project billing\n\n(no memories yet)");
  });

  it("memory_index skips unreachable scopes but reports them in health", async () => {
    mockFetch([
      { url: "https://api.github.com/user/installations?", respond: () => json({ installations: [{ id: 1, account: { login: "dav" } }] }) },
      { url: "https://api.github.com/user/installations/1/repositories", respond: () => json({ repositories: [{ full_name: "dav/mem", permissions: { push: true } }] }) },
      { url: "https://api.github.com/user", respond: () => json({ login: "dav" }) },
    ]);
    const r = await callTool(deps, "memory_index", {});
    expect(r.text).toContain("✗ scope:acme — app_not_installed");
    expect(r.text).not.toContain("# Memory index — acme");
  });

  it("memory_read / memory_search / memory_delete round trip", async () => {
    await save({ name: "a", body: "Deploy on Tuesday.\n" });
    const read = JSON.parse((await callTool(deps, "memory_read", { scope: "general", names: ["a"] })).text);
    expect(read[0].version).toMatch(/^[0-9a-f]{40}$/);
    healthyGitHub(); // memory_search checks scope reachability
    const found = JSON.parse((await callTool(deps, "memory_search", { query: "tuesday" })).text);
    expect(found.map((x: { name: string }) => x.name)).toEqual(["a"]);
    const del = JSON.parse((await callTool(deps, "memory_delete", { scope: "general", name: "a", version: read[0].version, source: "test" })).text);
    expect(del.status).toBe("deleted");
  });

  it("memory_scopes", async () => {
    healthyGitHub();
    const r = JSON.parse((await callTool(deps, "memory_scopes", {})).text);
    expect(r).toEqual([
      { scope: "general", repo: "dav/mem", reachable: true, writable: true },
      { scope: "acme", repo: "acme-org/claude-memory", reachable: true, writable: true },
    ]);
  });

  it("OpErrors become isError results with code and action", async () => {
    const r = await save({ name: "a", scope: "project", project: "someone/x" });
    expect(r.isError).toBe(true);
    expect(JSON.parse(r.text)).toMatchObject({ error: "no_memory_repo_for_owner", action: expect.any(String) });
  });

  it("reauth_required surfaces as retryable error", async () => {
    store.snapshot = async () => { const { GitHubError } = await import("../src/github"); throw new GitHubError("Bad credentials", 401, "unauthorized"); };
    const r = await save({ name: "a" });
    expect(JSON.parse(r.text)).toMatchObject({ error: "reauth_required", retryable: true });
  });

  it("unknown tool", async () => {
    expect((await callTool(deps, "nope", {})).isError).toBe(true);
  });
});

const sinceOf = (indexText: string) =>
  JSON.parse(/## Since\n[^\n]*\n```json\n([\s\S]*?)\n```/.exec(indexText)![1]) as Record<string, string>;

describe("since map", () => {
  it("memory_index ends with a since map covering every returned index", async () => {
    healthyGitHub();
    const since = sinceOf((await callTool(deps, "memory_index", { project: "acme-org/billing" })).text);
    expect(Object.keys(since).sort()).toEqual(["acme", "general", "project:acme-org/billing"]);
    expect(since["project:acme-org/billing"]).toBe("none");
  });

  it("reports scopes changed elsewhere, with a new map; silent when nothing changed", async () => {
    healthyGitHub();
    const since = sinceOf((await callTool(deps, "memory_index", {})).text);
    const quiet = await callTool(deps, "memory_read", { scope: "general", names: ["x"], since });
    expect(quiet.notes).toBeUndefined();

    // another surface saves to general
    await saveMemory(store, resolveTarget(cfg, "general"), { name: "from-elsewhere", description: "deploys freeze on fridays", type: "project", body: "b\n", source: "other" });

    const r = await callTool(deps, "memory_read", { scope: "general", names: ["x"], since });
    expect(JSON.parse(r.text)).toEqual([{ name: "x", error: "not_found" }]); // text stays plain JSON
    expect(r.notes).toContain("Memory changed since your index");
    expect(r.notes).toContain("[from-elsewhere]");
    expect(r.notes).not.toContain("Memory index — acme");
    const next = sinceOf(r.notes!);
    expect(next.general).not.toBe(since.general);
    expect(next.acme).toBe(since.acme);
    expect((await callTool(deps, "memory_read", { scope: "general", names: ["x"], since: next })).notes).toBeUndefined();
  });

  it("ignores unknown keys and survives a failing check", async () => {
    const r = await callTool(deps, "memory_read", { scope: "general", names: ["x"], since: { nope: "abc", "project:someone/x": "none" } });
    expect(r.isError).toBe(false);
    expect(r.notes).toBeUndefined();
  });
});

describe("createServer", () => {
  it("constructs with instructions", () => {
    expect(() => createServer(deps)).not.toThrow();
    expect(INSTRUCTIONS).toContain("memory_index");
    expect(INSTRUCTIONS).toContain("source");
    expect(INSTRUCTIONS).toContain("since");
    expect(INSTRUCTIONS).toContain("summarized");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run test/tools.test.ts`
Expected: FAIL (modules not found)

- [ ] **Step 3: Implement `src/instructions.ts`** (spec §7 C, with the outbox and `source` additions)

```ts
export const INSTRUCTIONS = `claude-memory: the user's persistent memory, shared across all Claude surfaces.

At the start of a conversation, call memory_index. In Claude Code, pass project = the working directory's \`git remote get-url origin\` if there is one. If its Health section shows problems, tell the user one line per problem, including the action given; otherwise say nothing about health. Read individual memories (memory_read) when relevant.

Save lasting facts to one of three scopes: the user (scope "general"), a client org as a whole (its client scope), or one codebase (scope "project" with project = its origin remote). If the scope is unclear, ask in one line. Never save secrets. Prefer updating an existing memory (pass its version from memory_read) over creating a new one; if memory_save returns similar_found or exists, update instead unless the user wants a separate memory.

Always pass source: a short description of where you are running, e.g. "claude-code on <hostname>", "claude-code cloud", "claude.ai chat", "claude mobile".

After every save attempt, end with exactly one of: "saved to <scope>", "queued in outbox for <scope>", or "not saved: <reason>". If a save fails with a retryable error (unavailable, reauth_required) tell the user plainly; in local Claude Code follow the outbox rule in the user's CLAUDE.md; elsewhere there is no outbox, so say the memory was not saved.

If the memory index is no longer in your context (for example after the conversation was summarized), call memory_index again.

memory_index ends with a "Since" map. Pass it as since on every later memory_read, memory_search, memory_save, and memory_delete call. If a result says "Memory changed since your index", treat the index it includes as replacing your copy for that scope, and use its new Since map from then on.

If memory_index lists Conflicts, offer to reconcile them: read both files, save the merged content to the original with its version, then memory_delete the conflict copy (its name is the filename without .md).`;
```

- [ ] **Step 4: Implement `src/tools.ts`**

```ts
import { McpServer, ResourceTemplate } from "@modelcontextprotocol/server";
import { z } from "zod";
import type { Props } from "./env";
import { OpError } from "./errors";
import { GitHub, toOpError } from "./github";
import { formatHealth, runHealth, scopeReachability } from "./health";
import { INSTRUCTIONS } from "./instructions";
import { deleteMemory, getIndex, getIndexVersioned, readMemories, saveMemory, searchMemories } from "./operations";
import { resolveTarget, type ScopeConfig, type Target } from "./scopes";
import type { Store } from "./store";

export interface ToolDeps { store: Store; gh: GitHub; cfg: ScopeConfig; props: Props; appSlug: string; now?: () => Date }

const RETRYABLE = new Set(["reauth_required", "unavailable"]);
const ok = (v: unknown) => ({ text: typeof v === "string" ? v : JSON.stringify(v, null, 2), isError: false });

async function reachableTargets(d: ToolDeps, scopes?: string[]): Promise<{ targets: Target[] }> {
  const reach = await scopeReachability(d.gh, d.cfg, d.appSlug);
  const wanted = scopes ?? Object.keys(d.cfg);
  return { targets: reach.filter((r) => r.reachable && wanted.includes(r.scope)).map((r) => resolveTarget(d.cfg, r.scope)) };
}

const sinceBlock = (m: Record<string, string>) =>
  `## Since\nPass this as since on later memory tool calls:\n\`\`\`json\n${JSON.stringify(m)}\n\`\`\``;

function targetForKey(cfg: ScopeConfig, key: string): Target {
  return key.startsWith("project:") ? resolveTarget(cfg, "project", key.slice("project:".length)) : resolveTarget(cfg, key);
}

// Best effort: returns undefined when nothing changed or the check itself fails.
async function changesSince(d: ToolDeps, since: Record<string, string>): Promise<string | undefined> {
  try {
    const next = { ...since };
    const parts: string[] = [];
    for (const [key, version] of Object.entries(since)) {
      let t: Target;
      try { t = targetForKey(d.cfg, key); } catch { delete next[key]; continue; }
      const cur = await getIndexVersioned(d.store, t);
      if (cur.version !== version) { parts.push(cur.text); next[key] = cur.version; }
    }
    if (!parts.length) return undefined;
    return [`## Memory changed since your index\nThese indexes replace your copies:`, ...parts, sinceBlock(next)].join("\n\n");
  } catch {
    return undefined;
  }
}

export async function callTool(d: ToolDeps, name: string, a: Record<string, unknown>): Promise<{ text: string; isError: boolean; notes?: string }> {
  const r = await dispatch(d, name, a);
  const since = a.since as Record<string, string> | undefined;
  if (name === "memory_index" || !since || typeof since !== "object") return r;
  const notes = await changesSince(d, since);
  return notes ? { ...r, notes } : r;
}

async function dispatch(d: ToolDeps, name: string, a: Record<string, unknown>): Promise<{ text: string; isError: boolean }> {
  const now = d.now?.() ?? new Date();
  const scope = (a.scope as string | undefined) ?? "general";
  const project = a.project as string | undefined;
  try {
    switch (name) {
      case "memory_scopes":
        return ok(await scopeReachability(d.gh, d.cfg, d.appSlug));
      case "memory_health":
        return ok(formatHealth(await runHealth({ gh: d.gh, cfg: d.cfg, props: d.props, appSlug: d.appSlug, project })));
      case "memory_index": {
        const health = await runHealth({ gh: d.gh, cfg: d.cfg, props: d.props, appSlug: d.appSlug, project });
        const parts = [`## Health\n${formatHealth(health)}`];
        const since: Record<string, string> = {};
        const tokenBad = health.some((c) => c.check === "github_token" && c.status === "fail") || health.some((c) => c.check === "github_api");
        if (!tokenBad) {
          const { targets } = await reachableTargets(d, a.scopes as string[] | undefined);
          if (project && health.some((c) => c.check === "project" && c.status === "ok")) {
            targets.push(resolveTarget(d.cfg, "project", project));
          }
          for (const t of targets) {
            const idx = await getIndexVersioned(d.store, t);
            parts.push(idx.text);
            since[t.scopeLabel] = idx.version;
          }
          parts.push(sinceBlock(since));
        }
        return ok(parts.join("\n\n"));
      }
      case "memory_read":
        return ok(await readMemories(d.store, resolveTarget(d.cfg, scope, project), (a.names as string[]).slice(0, 20)));
      case "memory_search": {
        const { targets } = await reachableTargets(d, a.scopes as string[] | undefined);
        if (project) targets.push(resolveTarget(d.cfg, "project", project));
        return ok(await searchMemories(d.store, targets, String(a.query ?? "")));
      }
      case "memory_save":
        return ok(await saveMemory(d.store, resolveTarget(d.cfg, scope, project), {
          name: String(a.name ?? ""), description: String(a.description ?? ""), type: String(a.type ?? ""), body: String(a.body ?? ""),
          version: a.version as string | undefined, force: Boolean(a.force), source: a.source as string | undefined,
        }, now));
      case "memory_delete":
        return ok(await deleteMemory(d.store, resolveTarget(d.cfg, scope, project), String(a.name ?? ""), a.version as string | undefined, a.source as string | undefined, now));
      default:
        return { text: JSON.stringify({ error: "invalid", message: `unknown tool ${name}` }), isError: true };
    }
  } catch (e) {
    const err = e instanceof OpError ? e : toOpError(e);
    return {
      text: JSON.stringify({ error: err.code, message: err.message, action: err.action, retryable: RETRYABLE.has(err.code), retry_after: err.retryAfter }, null, 2),
      isError: true,
    };
  }
}

const scopeArg = z.string().optional().describe('"general", a client scope name, or "project". Default "general".');
const projectArg = z.string().optional().describe("Git origin remote URL or owner/repo. Required when scope is \"project\".");
const sourceArg = z.string().optional().describe('Where you are running, e.g. "claude-code on earsvm", "claude.ai chat".');
const sinceArg = z.record(z.string(), z.string()).optional().describe("The Since map from memory_index (or from the latest change notice).");

export function createServer(d: ToolDeps): McpServer {
  const server = new McpServer({ name: "claude-memory", version: "0.1.0" }, { instructions: INSTRUCTIONS });
  const reg = (name: string, description: string, shape: Record<string, z.ZodType>) =>
    server.registerTool(name, { description, inputSchema: z.object(shape) }, async (args: Record<string, unknown>) => {
      const r = await callTool(d, name, args);
      const content = [{ type: "text" as const, text: r.text }];
      if (r.notes) content.push({ type: "text" as const, text: r.notes });
      return { content, isError: r.isError };
    });

  reg("memory_scopes", "List memory scopes and whether you can reach and write them.", {});
  reg("memory_health", "Check memory health: sign-in, scopes, project, rate limit. Each problem includes an action for the user.", { project: projectArg });
  reg("memory_index", "Call at conversation start. Health, then the MEMORY.md index of each reachable scope and the project.", {
    scopes: z.array(z.string()).optional(), project: projectArg });
  reg("memory_read", "Read memories in full. Returns each memory's version for safe updates.", {
    scope: scopeArg, project: projectArg, names: z.array(z.string()).min(1).max(20), since: sinceArg });
  reg("memory_search", "Search memories (all terms must match) across reachable scopes and the project.", {
    query: z.string().min(1), scopes: z.array(z.string()).optional(), project: projectArg, since: sinceArg });
  reg("memory_save", "Create a memory (no version) or update one (pass version from memory_read).", {
    scope: scopeArg, project: projectArg, name: z.string(), description: z.string(),
    type: z.enum(["user", "feedback", "project", "reference"]), body: z.string(),
    version: z.string().optional(), force: z.boolean().optional(), source: sourceArg, since: sinceArg });
  reg("memory_delete", "Delete a memory or a conflict copy (name = filename without .md). Pass version to avoid deleting a changed memory.", {
    scope: scopeArg, project: projectArg, name: z.string(), version: z.string().optional(), source: sourceArg, since: sinceArg });

  server.registerResource("scope-index", new ResourceTemplate("memory://{scope}/index", { list: undefined }),
    { description: "MEMORY.md index for a scope", mimeType: "text/markdown" },
    async (uri: URL, vars: Record<string, string | string[]>) => ({
      contents: [{ uri: uri.href, mimeType: "text/markdown", text: await getIndex(d.store, resolveTarget(d.cfg, String(vars.scope))) }],
    }));
  server.registerResource("project-index", new ResourceTemplate("memory://project/{owner}/{repo}/index", { list: undefined }),
    { description: "MEMORY.md index for a project", mimeType: "text/markdown" },
    async (uri: URL, vars: Record<string, string | string[]>) => ({
      contents: [{ uri: uri.href, mimeType: "text/markdown", text: await getIndex(d.store, resolveTarget(d.cfg, "project", `${vars.owner}/${vars.repo}`)) }],
    }));
  return server;
}
```

- [ ] **Step 5: Run the test and typecheck**

Run: `npx vitest run test/tools.test.ts && npx tsc --noEmit`
Expected: PASS and no type errors. If `registerTool` or `registerResource` callback types disagree with `@modelcontextprotocol/server@2.3.1`, open `node_modules/@modelcontextprotocol/server/dist/*.d.mts` and adjust **only the callback parameter types**. Keep the tool names, descriptions, and schemas exactly as written.

- [ ] **Step 6: Commit**

```bash
git add src/instructions.ts src/tools.ts test/tools.test.ts && git commit -m "feat: MCP tools, resources, and server instructions"
```

---

### Task 11: `github-auth.ts` + `consent.ts` — sign-in and refresh

**Files:**
- Create: `src/github-auth.ts`, `src/consent.ts`
- Test: covered in `test/auth.test.ts`, which is written in Task 12 because it needs the full Worker. This task has its own unit tests for the pure helpers.
- Test: `test/auth-helpers.test.ts`

**Interfaces:**
- Consumes: `Env`, `Props` (Task 1). Library: `env.OAUTH_PROVIDER` helpers: `parseAuthRequest`, `describeConsent`, `beginConsent`, `approveConsent`, `denyConsent`, `isConsentRemembered`, `beginUpstream`, `finishUpstream`, `completeAuthorization`, and `authorizationErrorRedirect`, `OAuthError` from `@cloudflare/workers-oauth-provider`. Reference: `node_modules/@cloudflare/workers-oauth-provider/docs/upstream-sign-in.md` and `consent-page.md`.
- Produces:
  - `isAllowedRedirect(uri: string): boolean`
  - `s256(verifier: string): Promise<string>`
  - `exchangeCode(env: Env, code: string, verifier: string): Promise<{ accessToken: string; refreshToken: string; expiresIn: number }>`
  - `refreshGitHubToken(env: Env, refreshToken: string): Promise<{ ok: true; accessToken: string; refreshToken: string; expiresIn: number } | { ok: false; revoked: boolean }>`
  - `authHandler: { fetch(request: Request, env: Env): Promise<Response> }`. It handles `GET`/`POST /authorize` and `GET /callback`, and returns 404 for anything else.
  - `tokenExchangeCallback(o: { grantType: string; props: Props; env: Env }): Promise<{ newProps: Props } | void>`
  - `consentPage(details: ConsentDescription, handle: string): string`

- [ ] **Step 1: Write the failing helper tests**

`test/auth-helpers.test.ts`:
```ts
import { env } from "cloudflare:workers";
import { describe, expect, it } from "vitest";
import { exchangeCode, isAllowedRedirect, refreshGitHubToken, s256 } from "../src/github-auth";
import { json, mockFetch } from "./setup";

describe("isAllowedRedirect", () => {
  it.each([
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
    "http://localhost:54321/callback",
    "http://127.0.0.1:8080/oauth/callback",
  ])("allows %s", (u) => expect(isAllowedRedirect(u)).toBe(true));
  it.each([
    "https://evil.example/cb",
    "https://claude.ai.evil.example/api/mcp/auth_callback",
    "https://claude.ai/other",
    "http://claude.ai/api/mcp/auth_callback",
    "https://localhost/cb",
    "not a url",
  ])("rejects %s", (u) => expect(isAllowedRedirect(u)).toBe(false));
});

it("s256 matches RFC 7636 appendix B", async () => {
  expect(await s256("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")).toBe("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM");
});

describe("exchangeCode", () => {
  it("posts code + verifier and parses JSON", async () => {
    const { calls } = mockFetch([{ method: "POST", url: "https://github.com/login/oauth/access_token", respond: () =>
      json({ access_token: "ghu_a", refresh_token: "ghr_a", expires_in: 28800, token_type: "bearer" }) }]);
    expect(await exchangeCode(env, "CODE", "VER")).toEqual({ accessToken: "ghu_a", refreshToken: "ghr_a", expiresIn: 28800 });
    const body = new URLSearchParams(await calls[0]!.text());
    expect(Object.fromEntries(body)).toMatchObject({ client_id: "Iv1.testclient", client_secret: "test-secret", code: "CODE", code_verifier: "VER",
      redirect_uri: "https://memory.test/callback" });
    expect(calls[0]!.headers.get("accept")).toBe("application/json");
  });
  it("throws on a 200 with error field", async () => {
    mockFetch([{ method: "POST", url: "https://github.com/login/oauth/access_token", respond: () => json({ error: "bad_verification_code" }) }]);
    await expect(exchangeCode(env, "C", "V")).rejects.toThrow(/bad_verification_code/);
  });
});

describe("refreshGitHubToken", () => {
  it("ok", async () => {
    mockFetch([{ method: "POST", url: "https://github.com/login/oauth/access_token", respond: () =>
      json({ access_token: "ghu_b", refresh_token: "ghr_b", expires_in: 28800 }) }]);
    expect(await refreshGitHubToken(env, "ghr_a")).toEqual({ ok: true, accessToken: "ghu_b", refreshToken: "ghr_b", expiresIn: 28800 });
  });
  it("revoked", async () => {
    mockFetch([{ method: "POST", url: "https://github.com/login/oauth/access_token", respond: () => json({ error: "bad_refresh_token" }) }]);
    expect(await refreshGitHubToken(env, "x")).toEqual({ ok: false, revoked: true });
  });
  it("outage", async () => {
    mockFetch([{ method: "POST", url: "https://github.com/login/oauth/access_token", respond: () => json({}, 502) }]);
    expect(await refreshGitHubToken(env, "x")).toEqual({ ok: false, revoked: false });
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run test/auth-helpers.test.ts`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement `src/consent.ts`** (adapted from the library's `consent-page.md`)

```ts
import type { ConsentDescription } from "@cloudflare/workers-oauth-provider";

const esc = (v: string) => v.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

export function consentPage(details: ConsentDescription, handle: string): string {
  const name = esc(details.clientName);
  const origin = details.clientDomain
    ? `Published by <strong>${esc(details.clientDomain)}</strong>.`
    : "This app registered itself; its name is not verified.";
  return `<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Allow ${name} to use claude-memory?</title>
<style>body{font:16px system-ui;max-width:32rem;margin:3rem auto;padding:0 1rem}button{font:inherit;padding:.5rem 1rem;margin-right:.5rem}</style>
<h1>Allow ${name} to use your claude-memory?</h1>
<p>${origin} Access will be sent to <strong>${esc(details.redirectHost)}</strong>.</p>
${details.redirectIsLoopback ? "<p><strong>This sends access to an app on your computer.</strong> Continue only if you just started signing in from it.</p>" : ""}
<p>Next you'll approve on GitHub. The server can only reach repositories where you installed the claude-memory GitHub App.</p>
<form method="post">
  <input type="hidden" name="handle" value="${esc(handle)}">
  <button name="decision" value="approve">Allow</button><button name="decision" value="deny">Deny</button>
</form>`;
}
```

- [ ] **Step 4: Implement `src/github-auth.ts`**

```ts
import { authorizationErrorRedirect, OAuthError, type AuthRequest } from "@cloudflare/workers-oauth-provider";
import { consentPage } from "./consent";
import type { Env, Props } from "./env";

const ALLOWED = new Set(["https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback"]);

export function isAllowedRedirect(uri: string): boolean {
  if (ALLOWED.has(uri)) return true;
  try {
    const u = new URL(uri);
    return u.protocol === "http:" && (u.hostname === "localhost" || u.hostname === "127.0.0.1");
  } catch {
    return false;
  }
}

export async function s256(verifier: string): Promise<string> {
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  return btoa(String.fromCharCode(...d)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function tokenRequest(env: Env, params: Record<string, string>) {
  const res = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: { accept: "application/json", "content-type": "application/x-www-form-urlencoded", "user-agent": "claude-memory-cloud" },
    body: new URLSearchParams({ client_id: env.GITHUB_CLIENT_ID, client_secret: env.GITHUB_CLIENT_SECRET, ...params }),
  });
  const data = (res.ok ? await res.json() : {}) as Record<string, unknown>;
  return { res, data };
}

export async function exchangeCode(env: Env, code: string, verifier: string) {
  const { res, data } = await tokenRequest(env, { code, code_verifier: verifier, redirect_uri: `${env.PUBLIC_URL}/callback` });
  if (!res.ok || data.error || !data.access_token) throw new Error(`GitHub code exchange failed: ${String(data.error ?? res.status)}`);
  return { accessToken: String(data.access_token), refreshToken: String(data.refresh_token ?? ""), expiresIn: Number(data.expires_in ?? 28800) };
}

export async function refreshGitHubToken(env: Env, refreshToken: string) {
  const { res, data } = await tokenRequest(env, { grant_type: "refresh_token", refresh_token: refreshToken });
  if (res.ok && data.access_token) {
    return { ok: true as const, accessToken: String(data.access_token), refreshToken: String(data.refresh_token ?? ""), expiresIn: Number(data.expires_in ?? 28800) };
  }
  return { ok: false as const, revoked: res.ok && typeof data.error === "string" };
}

/** Refresh the upstream GitHub token when our refresh grant runs and GitHub's token is within 2h of expiry. */
export async function tokenExchangeCallback(o: { grantType: string; props: Props; env: Env }) {
  if (o.grantType !== "refresh_token") return;
  if (o.props.githubTokenExpiresAt - Date.now() > 2 * 3600_000) return;
  if (!o.props.githubRefreshToken) throw new OAuthError("invalid_grant", { description: "GitHub sign-in expired; reconnect" });
  const r = await refreshGitHubToken(o.env, o.props.githubRefreshToken);
  if (!r.ok && r.revoked) throw new OAuthError("invalid_grant", { description: "GitHub access was revoked" });
  if (!r.ok) throw new OAuthError("temporarily_unavailable", { description: "GitHub is unavailable", statusCode: 503 });
  return { newProps: { ...o.props, githubToken: r.accessToken, githubRefreshToken: r.refreshToken, githubTokenExpiresAt: Date.now() + r.expiresIn * 1000 } };
}

const html = (body: string, status = 400) => new Response(body, { status, headers: { "content-type": "text/html; charset=utf-8" } });

async function startUpstream(env: Env, request: AuthRequest, headers?: Headers) {
  const verifier = crypto.randomUUID() + crypto.randomUUID();
  const up = await env.OAUTH_PROVIDER.beginUpstream(request, { data: { verifier }, headers });
  const gh = new URL("https://github.com/login/oauth/authorize");
  gh.search = new URLSearchParams({
    client_id: env.GITHUB_CLIENT_ID, redirect_uri: `${env.PUBLIC_URL}/callback`, state: up.state,
    code_challenge: await s256(verifier), code_challenge_method: "S256",
  }).toString();
  up.headers.set("Location", gh.toString());
  return new Response(null, { status: 302, headers: up.headers });
}

export const authHandler = {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    const oauth = env.OAUTH_PROVIDER;
    const remember = { secret: env.COOKIE_ENCRYPTION_KEY, maxAgeSeconds: 30 * 86400 };

    if (url.pathname === "/authorize" && req.method === "GET") {
      const request = await oauth.parseAuthRequest(req);
      if (!isAllowedRedirect(request.redirectUri)) return html("<h1>Redirect URI not allowed</h1>");
      if (await oauth.isConsentRemembered(req, request, { secret: env.COOKIE_ENCRYPTION_KEY })) return startUpstream(env, request);
      const details = await oauth.describeConsent(request);
      const consent = await oauth.beginConsent(request);
      consent.headers.set("Content-Type", "text/html; charset=utf-8");
      return new Response(consentPage(details, consent.handle), { headers: consent.headers });
    }

    if (url.pathname === "/authorize" && req.method === "POST") {
      const form = await req.formData();
      const handle = String(form.get("handle"));
      if (form.get("decision") !== "approve") {
        const denied = await oauth.denyConsent(req, handle);
        return new Response(null, { status: 302, headers: denied.headers });
      }
      const approved = await oauth.approveConsent(req, handle, { remember });
      if (!isAllowedRedirect(approved.request.redirectUri)) return html("<h1>Redirect URI not allowed</h1>");
      return startUpstream(env, approved.request, approved.headers);
    }

    if (url.pathname === "/callback" && req.method === "GET") {
      const { request, data, headers } = await oauth.finishUpstream<{ verifier: string }>(req);
      const code = url.searchParams.get("code");
      if (url.searchParams.get("error") || !code) {
        headers.set("Location", authorizationErrorRedirect(request, "access_denied"));
        return new Response(null, { status: 302, headers });
      }
      const tok = await exchangeCode(env, code, data.verifier);
      const userRes = await fetch("https://api.github.com/user", {
        headers: { authorization: `Bearer ${tok.accessToken}`, accept: "application/vnd.github+json", "user-agent": "claude-memory-cloud" },
      });
      if (!userRes.ok) return html("<h1>GitHub sign-in failed</h1>", 502);
      const user = (await userRes.json()) as { login: string; id: number };
      const props: Props = {
        login: user.login, githubToken: tok.accessToken, githubRefreshToken: tok.refreshToken,
        githubTokenExpiresAt: Date.now() + tok.expiresIn * 1000,
      };
      const { redirectTo } = await oauth.completeAuthorization({
        request, userId: String(user.id), metadata: { label: user.login }, scope: request.scope, props,
      });
      headers.set("Location", redirectTo);
      return new Response(null, { status: 302, headers });
    }

    return new Response("not found", { status: 404 });
  },
};
```

- [ ] **Step 5: Run the test and typecheck**

Run: `npx vitest run test/auth-helpers.test.ts && npx tsc --noEmit`
Expected: PASS and no type errors. If an `OAuthHelpers` method name or option shape differs from the code, check `node_modules/@cloudflare/workers-oauth-provider/dist/*.d.ts` and match it, keeping the flow order (consent → beginUpstream → GitHub → finishUpstream → completeAuthorization).

- [ ] **Step 6: Commit**

```bash
git add src/github-auth.ts src/consent.ts test/auth-helpers.test.ts && git commit -m "feat: GitHub App sign-in with consent, PKCE, and token refresh"
```

---

### Task 12: `index.ts` — wiring, host pin, `/health`; full OAuth flow test

**Files:**
- Modify: `src/index.ts` (replace the stub)
- Test: `test/wiring.test.ts`, `test/auth.test.ts`

**Interfaces:**
- Consumes: `authHandler`, `tokenExchangeCallback` (Task 11); `createServer` (Task 10); `GitHubStore` (Task 7); `GitHub` (Task 6); `parseScopes` (Task 5); `Env`, `Props` (Task 1).
- Produces: the Worker default export, plus these routes:
  - `/health`: no auth, returns `{ ok, version, min_hook_version }`
  - `/mcp`: protected
  - `/authorize`, `/callback`
  - `/oauth/token`, `/register`, and `/.well-known/*`, all served by the library

- [ ] **Step 1: Write the failing wiring test**

`test/wiring.test.ts`:
```ts
import { exports } from "cloudflare:workers";
import { describe, expect, it } from "vitest";

describe("worker wiring", () => {
  it("/health is public and versioned", async () => {
    const res = await exports.default.fetch("https://memory.test/health");
    expect(await res.json()).toEqual({ ok: true, version: "0.1.0", min_hook_version: "0.1.0" });
  });

  it("rejects requests for another host (issuer spoofing)", async () => {
    const res = await exports.default.fetch("https://evil.example/health");
    expect(res.status).toBe(421);
  });

  it("/mcp without a token → 401 with resource metadata pointer", async () => {
    const res = await exports.default.fetch("https://memory.test/mcp", { method: "POST", body: "{}" });
    expect(res.status).toBe(401);
    expect(res.headers.get("www-authenticate")).toMatch(/resource_metadata=/);
  });

  it("publishes OAuth metadata", async () => {
    const res = await exports.default.fetch("https://memory.test/.well-known/oauth-authorization-server");
    const md = (await res.json()) as Record<string, unknown>;
    expect(md.authorization_endpoint).toBe("https://memory.test/authorize");
    expect(md.token_endpoint).toBe("https://memory.test/oauth/token");
    expect(md.registration_endpoint).toBe("https://memory.test/register");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run test/wiring.test.ts`
Expected: FAIL (the stub doesn't do host pinning, `/mcp`, or metadata)

- [ ] **Step 3: Implement `src/index.ts`**

```ts
import OAuthProvider from "@cloudflare/workers-oauth-provider";
import { createMcpHandler } from "agents/mcp/server";
import type { Env, Props } from "./env";
import { GitHub } from "./github";
import { authHandler, tokenExchangeCallback } from "./github-auth";
import { parseScopes } from "./scopes";
import { GitHubStore } from "./store";
import { createServer } from "./tools";

/** API handler for /mcp. OAuthProvider calls fetch(request, env, ctx) with ctx.props set (decrypted). */
const mcpApi = {
  async fetch(request: Request, env: Env, ctx: ExecutionContext & { props?: Props }): Promise<Response> {
    const props = ctx.props as Props;
    const gh = new GitHub(props.githubToken);
    const deps = { store: new GitHubStore(gh, env.CACHE_KV), gh, cfg: parseScopes(env.SCOPES), props, appSlug: env.GITHUB_APP_SLUG };
    // createMcpHandler's .fetch takes (request, options); call the handler itself with (request, env, ctx).
    const handler = createMcpHandler(() => createServer(deps), { route: "/mcp" });
    return handler(request, env, ctx);
  },
};

let provider: OAuthProvider<Env> | undefined;
function getProvider(env: Env) {
  provider ??= new OAuthProvider<Env>({
    apiRoute: "/mcp",
    apiHandler: mcpApi as never,
    defaultHandler: authHandler as never,
    authorizeEndpoint: "/authorize",
    tokenEndpoint: "/oauth/token",
    clientRegistrationEndpoint: "/register",
    clientIdMetadataDocumentEnabled: true,
    resourceMetadata: { resource: `${env.PUBLIC_URL}/mcp`, authorization_servers: [env.PUBLIC_URL] },
    scopesSupported: ["memory"],
    tokenExchangeCallback: (o) => tokenExchangeCallback({ grantType: o.grantType, props: o.props as Props, env: o.env as Env }),
  });
  return provider;
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (url.host !== new URL(env.PUBLIC_URL).host) return new Response("misdirected request", { status: 421 });
    if (url.pathname === "/health") {
      return Response.json({ ok: true, version: env.WORKER_VERSION, min_hook_version: env.MIN_HOOK_VERSION });
    }
    return getProvider(env).fetch(request, env, ctx);
  },
};
```

- [ ] **Step 4: Run the wiring test**

Run: `npx vitest run test/wiring.test.ts && npx tsc --noEmit`
Expected: PASS. If `tokenExchangeCallback`'s option object lacks `env`, capture `env` from `getProvider`'s closure instead. If metadata URLs differ (for example, the library serves them at `/.well-known/oauth-authorization-server/mcp`), update the test path to what the library documents in `docs/mcp-discovery.md`.

- [ ] **Step 5: Write the full OAuth flow test.** This is the critical end-to-end check that props reach `/mcp`.

`test/auth.test.ts`:
```ts
import { exports } from "cloudflare:workers";
import { expect, it } from "vitest";
import { s256 } from "../src/github-auth";
import { json, mockFetch } from "./setup";

const BASE = "https://memory.test";
const CB = "https://claude.ai/api/mcp/auth_callback";
const cookieJar = new Map<string, string>();
const storeCookies = (res: Response) => {
  for (const c of res.headers.getSetCookie()) {
    const [kv] = c.split(";");
    const [k, v] = kv!.split("=");
    cookieJar.set(k!, v ?? "");
  }
};
const cookieHeader = () => [...cookieJar].map(([k, v]) => `${k}=${v}`).join("; ");
const go = async (url: string, init: RequestInit = {}) => {
  const res = await exports.default.fetch(url, { redirect: "manual", ...init, headers: { cookie: cookieHeader(), ...(init.headers ?? {}) } });
  storeCookies(res);
  return res;
};

it("register → consent → GitHub → callback → token → tools/list with props", async () => {
  const reg = await go(`${BASE}/register`, { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ client_name: "Claude", redirect_uris: [CB], token_endpoint_auth_method: "none" }) });
  expect(reg.status).toBe(201);
  const { client_id } = (await reg.json()) as { client_id: string };

  const verifier = "v".repeat(50);
  const authUrl = `${BASE}/authorize?` + new URLSearchParams({
    response_type: "code", client_id, redirect_uri: CB, state: "st", scope: "memory",
    code_challenge: await s256(verifier), code_challenge_method: "S256", resource: `${BASE}/mcp`,
  });
  const page = await go(authUrl);
  expect(page.status).toBe(200);
  const handle = /name="handle" value="([^"]+)"/.exec(await page.text())![1]!;

  const approve = await go(`${BASE}/authorize`, { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ handle, decision: "approve" }) });
  expect(approve.status).toBe(302);
  const gh = new URL(approve.headers.get("location")!);
  expect(gh.origin + gh.pathname).toBe("https://github.com/login/oauth/authorize");
  expect(gh.searchParams.get("code_challenge_method")).toBe("S256");
  expect(gh.searchParams.get("redirect_uri")).toBe(`${BASE}/callback`);

  mockFetch([
    { method: "POST", url: "https://github.com/login/oauth/access_token", respond: () =>
      json({ access_token: "ghu_live", refresh_token: "ghr_live", expires_in: 28800 }) },
    { url: "https://api.github.com/user/installations?", respond: () => json({ installations: [] }) },
    { url: "https://api.github.com/user", respond: (req) => {
      expect(req.headers.get("authorization")).toBe("Bearer ghu_live");
      return json({ login: "dav", id: 42 });
    } },
  ]);
  const cb = await go(`${BASE}/callback?code=GHCODE&state=${gh.searchParams.get("state")}`);
  expect(cb.status).toBe(302);
  const back = new URL(cb.headers.get("location")!);
  expect(back.origin + back.pathname).toBe(CB);
  expect(back.searchParams.get("state")).toBe("st");

  const tok = await go(`${BASE}/oauth/token`, { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ grant_type: "authorization_code", code: back.searchParams.get("code")!, redirect_uri: CB,
      client_id, code_verifier: verifier, resource: `${BASE}/mcp` }) });
  expect(tok.status).toBe(200);
  const { access_token } = (await tok.json()) as { access_token: string };

  const call = (body: unknown) => go(`${BASE}/mcp`, { method: "POST", body: JSON.stringify(body), headers: {
    authorization: `Bearer ${access_token}`, "content-type": "application/json",
    accept: "application/json, text/event-stream", "mcp-protocol-version": "2025-06-18" } });

  const init = await call({ jsonrpc: "2.0", id: 1, method: "initialize", params: {
    protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "test", version: "1" } } });
  expect(init.status).toBe(200);
  expect(await init.text()).toContain("memory_index");  // instructions mention it

  const list = await call({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} });
  const text = await list.text();
  for (const t of ["memory_scopes", "memory_index", "memory_health", "memory_read", "memory_search", "memory_save", "memory_delete"]) {
    expect(text).toContain(t);
  }

  // props reached the tool: memory_scopes calls GitHub with the user's token
  const scopes = await call({ jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "memory_scopes", arguments: {} } });
  expect(await scopes.text()).toContain("app_not_installed");
});

it("rejects a disallowed redirect URI before showing consent", async () => {
  const reg = await go(`${BASE}/register`, { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ client_name: "Evil", redirect_uris: ["https://evil.example/cb"], token_endpoint_auth_method: "none" }) });
  const { client_id } = (await reg.json()) as { client_id: string };
  const res = await go(`${BASE}/authorize?` + new URLSearchParams({ response_type: "code", client_id, redirect_uri: "https://evil.example/cb",
    state: "s", code_challenge: await s256("x".repeat(50)), code_challenge_method: "S256", resource: `${BASE}/mcp` }));
  expect(res.status).toBe(400);
  expect(await res.text()).toContain("Redirect URI not allowed");
});
```

- [ ] **Step 6: Run the OAuth flow test**

Run: `npx vitest run test/auth.test.ts`
Expected: PASS. This is the riskiest step; work through failures in this order:
- **401 on `/mcp` with a valid token:** the `resource` mismatch. Make the token request's `resource` equal `resourceMetadata.resource`.
- **Tool calls fail with props undefined:** the wrapper in `mcpApi` isn't receiving `ctx.props`. Log `Object.keys(ctx)` in a scratch test, and read the library's `dist` to see how the API handler is called.
- **Cookies missing between steps:** `__Host-` cookies require `https` URLs, which the test uses. Check that `getSetCookie()` returns values.
- **`initialize` returns 406:** the `accept` header must include both `application/json` and `text/event-stream`.
- **Never** weaken an assertion to make it pass. Fix the wiring instead.

- [ ] **Step 7: Run all tests, then commit**

Run: `npx vitest run && npx tsc --noEmit`
Expected: all PASS

```bash
git add src/index.ts test/wiring.test.ts test/auth.test.ts && git commit -m "feat: worker wiring, host pinning, health endpoint; full OAuth flow test"
```

---

### Task 13: Live GitHub integration tests (store + operations against a real repo)

**Files:**
- Create: `test/integration/github-live.test.ts`

**Interfaces:**
- Consumes: `GitHubStore` (Task 7), `GitHub` (Task 6), operations (Task 8).
- Requires these env vars: `GITHUB_TEST_TOKEN` (a token with contents:write on the test repo; `gh auth token` works, since the store doesn't care what kind of token it is) and `GITHUB_TEST_REPO=dav/claude-memory-test`. Without them, the suite is skipped.

- [ ] **Step 1: Write the test**

```ts
import { env } from "cloudflare:workers";
import { describe, expect, it } from "vitest";
import { GitHub } from "../../src/github";
import { deleteMemory, getIndex, readMemories, saveMemory, searchMemories } from "../../src/operations";
import type { Target } from "../../src/scopes";
import { GitHubStore } from "../../src/store";

const token = (env as unknown as Record<string, string>).GITHUB_TEST_TOKEN;
const repo = (env as unknown as Record<string, string>).GITHUB_TEST_REPO;
const run = token && repo ? describe : describe.skip;

run("live GitHub", () => {
  const stamp = Date.now().toString(36);
  const T: Target = { scopeLabel: "general", displayLabel: "general", repo, prefix: "" };
  const P: Target = { scopeLabel: `project:dav/it-${stamp}`, displayLabel: `project it-${stamp}`, repo, prefix: `projects/it-${stamp}/` };
  const store = () => new GitHubStore(new GitHub(token), env.CACHE_KV);
  const mem = (name: string, body = "live test\n") =>
    ({ name, description: `integration ${name} ${stamp}`, type: "reference", body, source: "integration-test" });

  it("create → read → stale update conflicts → delete, index consistent", { timeout: 60_000 }, async () => {
    const name = `it-${stamp}`;
    expect((await saveMemory(store(), T, mem(name))).status).toBe("created");
    const [r] = await readMemories(store(), T, [name]);
    const version = (r as { version: string }).version;
    expect((await saveMemory(store(), T, { ...mem(name, "v2\n"), version })).status).toBe("updated");
    const stale = await saveMemory(store(), T, { ...mem(name, "v3\n"), version });
    expect(stale.status).toBe("conflict");
    expect(await getIndex(store(), T)).toContain("## Conflicts");
    const cname = stale.conflict_file!.replace(/^memories\//, "").replace(/\.md$/, "");
    expect((await deleteMemory(store(), T, cname, undefined, "integration-test")).status).toBe("deleted");
    const [cur] = await readMemories(store(), T, [name]);
    expect((await deleteMemory(store(), T, name, (cur as { version: string }).version, "integration-test")).status).toBe("deleted");
    expect(await getIndex(store(), T)).not.toContain(name);
  });

  it("concurrent updates with the same version → exactly one updated, one conflict", { timeout: 60_000 }, async () => {
    const name = `race-${stamp}`;
    await saveMemory(store(), T, mem(name));
    const [r] = await readMemories(store(), T, [name]);
    const version = (r as { version: string }).version;
    const results = await Promise.all([
      saveMemory(store(), T, { ...mem(name, "A\n"), version }),
      saveMemory(store(), T, { ...mem(name, "B\n"), version }),
    ]);
    expect(results.map((x) => x.status).sort()).toEqual(["conflict", "updated"]);
  });

  it("concurrent creates of different names → both land in the index", { timeout: 60_000 }, async () => {
    const [a, b] = [`pa-${stamp}`, `pb-${stamp}`];
    const res = await Promise.all([saveMemory(store(), P, mem(a, "alpha unique\n")), saveMemory(store(), P, mem(b, "beta unique\n"))]);
    expect(res.map((x) => x.status)).toEqual(["created", "created"]);
    const idx = await getIndex(store(), P);
    expect(idx).toContain(`[${a}]`);
    expect(idx).toContain(`[${b}]`);
    expect((await searchMemories(store(), [P], "beta unique")).map((x) => x.name)).toEqual([b]);
  });

  it("commits carry trailers", { timeout: 30_000 }, async () => {
    const gh = new GitHub(token);
    const commits = await gh.request<{ commit: { message: string } }[]>("GET", `/repos/${repo}/commits?per_page=5`);
    expect(commits.some((c) => c.commit.message.includes("Memory-Source: integration-test"))).toBe(true);
  });
});
```

- [ ] **Step 2: Run against the real test repo**

Run: `GITHUB_TEST_TOKEN=$(gh auth token) GITHUB_TEST_REPO=dav/claude-memory-test npx vitest run test/integration`
Expected: 4 passed. The first run against an empty repo also exercises the README init path. Then check on github.com that `dav/claude-memory-test` has `README.md`, a coherent `MEMORY.md`, and commits with trailers.

- [ ] **Step 3: Confirm the default run skips it**

Run: `npx vitest run test/integration`
Expected: 4 skipped

- [ ] **Step 4: Commit**

```bash
git add test/integration && git commit -m "test: live GitHub integration for store, conflicts, and races"
```

---

### Task 14: Deploy staging and connect for real

**Files:**
- Modify: `wrangler.jsonc` (KV ids, real `PUBLIC_URL`, app slug)
- Modify: `README.md` (deploy and connect steps)

- [ ] **Step 1: Create the KV namespaces**

```bash
npx wrangler kv namespace create OAUTH_KV
npx wrangler kv namespace create CACHE_KV
```
Paste the printed ids into the top-level `kv_namespaces` in `wrangler.jsonc`. Set `PUBLIC_URL` to `https://claude-memory-staging.<sub>.workers.dev`, and `GITHUB_APP_SLUG` to the slug recorded in Task 0.

- [ ] **Step 2: Set the secrets** (the user pastes the values; never echo them)

```bash
npx wrangler secret put GITHUB_CLIENT_ID
npx wrangler secret put GITHUB_CLIENT_SECRET
npx wrangler secret put COOKIE_ENCRYPTION_KEY
```

- [ ] **Step 3: Deploy and smoke-test**

```bash
npm test && npm run deploy:staging
curl -sS https://claude-memory-staging.<sub>.workers.dev/health
curl -sS -o /dev/null -w '%{http_code}\n' -X POST https://claude-memory-staging.<sub>.workers.dev/mcp
```
Expected: `{"ok":true,"version":"0.1.0","min_hook_version":"0.1.0"}`, then `401`.

- [ ] **Step 4: Connect from Claude Code** (local, separate from claude.ai)

```bash
claude mcp add --transport http claude-memory-staging https://claude-memory-staging.<sub>.workers.dev/mcp
```
Then, in a `claude` session, run `/mcp` → claude-memory-staging → Authenticate. A browser opens: Allow → GitHub approve. Back in the session, ask: "call memory_index with project dav-test-client/sample-app".

Expected:
- The Health section: all ✓, two scopes, and the project mapped to `dav-test-client/claude-memory/projects/sample-app/`.
- Then the indexes.

Then ask for a test save to `general` and confirm the commit on github.com.

- [ ] **Step 5: Connect from claude.ai** at Settings → Connectors → Add custom connector
  - Name: `claude-memory-staging`
  - URL: `https://claude-memory-staging.<sub>.workers.dev/mcp`
  - OAuth: leave at the defaults (CIMD or automatic registration).

  Connect, then Allow, then approve on GitHub. In a new chat, ask "what's in my memory index?" and confirm the same output.
  - Optional: open a cloud Code session to confirm the connector appears there too. Full surface testing is Plan 3.
  - Remove the CLI-added server afterwards (`claude mcp remove claude-memory-staging`) so local sessions use the claude.ai connector, matching the real setup.

- [ ] **Step 6: Watch logs for leaks during a save** (manual check of the no-logging constraint)

Run: `npx wrangler tail claude-memory-staging` while doing one save from claude.ai.
Expected: request lines only, with no memory content and no tokens.

- [ ] **Step 7: Commit**

```bash
git add wrangler.jsonc README.md && git commit -m "chore: staging deployment config"
```

---

### Task 15: Update the spec with the planning deviations

**Files:**
- Modify: `claude-memory-mcp/docs/superpowers/specs/2026-10-13-cloud-memory-design.md`

- [ ] **Step 1: Edit §5 "Commits".** Change the `Memory-Source` source from "MCP initialize clientInfo" to "the optional `source` tool argument (Claude states where it runs); `unknown` if absent". Add the reason: connectors reach all surfaces through claude.ai, and stateless MCP only carries clientInfo on `initialize`.

- [ ] **Step 2: Edit §6 tool table.**
  - Add `source?` to `memory_save` and `memory_delete`.
  - Add the `memory_health` row and the `health` block in `memory_index`, if they aren't already present.

- [ ] **Step 3: Edit §7 F server table.** Replace the separate `no_user_access` and "repo missing" rows with one `not_reachable` row whose action lists the three fixes. Explain that GitHub App user tokens return 404 for all three cases. Keep `app_not_installed` (owner-level), which can be detected.

- [ ] **Step 4: Edit §11.**
  - Mark these items resolved: props encryption (confirmed in 1.2.3: AES-GCM, token-wrapped); clientInfo (replaced by `source`); Cloudflare demo (stale; using oauth-provider 1.2.3's built-in consent and upstream helpers instead).
  - Add: "MCP SDK v2 (`@modelcontextprotocol/server`) and `createMcpHandler`; `McpAgent` deprecated."

- [ ] **Step 5: Commit in `claude-memory-mcp`**

```bash
cd ~/src/claude-memory-mcp && git add docs/superpowers/specs/2026-10-13-cloud-memory-design.md && git commit -m "docs: align cloud memory spec with Plan 1 decisions"
```

---

## Done when

- `npm test` passes in `claude-memory-cloud`. That covers all unit tests, the wiring test, and the full OAuth flow test.
- The live integration suite passes against `dav/claude-memory-test`.
- Staging is deployed. `/health` responds, and `/mcp` returns 401 without a token.
- Both the Claude Code CLI and claude.ai connect via OAuth, `memory_index` shows healthy Health output, and a test save lands as a commit with trailers.
- The spec reflects the deviations.

Next: **Plan 2 (local kit)**.
