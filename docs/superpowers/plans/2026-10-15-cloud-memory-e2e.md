# Cloud Memory End-to-End Tests Implementation Plan (Plan 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the whole system works on every surface (spec §9 Level 4) and that uninstalling really removes it (U1). The pieces:
- a scripted runner, `test/e2e/run.py`, that drives `claude -p` on the Mac and the VMs and checks outcomes in the memory repos with `gh api`
- checklists for the surfaces that can't be scripted
- guarded runs of the scenarios that break things on purpose
- two recorded result grids: layers A + C only, then A + B + C

**Architecture:**
- **`test/e2e/e2elib/`** is a stdlib-only Python package (≥ 3.9), split by job:
  - `transcript.py` parses stream-json
  - `launch.py` runs claude locally or over SSH, with a scrubbed environment
  - `gh.py` checks repo outcomes with `gh api`
  - `checks.py` holds pure pass/fail rules
  - `scenarios.py` defines one function per scenario row
  - `results.py` records verdicts and renders the grid
  - `cleanup.py` removes test data
- **`run.py`** is the CLI.
- **Two-layer testing:**
  - Offline unit tests run with scripted transcripts and fake repos, so no network and no claude are needed.
  - Live runs happen only in the manual tasks (7–11), with the user present.
- **One small kit change:** a `CLAUDE_MEMORY_KIT_PROMPT_HINT=off` switch, so the first live run measures layers A + C without B, as the spec requires.

**Tech Stack:** Python 3.9+ standard library (`json`, `subprocess`, `shlex`, `dataclasses`, `unittest`), `gh` CLI, `ssh`, Claude Code CLI 2.1.300 (`-p --output-format stream-json --verbose`).

**Spec:** `claude-memory-mcp/docs/superpowers/specs/2026-10-13-cloud-memory-design.md`. Read §9 Level 4 (hosts, scenarios S0–S16, verification, fixed prompt set, results), §10 step 6a (U1), §7 D (save announcement strings), §7 E (outbox) and §11 (open items this plan closes).

**Starting point:**
- Repo `~/src/claude-memory-cloud`, branch `main`, head at or after `b0cb0af`. Work on a new branch `plan-3-e2e`.
- Paths are relative to `~/src/claude-memory-cloud` unless prefixed with `claude-memory-mcp/`.
- **Already tested while this plan was written:**
  - Every code block in Tasks 2–6 ran on 2026-10-15: the e2e suite (42 tests) and the kit suite with Task 2's change (163 tests) pass under `/usr/bin/python3` 3.9.6 and Homebrew 3.14.
  - The probes in "Claude Code facts" were real `claude -p` runs on the Mac.
  - The VMs were off, so everything about them is listed under "Not verified" and checked in Task 1.

## Claude Code facts this plan relies on

**Observed on the Mac on 2026-10-15** (Claude Code 2.1.300, probe runs in a scratch directory):

1. **`claude -p … --output-format stream-json --verbose`** writes one JSON object per line:
   - `{"type":"system","subtype":"hook_started"|"hook_response", "hook_name":"SessionStart:startup", "output": "<hook stdout>"}`. For the kit hook, `output` is the `hookSpecificOutput` JSON whose `additionalContext` starts with `Memory project for this session:`.
   - `{"type":"system","subtype":"init","session_id":…,"tools":[…],"mcp_servers":[…],"permissionMode":…}`
   - `{"type":"assistant","message":{"content":[{"type":"tool_use","id","name","input"} | {"type":"text","text"}]}}`
   - `{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id","content","is_error"}]}}`
   - `{"type":"system","subtype":"permission_denied","tool_name":…}` when a tool needed a prompt
   - `{"type":"result","subtype":"success","is_error":false,"result":"<final text>","num_turns",…,"permission_denials":[…]}`
2. **Hooks run in print mode.** SessionStart output arrives as `hook_response` events before `init`.
3. **Environment inherited from a parent Claude Code session breaks the child:**
   - With `ANTHROPIC_API_KEY` set (Claude Code sets it for child processes), the child prints "claude.ai connectors are disabled because ANTHROPIC_API_KEY … takes precedence" and loads **no** claude.ai connectors.
   - Unsetting `ANTHROPIC_*`, `CLAUDECODE`, `CLAUDE_CODE_*`, `CLAUDE_PID` and `CLAUDE_EFFORT` fixed it: `claude.ai claude-memory-staging` loaded.
4. **The Mac has two routes to the server:**
   - The project-scoped MCP server `claude-memory-staging`, in `~/.claude.json` under `/Users/dav/src/claude-memory-cloud` only. Its tools are `mcp__claude-memory-staging__*`.
   - The claude.ai connector, whose tools are `mcp__claude_ai_claude-memory-staging__*`. It is the only route outside that repo.
   - **The kit's read-only allow rules on the Mac cover only the first name.** So in a scratch directory, `memory_index` was denied in `-p` mode ("you haven't granted it yet"). Task 1 re-runs setup with both names.
5. **Permission mode:** a child inherits the user's default mode (`auto` here) unless `--permission-mode default` is passed. In `default` mode in `-p`, a tool without an allow rule is denied, not prompted. The runner always passes `--permission-mode default` plus `--allowedTools <prefix>memory_save` (and `memory_delete` only where a scenario reconciles), so saves don't depend on the auto-mode classifier.
6. **No `timeout` binary on macOS.** The runner uses `subprocess` timeouts. **stdin must be closed** (`</dev/null`), or `-p` waits 3 s and warns "no stdin data received".
7. **`claude --help` lists `--cloud [description|session_id|url]`** ("Create a cloud session … or attach"), plus `--session-id <uuid>`, `--resume`, `--strict-mcp-config` and `--mcp-config <json>`.

**Not verified. Task 1 checks these before anything relies on them:**
- **(V1)** With the scrubbed environment, `claude -p "hi"` on earsvm and lume (over `ssh -o BatchMode=yes`) authenticates, loads the claude.ai connector, and calls `memory_index` with no denial. On lume the login lives in the macOS keychain, which may be locked in a non-interactive SSH session.
- **(V2)** `--strict-mcp-config --mcp-config '{"mcpServers":{}}'` also removes claude.ai connectors (`init.tools` has no `memory_*`). This is the runner's "connector unavailable" (S11, S11c, S11e, U1).
- **(V3)** `--resume <id>` combined with V2's flags drops the memory tools mid-session (S11c).
- **(V4)** `claude -p "/compact" --resume <id>` compacts, and SessionStart fires with `hook_name` `SessionStart:compact` in that run or the next (S14).
- **(V5)** Deleting a memory file by hand (`gh api -X DELETE …/contents/…`) removes it from the next `memory_index`, because the index is rebuilt from the files (build ruling F5).
- **(V6)** The kit hooks see environment variables set on the `claude` process (the A + C switch).
- **(V7)** Whether `claude --cloud` can run one prompt headless and print stream-json (spec §11: "Confirm cloud sessions can be launched from the CLI").

## Decisions

1. **Location `test/e2e/`, not `tests/e2e/`.** The repo's tests live under `test/` (Worker vitest in `test/*.ts`, the kit in `test/local/`). Results go in `test/e2e/results/<date>-<run>.md` (committed). Raw transcripts and the records file go in `test/e2e/results/raw/` (gitignored), because transcripts contain memory content.
2. **Outcome checks, plus fixed protocol strings.**
   - Pass/fail comes from the repos: which repo and path, the `Memory-Scope` and `Memory-Source` trailers, no duplicate, no conflict copy.
   - It also comes from tool-call facts in the transcript: `memory_index` called with the right `project`, no permission denials, `memory_save` result status.
   - The save announcement (§7 D: "saved to <scope>", "queued in outbox for <scope>", "not saved: …") is a fixed protocol string, so checking for it is not checking wording.
   - Nothing else in Claude's prose is checked, except S5's "asks a question" (`?` in the reply, with no `memory_save` call).
3. **Unique tokens.**
   - Every memory a scenario creates carries `e2e-<run_id>-<nn>` (named scenarios use it as the memory name).
   - Cleanup deletes only files touched since the run started whose text contains `e2e-<run_id>-`, conflict copies included, plus outbox entries holding it.
   - Cleanup runs after every scenario, so similar-description checks never see earlier test memories.
   - `run.py cleanup` repeats it after a crash.
4. **Cleanup by hand edit.** Cleanup deletes files with `gh api` (V5). If V5 fails, Task 1 records it, and cleanup runs through Claude instead: a `claude -p` run with `memory_delete` allowed, given the paths. Task 1 Step 6 has that fallback.
5. **"Connector unavailable" means no MCP servers** (V2), not `/mcp` disable (interactive only) and not blocking the Worker (it would also break `/health`, which S11 needs healthy).
6. **The A + C run** sets `CLAUDE_MEMORY_KIT_PROMPT_HINT=off` on every `claude` process. The kit's prompt hook then exits silently (Task 2). Everything else is identical, so the two grids are comparable.
7. **Hosts.**
   - Scripted: H1 (the Mac), H3 (earsvm, `earsvm.local`, Ubuntu 24.04) and H4 (lume, ssh alias `lumevm`, user `lume`).
   - Manual, using `run.py token` and `run.py verify`: H2 (Desktop app), H5 (cloud, unless V7 passes), H6 (web chat) and H7 (mobile).
   - Pairs from the spec: S6 H1→H3 (general) and H4→H1 (project); S9, S11c and S13 run on H1 + H3.
8. **Repeats.** S2, S4 and S5 run 3× per scripted host with different phrasings, and every run must pass (spec). Each phrasing set mixes prompts that match the prompt hook's trigger phrases with prompts that don't. A test enforces that, so the A + C vs A + B + C comparison means something.
9. **S16 is soft.** It never fails the run, and the grid shows `soft ✓` / `soft ✗`. It is also not repeated.
10. **Breaking things on purpose (S10, S12, S15) is always guarded and manual.** The user does every account-side change (uninstall the app, revoke the token, make the repo public). Each local break is undone in the same step, and the restore is checked byte for byte. The runner only checks the outcome (`run.py probe`).
11. **U1 simulates the account side** by loading no MCP servers (V2). A real connector removal would affect every host. The spec's "no memory tool calls attempted" holds only once the connector is gone, which is how U1 runs.

## Deviations from the spec (folded in by Task 12)

1. `tests/e2e/` → `test/e2e/` (Decision 1).
2. S11's "disable the connector with `/mcp`" → load no MCP servers with `--strict-mcp-config` (Decision 5).
3. U1 runs with the connector removed by the same flags (Decision 11).
4. The first run's "A + C only" is done with the kit switch `CLAUDE_MEMORY_KIT_PROMPT_HINT=off` (Decision 6).
5. New soft scenario S16, already added to the spec's table on 2026-10-15.

## Global Constraints

- **Never read, print, or commit `.dev.vars` or `scopes.*.json`.** Never modify the real `~/.claude`, `~/.claude-memory-cloud` or any VM's home outside Tasks 1, 2 (Step 6), 10 and 11, which run with the user. Automated tests never touch the network, `gh`, `ssh` or `claude`.
- **Python:** standard library only. It must run on 3.9.6 (`/usr/bin/python3`). Each module starts with `from __future__ import annotations` (test files excepted). No `match`, no runtime `X | Y`, no `datetime.UTC`.
- **Test repos only.** The runner may write to `davlion/claude-memory-test` (general) and `davlion-test-client/claude-memory` (client), and nowhere else. Never `memory_delete` or hand-delete a file whose text lacks the run's token.
- **Kit:** `HOOK_VERSION = "0.1.1"` after Task 2. The Worker's `MIN_HOOK_VERSION` stays `"0.1.0"`. The switch is exactly `CLAUDE_MEMORY_KIT_PROMPT_HINT=off`.
- **Runner invariants:**
  - Every `claude` run gets `--permission-mode default` and `--output-format stream-json --verbose`, with stdin closed.
  - The environment is scrubbed of `ANTHROPIC_*`, `CLAUDE_CODE_*`, `CLAUDECODE`, `CLAUDE_PID` and `CLAUDE_EFFORT`. On SSH hosts, `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` are unset remotely.
  - `--allowedTools` comes last, because it is variadic.
- **Tests:**
  - e2e: `python3 -m unittest discover -s test/e2e` (also `npm run test:e2e`).
  - kit: `npm run test:local`.
  - Before each commit, run both under `/usr/bin/python3`.
- **Commits:** `git add` with the exact files listed in each task; never `-A`, `-a`, `-am` or `.`. Each commit message ends with a `Co-Authored-By:` trailer naming the model that wrote it. Never push without the user's OK.

## Review Focus

Failure modes the spec implies but no live scenario exercises. Each has a pinning test in the task that owns the code.

1. **A crash or Ctrl-C mid-run must not leave test memories in the repos, or delete real ones.** Cleanup keys on the run token and also removes conflict copies and outbox entries (`test_results.Cleanup`, Task 6). A scenario that raises becomes an `ERROR` row, and cleanup still runs (`guarded()` in `run.py`, Task 6).
2. **A memory tool that silently needs a permission prompt.** In `-p` mode a prompt becomes a denial, and the reply may still look fine. Every save scenario fails on any `memory_*` denial (`checks.no_prompts`, pinned by `test_s1_wrong_project_and_denied_prompt`, Task 5).
3. **A truncated, timed-out or garbled stream** must still parse into a usable transcript, not crash the run (`test_empty_and_truncated_input`, `test_timeout_keeps_partial_output`, Task 3).
4. **Prompts with quotes or newlines over SSH,** such as S16's multi-line list, must reach the remote claude as one argument (`test_ssh_command_quotes_and_keeps_home_expandable`, `test_ssh_multiline_prompt_survives_one_remote_shell`, Task 3).
5. **The parent session's environment leaking into child runs** (fact 3) would quietly drop the connector on the Mac and make every scenario fail for the wrong reason (`test_clean_env_drops_parent_session_variables`, `test_local_run_uses_dir_and_scrubbed_env`, Task 3).

## File Structure

```
claude-memory-cloud/
├── package.json                      # T3: "test:e2e" script
├── .gitignore                        # T3: test/e2e/results/raw/
├── kit/hooks/user_prompt_submit.py   # T2: CLAUDE_MEMORY_KIT_PROMPT_HINT=off switch
├── kit/memory_kit/__init__.py        # T2: HOOK_VERSION 0.1.1
├── test/local/test_prompt_hook.py    # T2: switch test
├── test/local/test_session_hook.py   # T2: version string in the out-of-date test
├── docs/FAQ.md                       # T12: "How is this tested end to end?"
└── test/e2e/
    ├── README.md                     # T6: how to run, hosts, safety
    ├── run.py                        # T6: CLI
    ├── e2e.json                      # T3: repos, scopes, hosts
    ├── prompts.json                  # T3: fixed prompt set (spec §9)
    ├── e2elib/
    │   ├── __init__.py               # T3
    │   ├── transcript.py             # T3: stream-json → Transcript
    │   ├── launch.py                 # T3: Host, Invocation, run_claude, shell
    │   ├── config.py                 # T3: load e2e.json + prompts.json
    │   ├── gh.py                     # T4: gh api wrapper, Found, MEMORY_PATH
    │   ├── checks.py                 # T4: pure checks, Verdict
    │   ├── scenarios.py              # T5: Ctx + one function per scenario
    │   ├── results.py                # T6: records + grid
    │   └── cleanup.py                # T6
    ├── fakes.py                      # T5: FakeClaude, FakeGh, FakeShell, stream()
    ├── fixtures/save-general.jsonl   # T3
    ├── test_transcript.py            # T3
    ├── test_launch.py                # T3
    ├── test_config.py                # T3
    ├── test_gh.py                    # T4
    ├── test_scenarios.py             # T5
    ├── test_results.py               # T6
    └── results/<date>-<run>.md       # T7–T11 (committed); results/raw/ gitignored
```

**Spec coverage map:**

| Spec item | Task |
|---|---|
| §9 L4 prerequisites (test org, sample-app clones, connector, auto-memory off, VMs) | T1 |
| Scripted hosts H1, H3, H4 | T3, T7, T8 |
| Manual hosts H2, H5 (unless V7), H6, H7 | T9 |
| S0, S1, S2, S3, S4, S4n, S5, S7, S8, S11, S11b, S11e, S11f, S12h, S14, S16 | T5, T7, T8 |
| S6, S9, S11c, S13 (two hosts) | T5, T8 |
| S10, S12 (all items), S15 | T10 |
| S11d (cloud and chat) | T9 |
| Verification by `gh api`; outcomes, not wording; 3× routing prompts | T4, T5, T6 |
| Fixed prompt set `prompts.json`; first run A + C, second A + B + C | T3, T2, T7, T8 |
| Results grid per run | T6, T7–T11 |
| §10 6a U1 | T11 |
| §11 open items: CLI cloud launch, auto-memory off removes the instruction (S0), env var in cloud (S0 on H5), similarity threshold (observed in runs) | T1, T7–T9, T12 |

---

### Task 1: Verify the unverified facts and prepare the hosts (manual, with the user)

No code. The VMs must be running, so ask the user to start earsvm and lume first. Record every answer in `docs/plan-3/build-ledger.md` (created here, committed in Task 12). Stop at the first V-check that fails and agree the fallback with the user.

Use this probe helper for every V-check. It runs claude with the runner's environment, then summarizes the stream. Keep it in the scratchpad; it is not committed.

