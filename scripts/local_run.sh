#!/bin/sh
# Run a small live query with the Apify SDK local storage and print counts.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="python3"
fi
export APIFY_LOCAL_STORAGE_DIR="$ROOT/storage"
mkdir -p "$APIFY_LOCAL_STORAGE_DIR/key_value_stores/default"
cat > "$APIFY_LOCAL_STORAGE_DIR/key_value_stores/default/INPUT.json" << 'EOF'
{
  "sources": ["ted", "uk_fts", "uk_contracts_finder", "canadabuys", "austender", "ccgp"],
  "keywords": ["server", "network", "software", "cctv", "IT"],
  "openOnly": true,
  "publishedWithinDays": 30,
  "maxItems": 20
}
EOF
rm -rf "$APIFY_LOCAL_STORAGE_DIR/datasets" "$APIFY_LOCAL_STORAGE_DIR/request_queues"
"$PY" -m src
"$PY" - << 'PY'
import json
from collections import Counter
from pathlib import Path

root = Path("storage")
counts = Counter()
items = []
for path in sorted((root / "datasets").rglob("*.json")):
    if not path.stem.isdigit():
        continue
    item = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(item, dict) or "source" not in item:
        continue
    items.append(item)
    counts[item.get("source") or "?"] += 1
print(f"dataset_items {len(items)}")
for source, count in sorted(counts.items()):
    print(f"dataset {source} {count}")
report_path = root / "key_value_stores" / "default" / "SOURCE_REPORT.json"
if report_path.exists():
    print(report_path.read_text(encoding="utf-8"))
PY
