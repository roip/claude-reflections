#!/usr/bin/env python3
"""
Claude Code Session Analyzer

Produces a corrected analysis of conversation dumps from dump-context.sh,
cutting through misleading raw metrics to show what actually happened.

Corrections applied automatically:
  - AFK/idle time is detected and subtracted from duration calculations
  - Tool result turns are separated from real user messages
  - Tool execution errors are separated from actual user corrections

Works with the conversation.md files in .claude/context-dumps/ subdirectories.

Usage:
    python session_analyzer.py <conversation.md>
    python session_analyzer.py .claude/context-dumps/20260124_143022_abc12345/conversation.md
    python session_analyzer.py   # auto-detects most recent dump
"""

import re
import sys
from pathlib import Path
from collections import Counter
from datetime import datetime


# ---------------------------------------------------------------------------
# Health thresholds (derived from analysis of ~30 real sessions)
#
# These are applied against CORRECTED metrics (per active hour, real user
# messages only, etc.) — not raw counts.
# ---------------------------------------------------------------------------

THRESHOLDS = {
    'active_hours':      {'healthy': 2.0,  'warning': 4.0,  'critical': 6.0},
    'real_user_msgs':    {'healthy': 50,   'warning': 100,  'critical': 200},
    'tool_errors':       {'healthy': 15,   'warning': 30,   'critical': 50},
    'user_corrections':  {'healthy': 5,    'warning': 15,   'critical': 30},
    'direction_changes': {'healthy': 5,    'warning': 15,   'critical': 25},
    'tool_errors_per_hr': {'healthy': 10,  'warning': 30,   'critical': 60},
    'lines':             {'healthy': 3000, 'warning': 6000, 'critical': 10000},
}