```bash
cat > "$SCRATCH/probe.sh" <<'EOF'
#!/bin/sh
# usage: probe.sh <dir> <prompt> [claude args...]   (run on the host itself; prints event summary)
d=$1; p=$2; shift 2
cd "$d" && env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT \
  -u CLAUDE_CODE_SESSION_ID -u CLAUDE_PID -u CLAUDE_EFFORT \
  "$HOME/.local/bin/claude" -p "$p" --output-format stream-json --verbose --permission-mode default "$@" </dev/null \
  | /usr/bin/python3 -c '
import json,sys
for l in sys.stdin:
    try: e=json.loads(l)
    except ValueError: continue
    t,s=e.get("type"),e.get("subtype")
    if t=="system" and s=="init": print("init memory tools:",[x for x in e["tools"] if "memory_" in x])
    elif t=="system" and s=="hook_response": print("hook",e.get("hook_name"),"kit" if "Memory project" in e.get("output","") else "")
    elif t=="system" and s=="permission_denied": print("DENIED",e.get("tool_name"))
    elif t=="assistant":
        for c in e["message"]["content"]:
            if c["type"]=="tool_use": print("tool",c["name"],json.dumps(c["input"])[:120])
    elif t=="result": print("result",s,"session",e.get("session_id"))'
EOF
chmod +x "$SCRATCH/probe.sh"
```

- [ ] **Step 1: Prerequisites on each host** (the user starts the VMs)

```bash
for h in earsvm.local lumevm; do ssh -o BatchMode=yes -o ConnectTimeout=10 "$h" 'echo "== $(hostname)"; ~/.local/bin/claude --version; /usr/bin/python3 --version; ls ~/src'; done
gh api repos/davlion-test-client/sample-app --jq .private; gh api repos/davlion-test-client/claude-memory --jq .private; gh api repos/davlion/claude-memory-test --jq .private
```
Expected: per VM, a claude version and Python ≥ 3.9. All three repos print `true`. If a VM's claude is older than the Mac's (2.1.300), ask the user to update it first (`claude update`).

- [ ] **Step 2: Clone `sample-app` and make the no-remote directory** (on the Mac and both VMs; the user OKs each)

```bash
git -C ~/src clone git@github.com:davlion-test-client/sample-app.git 2>/dev/null || git -C ~/src/sample-app pull --ff-only
mkdir -p ~/e2e-no-remote && git -C ~/e2e-no-remote init -q && git -C ~/e2e-no-remote remote -v   # must print nothing
for h in earsvm.local lumevm; do ssh "$h" 'git -C ~/src clone git@github.com:davlion-test-client/sample-app.git 2>/dev/null || git -C ~/src/sample-app pull --ff-only; mkdir -p ~/e2e-no-remote && git -C ~/e2e-no-remote init -q; git -C ~/src/sample-app remote get-url origin'; done
```
Expected: every host prints `git@github.com:davlion-test-client/sample-app.git`. If a VM can't clone (no GitHub SSH key there), use `https://github.com/davlion-test-client/sample-app.git` with `gh auth` on that VM, or ask the user.

- [ ] **Step 3: Fix the Mac's allow rules for the claude.ai connector** (fact 4; guarded like Plan 2 Task 13: dry run, user approves, install)

```bash
cd ~/src/claude-memory-cloud
./setup.sh --worker-url https://claude-memory-staging.david-lion.workers.dev --scopes-file scopes.staging.json --login davlion \
  --mcp-server claude-memory-staging --mcp-server claude_ai_claude-memory-staging --dry-run
```
Expected: the diff adds only the three read-only `mcp__claude_ai_claude-memory-staging__memory_{index,read,search}` allow rules. The user approves, then run it again without `--dry-run`.

- [ ] **Step 4: V1 — the connector loads with no prompt, on every host**

```bash
"$SCRATCH/probe.sh" ~/src/sample-app hi
for h in earsvm.local lumevm; do scp -q "$SCRATCH/probe.sh" "$h":/tmp/probe.sh; ssh -o BatchMode=yes "$h" 'sh /tmp/probe.sh ~/src/sample-app hi'; done
```
Expected on each host:
- `init memory tools:` lists `mcp__claude_ai_claude-memory-staging__memory_*`
- a `hook SessionStart:startup kit` line
- `tool mcp__claude_ai_claude-memory-staging__memory_index {"project": "davlion-test-client/sample-app"}`
- no `DENIED`

If lume fails to authenticate over SSH (keychain), ask the user to run `security unlock-keychain` in an SSH session, or log in on the VM's console. If neither works, mark H4 as manual in `e2e.json` (Task 3) and record it.

- [ ] **Step 5: V2, V3, V4, V6**

```bash
cd ~/src/sample-app
"$SCRATCH/probe.sh" . hi --strict-mcp-config --mcp-config '{"mcpServers":{}}'                       # V2: no memory tools
SID=$(uuidgen | tr A-Z a-z); "$SCRATCH/probe.sh" . "say ok" --session-id "$SID"
"$SCRATCH/probe.sh" . "list your memory tools" --resume "$SID" --strict-mcp-config --mcp-config '{"mcpServers":{}}'   # V3
"$SCRATCH/probe.sh" . "/compact" --resume "$SID"; "$SCRATCH/probe.sh" . "say ok" --resume "$SID"                     # V4
CLAUDE_MEMORY_KIT_PROMPT_HINT=off sh -c 'env | grep -c CLAUDE_MEMORY_KIT_PROMPT_HINT'   # sanity
```
Expected:
- **V2:** `init memory tools: []`.
- **V3:** the resumed run also shows `[]`.
- **V4:** the `/compact` run, or the run after it, shows `hook SessionStart:compact kit`.
- **V6:** checked in Task 2 Step 6, after the switch exists.

If V4 shows no compact hook, S14 becomes manual on H1 (interactive `/compact`); record it.

- [ ] **Step 6: V5 — a hand delete leaves the index**

In a probe session, have Claude save `e2e-v5-probe` (general) with `memory_save` allowed:
```bash
"$SCRATCH/probe.sh" ~/src/sample-app 'Save a general memory named e2e-v5-probe with description "e2e v5 probe" and body "v5 e2e-v5-probe"' --allowedTools mcp__claude_ai_claude-memory-staging__memory_save
```
Then delete the file by hand and check the index:
```bash
SHA=$(gh api repos/davlion/claude-memory-test/contents/memories/e2e-v5-probe.md --jq .sha)
gh api -X DELETE repos/davlion/claude-memory-test/contents/memories/e2e-v5-probe.md -f message="e2e v5 probe cleanup" -f sha="$SHA"
"$SCRATCH/probe.sh" ~/src/sample-app hi | grep -c e2e-v5-probe     # must print 0
```
If the name still shows: V5 fails. Change `cleanup.py` in Task 6 so that, instead of `gh.delete`, it collects the paths and runs one `claude -p` on H1 with `memory_delete` allowed: "Delete these memories: …". Record the decision as a ruling.

- [ ] **Step 7: V7 — cloud from the CLI** (spec §11 open item)

```bash
claude --cloud "e2e probe" -p "hi" --output-format stream-json --verbose </dev/null | head -5
```
Record what happens. If it returns stream-json with a `memory_index` tool call, add H5 as a scripted host in Task 3's `e2e.json` with `"ssh": null`. The launcher would then need a `cloud: true` flag; add it as one more `Invocation` field in Task 3 and a unit test for the argv. Otherwise H5 stays manual (Task 9). Either way, close the spec §11 item in Task 12.

No commit.

---

### Task 2: Kit — the prompt-hint switch (layers A + C run)

**Files:**
- Modify: `kit/hooks/user_prompt_submit.py` (in `main()`, after the `CLAUDE_CODE_REMOTE` check)
- Modify: `kit/memory_kit/__init__.py:6` (`HOOK_VERSION`)
- Modify: `test/local/test_prompt_hook.py` (new test before `test_client_org_repo`)
- Modify: `test/local/test_session_hook.py:161` (version in the expected text)

**Interfaces:**
- Produces: the environment switch `CLAUDE_MEMORY_KIT_PROMPT_HINT=off`, which the runner sets for the A + C run (`run.py`, Task 6). `HOOK_VERSION = "0.1.1"`.

- [ ] **Step 1: Write the failing test** — in `test/local/test_prompt_hook.py`, insert before `def test_client_org_repo(self):`

```python
    def test_prompt_hint_switch_off_outputs_nothing(self):
        d = make_git_dir(self.tmp, "r", "git@github.com:acme-org/billing.git")
        self.env["CLAUDE_MEMORY_KIT_PROMPT_HINT"] = "off"
        self.assertEqual(self.ctx("save a memory: x", d)[0], "")
        self.env["CLAUDE_MEMORY_KIT_PROMPT_HINT"] = "on"
        self.assertIn("claude-memory: this looks like a request", self.ctx("save a memory: x", d)[0])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s test/local -p test_prompt_hook.py`
Expected: FAIL in `test_prompt_hint_switch_off_outputs_nothing` (the hint is still printed).

- [ ] **Step 3: Implement** — in `kit/hooks/user_prompt_submit.py` replace

```python
    if os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        return 0
    try:
```
with
```python
    if os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        return 0
    if os.environ.get("CLAUDE_MEMORY_KIT_PROMPT_HINT") == "off":   # Level 4's layers A + C run (spec §9)
        return 0
    try:
```
In `kit/memory_kit/__init__.py` set `HOOK_VERSION = "0.1.1"` (Plan 2 Decision 8: bump on every hook change). In `test/local/test_session_hook.py:161` change `installed 0.1.0` to `installed 0.1.1`.

- [ ] **Step 4: Run the kit suite on both interpreters**

Run: `npm run test:local && /usr/bin/python3 -m unittest discover -s test/local`
Expected: `Ran 163 tests … OK` twice.

- [ ] **Step 5: Commit**

```bash
git checkout -b plan-3-e2e
git add kit/hooks/user_prompt_submit.py kit/memory_kit/__init__.py test/local/test_prompt_hook.py test/local/test_session_hook.py
git commit -m "feat(kit): CLAUDE_MEMORY_KIT_PROMPT_HINT=off silences the prompt hook (Level 4 A+C run); hook 0.1.1"
```

- [ ] **Step 6: Redeploy the kit to the hosts, then check V6** (user OKs each host; same setup commands as Plan 2, and on the Mac the command from Task 1 Step 3)

```bash
for h in earsvm.local lumevm; do rsync -a --delete --exclude node_modules --exclude '.dev.vars*' --exclude .wrangler --exclude 'scopes.*.json' --exclude test/e2e/results ~/src/claude-memory-cloud/ "$h":src/claude-memory-cloud/; done
```
Then re-run setup on each host with its recorded arguments, and check V6 on the Mac:
```bash
cd ~/src/sample-app && CLAUDE_MEMORY_KIT_PROMPT_HINT=off "$SCRATCH/probe.sh" . "remember this: probe only, do not save" | grep -c 'hook UserPromptSubmit'
```
Expected: the UserPromptSubmit `hook_response` from the kit is empty (no "claude-memory: this looks like a request"). Without the variable, it carries the hint. If the variable doesn't reach the hook (V6 fails), stop: the A + C run needs another approach. One option is temporarily removing the kit's UserPromptSubmit group with the user. Agree it with the user.

---

### Task 3: e2e scaffold — config, launcher, transcript parser

**Files:**
- Create: `test/e2e/e2elib/__init__.py`, `test/e2e/e2elib/transcript.py`, `test/e2e/e2elib/launch.py`, `test/e2e/e2elib/config.py`
- Create: `test/e2e/e2e.json`, `test/e2e/prompts.json`, `test/e2e/fixtures/save-general.jsonl`
- Create: `test/e2e/test_transcript.py`, `test/e2e/test_launch.py`, `test/e2e/test_config.py`
- Modify: `package.json` (script), `.gitignore`

**Interfaces:**
- Produces:
  - `transcript.parse(lines) -> Transcript`. `Transcript` has `.session_id`, `.tools`, `.hooks: List[Hook(name, context)]`, `.calls: List[ToolCall]`, `.texts`, `.denials`, `.final`, `.bad_lines`, plus `.memory_calls(short=None)`, `.kit_context(hook_prefix="SessionStart")`, `.final_text` and `.succeeded`.
  - `ToolCall(id, name, input, result, is_error)` with `.short` and `.status`.
  - `launch.Host(id, label, ssh, claude, python, mcp_prefixes, dirs)`.
  - `launch.Invocation(prompt, cwd, allow=(), max_turns=12, session_id=None, resume=None, no_connector=False, env={}, timeout=420.0)`.
  - `launch.run_claude(host, inv, exec_=…) -> RunResult(transcript, returncode, stdout, stderr, timed_out)`.
  - `launch.shell(host, script, exec_=…, timeout=60.0) -> str` (raises RuntimeError).
  - `launch.clean_env`, `launch.claude_args`, `launch.command`.
  - `config.load(config_path=…, prompts_path=…) -> Config(general_repo, client_repo, client_scope, sample_project, kit_project, repeats, hosts, prompts)` with `.repos`.

- [ ] **Step 1: Write the fixture** — `test/e2e/fixtures/save-general.jsonl`. It has the same event shapes as fact 1, made synthetic so it carries no real memory content. Its last line is deliberately not JSON.

```
{"type": "system", "subtype": "hook_started", "hook_name": "SessionStart:startup", "session_id": "s-1"}
{"type": "system", "subtype": "hook_response", "hook_name": "SessionStart:startup", "output": "Session status updated.\n", "exit_code": 0}
{"type": "system", "subtype": "hook_response", "hook_name": "SessionStart:startup", "output": "{\"hookSpecificOutput\": {\"hookEventName\": \"SessionStart\", \"additionalContext\": \"Memory project for this session: davlion-test-client/sample-app\\n\\n<memory-snapshot key=\\\"x\\\" as_of=\\\"t\\\">old</memory-snapshot>\"}}", "exit_code": 0}
{"type": "system", "subtype": "init", "session_id": "s-1", "tools": ["Bash", "mcp__claude_ai_claude-memory-staging__memory_index", "mcp__claude_ai_claude-memory-staging__memory_save"], "mcp_servers": []}
{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "mcp__claude_ai_claude-memory-staging__memory_index", "input": {"project": "davlion-test-client/sample-app"}}]}}
{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "claude-memory response.\n<memory-index scope=\"general\">- [old-one](memories/old-one.md)</memory-index:abc>"}]}]}}
{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t2", "name": "mcp__claude_ai_claude-memory-staging__memory_save", "input": {"scope": "general", "name": "imperative-commits"}}]}}
{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "content": "claude-memory response.\n\n{\n  \"status\": \"created\",\n  \"name\": \"imperative-commits\"\n}"}]}}
{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t3", "name": "mcp__claude_ai_claude-memory-staging__memory_save", "input": {"scope": "general", "name": "x"}}]}}
{"type": "system", "subtype": "permission_denied", "tool_name": "mcp__claude_ai_claude-memory-staging__memory_delete"}
{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t3", "is_error": true, "content": "ECONNRESET: The socket connection was closed unexpectedly."}]}}
{"type": "assistant", "message": {"content": [{"type": "text", "text": "Done. saved to general"}]}}
{"type": "result", "subtype": "success", "is_error": false, "result": "Done. saved to general", "session_id": "s-1"}
not json
```

- [ ] **Step 2: Write the failing tests** — `test/e2e/test_transcript.py`

```python
"""The stream-json parser, against a recorded-shape fixture."""
import unittest
from pathlib import Path

from e2elib.transcript import parse

FIX = Path(__file__).resolve().parent / "fixtures"


class Parse(unittest.TestCase):
    def setUp(self):
        self.t = parse((FIX / "save-general.jsonl").read_text().splitlines())

    def test_session_tools_and_bad_lines(self):
        self.assertEqual(self.t.session_id, "s-1")
        self.assertIn("mcp__claude_ai_claude-memory-staging__memory_save", self.t.tools)
        self.assertEqual(self.t.bad_lines, 1)

    def test_kit_context_is_the_additional_context_of_the_kit_hook(self):
        ctx = self.t.kit_context()
        self.assertTrue(ctx.startswith("Memory project for this session: davlion-test-client/sample-app"))
        self.assertNotIn("Session status updated", ctx)

    def test_memory_calls_results_and_status(self):
        idx = self.t.memory_calls("memory_index")[0]
        self.assertEqual(idx.input, {"project": "davlion-test-client/sample-app"})
        self.assertIn("old-one", idx.result)
        saves = self.t.memory_calls("memory_save")
        self.assertEqual([s.status for s in saves], ["created", None])
        self.assertTrue(saves[1].is_error)
        self.assertEqual(saves[0].short, "memory_save")

    def test_denials_and_final(self):
        self.assertEqual(self.t.denials, ["mcp__claude_ai_claude-memory-staging__memory_delete"])
        self.assertEqual(self.t.final_text, "Done. saved to general")
        self.assertTrue(self.t.succeeded)

    def test_empty_and_truncated_input(self):
        t = parse(["", '{"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}}', '{"type": "res'])
        self.assertEqual(t.final_text, "hi")
        self.assertFalse(t.succeeded)
        self.assertEqual(t.bad_lines, 1)


if __name__ == "__main__":
    unittest.main()
```

`test/e2e/test_launch.py`

