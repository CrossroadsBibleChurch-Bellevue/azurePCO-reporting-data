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