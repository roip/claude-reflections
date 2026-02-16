# Session Context: Claude Reflections OSS Package

## Status
**In progress** — Files extracted and sanitized, not yet git-initialized.

## What Was Done
- Extracted the context memory system from the `trtk` project's `.claude/` folder
- Sanitized all files: removed project-specific references (TrueTake, deal management, Firebase, etc.)
- Created a README.md explaining the full system
- Created `settings-example.json` showing the hook configuration
- Added MIT LICENSE

## Files Created So Far

| File | Source | Notes |
|------|--------|-------|
| `hooks/dump-context.sh` | `.claude/hooks/dump-context.sh` | Verbatim — no project-specific content |
| `agents/context-search.md` | `.claude/agents/context-search.md` | Verbatim — already generic |
| `agents/doc-agent.md` | `.claude/agents/doc-agent.md` | Heavily trimmed — removed project-specific doc structure, kept the pattern |
| `settings-example.json` | `.claude/settings.local.json` | Extracted only the hooks section, removed all permissions |
| `README.md` | New | Full explanation: problem, solution, setup, architecture, results |
| `LICENSE` | New | MIT |

## What's Still Needed

### More files to consider adding:
1. **CLAUDE.md snippet** — Example of how to register agents in project instructions
2. **`.gitignore`** — For the repo itself + recommended gitignore for users
3. **Example output** — A sanitized sample context dump showing what the output looks like
4. **Article draft** — The blog post / article about this experiment

### Before git init:
- Review all files for any remaining project-specific content
- Decide on repo name (currently `claude-reflections`)
- Create GitHub repo
- Add any additional agents or variations

## Architecture Overview (for the article)

The system has three components:

1. **`dump-context.sh`** (Hook) — Fires on PreCompact, SessionEnd, SessionStart. Saves the full transcript as JSONL + human-readable Markdown.

2. **`context-search`** (Agent) — Searches through saved dumps using grep. Returns summarized findings to the main conversation without blowing up context.

3. **`doc-agent`** (Agent) — Runs at end of sessions to extract and persist knowledge into project documentation.

### Key insight for the article:
The PreCompact hook is the critical one. It fires *right before* Claude Code compresses the context window — this is the moment where you capture what's about to be lost. SessionEnd and SessionStart are supplementary.

### Real-world stats from trtk project:
- 479 context dumps over ~3 weeks of active development
- Dumps include full tool call history (file reads, edits, bash commands)
- Context-search agent successfully recovered decisions and debugging context after compaction multiple times

## Origin Project
Extracted from: `trtk` (TrueTake) — a Next.js + Express monorepo for digital likeness management. The context memory system was developed organically during a multi-month development effort with Claude Code.