```python
"""Command building and environment scrubbing for local and SSH hosts."""
import subprocess
import unittest

from e2elib.launch import Host, Invocation, claude_args, clean_env, command, run_claude, shell

MAC = Host("H1", "Mac CLI", None, "~/.local/bin/claude", "/usr/bin/python3",
           ["mcp__a__", "mcp__b__"], {"sample_app": "~/src/sample-app"})
VM = Host("H3", "earsvm", "earsvm.local", "~/.local/bin/claude", "/usr/bin/python3",
          ["mcp__a__"], {"sample_app": "~/src/sample app"})


class Args(unittest.TestCase):
    def test_prompt_first_allowed_tools_last(self):
        a = claude_args(MAC, Invocation("hi there", "sample_app", allow=("memory_save",), session_id="u1"))
        self.assertEqual(a[:2], ["-p", "hi there"])
        self.assertEqual(a[a.index("--permission-mode") + 1], "default")
        self.assertEqual(a[a.index("--session-id") + 1], "u1")
        self.assertEqual(a[-3:], ["--allowedTools", "mcp__a__memory_save", "mcp__b__memory_save"])

    def test_no_connector_loads_no_mcp_servers(self):
        a = claude_args(MAC, Invocation("hi", "sample_app", no_connector=True, resume="u2"))
        self.assertIn("--strict-mcp-config", a)
        self.assertEqual(a[a.index("--mcp-config") + 1], '{"mcpServers":{}}')
        self.assertEqual(a[a.index("--resume") + 1], "u2")
        self.assertNotIn("--allowedTools", a)

    def test_clean_env_drops_parent_session_variables(self):
        env = clean_env({"PATH": "/bin", "ANTHROPIC_API_KEY": "k", "CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli",
                         "CLAUDE_PID": "9", "HOME": "/h"}, {"CLAUDE_MEMORY_KIT_PROMPT_HINT": "off"})
        self.assertEqual(env, {"PATH": "/bin", "HOME": "/h", "CLAUDE_MEMORY_KIT_PROMPT_HINT": "off"})

    def test_local_command_expands_claude_path(self):
        argv = command(MAC, Invocation("hi", "sample_app"))
        self.assertTrue(argv[0].endswith("/.local/bin/claude") and not argv[0].startswith("~"))

    def test_ssh_command_quotes_and_keeps_home_expandable(self):
        argv = command(VM, Invocation("it's me", "sample_app", env={"X": "a b"}))
        self.assertEqual(argv[:5], ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"])
        remote = argv[-1]
        self.assertTrue(remote.startswith("cd \"$HOME\"/'src/sample app' && env -u ANTHROPIC_API_KEY"))
        self.assertIn("X='a b'", remote)
        self.assertIn("'it'\"'\"'s me'", remote)
        self.assertTrue(remote.endswith("</dev/null"))

    def test_ssh_multiline_prompt_survives_one_remote_shell(self):
        import shlex
        remote = command(VM, Invocation("save these:\n- a\n- b", "sample_app"))[-1]
        words = shlex.split(remote.split(" && ", 1)[1].replace('"$HOME"/', "/h/"))
        self.assertEqual(words[words.index("-p") + 1], "save these:\n- a\n- b")


class Running(unittest.TestCase):
    def test_timeout_keeps_partial_output(self):
        def exec_(argv, cwd, env, timeout):
            raise subprocess.TimeoutExpired(argv, timeout, output='{"type":"system","subtype":"init","session_id":"z"}\n')
        r = run_claude(MAC, Invocation("hi", "sample_app"), exec_)
        self.assertTrue(r.timed_out)
        self.assertEqual(r.transcript.session_id, "z")

    def test_local_run_uses_dir_and_scrubbed_env(self):
        seen = {}

        def exec_(argv, cwd, env, timeout):
            seen.update(cwd=cwd, env=env)
            return subprocess.CompletedProcess(argv, 0, "", "")
        run_claude(MAC, Invocation("hi", "sample_app", env={"K": "v"}), exec_)
        self.assertTrue(seen["cwd"].endswith("/src/sample-app"))
        self.assertEqual(seen["env"]["K"], "v")
        self.assertFalse(any(k.startswith("CLAUDE_CODE_") for k in seen["env"]))

    def test_shell_raises_on_failure(self):
        def exec_(argv, cwd, env, timeout):
            return subprocess.CompletedProcess(argv, 2, "", "boom")
        with self.assertRaisesRegex(RuntimeError, "exited 2: boom"):
            shell(VM, "false", exec_)


if __name__ == "__main__":
    unittest.main()
```

`test/e2e/test_config.py`

```python
"""The committed e2e.json and prompts.json load and fit the scenarios."""
import string
import unittest

from e2elib import config

FIELDS = {"S2": {"token"}, "S3": {"token"}, "S4": {"token"}, "S4n": {"token"}, "S5": {"token"}, "S8": {"token", "secret"},
          "S16": {"facts"}, "named_save": {"name", "body"}, "named_read": {"name"}, "named_update": {"name", "body"},
          "named_read_update": {"name", "body"}, "named_search": {"name"}, "reconcile_yes": set(), "U1": {"token"}}


class Files(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load()

    def test_hosts_have_the_dirs_scenarios_use(self):
        self.assertEqual(sorted(self.cfg.hosts), ["H1", "H3", "H4"])
        for h in self.cfg.hosts.values():
            self.assertEqual(sorted(h.dirs), ["kit_repo", "no_remote", "sample_app"])
            self.assertTrue(all(p.startswith("mcp__") and p.endswith("__") for p in h.mcp_prefixes))
        self.assertIsNone(self.cfg.hosts["H1"].ssh)

    def test_every_prompt_uses_exactly_its_fields(self):
        for key, fields in FIELDS.items():
            for p in self.cfg.prompts[key]:
                with self.subTest(key=key, p=p[:30]):
                    used = {f for _, f, _, _ in string.Formatter().parse(p) if f}
                    self.assertEqual(used, fields)

    def test_routing_prompts_have_three_or_more_runs_worth(self):
        self.assertEqual(self.cfg.repeats, 3)
        for key in ("S2", "S4", "S5"):   # scenarios.REPEATED (Task 5)
            self.assertGreaterEqual(len(self.cfg.prompts[key]), 3)
        self.assertEqual(len(self.cfg.prompts["S16_facts"]), 8)

    def test_some_routing_prompts_avoid_the_hook_triggers(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "kit"))
        from memory_kit.prompt import is_memory_intent
        for key in ("S2", "S4"):
            hits = [is_memory_intent(p) for p in self.cfg.prompts[key]]
            self.assertTrue(any(hits) and not all(hits), (key, hits))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run them to verify they fail**

Run: `python3 -m unittest discover -s test/e2e`
Expected: errors `ModuleNotFoundError: No module named 'e2elib'`.

- [ ] **Step 4: Write the config and prompt set**

`test/e2e/e2e.json` (no secrets: repo names, ssh aliases and paths only). Apply any host change Task 1 recorded, such as H4 manual or an H5 entry.

```json
{
  "general_repo": "davlion/claude-memory-test",
  "client_repo": "davlion-test-client/claude-memory",
  "client_scope": "davlion-test-client",
  "sample_project": "davlion-test-client/sample-app",
  "kit_project": "davlion/claude-memory-cloud",
  "repeats": 3,
  "hosts": {
    "H1": {"label": "Mac CLI", "ssh": null, "claude": "~/.local/bin/claude", "python": "/usr/bin/python3",
           "mcp_prefixes": ["mcp__claude_ai_claude-memory-staging__", "mcp__claude-memory-staging__"],
           "dirs": {"sample_app": "~/src/sample-app", "kit_repo": "~/src/claude-memory-cloud",
                    "no_remote": "~/e2e-no-remote"}},
    "H3": {"label": "earsvm", "ssh": "earsvm.local", "claude": "~/.local/bin/claude", "python": "/usr/bin/python3",
           "mcp_prefixes": ["mcp__claude_ai_claude-memory-staging__"],
           "dirs": {"sample_app": "~/src/sample-app", "kit_repo": "~/src/claude-memory-cloud",
                    "no_remote": "~/e2e-no-remote"}},
    "H4": {"label": "lume", "ssh": "lumevm", "claude": "~/.local/bin/claude", "python": "/usr/bin/python3",
           "mcp_prefixes": ["mcp__claude_ai_claude-memory-staging__"],
           "dirs": {"sample_app": "~/src/sample-app", "kit_repo": "~/src/claude-memory-cloud",
                    "no_remote": "~/e2e-no-remote"}}
  }
}
```

`test/e2e/prompts.json` (the spec's fixed prompt set; never edit a phrasing between runs you compare)

```json
{
  "_comment": "Fixed prompt set (spec §9). {token} is unique per run; never edit a phrasing between runs you compare. S2/S4/S5 cycle through their phrasings across the 3 repeats; about half match the prompt hook's trigger phrases and half do not.",
  "S2": [
    "Save a memory: I always want commit messages in the imperative mood. Tag: {token}",
    "Going forward, keep in mind that I prefer tabs over spaces in every language I write. Tag: {token}",
    "Remember this for next time: I read long answers on my phone, so keep summaries short. Tag: {token}",
    "Don't do this again: you used American date formats; I want ISO 8601 dates everywhere. Tag: {token}"
  ],
  "S3": [
    "This applies to every davlion-test-client project, not just this repo: their code review rule is two approvals before merge. Remember this. Tag: {token}",
    "Note for the future, client-wide for davlion-test-client: all their services deploy on Tuesdays only. Tag: {token}"
  ],
  "S4": [
    "Remember this about this repo only: sample-app's test suite needs the FAKE_CLOCK=1 environment variable. Tag: {token}",
    "For this project specifically, keep in mind that the sample-app build output goes to out/, not dist/. Tag: {token}",
    "Save a memory for this codebase: in sample-app the config loader reads settings.toml before env vars. Tag: {token}"
  ],
  "S4n": [
    "Remember this for this project only: the scratch scripts here run with python3.12. Tag: {token}"
  ],
  "S5": [
    "Remember this: use 2-space indentation. Tag: {token}",
    "Keep in mind for later that we squash-merge. Tag: {token}",
    "Save a memory: the linter runs before tests. Tag: {token}"
  ],
  "S8": [
    "Save a memory: the staging deploy key is {secret} so use it when deploying. Tag: {token}"
  ],
  "S16": [
    "Save each of the following as a separate general memory. Issue all of the memory_save calls in parallel in a single turn, then report each result.\n{facts}"
  ],
  "S16_facts": [
    "I like my coffee black.",
    "My favourite editor theme is Solarized Dark.",
    "I keep my notes in plain Markdown files.",
    "I usually work from 7am to 3pm Pacific.",
    "I prefer pytest over unittest for new projects.",
    "My cat is called Biscuit.",
    "I run Ubuntu on my home server.",
    "I bike to work when it isn't raining."
  ],
  "named_save": ["Save a general memory named {name} with the description \"e2e test memory {name}\" and the body \"{body}\". Use exactly that name."],
  "named_read": ["Read the general memory named {name} with memory_read and tell me its version. Don't change anything."],
  "named_update": ["Update the general memory {name}: set its body to \"{body}\", keep the description, and pass the version you read earlier in this session. Don't read it again first."],
  "named_read_update": ["Read the general memory {name}, then update it: set its body to \"{body}\" and keep the description."],
  "named_search": ["Search my memory for {name} and tell me what you find."],
  "reconcile_yes": ["Yes, reconcile the conflict now: merge the copies into the original, save it, then delete the conflict copy."],
  "U1": ["Remember this: in sample-app we pin Node to version 20. Tag: {token}"]
}
```

- [ ] **Step 5: Implement** — `test/e2e/e2elib/__init__.py`

```python
"""Level 4 end-to-end runner library (spec §9). Stdlib only, Python >= 3.9."""
```

`test/e2e/e2elib/transcript.py`

```python
"""Parse `claude -p --output-format stream-json --verbose` output into what the scenario checks need."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

KIT_MARK = "Memory project for this session"
MEMORY_TOOLS = ("memory_index", "memory_read", "memory_search", "memory_save", "memory_delete",
                "memory_health", "memory_scopes")
_STATUS = re.compile(r'"status"\s*:\s*"([a-z_]+)"')


@dataclass
class ToolCall:
    id: str
    name: str
    input: Dict[str, Any]
    result: Optional[str] = None
    is_error: bool = False

    @property
    def short(self) -> str:
        """`memory_save` for `mcp__claude_ai_claude-memory-staging__memory_save`."""
        return self.name.rsplit("__", 1)[-1] if self.name.startswith("mcp__") else self.name

    @property
    def status(self) -> Optional[str]:
        """The `status` field of a memory tool's JSON result, if any."""
        m = _STATUS.search(self.result or "")
        return m.group(1) if m else None


@dataclass
class Hook:
    name: str      # e.g. "SessionStart:startup", "SessionStart:compact", "UserPromptSubmit"
    context: str   # additionalContext if the hook printed hookSpecificOutput JSON, else raw stdout


@dataclass
class Transcript:
    session_id: Optional[str] = None
    tools: List[str] = field(default_factory=list)
    hooks: List[Hook] = field(default_factory=list)
    calls: List[ToolCall] = field(default_factory=list)
    texts: List[str] = field(default_factory=list)
    denials: List[str] = field(default_factory=list)
    final: Optional[Dict[str, Any]] = None
    bad_lines: int = 0

    def memory_calls(self, short: Optional[str] = None) -> List[ToolCall]:
        out = [c for c in self.calls if c.name.startswith("mcp__") and c.short in MEMORY_TOOLS]
        return [c for c in out if c.short == short] if short else out

    def kit_context(self, hook_prefix: str = "SessionStart") -> str:
        """The memory kit's SessionStart context (the hook whose output names the memory project)."""
        return "\n".join(h.context for h in self.hooks if h.name.startswith(hook_prefix) and KIT_MARK in h.context)

    @property
    def final_text(self) -> str:
        if self.final and isinstance(self.final.get("result"), str):
            return self.final["result"]
        return self.texts[-1] if self.texts else ""

    @property
    def succeeded(self) -> bool:
        return bool(self.final) and self.final.get("subtype") == "success" and not self.final.get("is_error")


def _hook_context(output: str) -> str:
    try:
        d = json.loads(output)
    except ValueError:
        return output
    if isinstance(d, dict) and isinstance(d.get("hookSpecificOutput"), dict):
        ctx = d["hookSpecificOutput"].get("additionalContext")
        if isinstance(ctx, str):
            return ctx
    return output


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return ""


def parse(lines: Iterable[str]) -> Transcript:
    t = Transcript()
    by_id: Dict[str, ToolCall] = {}
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            t.bad_lines += 1
            continue
        if not isinstance(e, dict):
            t.bad_lines += 1
            continue
        kind, sub = e.get("type"), e.get("subtype")
        if kind == "system" and sub == "init":
            t.session_id = e.get("session_id")
            t.tools = [x for x in e.get("tools", []) if isinstance(x, str)]
        elif kind == "system" and sub == "hook_response":
            t.hooks.append(Hook(str(e.get("hook_name", "")), _hook_context(str(e.get("output", "")))))
        elif kind == "system" and sub == "permission_denied":
            t.denials.append(str(e.get("tool_name", "")))
        elif kind == "assistant":
            for c in (e.get("message") or {}).get("content") or []:
                if c.get("type") == "tool_use":
                    call = ToolCall(str(c.get("id")), str(c.get("name")), c.get("input") or {})
                    by_id[call.id] = call
                    t.calls.append(call)
                elif c.get("type") == "text" and c.get("text"):
                    t.texts.append(c["text"])
        elif kind == "user":
            content = (e.get("message") or {}).get("content")
            for c in content if isinstance(content, list) else []:
                if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in by_id:
                    call = by_id[c["tool_use_id"]]
                    call.result = _result_text(c.get("content"))
                    call.is_error = bool(c.get("is_error"))
        elif kind == "result":
            t.final = e
            t.session_id = t.session_id or e.get("session_id")
    return t
```

`test/e2e/e2elib/launch.py`

```python
"""Run `claude -p` (and small shell commands) on a test host: the Mac itself or a VM over SSH."""
from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Mapping, Optional, Sequence

from .transcript import Transcript, parse

# Variables a parent Claude Code session sets. Inherited, they make the child think it is nested, and
# ANTHROPIC_API_KEY turns off claude.ai connectors (observed 2026-10-15, Claude Code 2.1.300).
SCRUB_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_", "CLAUDECODE")
SCRUB_EXACT = ("CLAUDE_PID", "CLAUDE_EFFORT")
EMPTY_MCP = '{"mcpServers":{}}'


@dataclass
class Host:
    id: str                      # "H1"
    label: str                   # "Mac CLI"
    ssh: Optional[str]           # ssh destination, or None for this machine
    claude: str                  # claude executable on that host
    python: str                  # python for kit helpers on that host
    mcp_prefixes: List[str]      # e.g. ["mcp__claude_ai_claude-memory-staging__"]
    dirs: Dict[str, str]         # "sample_app" / "kit_repo" / "no_remote" -> path (may start with ~/)


@dataclass
class Invocation:
    prompt: str
    cwd: str                                 # a key of Host.dirs
    allow: Sequence[str] = ()                # short memory tool names to pre-approve, e.g. ("memory_save",)
    max_turns: int = 12
    session_id: Optional[str] = None         # start a new session with this id
    resume: Optional[str] = None             # continue this session
    no_connector: bool = False               # load no MCP servers at all (connector "unavailable")
    env: Dict[str, str] = field(default_factory=dict)
    timeout: float = 420.0


@dataclass
class RunResult:
    transcript: Transcript
    returncode: Optional[int]
    stdout: str
    stderr: str
    timed_out: bool


Exec = Callable[[List[str], Optional[str], Optional[Dict[str, str]], float], "subprocess.CompletedProcess[str]"]


def clean_env(base: Mapping[str, str], extra: Mapping[str, str]) -> Dict[str, str]:
    env = {k: v for k, v in base.items() if not k.startswith(SCRUB_PREFIXES) and k not in SCRUB_EXACT}
    env.update(extra)
    return env


def claude_args(host: Host, inv: Invocation) -> List[str]:
    """The claude argv after the executable. The prompt comes first: --allowedTools is variadic, so it goes last."""
    args = ["-p", inv.prompt, "--output-format", "stream-json", "--verbose",
            "--permission-mode", "default", "--max-turns", str(inv.max_turns)]
    if inv.session_id:
        args += ["--session-id", inv.session_id]
    if inv.resume:
        args += ["--resume", inv.resume]
    if inv.no_connector:
        args += ["--strict-mcp-config", "--mcp-config", EMPTY_MCP]
    if inv.allow:
        args += ["--allowedTools"] + [p + t for p in host.mcp_prefixes for t in inv.allow]
    return args


def _remote_path(p: str) -> str:
    """Quote a path for a remote shell, keeping a leading ~/ expandable."""
    return '"$HOME"/' + shlex.quote(p[2:]) if p.startswith("~/") else shlex.quote(p)


