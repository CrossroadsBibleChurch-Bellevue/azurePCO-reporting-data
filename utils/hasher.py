from typing import Any
import hashlib

# This is the hash creator, pretty simple, just gets passed various bits of data which is then combined and a hash compute based off of it.
# When I have been passing data into it, I usually use it like so: stable_hash_id("group_tag", groupID, tagID), where groupID and tagID are variables and then group_tag is the table it is being upsert into
# Make sure to use similar naming convention and if using it for the same table in different spots, make sure to use the EXACT same combination so that the hashes stay consistent.

# Compute stable hash ID to ensure no duplicates in upserting entries to dataverse
def stable_hash_id(*parts: Any) -> str:
    s = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()
