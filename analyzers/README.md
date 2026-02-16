# Session Analyzer

Analyzes conversation dumps produced by `dump-context.sh` to give you a corrected picture of what actually happened in a session.

## Why "Corrected"?

Raw Claude Code session metrics are misleading:

| What it looks like | What actually happened |
|-|-|
| "398 user turns" | 12 actual user messages (the rest are tool results) |
| "450 corrections/hour" | 185 tool errors + 0 user corrections |
| "20-hour session" | 1.9 hours of work + 14.5 hours idle |

This analyzer automatically adjusts for all of these.

## Usage

```bash
# Analyze a specific conversation dump
python analyzers/session_analyzer.py .claude/context-dumps/20260124_143022_abc12345/conversation.md

# Auto-detect the most recent dump
python analyzers/session_analyzer.py
```

No dependencies — Python 3 standard library only.

## What It Reports

**Time** — Detects AFK gaps (>1h) across sibling dumps of the same session. Subtracts idle time so error rates and activity metrics reflect actual work, not clock time.

**Interaction** — Separates real user text messages from tool result noise. Categorizes messages as guidance, approval, corrections, questions.

**Errors** — Separates tool execution failures (environment issues) from actual user corrections (communication issues). Categorizes errors by type (database, file not found, permission, etc).

**Behavioral Signals** — Direction changes, frustration markers, tool call volume.

**Work Focus** — Files modified, tools used.

**Verdict** — Overall health assessment with actionable recommendations.

## Thresholds

Based on analysis of ~30 real sessions:

| Metric | Healthy | Warning | Critical |
|-|-|-|-|
| Active work time | <2h | 2-4h | >4h |
| Tool errors | <15 | 15-30 | >30 |
| Tool errors/hour | <10 | 10-30 | >30 |
| User corrections | <5 | 5-15 | >15 |
| Direction changes | <5 | 5-15 | >15 |