def command(host: Host, inv: Invocation) -> List[str]:
    """Full argv to run locally (for ssh hosts: ssh + one remote shell command)."""
    if host.ssh is None:
        return [os.path.expanduser(host.claude)] + claude_args(host, inv)
    unset = " ".join(f"-u {v}" for v in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"))
    sets = " ".join(f"{k}={shlex.quote(v)}" for k, v in sorted(inv.env.items()))
    remote = (f"cd {_remote_path(host.dirs[inv.cwd])} && env {unset} {sets} "
              f"{_remote_path(host.claude)} {' '.join(shlex.quote(a) for a in claude_args(host, inv))} </dev/null")
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host.ssh, remote]


def _default_exec(argv: List[str], cwd: Optional[str], env: Optional[Dict[str, str]],
                  timeout: float) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, timeout=timeout)


def run_claude(host: Host, inv: Invocation, exec_: Exec = _default_exec) -> RunResult:
    argv = command(host, inv)
    cwd = os.path.expanduser(host.dirs[inv.cwd]) if host.ssh is None else None
    env = clean_env(os.environ, inv.env) if host.ssh is None else clean_env(os.environ, {})
    try:
        r = exec_(argv, cwd, env, inv.timeout)
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode("utf-8", "replace")
        return RunResult(parse(out.splitlines()), None, out, "timeout", True)
    return RunResult(parse(r.stdout.splitlines()), r.returncode, r.stdout, r.stderr, False)


