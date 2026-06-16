from typing import Dict, Any
import re

def sanitize_schema_name(name: str) -> str:
    n = re.sub(r"[^A-Za-z0-9_]", "_", name)
    return n[:80]

# -----------------------------
# Upsert helpers
# -----------------------------
def strip_nones(row: Dict[str, Any]) -> Dict[str, Any]:
    # Omit nulls to avoid accidental clears unless desired.
    return {k: v for k, v in row.items() if v is not None}

def upsert_row(table: Dict[str, Dict[str, Any]], row: Dict[str, Any], pk: str = "id"):
    rid = row.get(pk)
    if rid is None:
        return
    if rid not in table:
        table[rid] = row
        return
    existing = table[rid]
    for k, v in row.items():
        if k == "cr0b4_unique_id" or k not in existing or existing[k] is None:
            existing[k] = v