from typing import Any
import hashlib

# Compute stable hash ID to ensure no duplicates in upserting entries to dataverse
def stable_hash_id(*parts: Any) -> str:
    s = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()
