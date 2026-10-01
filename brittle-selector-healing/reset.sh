#!/usr/bin/env bash
# Reset the demo to its original form: the v1 spider, no agent fix, no outputs.
# Asks twice, because it throws away whatever the agent changed.
cd "$(dirname "$0")"

echo "This resets the demo in: $PWD"
echo "  • books.py goes back to the original v1 spider (the agent's fix is lost)"
echo "  • deletes books.before.py, out.json, wrong.json, ESCALATION.md and .heal/"
read -r -p "Continue? [y/N] " a
[[ "$a" == [yY] ]] || { echo "cancelled"; exit 1; }
read -r -p "Are you sure? Type RESET to confirm: " b
[ "$b" = "RESET" ] || { echo "cancelled"; exit 1; }

cp .baseline/books.py books.py
rm -rf .heal books.before.py out.json wrong.json ESCALATION.md __pycache__
echo "reset: the demo is back to its original form"