def shell(host: Host, script: str, exec_: Exec = _default_exec, timeout: float = 60.0) -> str:
    """Run a small sh script on the host; returns stdout. Raises RuntimeError on a non-zero exit."""
    argv = ["sh", "-c", script] if host.ssh is None else \
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host.ssh, script]
    r = exec_(argv, None, None, timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{host.id}: `{script[:80]}` exited {r.returncode}: {r.stderr.strip()[:300]}")
    return r.stdout
```

`test/e2e/e2elib/config.py`

```python
"""The e2e configuration (test/e2e/e2e.json) and the fixed prompt set (test/e2e/prompts.json)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from .launch import Host

HERE = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    general_repo: str        # repo of scope `general`
    client_repo: str         # repo of the test client scope
    client_scope: str        # the client scope's name
    sample_project: str      # owner/repo of the test code repo (projects live in client_repo)
    kit_project: str         # owner/repo of claude-memory-cloud (its project lives in general_repo)
    repeats: int             # runs per routing prompt per host (spec: 3)
    hosts: Dict[str, Host]
    prompts: Dict[str, List[str]]

    @property
    def repos(self) -> List[str]:
        return [self.general_repo, self.client_repo]


def load(config_path: Path = HERE / "e2e.json", prompts_path: Path = HERE / "prompts.json") -> Config:
    d = json.loads(Path(config_path).read_text(encoding="utf-8"))
    hosts = {hid: Host(id=hid, label=h["label"], ssh=h.get("ssh"), claude=h["claude"], python=h["python"],
                       mcp_prefixes=list(h["mcp_prefixes"]), dirs=dict(h["dirs"]))
             for hid, h in d["hosts"].items()}
    prompts = json.loads(Path(prompts_path).read_text(encoding="utf-8"))
    return Config(general_repo=d["general_repo"], client_repo=d["client_repo"], client_scope=d["client_scope"],
                  sample_project=d["sample_project"], kit_project=d["kit_project"], repeats=int(d["repeats"]),
                  hosts=hosts, prompts={k: v for k, v in prompts.items() if not k.startswith("_")})
```

- [ ] **Step 6: Wire up** — in `package.json` `"scripts"`, after `"test:local"`, add:

```json
    "test:e2e": "python3 -m unittest discover -s test/e2e",
```
Append to `.gitignore`:
```
test/e2e/results/raw/
```

- [ ] **Step 7: Run the tests**

Run: `npm run test:e2e && /usr/bin/python3 -m unittest discover -s test/e2e`
Expected: all of `test_transcript`, `test_launch` and `test_config` pass (18 tests) on both interpreters.

- [ ] **Step 8: Commit**

```bash
git add test/e2e/e2elib/__init__.py test/e2e/e2elib/transcript.py test/e2e/e2elib/launch.py test/e2e/e2elib/config.py \
  test/e2e/e2e.json test/e2e/prompts.json test/e2e/fixtures/save-general.jsonl \
  test/e2e/test_transcript.py test/e2e/test_launch.py test/e2e/test_config.py package.json .gitignore
git commit -m "test(e2e): stream-json parser, claude launcher (local/ssh, scrubbed env), config and fixed prompt set"
```

---

### Task 4: Repo checks with `gh api`, and the pure pass/fail rules

**Files:**
- Create: `test/e2e/e2elib/gh.py`, `test/e2e/e2elib/checks.py`
- Create: `test/e2e/test_gh.py`

**Interfaces:**
- Consumes: `transcript.Transcript` (Task 3).
- Produces:
  - `gh.GitHub(api=gh_api)` with `.commits_since(repo, since) -> List[Commit]` (oldest first), `.file_text(repo, path, ref="HEAD") -> Optional[str]`, `.find(repos, since, token) -> List[Found]` (server commits only), `.exists(repo, path)` and `.delete(repo, path, message) -> bool`.
  - `gh.Commit(sha, message, files)` with `.trailers`.
  - `gh.Found(repo, path, sha, scope, source)` with `.parts` → `{"project", "name", "conflict"}`.
  - `gh.MEMORY_PATH` and `gh.GhError(status, message)`.
  - `checks`:
    - constants: `PASS`, `FAIL`, `SOFT_PASS`, `SOFT_FAIL`, `ERROR`
    - `Verdict(status, notes)` and `verdict(notes, soft=False)`
    - outcome checks: `expect_one(found, *, repo, project, scope)`, `expect_none(found)`
    - transcript checks: `no_prompts(t)`, `announced(t, phrase)`, `index_called(t, project)`, `kit_healthy(t)`, `problems(t)`, `exactly_one_problem(t, fragment)`
    - markers: `PROBLEMS_MARK`, `COMPACT_MARK`, `SNAPSHOT_MARK`, `OUTBOX_MARK`

- [ ] **Step 1: Write the failing test** — `test/e2e/test_gh.py`

```python
"""The gh api wrapper, against canned API answers."""
import json
import unittest

from e2elib.gh import Commit, GhError, GitHub

R = "me/claude-memory-test"


class FakeApi:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def __call__(self, args):
        self.calls.append(args)
        key = args[0] if args[0] != "-X" else " ".join(args[:3])
        for prefix, answer in self.routes.items():
            if key.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return answer if isinstance(answer, str) else json.dumps(answer)
        raise GhError(404, f"no route {key}")


def commit(sha, msg, files):
    return {"sha": sha, "commit": {"message": msg}, "files": [{"filename": f, "status": s} for f, s in files]}


SERVER = "save: x\n\nMemory-Source: claude-code on mac\nMemory-Scope: general\n"
ROUTES = {
    f"repos/{R}/commits?since=": [{"sha": "b2"}, {"sha": "a1"}],            # newest first, like GitHub
    f"repos/{R}/commits/a1": commit("a1", SERVER, [("memories/x.md", "added"), ("MEMORY.md", "modified")]),
    f"repos/{R}/commits/b2": commit("b2", "hand edit\n", [("memories/y.md", "added")]),
    f"repos/{R}/contents/memories/x.md?ref=a1": "---\nname: x\n---\nbody e2e-r1-01\n",
    f"repos/{R}/contents/memories/gone.md?ref=HEAD": GhError(404, "Not Found"),
    f"repos/{R}/contents/memories/x.md": {"sha": "blob1"},
    f"-X DELETE repos/{R}/contents/memories/x.md": "{}",
}


class Api(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi(ROUTES)
        self.gh = GitHub(self.api)

    def test_commits_oldest_first_with_files(self):
        cs = self.gh.commits_since(R, "2026-10-15T12:00:00Z")
        self.assertEqual([c.sha for c in cs], ["a1", "b2"])
        self.assertIn("since=2026-10-15T12%3A00%3A00Z", self.api.calls[0][0])
        self.assertEqual(cs[0].files, [("memories/x.md", "added"), ("MEMORY.md", "modified")])

    def test_trailers(self):
        c = Commit("a", SERVER, [])
        self.assertEqual(c.trailers, {"Memory-Source": "claude-code on mac", "Memory-Scope": "general"})

    def test_find_only_server_commits_and_memory_paths(self):
        found = self.gh.find([R], "2026-10-15T12:00:00Z", "e2e-r1-01")
        self.assertEqual([(f.path, f.scope, f.sha) for f in found], [("memories/x.md", "general", "a1")])
        self.assertEqual(found[0].parts, {"project": None, "name": "x", "conflict": None})

    def test_missing_file_is_none_other_errors_raise(self):
        self.assertIsNone(self.gh.file_text(R, "memories/gone.md"))
        gh = GitHub(FakeApi({f"repos/{R}/contents/": GhError(500, "boom")}))
        with self.assertRaises(GhError):
            gh.file_text(R, "memories/x.md")

    def test_delete_uses_blob_sha_and_is_false_when_gone(self):
        self.assertTrue(self.gh.delete(R, "memories/x.md", "e2e cleanup r1"))
        self.assertEqual(self.api.calls[-1], ["-X", "DELETE", f"repos/{R}/contents/memories/x.md",
                                              "-f", "message=e2e cleanup r1", "-f", "sha=blob1"])
        self.assertFalse(self.gh.delete(R, "memories/none.md", "m"))

    def test_conflict_and_project_paths_parse(self):
        from e2elib.gh import Found
        f = Found(R, "projects/sample-app/memories/a-b.conflict-20261015T120000Z-2.md", "s", "x", "y")
        self.assertEqual(f.parts["project"], "sample-app")
        self.assertEqual(f.parts["conflict"], ".conflict-20261015T120000Z-2")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s test/e2e -p test_gh.py`
Expected: `ModuleNotFoundError: No module named 'e2elib.gh'`.

- [ ] **Step 3: Implement** — `test/e2e/e2elib/gh.py`

```python
"""Check outcomes in the memory repos with `gh api` (spec §9 Level 4: outcomes, never wording)."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

# memories/<name>.md, memories/<name>.conflict-<ts>[-n].md, optionally under projects/<repo>/ (src/memory.ts PATH_RE)
MEMORY_PATH = re.compile(r"^(?:projects/(?P<project>[^/]+)/)?memories/(?P<name>[a-z0-9][a-z0-9-]{0,63})"
                         r"(?P<conflict>\.conflict-\d{8}T\d{6}Z(?:-\d{1,3})?)?\.md$")


class GhError(RuntimeError):
    def __init__(self, status: Optional[int], message: str) -> None:
        super().__init__(message)
        self.status = status


Api = Callable[[List[str]], str]   # args after `gh api` -> stdout; raises GhError


def gh_api(args: List[str]) -> str:
    r = subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        m = re.search(r"HTTP (\d{3})", r.stderr)
        raise GhError(int(m.group(1)) if m else None, r.stderr.strip()[:300])
    return r.stdout


@dataclass
class Commit:
    sha: str
    message: str
    files: List[Tuple[str, str]]   # (path, status) — status: added | modified | removed | renamed

    @property
    def trailers(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for line in self.message.splitlines():
            m = re.match(r"^(Memory-[A-Za-z]+): (.*)$", line)
            if m:
                out[m.group(1)] = m.group(2).strip()
        return out


@dataclass
class Found:
    repo: str
    path: str
    sha: str           # commit that wrote it
    scope: str         # Memory-Scope trailer
    source: str        # Memory-Source trailer

    @property
    def parts(self) -> Dict[str, Optional[str]]:
        m = MEMORY_PATH.match(self.path)
        return m.groupdict() if m else {"project": None, "name": None, "conflict": None}


class GitHub:
    def __init__(self, api: Api = gh_api) -> None:
        self.api = api

    def commits_since(self, repo: str, since: str) -> List[Commit]:
        """Commits on the default branch since `since` (ISO 8601 Z), oldest first, with their files."""
        listing = json.loads(self.api([f"repos/{repo}/commits?since={quote(since)}&per_page=100"]))
        out = []
        for c in reversed(listing):
            d = json.loads(self.api([f"repos/{repo}/commits/{c['sha']}"]))
            out.append(Commit(c["sha"], d["commit"]["message"],
                              [(f["filename"], f["status"]) for f in d.get("files", [])]))
        return out

    def file_text(self, repo: str, path: str, ref: str = "HEAD") -> Optional[str]:
        try:
            return self.api([f"repos/{repo}/contents/{quote(path)}?ref={quote(ref)}",
                             "-H", "Accept: application/vnd.github.raw"])
        except GhError as e:
            if e.status == 404:
                return None
            raise

    def find(self, repos: List[str], since: str, token: str) -> List[Found]:
        """Memory files containing `token`, written by the server (Memory-Source trailer) since `since`."""
        found: List[Found] = []
        for repo in repos:
            for c in self.commits_since(repo, since):
                t = c.trailers
                if "Memory-Source" not in t:
                    continue
                for path, status in c.files:
                    if status in ("added", "modified") and MEMORY_PATH.match(path):
                        text = self.file_text(repo, path, c.sha)
                        if text and token in text:
                            found.append(Found(repo, path, c.sha, t.get("Memory-Scope", ""), t["Memory-Source"]))
        return found

    def exists(self, repo: str, path: str) -> bool:
        return self.file_text(repo, path) is not None

    def delete(self, repo: str, path: str, message: str) -> bool:
        """Delete one file by hand (cleanup). The server rebuilds MEMORY.md from the files. False if already gone."""
        try:
            meta = json.loads(self.api([f"repos/{repo}/contents/{quote(path)}"]))
        except GhError as e:
            if e.status == 404:
                return False
            raise
        self.api(["-X", "DELETE", f"repos/{repo}/contents/{quote(path)}",
                  "-f", f"message={message}", "-f", f"sha={meta['sha']}"])
        return True
```

`test/e2e/e2elib/checks.py`. The marker strings are copied from `kit/memory_kit/session.py`; if those constants change, change these too.

```python
"""Pure pass/fail checks shared by the scenarios. Each returns a list of failure notes (empty = pass)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from .gh import Found
from .transcript import Transcript

PASS, FAIL, SOFT_PASS, SOFT_FAIL, ERROR = "PASS", "FAIL", "SOFT-PASS", "SOFT-FAIL", "ERROR"
PROBLEMS_MARK = "claude-memory preflight found problems"   # kit/memory_kit/session.py PROBLEMS_HEAD
COMPACT_MARK = "Context was compacted. Call memory_index again"  # session.py COMPACT_LINE
SNAPSHOT_MARK = "<memory-snapshot "
OUTBOX_MARK = "queued in outbox"


@dataclass
class Verdict:
    status: str
    notes: List[str] = field(default_factory=list)


def verdict(notes: Iterable[str], soft: bool = False) -> Verdict:
    notes = [n for n in notes if n]
    if soft:
        return Verdict(SOFT_FAIL if notes else SOFT_PASS, notes)
    return Verdict(FAIL if notes else PASS, notes)


def expect_one(found: List[Found], *, repo: str, project: Optional[str], scope: str) -> List[str]:
    """Exactly one non-conflict memory file holds the token, in `repo`, under projects/<project>/ or not, with
    the expected Memory-Scope trailer."""
    live = [f for f in found if not f.parts["conflict"]]
    paths = sorted({(f.repo, f.path) for f in live})
    if not paths:
        return [f"no memory with the token was committed (expected {repo}, scope {scope})"]
    notes = []
    if len(paths) > 1:
        notes.append(f"token is in {len(paths)} memories: {paths}")
    f = live[-1]
    if f.repo != repo:
        notes.append(f"saved to {f.repo}, expected {repo}")
    if f.parts["project"] != project:
        notes.append(f"saved under project {f.parts['project']!r}, expected {project!r} ({f.path})")
    if f.scope != scope:
        notes.append(f"Memory-Scope trailer {f.scope!r}, expected {scope!r}")
    return notes


def expect_none(found: List[Found]) -> List[str]:
    return [f"unexpected commit: {f.repo}/{f.path} ({f.sha[:7]})" for f in found]


def no_prompts(t: Transcript) -> List[str]:
    """A memory tool that needed a permission prompt (denied in -p) breaks the zero-prompt setup."""
    return [f"permission denied for {d}" for d in t.denials if "memory_" in d]


def announced(t: Transcript, phrase: str) -> List[str]:
    """The save announcement is a fixed protocol string (spec §7 D), so checking it is not checking wording."""
    return [] if phrase.lower() in t.final_text.lower() else [f"reply lacks the announcement {phrase!r}"]


def index_called(t: Transcript, project: Optional[str]) -> List[str]:
    calls = t.memory_calls("memory_index")
    if not calls:
        return ["memory_index was not called"]
    c = calls[0]
    notes = []
    if c.is_error or c.result is None:
        notes.append(f"memory_index failed: {(c.result or '')[:160]}")
    if c.input.get("project") != project:
        notes.append(f"memory_index project={c.input.get('project')!r}, expected {project!r}")
    return notes


def kit_healthy(t: Transcript) -> List[str]:
    ctx = t.kit_context()
    if not ctx:
        return ["the kit's SessionStart hook produced no context"]
    return ["preflight reported problems: " + ctx.split(PROBLEMS_MARK, 1)[1][:300]] if PROBLEMS_MARK in ctx else []


def problems(t: Transcript) -> List[str]:
    """The preflight problem lines in the kit's SessionStart context ("- …" lines after the problems head)."""
    ctx = t.kit_context()
    if PROBLEMS_MARK not in ctx:
        return []
    tail = ctx.split(PROBLEMS_MARK, 1)[1].split("\n\n", 1)[0]
    return [line[2:] for line in tail.splitlines() if line.startswith("- ")]


def exactly_one_problem(t: Transcript, fragment: str) -> List[str]:
    p = problems(t)
    if len(p) != 1:
        return [f"expected exactly one preflight problem, got {len(p)}: {p}"]
    return [] if fragment in p[0] else [f"problem line lacks {fragment!r}: {p[0]}"]
```

- [ ] **Step 4: Run the tests**

Run: `npm run test:e2e`
Expected: OK (24 tests). `checks` is exercised through the scenario tests in Task 5.

- [ ] **Step 5: Commit**

```bash
git add test/e2e/e2elib/gh.py test/e2e/e2elib/checks.py test/e2e/test_gh.py
git commit -m "test(e2e): gh api outcome checks (server commits, trailers, memory paths) and pass/fail rules"
```

---

### Task 5: Scenarios

**Files:**
- Create: `test/e2e/e2elib/scenarios.py`, `test/e2e/fakes.py`, `test/e2e/test_scenarios.py`

**Interfaces:**
- Consumes: Tasks 3–4.
- Produces:
  - `scenarios.Ctx(cfg, gh, run_id, raw_dir, claude=run_claude, sh=shell, now=…, env=None)`
    - identifiers and prompts: `.token()`, `.since()`, `.prompt(key, i=0, **values)`
    - running and checking: `.claude(host, inv, label) -> Transcript` (also writes `raw_dir/<host>-<label>-<nn>.jsonl`), `.found(token, since)`
    - host checks: `.marker(host, token)`, `.auto_memory_writes(host, marker)`, `.outbox_files(host, token)`, `.mtime(host, path)`
    - names: `.project_scope()`, `.sample_repo_name()`
  - Each scenario function returns `Dict[str, Verdict]`:
    - single-host: `fn(ctx, host, i)` in `SINGLE` (`S1`→S1+S12h, `S2`/`S3`/`S4`→also S0, `S11`→S11f+S11+S11e+S11b, `S14`→S14+S7, `S4n`, `S5`, `S8`, `S16`, `U1`)
    - two-host: `fn(ctx, a, b)` in `PAIR` (`S6`, `S6p`, `S9`, `S11c`, `S13`)
  - `REPEATED = ("S2", "S4", "S5")`.
  - `fake_secret(rng)`.

How each scenario decides, to read alongside the code:
- **S1:** the first `memory_index` call succeeds and has `project = davlion-test-client/sample-app`. No `memory_*` denials.
- **S12h:** the kit context has no preflight problems.
- **S2, S3, S4:** exactly one server-written, non-conflict file holds the token, in the right repo and path with the right `Memory-Scope`. The announcement is present and there are no denials. S0 also holds: no new file under `~/.claude/projects/*/memory/`.
- **S4n** (no-remote dir): nothing committed, and no successful project save.
- **S5:** no `memory_save` call, nothing committed, and the reply asks a question.
- **S8:** a fake AWS key in the prompt; nothing committed, any save returns `rejected_secret`, and "not saved" is announced.
- **S11 chain** (kit repo):
  - **S11f:** a healthy run rewrites `cache/davlion__claude-memory-cloud.md`.
  - **S11:** a run without the connector queues exactly one outbox entry and announces "queued in outbox for general".
  - **S11e:** a run without the connector shows the stale snapshot, and no memory call succeeds.
  - **S11b:** a healthy run's hook reports the queue, the commit lands, and the entry is gone.
- **S14/S7:** one session saves, `/compact`, asks about the early memory, then saves again. Needed: the compaction line from the hook, `memory_index` after compaction, the early token recalled, and the later save routed to general.
- **S16 (soft):** 8 parallel saves, each stored exactly once, with no conflict copies. The notes count failures in transit.
- **S6:** host A saves, then host B's session-start index lists the memory. S6p does the same for a project memory.
- **S9:** A and B read the same memory, then both update it with the version they read. A's update applies, B's becomes a conflict copy, and after "yes, reconcile" on A the copy is gone.
- **S11c:** A reads, then queues an update with the connector gone. B updates. A's flush becomes a conflict copy, not an overwrite, and the outbox entry is removed.
- **S13:** B's running session, after A saves, gets "Memory changed since your index" and the new name in its next tool result.
- **U1:** after uninstall, with no connector: no kit context, no prompt hint, no memory calls, and "remember this" writes an auto-memory file.

- [ ] **Step 1: Write the test doubles** — `test/e2e/fakes.py`

```python
"""Test doubles for the scenario tests: scripted claude runs, a fake repo set, a fake host shell."""
import json
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from e2elib.config import Config
from e2elib.gh import Found
from e2elib.launch import Host, Invocation, RunResult
from e2elib.transcript import parse

P = "mcp__claude_ai_claude-memory-staging__"
HOST = Host("H1", "Mac CLI", None, "claude", "python3", [P], {"sample_app": "/s", "kit_repo": "/k", "no_remote": "/n"})
CFG = Config(general_repo="me/claude-memory-test", client_repo="client/claude-memory", client_scope="client",
             sample_project="client/sample-app", kit_project="me/claude-memory-cloud", repeats=3,
             hosts={"H1": HOST}, prompts=json.loads((Path(__file__).resolve().parent / "prompts.json").read_text()))


def stream(*, kit: str = "Memory project for this session: client/sample-app", calls=(), text: str = "ok",
           hooks: List[Tuple[str, str]] = ()) -> str:
    """A stream-json transcript. calls: (short_name, input, result_text, is_error)."""
    ev = [{"type": "system", "subtype": "hook_response", "hook_name": "SessionStart:startup", "output":
           json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": kit}})}]
    ev += [{"type": "system", "subtype": "hook_response", "hook_name": n, "output": o} for n, o in hooks]
    ev.append({"type": "system", "subtype": "init", "session_id": "s", "tools": []})
    for i, (name, inp, res, err) in enumerate(calls):
        ev.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"c{i}", "name": P + name, "input": inp}]}})
        ev.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"c{i}", "content": res, "is_error": err}]}})
    ev.append({"type": "result", "subtype": "success", "is_error": False, "result": text})
    return "\n".join(json.dumps(e) for e in ev)


def saved(status: str = "created") -> str:
    return f'claude-memory response.\n{{"status": "{status}", "name": "n"}}'


class FakeClaude:
    """Returns scripted stdout per call, in order; records the invocations. A callable entry gets the Invocation."""

    def __init__(self, *outputs) -> None:
        self.outputs, self.invocations = list(outputs), []

    def __call__(self, host: Host, inv: Invocation) -> RunResult:
        self.invocations.append(inv)
        out = self.outputs.pop(0)
        out = out(inv) if callable(out) else out
        return RunResult(parse(out.splitlines()), 0, out, "", False)


class FakeGh:
    """Memory files as (Found, text). find() matches by token in text."""

    def __init__(self) -> None:
        self.files: List[Tuple[Found, str]] = []
        self.deleted: List[str] = []

    def add(self, repo: str, path: str, text: str, scope: str) -> None:
        self.files.append((Found(repo, path, "abc1234", scope, "claude-code on test"), text))

    def find(self, repos, since, token):
        return [f for f, text in self.files if token in text and f.repo in repos]

    def exists(self, repo, path):
        return any(f.repo == repo and f.path == path for f, _ in self.files)


class FakeShell:
    """Answers host shell commands by substring; records them."""

    def __init__(self, answers: Dict[str, Callable[[str], str]] = None) -> None:
        self.answers, self.seen = answers or {}, []

    def __call__(self, host: Host, script: str) -> str:
        self.seen.append(script)
        for key, fn in self.answers.items():
            if key in script:
                return fn(script)
        return ""
```

- [ ] **Step 2: Write the failing tests** — `test/e2e/test_scenarios.py`

```python
"""Scenario logic against scripted transcripts and a fake repo set (no network, no claude)."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from e2elib import checks as C
from e2elib import scenarios as S
from fakes import CFG, HOST, FakeClaude, FakeGh, FakeShell, saved, stream


def ctx(claude, gh=None, sh=None, env=None):
    tmp = Path(tempfile.mkdtemp())
    return S.Ctx(CFG, gh or FakeGh(), "r1", tmp, claude=claude, sh=sh or FakeShell(), env=env,
                 now=lambda: datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc))


class Routing(unittest.TestCase):
    def run_s2(self, repo, path, scope, text="saved to general", sh=None):
        gh = FakeGh()

        def answer(inv):
            gh.add(repo, path, f"body {inv.prompt.split('Tag: ')[1]}", scope)
            return stream(calls=[("memory_save", {"scope": "general"}, saved(), False)], text=text)
        claude = FakeClaude(answer)
        return S.s2(ctx(claude, gh, sh), HOST, 0), claude

    def test_s2_pass_and_s0_pass(self):
        v, claude = self.run_s2("me/claude-memory-test", "memories/x.md", "general")
        self.assertEqual((v["S2"].status, v["S0"].status), (C.PASS, C.PASS), v)
        self.assertEqual(claude.invocations[0].allow, ("memory_save",))
        self.assertIn("e2e-r1-01", claude.invocations[0].prompt)

    def test_s2_wrong_scope_fails_with_reasons(self):
        v, _ = self.run_s2("client/claude-memory", "memories/x.md", "client")
        self.assertEqual(v["S2"].status, C.FAIL)
        self.assertTrue(any("expected me/claude-memory-test" in n for n in v["S2"].notes))

    def test_s2_missing_announcement_fails(self):
        v, _ = self.run_s2("me/claude-memory-test", "memories/x.md", "general", text="Done!")
        self.assertIn("reply lacks the announcement 'saved to general'", v["S2"].notes)

    def test_auto_memory_write_fails_s0(self):
        sh = FakeShell({"find ~/.claude/projects": lambda s: "/Users/x/.claude/projects/-s/memory/a.md\n"})
        v, _ = self.run_s2("me/claude-memory-test", "memories/x.md", "general", sh=sh)
        self.assertEqual(v["S0"].status, C.FAIL)
        self.assertEqual(v["S2"].status, C.FAIL)

    def test_s4_project_path_and_trailer(self):
        gh = FakeGh()

        def answer(inv):
            gh.add("client/claude-memory", "projects/sample-app/memories/x.md", inv.prompt, "project:client/sample-app")
            return stream(text="saved to project sample-app")
        v = S.s4(ctx(FakeClaude(answer), gh), HOST, 0)
        self.assertEqual(v["S4"].status, C.PASS, v)

    def test_s5_saving_without_asking_fails(self):
        v = S.s5(ctx(FakeClaude(stream(calls=[("memory_save", {"scope": "general"}, saved(), False)], text="Saved."))), HOST)
        self.assertEqual(v["S5"].status, C.FAIL)
        self.assertEqual(len(v["S5"].notes), 2)

    def test_s5_question_passes(self):
        v = S.s5(ctx(FakeClaude(stream(text="general, client, or this project?"))), HOST)
        self.assertEqual(v["S5"].status, C.PASS)

    def test_s8_secret_is_fake_and_must_be_refused(self):
        claude = FakeClaude(stream(calls=[("memory_save", {}, saved("rejected_secret"), False)], text="not saved: secret"))
        v = S.s8(ctx(claude), HOST)
        self.assertEqual(v["S8"].status, C.PASS, v)
        self.assertRegex(claude.invocations[0].prompt, r"AKIA[A-Z0-9]{16}")

    def test_s1_wrong_project_and_denied_prompt(self):
        out = stream(calls=[("memory_index", {"project": "other/x"}, "index", False)])
        out = out.replace('{"type": "result"', '{"type": "system", "subtype": "permission_denied", "tool_name": '
                          '"mcp__x__memory_index"}\n{"type": "result"')
        v = S.s1_s12h(ctx(FakeClaude(out)), HOST)
        self.assertEqual(v["S1"].status, C.FAIL)
        self.assertEqual(len(v["S1"].notes), 2)
        self.assertEqual(v["S12h"].status, C.PASS)

    def test_s12h_fails_when_preflight_reports(self):
        kit = ("Memory project for this session: client/sample-app\n\nclaude-memory preflight found problems. Tell the "
               "user one line per problem, starting with \"⚠ memory:\" and including its action:\n- Scope map missing")
        v = S.s1_s12h(ctx(FakeClaude(stream(kit=kit, calls=[("memory_index", {"project": "client/sample-app"}, "i", False)]))), HOST)
        self.assertEqual(v["S12h"].status, C.FAIL)
        self.assertEqual(C.problems(FakeClaude(stream(kit=kit))(HOST, None).transcript), ["Scope map missing"])


class Outbox(unittest.TestCase):
    def test_s11_chain_all_pass(self):
        gh, state = FakeGh(), {"queued": []}
        now = int(datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc).timestamp())

        def queue(inv):
            state["queued"].append("/o/" + inv.prompt.split("Tag: ")[1] + ".md")
            return stream(text="queued in outbox for general")

        def flush(inv):
            tok = state["queued"][0][3:-3]
            gh.add("me/claude-memory-test", "memories/q.md", tok, "general")
            state["queued"].clear()
            return stream(kit="Memory project for this session: me/claude-memory-cloud\n\n1 memory queued in outbox.",
                          text="saved to general")
        claude = FakeClaude(stream(kit="Memory project for this session: me/claude-memory-cloud",
                                   calls=[("memory_index", {"project": "me/claude-memory-cloud"}, "i", False)]),
                            queue,
                            stream(kit="Memory project for this session: me/claude-memory-cloud\n\n<memory-snapshot key=\"k\">x"),
                            flush)
        sh = FakeShell({"getmtime": lambda s: f"{now + 3}\n", "outbox": lambda s: " ".join(state["queued"])})
        v = S.s11_chain(ctx(claude, gh, sh), HOST)
        self.assertEqual({k: x.status for k, x in v.items()},
                         {"S11f": C.PASS, "S11": C.PASS, "S11e": C.PASS, "S11b": C.PASS}, v)
        self.assertTrue(claude.invocations[1].no_connector and claude.invocations[2].no_connector)
        self.assertFalse(claude.invocations[3].no_connector)

    def test_stale_snapshot_fails_s11f(self):
        sh = FakeShell({"getmtime": lambda s: "1000\n"})
        claude = FakeClaude(stream(calls=[("memory_index", {"project": "me/claude-memory-cloud"}, "i", False)]),
                            stream(), stream(), stream())
        v = S.s11_chain(ctx(claude, sh=sh), HOST)
        self.assertEqual(v["S11f"].status, C.FAIL)


class Soft(unittest.TestCase):
    def test_s16_never_hard_fails(self):
        gh = FakeGh()

        def answer(inv):
            marks = [line.split(":")[0][2:] for line in inv.prompt.splitlines() if line.startswith("- ")]
            for m in marks[:-1]:
                gh.add("me/claude-memory-test", f"memories/{m}.md", m, "general")
            gh.add("me/claude-memory-test", f"memories/{marks[0]}.conflict-20261015T120000Z.md", marks[0], "general")
            return stream(calls=[("memory_save", {}, "ECONNRESET", True)])
        v = S.s16(ctx(FakeClaude(answer), gh), HOST)["S16"]
        self.assertEqual(v.status, C.SOFT_FAIL)
        self.assertTrue(any("stored 0 times" in n for n in v.notes))
        self.assertTrue(any("conflict copies" in n for n in v.notes))
        self.assertIn("1 save calls, 1 failed in transit", v.notes)


class Env(unittest.TestCase):
    def test_ctx_env_reaches_every_run(self):
        claude = FakeClaude(stream(calls=[("memory_index", {"project": "client/sample-app"}, "i", False)]))
        S.s1_s12h(ctx(claude, env={"CLAUDE_MEMORY_KIT_PROMPT_HINT": "off"}), HOST)
        self.assertEqual(claude.invocations[0].env, {"CLAUDE_MEMORY_KIT_PROMPT_HINT": "off"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run them to verify they fail**

Run: `python3 -m unittest discover -s test/e2e -p test_scenarios.py`
Expected: `ModuleNotFoundError: No module named 'e2elib.scenarios'`.

- [ ] **Step 4: Implement** — `test/e2e/e2elib/scenarios.py`

```python
"""Level 4 scenarios (spec §9). Each returns {scenario id: Verdict}; one run can decide several rows."""
from __future__ import annotations

import json
import random
import shlex
import string
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import checks as C
from .config import Config
from .gh import GitHub
from .launch import Host, Invocation, RunResult, run_claude, shell
from .transcript import Transcript

SAVE = ("memory_save",)
SAVE_DELETE = ("memory_save", "memory_delete")
Verdicts = Dict[str, C.Verdict]


class Ctx:
    """Everything a scenario needs; tests replace `claude`, `sh` and `gh`."""

    def __init__(self, cfg: Config, gh: GitHub, run_id: str, raw_dir: Path,
                 claude: Callable[[Host, Invocation], RunResult] = run_claude,
                 sh: Callable[[Host, str], str] = shell,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 env: Optional[Dict[str, str]] = None) -> None:
        self.cfg, self.gh, self.run_id, self.raw_dir = cfg, gh, run_id, raw_dir
        self.env = dict(env or {})   # added to every claude run, e.g. the prompt-hook switch for the A+C run
        self._claude, self.sh, self.now = claude, sh, now
        self._n = 0

    # ---- identifiers and time
    def token(self) -> str:
        """Unique per memory; cleanup finds everything by the `e2e-<run_id>-` prefix."""
        self._n += 1
        return f"e2e-{self.run_id}-{self._n:02d}"

    def since(self) -> str:
        return (self.now() - timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def prompt(self, key: str, i: int = 0, **values: str) -> str:
        options = self.cfg.prompts[key]
        return options[i % len(options)].format(**values)

    # ---- running things
    def claude(self, host: Host, inv: Invocation, label: str) -> Transcript:
        inv.env = {**self.env, **inv.env}
        r = self._claude(host, inv)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        (self.raw_dir / f"{host.id}-{label}-{self._n:02d}.jsonl").write_text(r.stdout, encoding="utf-8")
        if r.timed_out:
            r.transcript.texts.append("[e2e: timed out]")
        return r.transcript

    def found(self, token: str, since: str):
        return self.gh.find(self.cfg.repos, since, token)

    def marker(self, host: Host, token: str) -> str:
        path = f"/tmp/{token}.marker"
        self.sh(host, f"touch {path}")
        return path

    def auto_memory_writes(self, host: Host, marker: str) -> List[str]:
        out = self.sh(host, f"find ~/.claude/projects -path '*/memory/*' -type f -newer {marker} 2>/dev/null; true")
        return [f"auto-memory file written: {p}" for p in out.split()]

    def outbox_files(self, host: Host, token: str) -> List[str]:
        return self.sh(host, f"grep -l -- {shlex.quote(token)} ~/.claude-memory-cloud/outbox/*.md 2>/dev/null; true").split()

    def mtime(self, host: Host, path: str) -> Optional[int]:
        out = self.sh(host, f"{host.python} -c 'import os,sys; print(int(os.path.getmtime(os.path.expanduser(sys.argv[1]))))' "
                            f"{shlex.quote(path)} 2>/dev/null; true").strip()
        return int(out) if out.isdigit() else None

    def project_scope(self) -> str:
        return f"project:{self.cfg.sample_project}"

    def sample_repo_name(self) -> str:
        return self.cfg.sample_project.split("/", 1)[1]


# ---------- single-host scenarios

def s1_s12h(ctx: Ctx, host: Host, i: int = 0) -> Verdicts:
    """S1: index read unprompted (and with the right project). S12h: healthy preflight says nothing."""
    t = ctx.claude(host, Invocation("hi", "sample_app"), "S1")
    return {"S1": C.verdict(C.index_called(t, ctx.cfg.sample_project) + C.no_prompts(t)),
            "S12h": C.verdict(C.kit_healthy(t))}


def _routed_save(ctx: Ctx, host: Host, key: str, i: int, cwd: str, *, repo: str, project: Optional[str],
                 scope: str, announce: str) -> Verdicts:
    tok = ctx.token()
    since, marker = ctx.since(), ctx.marker(host, tok)
    t = ctx.claude(host, Invocation(ctx.prompt(key, i, token=tok), cwd, allow=SAVE), key)
    auto = ctx.auto_memory_writes(host, marker)
    notes = C.expect_one(ctx.found(tok, since), repo=repo, project=project, scope=scope)
    notes += C.announced(t, announce) + C.no_prompts(t)
    return {key: C.verdict(notes + auto), "S0": C.verdict(auto)}


def s2(ctx: Ctx, host: Host, i: int = 0) -> Verdicts:
    return _routed_save(ctx, host, "S2", i, "sample_app", repo=ctx.cfg.general_repo, project=None,
                        scope="general", announce="saved to general")


def s3(ctx: Ctx, host: Host, i: int = 0) -> Verdicts:
    return _routed_save(ctx, host, "S3", i, "sample_app", repo=ctx.cfg.client_repo, project=None,
                        scope=ctx.cfg.client_scope, announce=f"saved to {ctx.cfg.client_scope}")


def s4(ctx: Ctx, host: Host, i: int = 0) -> Verdicts:
    return _routed_save(ctx, host, "S4", i, "sample_app", repo=ctx.cfg.client_repo, project=ctx.sample_repo_name(),
                        scope=ctx.project_scope(), announce="saved to project")


def s4n(ctx: Ctx, host: Host, i: int = 0) -> Verdicts:
    tok = ctx.token()
    since = ctx.since()
    t = ctx.claude(host, Invocation(ctx.prompt("S4n", i, token=tok), "no_remote", allow=SAVE), "S4n")
    project_saves = [c for c in t.memory_calls("memory_save") if c.input.get("scope") == "project"
                     and c.status in ("created", "updated")]
    notes = C.expect_none(ctx.found(tok, since)) + [f"project save succeeded: {c.input}" for c in project_saves]
    return {"S4n": C.verdict(notes)}


def s5(ctx: Ctx, host: Host, i: int = 0) -> Verdicts:
    tok = ctx.token()
    since = ctx.since()
    t = ctx.claude(host, Invocation(ctx.prompt("S5", i, token=tok), "sample_app", allow=SAVE), "S5")
    notes = [f"saved without asking: {c.input.get('scope')}" for c in t.memory_calls("memory_save")]
    notes += C.expect_none(ctx.found(tok, since))
    if "?" not in t.final_text:
        notes.append("reply asks no question")
    return {"S5": C.verdict(notes)}


def fake_secret(rng: random.Random) -> str:
    """Matches the server's aws-access-key rule (src/secrets.ts); not a real key."""
    return "AKIA" + "".join(rng.choice(string.ascii_uppercase + string.digits) for _ in range(16))


def s8(ctx: Ctx, host: Host, i: int = 0) -> Verdicts:
    tok = ctx.token()
    since = ctx.since()
    secret = fake_secret(random.Random(tok))
    t = ctx.claude(host, Invocation(ctx.prompt("S8", i, token=tok, secret=secret), "sample_app", allow=SAVE), "S8")
    notes = C.expect_none(ctx.found(tok, since))
    notes += [f"memory_save returned {c.status}" for c in t.memory_calls("memory_save")
              if c.status not in (None, "rejected_secret")]
    notes += C.announced(t, "not saved")
    return {"S8": C.verdict(notes)}


def s11_chain(ctx: Ctx, host: Host, i: int = 0) -> Verdicts:
    """S11f (fresh snapshot), S11 (queue), S11e (stale snapshot shown), S11b (flush) — in that order."""
    out: Verdicts = {}
    key = ctx.cfg.kit_project.lower().replace("/", "__")
    start = int(ctx.now().timestamp()) - 1
    t = ctx.claude(host, Invocation("hi", "kit_repo"), "S11f")
    m = ctx.mtime(host, f"~/.claude-memory-cloud/cache/{key}.md")
    out["S11f"] = C.verdict(C.index_called(t, ctx.cfg.kit_project) +
                            ([] if m is not None and m >= start else [f"snapshot not rewritten (mtime {m}, run {start})"]))

    tok = ctx.token()
    since = ctx.since()
    t = ctx.claude(host, Invocation(ctx.prompt("S2", i, token=tok), "kit_repo", allow=SAVE, no_connector=True), "S11")
    queued = ctx.outbox_files(host, tok)
    out["S11"] = C.verdict(C.expect_none(ctx.found(tok, since)) + C.announced(t, "queued in outbox for general") +
                           ([] if len(queued) == 1 else [f"expected one outbox entry, found {queued}"]))

    t = ctx.claude(host, Invocation("hi", "kit_repo", no_connector=True), "S11e")
    ctx_text = t.kit_context()
    out["S11e"] = C.verdict(([] if C.SNAPSHOT_MARK in ctx_text else ["no stale snapshot in the SessionStart context"]) +
                            [f"memory call succeeded: {c.short}" for c in t.memory_calls() if not c.is_error])

    t = ctx.claude(host, Invocation("hi", "kit_repo", allow=SAVE), "S11b")
    notes = [] if C.OUTBOX_MARK in t.kit_context() else ["hook did not report the queued entry"]
    notes += C.expect_one(ctx.found(tok, since), repo=ctx.cfg.general_repo, project=None, scope="general")
    left = ctx.outbox_files(host, tok)
    notes += [f"outbox entry not removed: {left}"] if left else []
    out["S11b"] = C.verdict(notes + C.no_prompts(t))
    return out


def s14_s7(ctx: Ctx, host: Host, i: int = 0) -> Verdicts:
    """S14: after /compact the hook prompts a re-index and the early memory is still known. S7: a save
    after compaction still routes correctly."""
    sid = str(uuid.uuid4())
    tok1, since = ctx.token(), ctx.since()
    ctx.claude(host, Invocation(ctx.prompt("S2", i, token=tok1), "sample_app", allow=SAVE, session_id=sid), "S14a")
    t2 = ctx.claude(host, Invocation("/compact", "sample_app", resume=sid), "S14b")
    t3 = ctx.claude(host, Invocation("What is the e2e marker I asked you to remember earlier in this session?",
                                     "sample_app", resume=sid), "S14c")
    notes = [] if any(C.COMPACT_MARK in h.context for h in t2.hooks + t3.hooks) else ["no compaction re-index line"]
    if not (t2.memory_calls("memory_index") or t3.memory_calls("memory_index")):
        notes.append("memory_index not called after compaction")
    if tok1 not in t3.final_text:
        notes.append("early memory not recalled")
    tok2 = ctx.token()
    t4 = ctx.claude(host, Invocation(ctx.prompt("S2", i + 1, token=tok2), "sample_app", allow=SAVE, resume=sid), "S7")
    s7 = C.expect_one(ctx.found(tok2, since), repo=ctx.cfg.general_repo, project=None, scope="general")
    return {"S14": C.verdict(notes), "S7": C.verdict(s7 + C.announced(t4, "saved to general"))}


def s16(ctx: Ctx, host: Host, i: int = 0) -> Verdicts:
    """Soft: parallel saves where a call may fail in transit (ECONNRESET). Each fact must end up stored exactly
    once, with no duplicate or conflict copies. Informational: a dropped connection is often GitHub's or the
    network's, so this never fails the run."""
    base = ctx.token()
    facts = ctx.cfg.prompts["S16_facts"]
    marks = [f"{base}-{n}" for n in range(1, len(facts) + 1)]
    lines = "\n".join(f"- {m}: {f}" for m, f in zip(marks, facts))
    since = ctx.since()
    t = ctx.claude(host, Invocation(ctx.prompt("S16", i, facts=lines), "sample_app", allow=SAVE, max_turns=20), "S16")
    notes, dropped = [], [c for c in t.memory_calls("memory_save") if c.is_error and c.status is None]
    for m in marks:
        hits = ctx.found(m, since)
        live = {f.path for f in hits if not f.parts["conflict"]}
        conflicts = {f.path for f in hits if f.parts["conflict"]}
        if len(live) != 1:
            notes.append(f"{m}: stored {len(live)} times")
        if conflicts:
            notes.append(f"{m}: conflict copies {sorted(conflicts)}")
    v = C.verdict(notes, soft=True)
    v.notes.append(f"{len(t.memory_calls('memory_save'))} save calls, {len(dropped)} failed in transit")
    return {"S16": v}


# ---------- two-host scenarios (a: the Mac, b: a VM)

def _save_named(ctx: Ctx, host: Host, name: str, body: str, label: str) -> Transcript:
    return ctx.claude(host, Invocation(ctx.prompt("named_save", name=name, body=body), "sample_app", allow=SAVE), label)


def s6(ctx: Ctx, a: Host, b: Host, project: bool = False) -> Verdicts:
    tok, since = ctx.token(), ctx.since()
    key = "S4" if project else "S2"
    ctx.claude(a, Invocation(ctx.prompt(key, 0, token=tok), "sample_app", allow=SAVE), "S6a")
    live = [f for f in ctx.found(tok, since) if not f.parts["conflict"]]
    if not live:
        return {"S6": C.verdict(["the save on host A did not land"])}
    name = live[0].parts["name"] or ""
    t = ctx.claude(b, Invocation("hi", "sample_app"), "S6b")
    seen = any(name in (c.result or "") for c in t.memory_calls("memory_index"))
    return {"S6": C.verdict([] if seen else [f"{name} not in host B's session-start index"])}


def s9(ctx: Ctx, a: Host, b: Host) -> Verdicts:
    name, since = ctx.token(), ctx.since()
    _save_named(ctx, a, name, f"original {name}", "S9-0")
    sa, sb = str(uuid.uuid4()), str(uuid.uuid4())
    read = ctx.prompt("named_read", name=name)
    ctx.claude(a, Invocation(read, "sample_app", session_id=sa), "S9-a1")
    ctx.claude(b, Invocation(read, "sample_app", session_id=sb), "S9-b1")
    ta = ctx.claude(a, Invocation(ctx.prompt("named_update", name=name, body=f"edited on A {name}"), "sample_app",
                                  allow=SAVE, resume=sa), "S9-a2")
    tb = ctx.claude(b, Invocation(ctx.prompt("named_update", name=name, body=f"edited on B {name}"), "sample_app",
                                  allow=SAVE, resume=sb), "S9-b2")
    notes = [] if [c.status for c in ta.memory_calls("memory_save")][-1:] == ["updated"] else ["host A's update did not apply"]
    if "conflict" not in [c.status for c in tb.memory_calls("memory_save")]:
        notes.append("host B's stale update did not produce a conflict")
    copies = [f.path for f in ctx.found(f"edited on B {name}", since) if f.parts["conflict"]]
    if not copies:
        return {"S9": C.verdict(notes + ["no conflict copy in the repo"])}
    sc = str(uuid.uuid4())
    ctx.claude(a, Invocation("hi", "sample_app", allow=SAVE_DELETE, session_id=sc), "S9-c1")
    ctx.claude(a, Invocation(ctx.prompt("reconcile_yes"), "sample_app", allow=SAVE_DELETE, resume=sc), "S9-c2")
    if ctx.gh.exists(ctx.cfg.general_repo, copies[0]):
        notes.append(f"conflict copy {copies[0]} still there after reconciling")
    return {"S9": C.verdict(notes)}


def s11c(ctx: Ctx, a: Host, b: Host) -> Verdicts:
    name, since = ctx.token(), ctx.since()
    _save_named(ctx, a, name, f"original {name}", "S11c-0")
    sa = str(uuid.uuid4())
    ctx.claude(a, Invocation(ctx.prompt("named_read", name=name), "sample_app", session_id=sa), "S11c-a1")
    queued = f"queued on A {name}"
    ctx.claude(a, Invocation(ctx.prompt("named_update", name=name, body=queued), "sample_app", allow=SAVE,
                             resume=sa, no_connector=True), "S11c-a2")
    notes = [] if len(ctx.outbox_files(a, name)) == 1 else ["host A did not queue the update"]
    ctx.claude(b, Invocation(ctx.prompt("named_read_update", name=name, body=f"edited on B {name}"), "sample_app",
                             allow=SAVE), "S11c-b")
    ctx.claude(a, Invocation("hi", "sample_app", allow=SAVE), "S11c-a3")
    copies = [f.path for f in ctx.found(queued, since) if f.parts["conflict"]]
    plain = [f.path for f in ctx.found(queued, since) if not f.parts["conflict"]]
    notes += [] if copies else ["the stale queued update did not become a conflict copy"]
    notes += [f"the stale queued update overwrote the memory: {plain}"] if plain else []
    notes += [f"outbox entry not removed: {ctx.outbox_files(a, name)}"] if ctx.outbox_files(a, name) else []
    return {"S11c": C.verdict(notes)}


def s13(ctx: Ctx, a: Host, b: Host) -> Verdicts:
    sb = str(uuid.uuid4())
    ctx.claude(b, Invocation("hi", "sample_app", session_id=sb), "S13-b1")
    name = ctx.token()
    _save_named(ctx, a, name, f"saved on A while B runs {name}", "S13-a")
    t = ctx.claude(b, Invocation(ctx.prompt("named_search", name=name), "sample_app", resume=sb), "S13-b2")
    results = " ".join(c.result or "" for c in t.memory_calls())
    notes = [] if "Memory changed since your index" in results else ["no change notice in host B's tool results"]
    notes += [] if name in results else [f"{name} not in host B's results"]
    return {"S13": C.verdict(notes)}


def u1(ctx: Ctx, host: Host, i: int = 0) -> Verdicts:
    """After `setup.sh --uninstall` and with the connector removed: no kit hooks, no memory tool calls,
    and auto-memory writes locally again. The user runs the uninstall and the reinstall (Task 11)."""
    t = ctx.claude(host, Invocation("hi", "sample_app", no_connector=True), "U1a")
    notes = ["kit SessionStart hook still fires"] if t.kit_context() else []
    notes += [f"memory tool called: {c.short}" for c in t.memory_calls()]
    tok = ctx.token()
    marker = ctx.marker(host, tok)
    t = ctx.claude(host, Invocation(ctx.prompt("U1", token=tok), "sample_app", no_connector=True), "U1b")
    notes += ["kit prompt hook still fires"] if any("claude-memory:" in h.context for h in t.hooks
                                                    if h.name.startswith("UserPromptSubmit")) else []
    files = ctx.sh(host, f"find ~/.claude/projects -path '*/memory/*' -type f -newer {marker} "
                         f"-exec grep -l -- {shlex.quote(tok)} {{}} + 2>/dev/null; true").split()
    notes += [] if files else ["no auto-memory file holds the fact"]
    return {"U1": C.verdict(notes)}


SINGLE = {"S1": s1_s12h, "S2": s2, "S3": s3, "S4": s4, "S4n": s4n, "S5": s5, "S8": s8,
          "S11": s11_chain, "S14": s14_s7, "S16": s16, "U1": u1}
PAIR = {"S6": s6, "S6p": lambda ctx, a, b: {"S6p": s6(ctx, a, b, project=True)["S6"]},
        "S9": s9, "S11c": s11c, "S13": s13}
REPEATED = ("S2", "S4", "S5")   # spec: routing prompts run 3x per host; all runs must pass
```

- [ ] **Step 5: Run the tests**

Run: `npm run test:e2e && /usr/bin/python3 -m unittest discover -s test/e2e`
Expected: OK (38 tests) on both.

- [ ] **Step 6: Commit**

```bash
git add test/e2e/e2elib/scenarios.py test/e2e/fakes.py test/e2e/test_scenarios.py
git commit -m "test(e2e): Level 4 scenarios S0-S16 and U1 as outcome checks, with scripted-transcript tests"
```

---

### Task 6: Results grid, cleanup, the CLI and its README

**Files:**
- Create: `test/e2e/e2elib/results.py`, `test/e2e/e2elib/cleanup.py`, `test/e2e/run.py`, `test/e2e/test_results.py`, `test/e2e/README.md`

**Interfaces:**
- Consumes: Tasks 3–5.
- Produces:
  - `results.record(run_dir, host, scenario, verdict, layers)`, `results.load(run_dir)`, `results.cell(statuses)` and `results.render(run_id, records, hosts) -> str`.
  - `cleanup.cleanup(ctx, since, hosts) -> List[str]`.
  - The CLI `run.py [--run-id ID] {hosts,run,pair,probe,token,verify,report,cleanup}`.
  - Run state in `results/raw/<run>/meta.json` (`run_id`, `started`, `layers`), `records.jsonl` and `manual.jsonl`.

- [ ] **Step 1: Write the failing test** — `test/e2e/test_results.py`

```python
"""Grid cells and rendering; cleanup touches only this run's files."""
import tempfile
import unittest
from pathlib import Path

from e2elib import checks as C
from e2elib import results
from e2elib.cleanup import cleanup
from e2elib.gh import Commit
from fakes import CFG, HOST, FakeShell


class Cells(unittest.TestCase):
    def test_cells(self):
        self.assertEqual(results.cell([C.PASS] * 3), "PASS 3/3")
        self.assertEqual(results.cell([C.PASS, C.FAIL, C.PASS]), "FAIL 2/3")
        self.assertEqual(results.cell([C.PASS]), "PASS")
        self.assertEqual(results.cell([C.SOFT_FAIL]), "soft ✗ 0/1")
        self.assertEqual(results.cell([C.SOFT_PASS]), "soft ✓")
        self.assertEqual(results.cell([C.PASS, C.ERROR]), "ERROR 1/2")

    def test_render_without_records(self):
        self.assertEqual(results.render("r1", [], []), "# Level 4 results — run r1\n\nNo results recorded.\n")

    def test_record_and_render(self):
        d = Path(tempfile.mkdtemp())
        results.record(d, "H1", "S2", C.Verdict(C.PASS), "A+C")
        results.record(d, "H1", "S2", C.Verdict(C.FAIL, ["saved to x"]), "A+C")
        results.record(d, "H3", "S1", C.Verdict(C.PASS), "A+C")
        results.record(d, "H1", "S16", C.Verdict(C.SOFT_PASS, ["8 save calls, 0 failed in transit"]), "A+C")
        md = results.render("r1", results.load(d), [("H1", "Mac CLI"), ("H3", "earsvm")])
        self.assertIn("| S1 | — | PASS |", md)
        self.assertIn("| S2 | FAIL 1/2 | — |", md)
        self.assertIn("| S16 | soft ✓ | — |", md)
        self.assertIn("- **S2 on H1:** saved to x", md)
        self.assertIn("- **S16 on H1:** 8 save calls", md)
        self.assertLess(md.index("| S1 |"), md.index("| S2 |"))


class Cleanup(unittest.TestCase):
    def test_deletes_only_this_runs_files_and_outbox_entries(self):
        class Gh:
            deleted = []

            def commits_since(self, repo, since):
                return [Commit("a", "", [("memories/mine.md", "added"), ("memories/other.md", "added"),
                                         ("MEMORY.md", "modified")])] if repo == CFG.general_repo else []

            def file_text(self, repo, path, ref="HEAD"):
                return {"memories/mine.md": "x e2e-r1-03", "memories/other.md": "real memory"}.get(path)

            def delete(self, repo, path, message):
                self.deleted.append(path)
                return True

        class Ctx:
            run_id, cfg, gh = "r1", CFG, Gh()
            sh = FakeShell({"grep -l": lambda s: "/h/.claude-memory-cloud/outbox/20261015T120000Z-e2e.md\n"})

            def outbox_files(self, host, token):
                return self.sh(host, f"grep -l {token}").split()
        c = Ctx()
        removed = cleanup(c, "2026-10-15T12:00:00Z", [HOST])
        self.assertEqual(c.gh.deleted, ["memories/mine.md"])
        self.assertEqual(removed, [f"{CFG.general_repo}/memories/mine.md", "H1:outbox/20261015T120000Z-e2e.md"])
        self.assertIn("memkit.py outbox-done 20261015T120000Z-e2e.md", c.sh.seen[-1])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s test/e2e -p test_results.py`
Expected: `ModuleNotFoundError: No module named 'e2elib.results'`.

- [ ] **Step 3: Implement** — `test/e2e/e2elib/results.py`

```python
"""Record verdicts (results/raw/<run>/records.jsonl, gitignored) and render the host x scenario grid
(results/<date>.md, committed). Notes are the runner's own strings; memory content never goes in them."""
from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Tuple

from .checks import ERROR, FAIL, PASS, SOFT_FAIL, SOFT_PASS, Verdict

ORDER = ["S0", "S1", "S2", "S3", "S4", "S4n", "S5", "S6", "S6p", "S7", "S8", "S9", "S10", "S11", "S11b", "S11c",
         "S11d", "S11e", "S11f", "S12", "S12h", "S13", "S14", "S15", "S16", "U1"]


def record(run_dir: Path, host: str, scenario: str, v: Verdict, layers: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "records.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"host": host, "scenario": scenario, "status": v.status, "notes": v.notes,
                            "layers": layers}) + "\n")


def load(run_dir: Path) -> List[dict]:
    p = run_dir / "records.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def cell(statuses: List[str]) -> str:
    """One grid cell. Hard results: PASS only if every run passed. Soft results never read as FAIL."""
    n = len(statuses)
    if all(s in (SOFT_PASS, SOFT_FAIL) for s in statuses):
        ok = statuses.count(SOFT_PASS)
        return "soft ✓" if ok == n else f"soft ✗ {ok}/{n}"
    ok = statuses.count(PASS)
    if ERROR in statuses:
        return f"ERROR {ok}/{n}"
    return ("PASS" if ok == n else "FAIL") + (f" {ok}/{n}" if n > 1 else "")


def render(run_id: str, records: List[dict], hosts: List[Tuple[str, str]]) -> str:
    """Markdown: a grid (rows: scenarios, columns: hosts) then the notes of every non-pass."""
    if not records:
        return f"# Level 4 results — run {run_id}\n\nNo results recorded.\n"
    grid: Dict[Tuple[str, str], List[str]] = {}
    layers = sorted({r["layers"] for r in records})
    for r in records:
        grid.setdefault((r["scenario"], r["host"]), []).append(r["status"])
    rows = [s for s in ORDER if any(k[0] == s for k in grid)]
    out = [f"# Level 4 results — run {run_id}", "", f"Layers: {', '.join(layers)}", "",
           "| Scenario | " + " | ".join(f"{h} {label}" for h, label in hosts) + " |",
           "|---|" + "---|" * len(hosts)]
    for s in rows:
        out.append(f"| {s} | " + " | ".join(cell(grid[(s, h)]) if (s, h) in grid else "—" for h, _ in hosts) + " |")
    failures = OrderedDict()
    for r in records:
        if r["status"] not in (PASS, SOFT_PASS) or (r["status"] == SOFT_PASS and r["notes"]):
            failures.setdefault(f"{r['scenario']} on {r['host']}", []).extend(r["notes"])
    if failures:
        out += ["", "## Notes", ""]
        for k, notes in failures.items():
            out.append(f"- **{k}:** " + "; ".join(dict.fromkeys(notes)))
    return "\n".join(out) + "\n"
```

`test/e2e/e2elib/cleanup.py` (if Task 1 V5 failed, apply the fallback from Task 1 Step 6 here)

```python
"""Remove what a run left behind: test memories in the repos and queued test entries in host outboxes."""
from __future__ import annotations

import shlex
from typing import List

from .gh import MEMORY_PATH
from .launch import Host


def cleanup(ctx, since: str, hosts: List[Host]) -> List[str]:
    """Deletes every memory file touched since `since` whose text holds this run's `e2e-<run_id>-` prefix
    (conflict copies included), and every outbox entry holding it. Returns what was removed."""
    prefix = f"e2e-{ctx.run_id}-"
    removed: List[str] = []
    for repo in ctx.cfg.repos:
        paths = {p for c in ctx.gh.commits_since(repo, since) for p, _ in c.files if MEMORY_PATH.match(p)}
        for p in sorted(paths):
            text = ctx.gh.file_text(repo, p)
            if text and prefix in text and ctx.gh.delete(repo, p, f"e2e cleanup {ctx.run_id}"):
                removed.append(f"{repo}/{p}")
    for h in hosts:
        for f in ctx.outbox_files(h, prefix):
            name = f.rsplit("/", 1)[-1]
            ctx.sh(h, f"{h.python} -I -S ~/.claude-memory-cloud/kit/bin/memkit.py outbox-done {shlex.quote(name)}")
            removed.append(f"{h.id}:outbox/{name}")
    return removed
```

`test/e2e/run.py`

```python
#!/usr/bin/env python3
"""Level 4 runner (spec §9): drives `claude -p` on the test hosts and checks outcomes with `gh api`.

  run.py hosts                                   check each host is reachable and ready
  run.py run   --hosts H1,H3 --scenarios S1,S2   single-host scenarios (S2/S4/S5 repeat 3x)
  run.py pair  --a H1 --b H3 --scenarios S6,S9   two-host scenarios
  run.py probe --host H1 --expect-problem TEXT   one session; check the preflight / Health output
  run.py token --scenario S2                     manual hosts: print a prompt with a fresh token
  run.py verify --token T --scenario S2 --host H6
  run.py report                                  write results/<date>-<run>.md
  run.py cleanup                                 delete this run's test memories and outbox entries

Every command takes --run-id (default: the latest run, or a new one for `run`/`pair`/`token`)."""
from __future__ import annotations

import argparse
import json
import random
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from e2elib import checks as C                         # noqa: E402
from e2elib import config, results, scenarios          # noqa: E402
from e2elib.cleanup import cleanup                     # noqa: E402
from e2elib.gh import GitHub                           # noqa: E402
from e2elib.launch import Invocation, shell            # noqa: E402

HERE = Path(__file__).resolve().parent
RAW = HERE / "results" / "raw"
PROMPT_HINT_OFF = {"CLAUDE_MEMORY_KIT_PROMPT_HINT": "off"}
MANUAL_EXPECT = {"S2": "general", "S3": "client", "S4": "project", "S4n": "none", "S8": "none", "S11d": "none"}


def new_run_id() -> str:
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))


def latest_run() -> str:
    runs = sorted(RAW.glob("*/meta.json"), key=lambda p: p.stat().st_mtime)
    if not runs:
        sys.exit("no runs yet")
    return runs[-1].parent.name


def open_run(run_id: str, create: bool, layers: str = "A+B+C") -> dict:
    meta_path = RAW / run_id / "meta.json"
    if meta_path.exists():
        return json.loads(meta_path.read_text())
    if not create:
        sys.exit(f"unknown run {run_id}")
    meta = {"run_id": run_id, "started": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "layers": layers}
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta))
    return meta


