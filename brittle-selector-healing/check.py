"""Check the scraped books. Run: uv run python check.py [out.json]

Exits 0 when every check passes, 1 otherwise.
"""

import json
import sys

EXPECTED_COUNT = 10
FIELDS = ["title", "price", "availability"]
AVAILABILITY = {"In stock", "Out of stock"}

# Known-correct records, copied by hand from the live site.
GOLDEN = {
    "A Light in the Attic": (51.77, "In stock"),
    "Sharp Objects": (47.82, "In stock"),
    "The Black Maria": (52.15, "Out of stock"),
}

path = sys.argv[1] if len(sys.argv) > 1 else "out.json"
with open(path) as f:
    items = json.load(f)


def count():
    if len(items) != EXPECTED_COUNT:
        return [f"expected {EXPECTED_COUNT} items, got {len(items)}"]
    return []


def fields_present():
    errors = []
    for n, i in enumerate(items, 1):
        empty = [f for f in FIELDS if i.get(f) in (None, "")]
        if empty:
            errors.append(f"item {n}: {', '.join(empty)} empty")
    return errors


def values_sane():
    if all(i.get(f) in (None, "") for i in items for f in FIELDS):
        return None  # nothing to judge: say so instead of passing by default
    errors = []
    for i in items:
        title, price, avail = i.get("title"), i.get("price"), i.get("availability")
        if isinstance(title, str) and title.lstrip().startswith("<"):
            errors.append(f"title is HTML, not text: {title[:40]!r}")
        if price is not None and not (
            isinstance(price, (int, float)) and 1 <= price <= 200
        ):
            errors.append(f"{title!r}: price {price!r} is not a number in 1-200")
        if avail is not None and avail not in AVAILABILITY:
            errors.append(
                f"{title!r}: availability {avail!r} not in {sorted(AVAILABILITY)}"
            )
    return errors


def golden_sample():
    by_title = {i.get("title"): i for i in items}
    errors = []
    for title, (price, avail) in GOLDEN.items():
        got = by_title.get(title)
        if got is None:
            errors.append(f"{title!r}: missing")
        elif (got.get("price"), got.get("availability")) != (price, avail):
            errors.append(
                f"{title!r}: expected {price} / {avail}, "
                f"got {got.get('price')} / {got.get('availability')}"
            )
    return errors


failed = False
for name, check in [
    ("item count", count),
    ("fields present", fields_present),
    ("values sane", values_sane),
    ("golden sample", golden_sample),
]:
    errors = check()
    if errors is None:
        print(f"– {name}  (skipped: every value is empty)")
        continue
    print(f"{'✗' if errors else '✓'} {name}")
    for e in errors[:5]:
        print(f"    {e}")
    if len(errors) > 5:
        print(f"    ... and {len(errors) - 5} more")
    failed = failed or bool(errors)

sys.exit(1 if failed else 0)
