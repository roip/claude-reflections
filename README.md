# Claude Code Context Memory

**Persistent memory across sessions for Claude Code using hooks and custom agents.**

Developed to analyze claude sessions, and identify project, CLAUDE.md and communication issues,  
Claude Code's context window is finite. When it fills up, the conversation gets compacted — and context is lost. This project uses Claude Code's **hooks** and **custom agents** to capture, store, and retrieve conversation context across sessions.

## The Problem

When working on a multi-session project with Claude Code:

1. **Context compaction loses detail** — When the context window fills, Claude Code compresses earlier messages. Decisions, debugging steps, and nuanced context disappear.
2. **New sessions start cold** — Each `/clear` or new session starts fresh. Claude doesn't remember what happened yesterday.
3. **Session knowledge evaporates** — What files were modified? What was decided? What failed? Gone.

## The Solution

Four components working together:

### 1. `dump-context.sh` — The Hook

A shell script that fires on three Claude Code lifecycle events:
- **PreCompact** — Right before context compression (saves what's about to be lost)
- **SessionEnd** — When a session ends
- **SessionStart** — When `/clear` is run (captures the session being cleared)

Each dump creates a timestamped folder with:
- `transcript.jsonl` — Raw conversation in JSONL format
- `conversation.md` — Human-readable formatted version
- `hook-input.json` — Metadata (session ID, trigger type)
- `README.md` — Statistics (message counts, timestamps)

### 2. `context-search` — The Search Agent

A custom agent that can grep through all saved context dumps to find:
- Previous decisions ("Why did we choose X over Y?")
- Lost context after compaction ("What were we debugging before?")
- Session summaries ("What happened yesterday?")
- Post-mortem analysis ("What went wrong in the last session?")

### 3. `session_analyzer.py` — The Analyzer

A Python script that analyzes conversation dumps to produce corrected session metrics. Raw dump metrics are misleading — this script fixes them:

- **Filters AFK time** — Detects idle gaps across sibling dumps so error rates reflect actual work, not wall-clock time
- **Separates real user messages** from tool result noise (e.g., "398 turns" → "12 actual messages")
- **Separates tool errors from user corrections** (e.g., "450 corrections" → "185 tool errors + 0 corrections")

```bash
python analyzers/session_analyzer.py .claude/context-dumps/20260124_143022_abc12345/conversation.md
```

See [`analyzers/README.md`](analyzers/README.md) for details.

## Setup

### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI installed
- `jq` available on your system (`apt install jq` / `brew install jq`)

### Installation

1. **Copy the hook script:**

```bash
mkdir -p .claude/hooks .claude/agents .claude/context-dumps
cp hooks/dump-context.sh .claude/hooks/
chmod +x .claude/hooks/dump-context.sh
```

2. **Copy the agents:**

```bash
cp agents/context-search.md .claude/agents/
cp agents/doc-agent.md .claude/agents/
```

3. **Configure the hooks** in your project `.claude/settings.local.json`:

```json
{
  "hooks": {
    "PreCompact": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/dump-context.sh",
            "timeout": 30
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/dump-context.sh",
            "timeout": 30
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/dump-context.sh",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

4. **Add to `.gitignore`:**

```gitignore
# Context dumps contain conversation data — don't commit
.claude/context-dumps/
```

5. **Register the agent** in your `CLAUDE.md`:

```markdown
## Custom Agent

| Agent | Purpose |
|-------|---------|
| `context-search` | Search previous conversation dumps for lost context |
```

### Verify Installation

Start a Claude Code session. You should see a hook confirmation on startup:
```
SessionStart:startup hook success: Success
```

Run a `/clear` or let the context compact naturally — a new folder should appear in `.claude/context-dumps/`.

Might need to restart vscode for this to catch on

## Usage

### Searching Past Context

Claude will automatically use the `context-search` agent when you ask about previous sessions:

```
> What did we discuss about authentication in the last session?
> What files were modified before the last compaction?
> Do a post-mortem on today's work
```

### Cleaning Up Old Dumps

```
> Delete context dumps older than 7 days
```

## How It Works

### Hook Lifecycle

```
Session Start ─→ [dump-context.sh fires] ─→ Saves previous session transcript
       │
       ▼
   ... working ...
       │
       ▼
Context Window Full ─→ [PreCompact hook fires] ─→ Saves full transcript
       │                                             BEFORE compaction
       ▼
   Compacted context (detail lost)
       │
       ▼
   ... working ...
       │
       ▼
Session End ─→ [dump-context.sh fires] ─→ Saves final transcript
```

### Dump Structure

```
.claude/context-dumps/
├── dump.log                              # Append-only log of all dumps
├── 20260115_143022_abc12345/             # Timestamped + session ID prefix
│   ├── README.md                         # Statistics & metadata
│   ├── hook-input.json                   # Raw hook payload
│   ├── transcript.jsonl                  # Full conversation (JSONL)
│   └── conversation.md                   # Human-readable formatted version
├── 20260115_160530_abc12345/             # Same session, later dump
│   └── ...
└── 20260116_091200_def67890/             # Different session
    └── ...
```

### What Gets Captured

The `transcript.jsonl` contains every message in the conversation:
- User messages
- Assistant responses
- Tool calls (with full input parameters)
- Tool results (truncated for large outputs)

The `conversation.md` reformats this into a readable document with headers for each message type.

## Architecture Decisions

**Why shell script instead of a Claude Code plugin?**
Hooks run as shell commands — they're simple, debuggable, and don't require any SDK. `jq` handles the JSON parsing.

**Why JSONL + Markdown?**
JSONL preserves the full fidelity for programmatic access. Markdown makes it grep-able and human-readable. Both are generated from the same source.

**Why custom agents instead of instructions in CLAUDE.md?**
Agents get their own context and tools. Searching through dozens of dump files would pollute the main conversation context. The agent does the heavy lifting and returns a summary.

**Why not a database?**
Files are simple, portable, and grep-able. No dependencies beyond `jq`. The dumps are small enough that file-based search is fast.

## Real-World Results

In production use on a multi-month development project:
- **479 context dumps** accumulated over ~3 weeks of active development
- Context recovery after compaction works reliably
- Post-mortem analysis revealed interaction patterns and recurring issues
- Session handoff documentation reduced cold-start time for new sessions
- recommended edits to CLAUDE.md fixed many tool execution fails 

## Limitations

- **Disk usage** — Each dump includes the full transcript. Run cleanup periodically.
- **No semantic search** — The context-search agent uses grep, not embeddings. Good enough for keyword search, not great for "find conversations similar to X."
- **Transcript format may change** — Claude Code's JSONL format isn't formally documented. The parsing in `dump-context.sh` may need updates.

## License

MIT