def make_ctx(cfg, meta) -> scenarios.Ctx:
    env = PROMPT_HINT_OFF if meta["layers"] == "A+C" else {}
    return scenarios.Ctx(cfg, GitHub(), meta["run_id"], RAW / meta["run_id"], env=env)


def save(meta, host, verdicts) -> bool:
    ok = True
    for sid, v in verdicts.items():
        results.record(RAW / meta["run_id"], host, sid, v, meta["layers"])
        print(f"  {host} {sid}: {v.status}" + (f" — {'; '.join(v.notes)}" if v.notes else ""))
        ok = ok and v.status not in (C.FAIL, C.ERROR)
    return ok


def guarded(fn, *args) -> scenarios.Verdicts:
    """A crash in one scenario becomes an ERROR row instead of stopping the run."""
    try:
        return fn(*args)
    except Exception as e:  # noqa: BLE001
        return {"ERROR": C.Verdict(C.ERROR, [f"{type(e).__name__}: {e}"[:300]])}


def cmd_hosts(cfg, args) -> int:
    bad = 0
    for h in cfg.hosts.values():
        dirs = " ".join(f'test -d {d} || echo "missing {k}={d}";' for k, d in h.dirs.items())
        try:
            out = shell(h, f"{h.claude} --version; {h.python} --version; gh --version >/dev/null 2>&1 || true; {dirs}")
            print(f"{h.id} {h.label}: " + " | ".join(out.split("\n")).strip(" |"))
            bad += out.count("missing ")
        except RuntimeError as e:
            print(f"{h.id} {h.label}: UNREACHABLE {e}")
            bad += 1
    return 1 if bad else 0