TOOL_ERROR_PATTERNS = [
    r'psql: error:',
    r'ENOENT',
    r'cannot find',
    r'permission denied',
    r'connection.*failed',
    r'ERROR:.*\n',
    r'SyntaxError',
    r'TypeError',
    r'Migration failed',
    r'command not found',
    r'No such file',
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def section(title):
    print(f"\n{'=' * 80}")
    print(title)
    print('=' * 80)


def status_for(metric, value):
    t = THRESHOLDS.get(metric, {})
    if value <= t.get('healthy', float('inf')):
        return '✅'
    elif value <= t.get('warning', float('inf')):
        return '⚠️'
    return '❌'


def parse_timestamp(ts_str):
    """Parse a timestamp string, stripping timezone abbreviations."""
    cleaned = re.sub(r'\s+(PST|PDT|EST|EDT|CST|CDT|MST|MDT|UTC)\s*', ' ', ts_str).strip()
    for fmt in ['%a %b %d %H:%M:%S %Y', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S']:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Core analysis — extracts all corrected metrics from a single conversation
# ---------------------------------------------------------------------------

def analyze(filepath):
    """Run full analysis on a conversation dump. Returns a metrics dict."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    p = Path(filepath)
    m = {}  # metrics

    # --- Session metadata ---
    sid = re.search(r'Session ID: ([a-f0-9-]+)', content)
    m['session_id'] = sid.group(1)[:8] if sid else 'unknown'

    ts = re.search(r'Dumped at: (.+)', content)
    m['timestamp'] = ts.group(1).strip() if ts else 'unknown'

    m['file_size_kb'] = p.stat().st_size // 1024
    m['lines'] = len(content.split('\n'))

    # --- Raw counts (what the dump looks like at face value) ---
    m['raw_user_sections'] = len(re.findall(r'^## USER$', content, re.MULTILINE))
    m['raw_assistant_sections'] = len(re.findall(r'^## ASSISTANT$', content, re.MULTILINE))
    m['raw_tool_calls'] = len(re.findall(r'"tool_use_id":', content))

    # --- Corrected user messages ---
    # Most "## USER" sections are tool results, not the human typing.
    # Extract only actual text messages, filtering out IDE file-open events.
    user_text_messages = re.findall(
        r'## USER\n\[.*?"type": "text".*?"text": "([^"]+)"', content, re.DOTALL)
    real_msgs = [msg for msg in user_text_messages if '<ide_opened_file>' not in msg]
    m['real_user_msgs'] = len(real_msgs)

    # Categorize user messages
    cats = {'guidance': 0, 'approval': 0, 'corrections': 0, 'questions': 0, 'other': 0}
    for msg in real_msgs:
        ml = msg.lower()
        if any(w in ml for w in ['read', 'check', 'try', 'run', 'create', 'update', 'fix', 'implement']):
            cats['guidance'] += 1
        elif any(w in ml for w in ['good', 'looks good', 'perfect', 'yes', 'correct', 'right']):
            cats['approval'] += 1
        elif any(w in ml for w in ['no', 'wrong', 'incorrect', 'stop', "don't", "shouldn't"]):
            cats['corrections'] += 1
        elif '?' in msg:
            cats['questions'] += 1
        else:
            cats['other'] += 1
    m['msg_categories'] = cats
    m['user_messages'] = real_msgs

    # --- Separate tool errors from user corrections ---
    user_turns = content.split('## USER\n')

    tool_errors = []
    user_corrections = []
    user_clarifications = []

    for i, turn in enumerate(user_turns[1:], 1):
        user_text_match = re.search(r'"text": "([^"]*)"', turn)
        user_text = user_text_match.group(1) if user_text_match else ""

        has_tool_error = '"is_error": true' in turn
        tool_error_match = any(re.search(pat, turn, re.IGNORECASE) for pat in TOOL_ERROR_PATTERNS)

        if has_tool_error or tool_error_match:
            snippet = ""
            if has_tool_error:
                em = re.search(r'"is_error": true.*?"content": "([^"]{0,200})', turn, re.DOTALL)
                if em:
                    snippet = em.group(1).replace('\\n', ' ')[:100]
            elif tool_error_match:
                for pat in TOOL_ERROR_PATTERNS:
                    em = re.search(f'({pat}[^\\n]{{0,100}})', turn, re.IGNORECASE)
                    if em:
                        snippet = em.group(1)
                        break
            tool_errors.append({'turn': i, 'error': snippet})
            continue

        # Only check for corrections in turns that aren't tool errors
        correction_pats = [
            r"\b(no|nope|wrong|incorrect|that's not right|stop|revert|undo)\b",
            r"\b(don't|do not|shouldn't|should not)\b.*\b(do|use|try)\b",
        ]
        if any(re.search(p, user_text, re.IGNORECASE) for p in correction_pats):
            user_corrections.append({'turn': i, 'text': user_text[:150]})

        clarification_pats = [
            r'\b(actually|instead|what I meant|should be|to clarify)\b',
            r'\b(try|use|do)\b.*\binstead\b',
        ]
        if any(re.search(p, user_text, re.IGNORECASE) for p in clarification_pats):
            user_clarifications.append({'turn': i, 'text': user_text[:150]})

    m['tool_errors'] = len(tool_errors)
    m['tool_error_details'] = tool_errors
    m['user_corrections'] = len(user_corrections)
    m['user_correction_details'] = user_corrections
    m['user_clarifications'] = len(user_clarifications)

    # Categorize tool errors
    error_categories = Counter()
    for err in tool_errors:
        txt = err['error'].lower()
        if 'psql' in txt or 'connection' in txt:
            error_categories['Database Connection'] += 1
        elif 'error:' in txt or 'failed' in txt:
            error_categories['SQL/Migration'] += 1
        elif 'enoent' in txt or 'cannot find' in txt:
            error_categories['File Not Found'] += 1
        elif 'permission' in txt:
            error_categories['Permission'] += 1
        else:
            error_categories['Other Technical'] += 1
    m['error_categories'] = error_categories

    # --- Direction changes and frustration markers ---
    m['direction_changes'] = len(re.findall(
        r'(try again|different approach|let me try)', content, re.IGNORECASE))

    m['frustration_markers'] = len(re.findall(
        r'## USER.*?"text": "[^"]*\b(still|again|same issue)\b',
        content, re.IGNORECASE | re.DOTALL))

    # --- AFK / idle time detection ---
    # Look for timestamps embedded in the conversation to find gaps.
    # The dump itself has a single timestamp, but if sibling dumps exist
    # (same session, different dump times), we can compute active time.
    m['overnight_heuristic'] = False
    if ts:
        parsed = parse_timestamp(ts.group(1))
        if parsed:
            is_late = parsed.hour >= 20 or parsed.hour <= 5
            if is_late and m['file_size_kb'] > 500:
                m['overnight_heuristic'] = True

    # Check for sibling dumps (same parent directory pattern)
    sibling_dumps = []
    dump_dir = p.parent.parent  # e.g. .claude/context-dumps/
    if dump_dir.exists():
        for sibling in sorted(dump_dir.glob('*/conversation.md')):
            with open(sibling, 'r', encoding='utf-8') as f:
                header = f.read(5000)
            sib_sid = re.search(r'Session ID: ([a-f0-9-]+)', header)
            sib_ts = re.search(r'Dumped at: (.+)', header)
            if sib_sid and sib_ts:
                if sib_sid.group(1)[:8] == m['session_id']:
                    dt = parse_timestamp(sib_ts.group(1))
                    if dt:
                        sibling_dumps.append({
                            'time': dt,
                            'size_kb': sibling.stat().st_size // 1024,
                        })
        sibling_dumps.sort(key=lambda x: x['time'])

    # Compute active time from sibling timeline
    if len(sibling_dumps) >= 2:
        wall_clock_hrs = (sibling_dumps[-1]['time'] - sibling_dumps[0]['time']).total_seconds() / 3600

        active_minutes = 0
        gap_minutes = 0
        gaps_found = []
        period_start = sibling_dumps[0]['time']
        last_time = sibling_dumps[0]['time']

        for entry in sibling_dumps[1:]:
            gap_min = (entry['time'] - last_time).total_seconds() / 60
            if gap_min > 60:
                active_minutes += (last_time - period_start).total_seconds() / 60
                gap_type = 'OVERNIGHT' if gap_min > 360 else 'LONG BREAK' if gap_min > 120 else 'BREAK'
                gaps_found.append({
                    'start': last_time, 'end': entry['time'],
                    'minutes': gap_min, 'type': gap_type,
                })
                gap_minutes += gap_min
                period_start = entry['time']
            last_time = entry['time']
        active_minutes += (last_time - period_start).total_seconds() / 60

        m['wall_clock_hours'] = wall_clock_hrs
        m['active_hours'] = active_minutes / 60
        m['gap_hours'] = gap_minutes / 60
        m['gaps'] = gaps_found
        m['growth_ratio'] = sibling_dumps[-1]['size_kb'] / sibling_dumps[0]['size_kb'] if sibling_dumps[0]['size_kb'] > 0 else 0
    else:
        m['wall_clock_hours'] = None
        m['active_hours'] = None
        m['gap_hours'] = None
        m['gaps'] = []
        m['growth_ratio'] = None

    # --- Work focus ---
    file_mods = re.findall(
        r'File (?:created|written|modified) successfully at: ([^\n]+)', content)
    m['files_modified'] = Counter(file_mods)

    tool_names = re.findall(r'"name": "([^"]+)"', content)
    m['tool_usage'] = Counter(tool_names)

    return m


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(m, filepath):
    """Print the full corrected session report."""

    section('CLAUDE CODE SESSION ANALYSIS')
    print(f"\nSession:  {m['session_id']}")
    print(f"Dumped:   {m['timestamp']}")
    print(f"File:     {Path(filepath).name} ({m['file_size_kb']}KB, {m['lines']:,} lines)")

    # --- Time ---
    section('TIME')

    if m['active_hours'] is not None:
        print(f"\n  Wall-clock duration:  {m['wall_clock_hours']:.1f}h")
        print(f"  Active work time:    {m['active_hours']:.1f}h {status_for('active_hours', m['active_hours'])}")
        print(f"  Idle/AFK time:       {m['gap_hours']:.1f}h (excluded from rate calculations)")

        if m['gaps']:
            print(f"\n  Gaps detected:")
            for g in m['gaps']:
                print(f"    {g['type']:12s}  {g['start'].strftime('%a %H:%M')} → "
                      f"{g['end'].strftime('%a %H:%M')} ({g['minutes']/60:.1f}h)")

        if m['wall_clock_hours'] > 8 and m['active_hours'] < m['wall_clock_hours'] * 0.3:
            print(f"\n  ⚠️  Session was left open during extended inactivity.")
            print(f"     The {m['wall_clock_hours']:.1f}h wall-clock time is misleading — "
                  f"actual work was {m['active_hours']:.1f}h.")

        active_hrs = m['active_hours']
    else:
        print("\n  (Single dump — no timeline data for gap detection.)")
        if m['overnight_heuristic']:
            print("  ⚠️  Large file with late-night timestamp — likely left open overnight.")
            print("     Best practice: always compact before breaks >1 hour.")
        active_hrs = None

    if m['growth_ratio'] is not None:
        print(f"\n  Growth ratio: {m['growth_ratio']:.1f}x (first dump → this dump)")

    # --- Corrected Interaction Metrics ---
    section('INTERACTION (corrected)')

    print(f"\n  Raw '## USER' sections:   {m['raw_user_sections']:>5}")
    print(f"  Actual user messages:     {m['real_user_msgs']:>5}  "
          f"{status_for('real_user_msgs', m['real_user_msgs'])}")
    if m['raw_user_sections'] > 0:
        noise_pct = (1 - m['real_user_msgs'] / m['raw_user_sections']) * 100
        print(f"  Noise (tool results):     {noise_pct:.0f}%")

    if active_hrs and active_hrs > 0:
        msgs_per_hr = m['real_user_msgs'] / active_hrs
        print(f"  Messages per active hour: {msgs_per_hr:.1f}")

    cats = m['msg_categories']
    if any(cats.values()):
        print(f"\n  Message breakdown:")
        print(f"    Guidance:    {cats['guidance']:>3}   (directing Claude's work)")
        print(f"    Approval:    {cats['approval']:>3}   (confirming / encouraging)")
        print(f"    Corrections: {cats['corrections']:>3}   (disagreeing with approach)")
        print(f"    Questions:   {cats['questions']:>3}")
        print(f"    Other:       {cats['other']:>3}")

    # --- Error Analysis ---
    section('ERRORS (corrected)')

    print(f"\n  Tool execution errors:  {m['tool_errors']:>5}  "
          f"{status_for('tool_errors', m['tool_errors'])}")
    print(f"  User corrections:       {m['user_corrections']:>5}  "
          f"{status_for('user_corrections', m['user_corrections'])}")
    print(f"  User clarifications:    {m['user_clarifications']:>5}")

    if active_hrs and active_hrs > 0:
        err_rate = m['tool_errors'] / active_hrs
        print(f"\n  Tool errors per active hour: {err_rate:.1f}  "
              f"{status_for('tool_errors_per_hr', err_rate)}")

    if m['error_categories']:
        print(f"\n  Error breakdown:")
        for cat, count in m['error_categories'].most_common():
            print(f"    {count:3d}x {cat}")

    if m['tool_errors'] > 0 and m['tool_errors'] > m['user_corrections'] * 3:
        print(f"\n  The apparent 'error rate' is dominated by tool failures, not the user")
        print(f"  saying 'wrong approach'. This indicates an environment/config issue.")
    elif m['user_corrections'] > m['tool_errors']:
        print(f"\n  User corrections outnumber tool errors — possible communication gap.")

    # --- Behavioral Signals ---
    section('BEHAVIORAL SIGNALS')

    print(f"\n  Direction changes:    {m['direction_changes']:>3}  "
          f"{status_for('direction_changes', m['direction_changes'])}")
    print(f"  Frustration markers:  {m['frustration_markers']:>3}")
    print(f"  Tool calls:           {m['raw_tool_calls']:>3}")

    # --- Work Focus ---
    if m['files_modified']:
        section('WORK FOCUS')
        print(f"\n  Files created/modified: {len(m['files_modified'])}")
        for f, count in m['files_modified'].most_common(10):
            print(f"    {count}x {f}")

    if m['tool_usage']:
        print(f"\n  Top tools used:")
        for tool, count in m['tool_usage'].most_common(8):
            print(f"    {count:4d}x {tool}")

    # --- Overall Verdict ---
    section('VERDICT')

    problems = []
    if m['tool_errors'] > THRESHOLDS['tool_errors']['warning']:
        problems.append(f"High tool error count ({m['tool_errors']})")
    if m['user_corrections'] > THRESHOLDS['user_corrections']['warning']:
        problems.append(f"Many user corrections ({m['user_corrections']})")
    if m['direction_changes'] > THRESHOLDS['direction_changes']['warning']:
        problems.append(f"Frequent direction changes ({m['direction_changes']})")
    if active_hrs and active_hrs > THRESHOLDS['active_hours']['warning']:
        problems.append(f"Long active session ({active_hrs:.1f}h)")
    if m['lines'] > THRESHOLDS['lines']['warning']:
        problems.append(f"Large transcript ({m['lines']:,} lines)")

    if not problems:
        print("\n✅ HEALTHY — Session metrics are within normal ranges.")
        if active_hrs:
            print(f"\n  {m['real_user_msgs']} real user messages over {active_hrs:.1f}h of active work.")
        else:
            print(f"\n  {m['real_user_msgs']} real user messages.")
        if m['tool_errors'] == 0 and m['user_corrections'] == 0:
            print("  No tool errors or user corrections — clean session.")
    else:
        severity = '❌ CRITICAL' if len(problems) >= 3 else '⚠️  WARNING'
        print(f"\n{severity}")
        for p in problems:
            print(f"  - {p}")

    # Recommendations
    recs = []
    if active_hrs and active_hrs > THRESHOLDS['active_hours']['warning']:
        recs.append("Consider compacting — long sessions degrade context quality.")
    if m['tool_errors'] > THRESHOLDS['tool_errors']['warning']:
        recs.append("Fix root cause of tool errors before continuing work.")
    if m['direction_changes'] > THRESHOLDS['direction_changes']['warning']:
        recs.append("Apply the 3-strike rule: after 3 failed attempts, try a different approach.")
    if m['user_corrections'] > THRESHOLDS['user_corrections']['warning']:
        recs.append("Communication gap detected — try starting fresh with a clearer task description.")
    if m['overnight_heuristic'] or (m['gaps'] and any(g['type'] == 'OVERNIGHT' for g in m['gaps'])):
        recs.append("Compact before breaks >1 hour to avoid context degradation.")

    if recs:
        print(f"\n  Recommendations:")
        for r in recs:
            print(f"    → {r}")

    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def find_latest_conversation():
    """Auto-detect the most recent conversation dump."""
    dumps = Path.cwd() / '.claude' / 'context-dumps'
    search_dir = dumps if dumps.exists() else Path.cwd()
    for pattern in ['**/conversation.md', 'conversation*.md']:
        files = sorted(search_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            return files[0]
    return None


def main():
    if len(sys.argv) >= 2 and sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        sys.exit(0)

    if len(sys.argv) >= 2:
        target = sys.argv[1]
    else:
        found = find_latest_conversation()
        if found:
            target = str(found)
            print(f"Auto-detected: {found}\n")
        else:
            print(__doc__)
            sys.exit(1)

    target_path = Path(target)
    if not target_path.is_file():
        print(f"Error: File not found: {target}")
        sys.exit(1)

    metrics = analyze(str(target_path))
    print_report(metrics, str(target_path))


if __name__ == '__main__':
    main()
