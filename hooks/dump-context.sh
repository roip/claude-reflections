#!/bin/bash
# Hook that dumps the conversation context to files at key moments:
# - PreCompact: Before Claude Code compacts the context window
# - SessionStart (source: clear): When user runs /clear conversation
# - SessionEnd: When the session ends
#
# This preserves the full conversation so you can search it later,
# recover lost context after compaction, or do post-mortem analysis.

# Read hook input from stdin
INPUT=$(cat)

# Check if we got any input
if [ -z "$INPUT" ]; then
    exit 0
fi

# Extract values from the hook input
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // ""')
TRIGGER=$(echo "$INPUT" | jq -r '.trigger // "unknown"')
CUSTOM_INSTRUCTIONS=$(echo "$INPUT" | jq -r '.custom_instructions // ""')

# Always use project root for dumps (not CWD which changes with cd)
# CLAUDE_PROJECT_DIR is set by Claude Code to the project root
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(echo "$INPUT" | jq -r '.cwd // "."')}"

# Create dump directory with timestamp
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DUMP_DIR="${PROJECT_ROOT}/.claude/context-dumps/${TIMESTAMP}_${SESSION_ID:0:8}"
mkdir -p "$DUMP_DIR"

# Log the dump
echo "=== Context Dump: $(date) ===" >> "${PROJECT_ROOT}/.claude/context-dumps/dump.log"
echo "Session: $SESSION_ID" >> "${PROJECT_ROOT}/.claude/context-dumps/dump.log"
echo "Trigger: $TRIGGER" >> "${PROJECT_ROOT}/.claude/context-dumps/dump.log"
echo "Dump Dir: $DUMP_DIR" >> "${PROJECT_ROOT}/.claude/context-dumps/dump.log"
echo "" >> "${PROJECT_ROOT}/.claude/context-dumps/dump.log"

# 1. Save the raw hook input
echo "$INPUT" | jq '.' > "$DUMP_DIR/hook-input.json"

# 2. Copy the full transcript if it exists
if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
    cp "$TRANSCRIPT_PATH" "$DUMP_DIR/transcript.jsonl"

    # 3. Extract and format conversation in a readable way
    {
        echo "# Conversation Transcript"
        echo "Session ID: $SESSION_ID"
        echo "Dumped at: $(date)"
        echo "Trigger: $TRIGGER"
        echo ""
        echo "---"
        echo ""

        # Parse each line of the JSONL and format nicely
        while IFS= read -r line; do
            TYPE=$(echo "$line" | jq -r '.type // "unknown"')

            case "$TYPE" in
                "user")
                    echo "## USER"
                    echo "$line" | jq -r '.message.content // .content // "(no content)"' 2>/dev/null || echo "(parse error)"
                    echo ""
                    ;;
                "assistant")
                    echo "## ASSISTANT"
                    # Handle both string content and array content
                    CONTENT=$(echo "$line" | jq -r 'if .message.content | type == "string" then .message.content elif .message.content | type == "array" then [.message.content[] | select(.type == "text") | .text] | join("\n") else "(no content)" end' 2>/dev/null)
                    echo "$CONTENT"
                    echo ""
                    ;;
                "tool_use")
                    TOOL=$(echo "$line" | jq -r '.tool // .name // "unknown"')
                    echo "## TOOL USE: $TOOL"
                    echo '```json'
                    echo "$line" | jq -r '.input // .parameters // {}' 2>/dev/null
                    echo '```'
                    echo ""
                    ;;
                "tool_result")
                    echo "## TOOL RESULT"
                    RESULT=$(echo "$line" | jq -r '.content // .result // "(no result)"' 2>/dev/null | head -100)
                    echo "$RESULT"
                    if [ $(echo "$line" | jq -r '.content // .result // ""' 2>/dev/null | wc -l) -gt 100 ]; then
                        echo "... (truncated)"
                    fi
                    echo ""
                    ;;
            esac
        done < "$TRANSCRIPT_PATH"
    } > "$DUMP_DIR/conversation.md"

    # 4. Create a summary file
    {
        echo "# Context Dump Summary"
        echo ""
        echo "- **Session ID:** $SESSION_ID"
        echo "- **Timestamp:** $(date)"
        echo "- **Trigger:** $TRIGGER"
        echo "- **Custom Instructions:** ${CUSTOM_INSTRUCTIONS:-"(none)"}"
        echo ""
        echo "## Statistics"
        echo ""
        TOTAL_LINES=$(wc -l < "$TRANSCRIPT_PATH")
        USER_MSGS=$(grep -c '"type":"user"' "$TRANSCRIPT_PATH" 2>/dev/null || echo "0")
        ASSISTANT_MSGS=$(grep -c '"type":"assistant"' "$TRANSCRIPT_PATH" 2>/dev/null || echo "0")
        TOOL_USES=$(grep -c '"type":"tool_use"' "$TRANSCRIPT_PATH" 2>/dev/null || echo "0")

        echo "- Total events: $TOTAL_LINES"
        echo "- User messages: $USER_MSGS"
        echo "- Assistant messages: $ASSISTANT_MSGS"
        echo "- Tool uses: $TOOL_USES"
        echo ""
        echo "## Files"
        echo ""
        echo "- \`hook-input.json\` - Raw hook input data"
        echo "- \`transcript.jsonl\` - Full conversation transcript (JSONL format)"
        echo "- \`conversation.md\` - Human-readable conversation"
    } > "$DUMP_DIR/README.md"

else
    echo "Warning: Transcript file not found at: $TRANSCRIPT_PATH" > "$DUMP_DIR/error.txt"
fi

# Success - allow the compact to proceed
exit 0