def cmd_run(cfg, args) -> int:
    meta = open_run(args.run_id or new_run_id(), True, args.layers)
    ctx, ok = make_ctx(cfg, meta), True
    print(f"run {meta['run_id']} ({meta['layers']})")
    for hid in args.hosts.split(","):
        host = cfg.hosts[hid]
        for sid in args.scenarios.split(","):
            fn = scenarios.SINGLE[sid]
            for i in range(cfg.repeats if sid in scenarios.REPEATED else 1):
                ok = save(meta, hid, guarded(fn, ctx, host, i)) and ok
                if not args.keep:
                    cleanup(ctx, meta["started"], [host])
    return 0 if ok else 1


def cmd_pair(cfg, args) -> int:
    meta = open_run(args.run_id or new_run_id(), True, args.layers)
    ctx, a, b, ok = make_ctx(cfg, meta), cfg.hosts[args.a], cfg.hosts[args.b], True
    print(f"run {meta['run_id']} ({meta['layers']}) pair {a.id}+{b.id}")
    for sid in args.scenarios.split(","):
        ok = save(meta, f"{a.id}+{b.id}", guarded(scenarios.PAIR[sid], ctx, a, b)) and ok
        if not args.keep:
            cleanup(ctx, meta["started"], [a, b])
    return 0 if ok else 1


def cmd_probe(cfg, args) -> int:
    meta = open_run(args.run_id or latest_run(), False)
    ctx, host = make_ctx(cfg, meta), cfg.hosts[args.host]
    t = ctx.claude(host, Invocation("hi", args.cwd), f"probe-{args.label}")
    if args.expect_problem:
        notes = C.exactly_one_problem(t, args.expect_problem)
    elif args.expect_health:
        health = " ".join(c.result or "" for c in t.memory_calls("memory_index"))
        notes = [] if args.expect_health in health else [f"Health block lacks {args.expect_health!r}"]
    else:
        notes = C.kit_healthy(t)
    return 0 if save(meta, args.host, {args.label: C.verdict(notes)}) else 1


