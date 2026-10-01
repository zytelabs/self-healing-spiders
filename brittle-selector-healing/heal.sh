#!/usr/bin/env bash
# Heal books.py after the site changes: up to 3 agent attempts, then escalate to a human.
# Usage: ./heal.sh [site]      site defaults to v2
set -uo pipefail
cd -P "$(dirname "$0")"   # -P: /tmp is really /private/tmp, and the agent reports the real path

SITE=${1:-v2}

# ── what you can turn ───────────────────────────────────────────────
MAX_ATTEMPTS=${HEAL_MAX_ATTEMPTS:-2}   # tries before a human gets ESCALATION.md
BUDGET_USD=${HEAL_BUDGET_USD:-10}      # stop early once this much is spent
MODEL=${HEAL_MODEL:-}                  # opus | sonnet | haiku, empty = CLI default
EFFORT=${HEAL_EFFORT:-}                # low | medium | high | xhigh | max
TOOLS="Read Grep Glob"                 # the only tools it gets: no web, no MCP, no subagents
TOOLS="$TOOLS Bash"                    # run the crawl and the checks, write books.py
# ────────────────────────────────────────────────────────────────────

CLAUDE=${CLAUDE_BIN:-claude}
opts=(--permission-mode bypassPermissions --tools "${TOOLS// /,}" --strict-mcp-config)
[ -n "$MODEL" ] && opts+=(--model "$MODEL")
[ -n "$EFFORT" ] && opts+=(--effort "$EFFORT")
LOG=.heal

rm -rf "$LOG" ESCALATION.md
mkdir -p "$LOG/guard"
cp -R check.py site "$LOG/guard/"          # the agent must not change what judges it

run_check() {
  uv run scrapy runspider books.py -a site="$SITE" -O out.json -L ERROR >"$LOG/crawl.log" 2>&1
  uv run python check.py out.json
}

guard_intact() {
  diff -q check.py "$LOG/guard/check.py" >/dev/null && diff -rq site "$LOG/guard/site" >/dev/null
}

meter() {  # meter <spent>
  awk -v s="$1" -v b="$BUDGET_USD" 'BEGIN {
    w = 30; f = int(s / b * w); if (f > w) f = w
    bar = ""; for (i = 0; i < w; i++) bar = bar (i < f ? "#" : "-")
    printf "$%.2f of $%.2f  [%s]", s, b, bar }'
}

echo "▶ model: ${MODEL:-default} · effort: ${EFFORT:-default} · attempts: $MAX_ATTEMPTS · budget: \$$BUDGET_USD"
echo "▶ crawling site/$SITE.html"
if result=$(run_check); then
  echo "$result"; echo "✓ nothing to heal"; exit 0
fi
echo "$result"
cp books.py books.before.py
echo "▶ backed up books.py → books.before.py"

spent=0; secs_total=0; history=""
for n in $(seq 1 $MAX_ATTEMPTS); do
  echo
  echo "━━ attempt $n/$MAX_ATTEMPTS ━━  agent working…"
  prompt="books.py is a Scrapy spider. The site it scrapes (site/$SITE.html) was redesigned and the spider broke.

This command must pass:
  uv run scrapy runspider books.py -a site=$SITE -O out.json && uv run python check.py out.json

Its output right now:
$result

Fix books.py so the command passes. Only edit books.py. Do not edit check.py or anything in site/."
  [ "$n" -gt 1 ] && prompt="$prompt

This is attempt $n. Your previous attempt did not pass."

  start=$SECONDS
  "$CLAUDE" -p "$prompt" --output-format stream-json --verbose "${opts[@]}" \
    | tee "$LOG/attempt-$n.jsonl" \
    | jq -rR --unbuffered --arg pwd "$PWD" 'fromjson? | select(.type == "assistant") | .message.content[]?
        | select(.type == "tool_use")
        | (.input.file_path // .input.command // .input.pattern // .input.query // "" | tostring
           | split("cd " + $pwd + " && ") | join("") | split("cd " + $pwd + "; ") | join("")
           | split($pwd + "/") | join("")) as $arg
        | ($arg | split("\n")) as $lines
        | "   → \(.name) \($lines[0] // "" | .[0:90])\(if ($lines | length) > 1 then " …" else "" end)"'
  secs=$((SECONDS - start)); secs_total=$((secs_total + secs))

  final=$(grep '"type":"result"' "$LOG/attempt-$n.jsonl" | tail -1)
  [ -z "$final" ] && final='{}'
  cost=$(jq -r '.total_cost_usd // 0' <<<"$final")
  turns=$(jq -r '.num_turns // 0' <<<"$final")
  used=$(jq -r '.modelUsage // {} | keys | join(",")' <<<"$final")
  spent=$(awk -v a="$spent" -v b="$cost" 'BEGIN { printf "%.4f", a + b }')

  if ! guard_intact; then
    verdict="FAIL: edited check.py or site/, reverted"
    cp "$LOG/guard/check.py" check.py; rm -rf site; cp -R "$LOG/guard/site" site
    result="Your attempt edited check.py or site/, which is not allowed. It was reverted."
  elif result=$(run_check); then
    verdict="PASS"
  elif cmp -s books.py books.before.py; then
    verdict="FAIL: books.py unchanged"
  else
    verdict="FAIL"
  fi

  line=$(printf "attempt %d  %-4s  \$%.2f  %3ds  %2s turns" "$n" "${verdict%%:*}" "$cost" "$secs" "$turns")
  note=""; [[ "$verdict" == *:* ]] && note="  (${verdict#*: })"
  history="$history$line$note"$'\n'
  echo "   $line  ${used}"
  echo "   $(meter "$spent")"

  if [ "$verdict" = "PASS" ]; then
    echo
    echo "$result"
    echo
    diff -u books.before.py books.py | sed 's/^/   /'
    echo
    echo "   what changed, any time:  diff -u books.before.py books.py"
    printf "✓ HEALED on attempt %d of %d · \$%.2f · %ds\n" "$n" "$MAX_ATTEMPTS" "$spent" "$secs_total"
    exit 0
  fi

  if awk -v s="$spent" -v b="$BUDGET_USD" 'BEGIN { exit !(s >= b) }'; then
    echo "   budget spent, stopping early"; break
  fi
done

{
  echo "# Escalation: books.py could not be healed"
  echo
  printf 'Site: `site/%s.html` · attempts: %d of %d · spent: $%.2f · %ds\n' "$SITE" "$n" "$MAX_ATTEMPTS" "$spent" "$secs_total"
  echo
  echo "## Attempts"
  echo '```'; printf "%s" "$history"; echo '```'
  echo
  echo "## What the agent said after its last attempt"
  echo
  jq -r '.result // "(no message)"' <<<"$final"
  echo
  echo "## Check output after the last attempt"
  echo '```'; echo "$result"; echo '```'
  echo
  echo "## Last attempt's change to books.py"
  echo '```diff'; diff -u books.before.py books.py; echo '```'
  echo
  echo "Original spider: \`books.before.py\` · full agent transcripts: \`$LOG/attempt-*.jsonl\`"
} > ESCALATION.md

echo
printf "✗ ESCALATED to a human after %d attempts · \$%.2f · %ds  → ESCALATION.md\n" "$n" "$spent" "$secs_total"
exit 1
