"""Show what the crawl wrote. Usage: uv run python show.py [rows]"""

import json
import sys

rows = [json.loads(line) for line in open("books.jsonl")]
limit = int(sys.argv[1]) if len(sys.argv) > 1 else 25
complete = lambda r: all(r.get(f) for f in ("name", "price", "availability"))

for r in rows[:limit]:
    mark = "✓" if complete(r) else "✗"
    print(mark, json.dumps({k: r[k] for k in ("name", "price", "currency", "availability")}, ensure_ascii=False))
if len(rows) > limit:
    print(f"… {len(rows) - limit} more")
broken = sum(not complete(r) for r in rows)
print(f"\n{len(rows)} books in books.jsonl · {len(rows) - broken} complete · {broken} missing fields")