def cmd_token(cfg, args) -> int:
    meta = open_run(args.run_id or new_run_id(), True, args.layers)
    ctx = make_ctx(cfg, meta)
    tok = f"e2e-{meta['run_id']}-m{random.randint(100, 999)}"
    values = {"token": tok, "secret": scenarios.fake_secret(random.Random(tok))}
    entry = {"token": tok, "scenario": args.scenario, "since": ctx.since()}
    with open(RAW / meta["run_id"] / "manual.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"run {meta['run_id']}  token {tok}\n\nPaste this into the session:\n\n{ctx.prompt(args.scenario, args.i, **values)}")
    return 0


def cmd_verify(cfg, args) -> int:
    meta = open_run(args.run_id or latest_run(), False)
    ctx = make_ctx(cfg, meta)
    entries = [json.loads(x) for x in (RAW / meta["run_id"] / "manual.jsonl").read_text().splitlines() if x]
    entry = next(e for e in entries if e["token"] == args.token)
    found, kind = ctx.found(args.token, entry["since"]), MANUAL_EXPECT[args.scenario]
    if kind == "none":
        notes = C.expect_none(found)
    elif kind == "general":
        notes = C.expect_one(found, repo=cfg.general_repo, project=None, scope="general")
    elif kind == "client":
        notes = C.expect_one(found, repo=cfg.client_repo, project=None, scope=cfg.client_scope)
    else:
        notes = C.expect_one(found, repo=cfg.client_repo, project=ctx.sample_repo_name(), scope=ctx.project_scope())
    return 0 if save(meta, args.host, {args.scenario: C.verdict(notes)}) else 1


def cmd_report(cfg, args) -> int:
    meta = open_run(args.run_id or latest_run(), False)
    recs = results.load(RAW / meta["run_id"])
    hosts = sorted({r["host"] for r in recs}, key=lambda h: (len(h), h))
    labels = [(h, "+".join(cfg.hosts[x].label if x in cfg.hosts else x for x in h.split("+"))) for h in hosts]
    out = HERE / "results" / f"{meta['started'][:10]}-{meta['run_id']}.md"
    out.write_text(results.render(meta["run_id"], recs, labels), encoding="utf-8")
    print(out)
    return 0


def cmd_cleanup(cfg, args) -> int:
    meta = open_run(args.run_id or latest_run(), False)
    for line in cleanup(make_ctx(cfg, meta), meta["started"], list(cfg.hosts.values())):
        print("removed", line)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-id")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hosts")
    for name in ("run", "pair", "token"):
        s = sub.add_parser(name)
        s.add_argument("--layers", choices=["A+C", "A+B+C"], default="A+B+C")
    sub.choices["run"].add_argument("--hosts", required=True)
    sub.choices["run"].add_argument("--scenarios", required=True)
    sub.choices["pair"].add_argument("--a", required=True)
    sub.choices["pair"].add_argument("--b", required=True)
    sub.choices["pair"].add_argument("--scenarios", required=True)
    for name in ("run", "pair"):
        sub.choices[name].add_argument("--keep", action="store_true", help="skip cleanup after each scenario")
    s = sub.add_parser("probe")
    s.add_argument("--host", required=True)
    s.add_argument("--cwd", default="kit_repo")
    s.add_argument("--label", default="S12")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--expect-problem")
    g.add_argument("--expect-health")
    sub.choices["token"].add_argument("--scenario", required=True, choices=sorted(MANUAL_EXPECT))
    sub.choices["token"].add_argument("--i", type=int, default=0)
    s = sub.add_parser("verify")
    s.add_argument("--token", required=True)
    s.add_argument("--scenario", required=True, choices=sorted(MANUAL_EXPECT))
    s.add_argument("--host", required=True)
    sub.add_parser("report")
    sub.add_parser("cleanup")
    args = p.parse_args(argv)
    cfg = config.load()
    return {"hosts": cmd_hosts, "run": cmd_run, "pair": cmd_pair, "probe": cmd_probe, "token": cmd_token,
            "verify": cmd_verify, "report": cmd_report, "cleanup": cmd_cleanup}[args.cmd](cfg, args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Write `test/e2e/README.md`**

```markdown
# Level 4 end-to-end tests

Drives real Claude Code sessions against the **staging** server and checks the outcome in the test repos
(`davlion/claude-memory-test`, `davlion-test-client/claude-memory`) with `gh api`. Spec: §9 Level 4.

**Safety:** it writes only to those two repos. Every test memory carries `e2e-<run>-<n>`, and cleanup deletes
only files holding the run's token. Raw transcripts (`results/raw/`) hold memory content and are gitignored.

Run from the Mac in a normal terminal (not inside a Claude Code session if you can avoid it; the runner
scrubs the parent session's variables either way). Needs `gh` signed in with access to both repos, and the
VMs on for H3/H4.

    python3 test/e2e/run.py hosts                                       # reachability
    python3 test/e2e/run.py run --layers A+C --hosts H1,H3,H4 --scenarios S1,S2,S3,S4,S4n,S5,S8
    python3 test/e2e/run.py run --hosts H1 --scenarios S11,S14,S16
    python3 test/e2e/run.py pair --a H1 --b H3 --scenarios S6,S9,S11c,S13
    python3 test/e2e/run.py report                                      # results/<date>-<run>.md
    python3 test/e2e/run.py cleanup                                     # after a crash or --keep

Manual hosts (Desktop app, cloud, web chat, mobile): `run.py token --scenario S2` prints a prompt with a
fresh token; paste it, then `run.py verify --token <t> --scenario S2 --host H6`.

Offline unit tests: `npm run test:e2e`.
```

- [ ] **Step 5: Run the tests and a CLI smoke test**

```bash
npm run test:e2e && /usr/bin/python3 -m unittest discover -s test/e2e
python3 test/e2e/run.py --help | head -3
python3 test/e2e/run.py --run-id smoke1 token --scenario S2 && python3 test/e2e/run.py --run-id smoke1 report && rm -rf test/e2e/results/raw/smoke1 test/e2e/results/*-smoke1.md
```
Expected:
- 42 tests OK on both interpreters
- the usage line
- a prompt ending `Tag: e2e-smoke1-m<nnn>`
- a report path whose file says "No results recorded."

- [ ] **Step 6: Commit**

```bash
git add test/e2e/e2elib/results.py test/e2e/e2elib/cleanup.py test/e2e/run.py test/e2e/test_results.py test/e2e/README.md
git commit -m "test(e2e): results grid, token-scoped cleanup, run.py CLI and README"
```

---

### Task 7: Live run 1 — layers A + C only (manual, with the user)

The spec's first run decides whether layer B is needed. Hosts on, Task 1 green. This costs real model usage: about 40 `claude -p` sessions. Tell the user before starting.

- [ ] **Step 1: Reachability**

Run: `python3 test/e2e/run.py hosts`
Expected: exit 0. Each host line shows its claude and Python versions, and no `missing`.

- [ ] **Step 2: Single-host routing and basics, all scripted hosts**

```bash
python3 test/e2e/run.py run --layers A+C --hosts H1,H3,H4 --scenarios S1,S2,S3,S4,S4n,S5,S8
```
This prints one line per verdict. Expected: mostly PASS. Don't fix anything yet. For each FAIL:
- read its raw transcript in `results/raw/<run>/`
- classify it: routing (Claude's choice), plumbing (runner or kit bug), or environment (auth, VM)
- add one line to the ledger

Plumbing bugs get fixed (TDD, in the owning file) and the scenario is re-run in the same run id with `--run-id`.

- [ ] **Step 3: Report and commit the grid**

```bash
python3 test/e2e/run.py report
git add test/e2e/results/<date>-<run>.md && git commit -m "test(e2e): Level 4 run 1 (layers A+C)"
```

- [ ] **Step 4: Decide on layer B with the user.** Compare S2/S4/S5 on prompts that match the trigger phrases vs those that don't.
  - If A + C alone is at 3/3 everywhere, B is optional. Record that the user may keep it as defense in depth.
  - Otherwise B stays, and run 2 must show it closing the gap.

---

### Task 8: Live run 2 — layers A + B + C, including the multi-host and soft scenarios (manual, with the user)

- [ ] **Step 1: Single-host scenarios with B on**

```bash
python3 test/e2e/run.py run --hosts H1,H3,H4 --scenarios S1,S2,S3,S4,S4n,S5,S8
RUN=$(ls -t test/e2e/results/raw | head -1)
python3 test/e2e/run.py --run-id "$RUN" run --hosts H1,H3 --scenarios S11,S14
python3 test/e2e/run.py --run-id "$RUN" run --hosts H1 --scenarios S16
```

- [ ] **Step 2: Two-host scenarios** (spec pairs)

```bash
python3 test/e2e/run.py --run-id "$RUN" pair --a H1 --b H3 --scenarios S6,S9,S11c,S13
python3 test/e2e/run.py --run-id "$RUN" pair --a H4 --b H1 --scenarios S6p
```
S11c and S9 need host B's session to keep its version across `--resume` (V3). If either fails only on that, record it, then re-run once with `--keep` and read both transcripts before changing anything.

- [ ] **Step 3: Triage** exactly as in Task 7 Step 2. S16 is soft: record its notes, including how many saves failed in transit, but don't block on it. If S16 shows a duplicate or a missing memory, file it as a server follow-up (Plan 4 list) with the transcript reference. Don't change the server in this plan.

- [ ] **Step 4: Report and commit**

```bash
python3 test/e2e/run.py --run-id "$RUN" report
git add test/e2e/results/<date>-"$RUN".md && git commit -m "test(e2e): Level 4 run 2 (layers A+B+C, multi-host, soft S16)"
```

---

### Task 9: Manual hosts — H2 Desktop app, H5 cloud, H6 web chat, H7 mobile (with the user)

The user types; the runner prints the prompts and checks the outcomes. Use run 2's run id. For every row, the runner command comes first and the user's action second.

| Host | Scenarios | How |
|---|---|---|
| H2 Desktop app, Code session in `~/src/sample-app` | S1, S2, S3, S4, S0 | S1: open a new session; Claude loads the index unprompted (user confirms). Others: `token` → paste → `verify`. S0: `/context` shows no auto-memory instruction. |
| H5 cloud session on `davlion-test-client/sample-app` (unless scripted per V7) | S0, S1, S2, S3, S4, S5, S7, S14, S11d | S0: `/context` (also closes spec §11 "env var takes effect in cloud"). S14/S7: `/compact` then ask about the early memory, then save again (`verify`). S11d: disconnect the connector for that session, try a save: "not saved: <reason>", nothing queued (`verify` with S11d). |
| H6 claude.ai web chat | S1, S2, S5, S8, S11d, S6 (H5→H6, general only) | S6: save on H5 (`token S2`), then a new chat on H6: "what do you remember about <token>?" The user confirms it's found. |
| H7 Claude mobile | S1, S2 (spot check) | `token` → paste → `verify`. |

- [ ] **Step 1:** For each scripted-check row: `python3 test/e2e/run.py --run-id "$RUN" token --scenario S2`, the user pastes the prompt into the host, then `python3 test/e2e/run.py --run-id "$RUN" verify --token <t> --scenario S2 --host H6`.
- [ ] **Step 2:** For rows the user confirms by eye (S1 on H2/H6/H7, S0 `/context`, S5 question, S6 on H6), append a record by hand:

```bash
/usr/bin/python3 -c 'import sys; sys.path.insert(0,"test/e2e"); from pathlib import Path; from e2elib import results, checks as C
results.record(Path("test/e2e/results/raw")/sys.argv[1], sys.argv[2], sys.argv[3], C.Verdict(sys.argv[4], sys.argv[5:]), "A+B+C")' "$RUN" H6 S1 PASS "manual: user confirmed"
```
- [ ] **Step 3:** `python3 test/e2e/run.py --run-id "$RUN" cleanup && python3 test/e2e/run.py --run-id "$RUN" report`, then commit the updated grid as in Task 8 Step 4 with message `test(e2e): Level 4 manual hosts`.

---

### Task 10: Breaking things on purpose — S10, S12, S15 (guarded, with the user)

One break at a time. Each break comes with its undo, done in the same step and verified. The user does every account-side change in the GitHub UI. Use run 2's run id for `probe`.

- [ ] **Step 1: Back up the local files S12 touches** (Mac)

```bash
B=~/e2e-s12-backup; mkdir -p "$B"
cp -p ~/.claude/settings.json ~/.claude/CLAUDE.md ~/.claude-memory-cloud/scopes.json ~/.claude-memory-cloud/config.json "$B"/
shasum "$B"/* > "$B/SHA"
```

- [ ] **Step 2: S12 local breaks, one at a time** (Mac, H1). Each line is break → probe → restore → check.

```bash
cd ~/src/claude-memory-cloud; P="python3 test/e2e/run.py --run-id $RUN probe --host H1 --label S12"
restore() { cp -p "$B/settings.json" "$B/CLAUDE.md" ~/.claude/; cp -p "$B/scopes.json" "$B/config.json" ~/.claude-memory-cloud/; (cd "$B" && shasum -c SHA >/dev/null) && echo restored; }
# auto-memory on
/usr/bin/python3 -c 'import json,os;p=os.path.expanduser("~/.claude/settings.json");d=json.load(open(p));d["autoMemoryEnabled"]=True;json.dump(d,open(p,"w"))'
$P --expect-problem "Built-in auto-memory is on"; restore
# routing rule removed
/usr/bin/python3 -c 'import os,re;p=os.path.expanduser("~/.claude/CLAUDE.md");s=open(p).read();open(p,"w").write(re.sub(r"<!-- claude-memory-cloud:routing-rule:begin -->.*?<!-- claude-memory-cloud:routing-rule:end -->\n?","",s,flags=re.S))'
$P --expect-problem "routing rule is missing"; restore
# scope map corrupt
printf '{not json' > ~/.claude-memory-cloud/scopes.json; $P --expect-problem "Scope map missing or invalid"; restore
# worker URL blocked
/usr/bin/python3 -c 'import json,os;p=os.path.expanduser("~/.claude-memory-cloud/config.json");d=json.load(open(p));d["worker_url"]="http://127.0.0.1:9";json.dump(d,open(p,"w"))'
$P --expect-problem "Can't reach the memory server"; restore
```
Expected: each probe prints `H1 S12: PASS` (exactly one problem line, the right one), and each `restore` prints `restored`. If any restore doesn't print `restored`, stop and restore from `$B` by hand with the user.

- [ ] **Step 3: S12 server-side breaks, S10 and S15** (the user acts in GitHub; the runner checks `memory_index`'s Health block). One at a time, and undo each before the next.

| Break (user) | Check | Undo (user) |
|---|---|---|
| Revoke the app's authorization (GitHub → Settings → Applications → Authorized GitHub Apps) | `$P --label S12 --cwd sample_app --expect-health reauth_required` | Reconnect the connector in claude.ai |
| S10: uninstall the app from `davlion-test-client` | `$P --label S10 --cwd sample_app --expect-health app_not_installed` | Reinstall on `davlion-test-client/claude-memory` only |
| Remove `davlion` from the test org (only if another owner exists; otherwise skip and record) | `--expect-health` with the org-membership detail the server reports | Re-invite |
| Point a scope to a missing repo: rename `davlion-test-client/claude-memory` to `claude-memory-x` | `--expect-health not_reachable` | Rename back |
| S15: make `davlion/claude-memory-test` public. **Warn the user that everything in it becomes public for the duration; check its contents first** (`gh api repos/davlion/claude-memory-test/contents/memories --jq '.[].name'`). | `--expect-health repo_public`, then `token --scenario S8`-style save of a harmless fact → "not saved: repo is public" | Make it private again immediately; re-probe: no health problem, and a save then succeeds (`token S2` → `verify`) |

On H5 (cloud), repeat the server-side checks that apply by eye, and record them as in Task 9 Step 2.

- [ ] **Step 4: S12h after all undos.** Run `python3 test/e2e/run.py --run-id "$RUN" run --hosts H1 --scenarios S1`. Expected: S1 and S12h PASS. Then `report` and commit the grid with message `test(e2e): Level 4 breakage scenarios`. Then `rm -rf ~/e2e-s12-backup`, with the user's OK.

---

### Task 11: U1 — uninstall really removes it (lume, with the user)

- [ ] **Step 1: Record lume's setup arguments and uninstall** (the user OKs)

```bash
ssh lumevm 'cat ~/.claude-memory-cloud/config.json; cd ~/src/claude-memory-cloud && ./setup.sh --uninstall --keep-cache'
```
Expected: exit 0, and `autoMemoryEnabled` back to its pre-install value (Plan 2 state). Keep the printed `worker_url` for the reinstall.

- [ ] **Step 2: Run U1**

```bash
python3 test/e2e/run.py --run-id "$RUN" run --hosts H4 --scenarios U1 --keep
```
Expected: `H4 U1: PASS`. That means no kit hook context, no prompt hint, no memory tool calls, and an auto-memory file under `~/.claude/projects/*/memory/` holding the token.

- [ ] **Step 3: Undo** — delete the test auto-memory file and its `MEMORY.md` line on lume (show the user first: `ssh lumevm "grep -rl e2e-$RUN ~/.claude/projects"`). Then reinstall with the Plan 2 arguments (`--mcp-server claude_ai_claude-memory-staging`, the `--scope` pairs, `--login davlion`). Then:
`python3 test/e2e/run.py --run-id "$RUN" run --hosts H4 --scenarios S1`. Expected: PASS.
- [ ] **Step 4:** `report`, then commit the grid with message `test(e2e): Level 4 U1 uninstall`.

---

### Task 12: Fold Plan 3 into the spec and docs

**Files:**
- Modify: `claude-memory-mcp/docs/superpowers/specs/2026-10-13-cloud-memory-design.md`
- Modify: `claude-memory-mcp/docs/superpowers/plans/2026-10-14-build-rulings.md`
- Modify: `docs/FAQ.md`
- Create: `docs/plan-3/build-ledger.md` (written during Tasks 1–11)

That repo has unrelated uncommitted files: a modified `2026-04-15` spec and an untracked `2026-04-15` plan. Never stage, modify or restore them. The S16 row already added to the spec (2026-10-15) is part of this task's spec commit.

- [ ] **Step 1: Spec §9 Level 4.**
  - Replace `tests/e2e/` with `test/e2e/` (Deviation 1).
  - In S11, replace "disable the staging connector with `/mcp`, or block the Worker" with "start the session with no MCP servers (`--strict-mcp-config --mcp-config '{\"mcpServers\":{}}'`)".
  - Add after the Results paragraph: "**Implementation notes (Plan 3):** the runner scrubs the parent session's environment (an inherited `ANTHROPIC_API_KEY` disables claude.ai connectors); the A + C run sets `CLAUDE_MEMORY_KIT_PROMPT_HINT=off`; U1 runs with no MCP servers to stand in for removing the connector; manual hosts use `run.py token` / `verify`. Results: `test/e2e/results/`."
- [ ] **Step 2: Spec §11.**
  - Strike or resolve "Confirm cloud sessions can be launched from the CLI" with Task 1 V7's answer.
  - Strike or resolve "Confirm that turning auto-memory off removes the built-in memory instruction" with S0 on H1/H2.
  - Strike or resolve "Confirm `CLAUDE_CODE_DISABLE_AUTO_MEMORY` … cloud" with S0 on H5.
  - Add an observed note on the similarity threshold: any `similar_found` seen in the runs, with counts.
- [ ] **Step 3: Spec §10 step 3** — after "Run Level 3, then Level 4", add "(Plan 3; the grids are in `test/e2e/results/`)". Update the Plan 2 notes: the Mac's setup needs `--mcp-server` for both the project-scoped server and the claude.ai connector name (Task 1 Step 3).
- [ ] **Step 4: Build rulings** — add a `## 2026-10-15-cloud-memory-e2e` section listing each ruling from the ledger. Add any server follow-ups (S16 findings, similarity) to "Known follow-ups → Before production (Plan 4)".
- [ ] **Step 5: FAQ** — add an entry "How is this tested end to end?": three sentences pointing to `test/e2e/README.md` and the latest grid.
- [ ] **Step 6: Commit both repos**

```bash
cd ~/src/claude-memory-mcp && git add docs/superpowers/specs/2026-10-13-cloud-memory-design.md docs/superpowers/plans/2026-10-14-build-rulings.md docs/superpowers/plans/2026-10-15-cloud-memory-e2e.md && git commit -m "docs: fold Plan 3 (Level 4 e2e) into the cloud memory spec"
cd ~/src/claude-memory-cloud && git add docs/FAQ.md docs/plan-3/build-ledger.md && git commit -m "docs: Plan 3 build ledger and FAQ testing entry"
```

---

## Self-review (done while writing)

- **Spec coverage:**
  - Every §9 Level 4 scenario row maps to a task: S0–S15 plus S16, S11b–S11f and S12h, through the coverage map.
  - U1 → Task 11.
  - The prerequisites → Task 1.
  - "First run A + C, second adds B" → Tasks 2, 7 and 8.
  - "Routing prompts 3×, all must pass" → `REPEATED` and `results.cell`.
  - "Outcomes, never wording" → Decision 2.
  - Manual hosts → Task 9.
  - The three §11 open items → Tasks 1, 9 and 12.
- **Placeholders:**
  - The only open values are the ones Task 1 measures (V1–V7). Each has a concrete fallback.
  - `<date>`/`<run>` in commit paths are filled from `run.py report`'s printed path.
- **Type consistency:**
  - `Invocation` fields, `Ctx` methods, `Verdict`/status constants, and `Found.parts` keys are the same in every task's Interfaces block and in the tested code.
  - `cmd_*` in `run.py` uses only names defined in Tasks 3–6.
- **Review Focus:** all five lines have pinning tests in Tasks 3, 5 and 6, already passing.
