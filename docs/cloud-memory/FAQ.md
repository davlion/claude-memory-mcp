# claude-memory-cloud — FAQ

> **Draft.** Seeded from the design discussion; answers will be checked against the built server. This file moves to the `claude-memory-cloud` repo once that repo exists.

## What it is

### What problem does this solve?
Claude Code's built-in memory lives in files on one machine. claude.ai chat has its own separate memory. Neither reaches the other, or your other machines. claude-memory-cloud keeps one set of memories in a private GitHub repo and makes it available to every Claude surface through a custom connector.

### Which Claude surfaces does it work with?
- Claude Code on any Mac, Linux machine, or VM
- Claude Code cloud sessions
- claude.ai chat on web, Desktop, and mobile

Local Claude Code needs to be logged in with your claude.ai account for the connector to appear.

### What are scopes?
Each memory belongs to one of three kinds of scope:
- **general:** about you and how you work. Lives in `<you>/claude-memory`.
- **client:** about a client organization as a whole. Lives in the client's own repo, e.g. `acme-org/claude-memory`.
- **project:** about one codebase. Lives under `projects/<repo>/` in the memory repo of whoever owns that codebase.

Claude picks the scope from what you said and where you're working, and asks in one line when it's unclear.

### How does it know which project I'm in?
From the git `origin` remote of the directory Claude Code is running in. So the same project gets the same memories on every machine, whatever the local folder is called. With no git remote, only general and client memories apply.

## Security and privacy

### Who can see my memories?
- You, through GitHub, because they're files in your private repo.
- The server, which runs in your own Cloudflare account.
- Anthropic, whenever Claude reads a memory, the same as anything else in a conversation.

The server doesn't log memory content or tokens.

### Is Cloudflare in the middle a security risk?
The server sees memory text in plaintext, because that's how TLS works at Cloudflare's edge. Mitigations:
- The GitHub App can touch only the memory repos it's installed on, nothing else, and only with your own access.
- Memories must never contain secrets; the server rejects saves that look like credentials.
- Every change is a commit in your repo, so there's a full audit trail.
- A client that prefers it can host its own copy of the server.

### Why a GitHub App instead of a personal access token?
A GitHub App is installed on specific repos and requests only one permission (contents). Its effective access is the overlap of three things: what the app may do, which repos it's installed on, and what you yourself can access. A personal token usually reaches everything you can reach. Fine-grained personal tokens can be narrowed too, but they're per-user, harder to manage, and can't be granted by a client org owner the way an app installation can.

### What happens if a client removes my access?
It ends immediately. Uninstalling the app, or removing you from the org, cuts off that scope. The health check then reports the scope as unreachable and says what to do.

### Does the server need the GitHub App's private key?
No. It acts only as you, using user tokens that expire after 8 hours and refresh automatically. No private key is generated or stored.

## Day to day

### How do I save a memory?
Say it naturally: "save a memory that we deploy on Tuesdays", "remember that…", "don't do X again". Claude ends every save attempt with exactly one of:
- **"saved to <scope>"**
- **"queued in outbox for <scope>"**
- **"not saved: <reason>"**

### What happens if I save while the server is unreachable?
In local Claude Code, the memory goes into an outbox (`~/.claude/memory-outbox/`). Claude flushes it at the next session start where the server works, through the normal checks. In cloud sessions and chat there's no local disk, so Claude tells you it wasn't saved.

### Can I still read memories offline?
In local Claude Code, yes, but read-only and possibly out of date. After each successful load, Claude keeps a snapshot of your memory index, and the session-start hook loads it, labeled with its date. Full memory text and search need the server.

### If I save a memory on my laptop, when do my other sessions see it?
- **New sessions:** immediately; they load the latest index at start.
- **Sessions already running:** on their next memory tool call. The server notices the index has changed and sends the new one along with the result.

Nothing is pushed to a session that's sitting idle.

### Should I keep sessions short so memories stay fresh?
No. Memories rarely change mid-session, and a long session's working context is worth more than a perfectly current index. The one real risk in long sessions is context compaction, which can drop the memory index. Claude re-loads it after compaction.

### What if two sessions edit the same memory at once?
Nothing is lost. The second save finds the memory changed since it was read, and is saved as a conflict copy. The index lists conflicts, and Claude offers to merge them.

### What if I save something that's almost the same as an existing memory?
The server checks for similar memories and asks Claude to update the existing one instead, unless you really want a separate memory.

### Can I edit memories by hand?
Yes. They're plain Markdown files in your repo. The server rebuilds the index on its next write.

### What about Claude Code's built-in memory?
The setup script turns it off, so memories don't end up in two places. Your existing local memory files are left in place as a backup.

## Setup and operations

### What does it cost?
Normally nothing. GitHub private repos are free, Cloudflare Workers' free plan is far above personal use, and the GitHub App is free.

### How do I know it's working?
At session start, Claude runs a health check and stays silent if everything's fine. Each problem is reported in one line with what to do, e.g. "reconnect the claude-memory connector in claude.ai → Settings → Connectors". You can also ask "is memory working?" at any time.

### Why TypeScript for the server, and Python and shell for the rest?
Cloudflare's OAuth and MCP libraries for Workers are TypeScript, so the server is TypeScript. Everything that runs on your machine (hooks, setup script, test runner) is Python and shell, to keep it simple and dependency-free.
