import time
from dataclasses import dataclass
from typing import Tuple
from PowerPlatform.Dataverse.client import DataverseClient


# -----------------------------
# Alternate key definitions
# -----------------------------
@dataclass(frozen=True)
class AlternateKeySpec:
    table: str
    key_schema_name: str
    columns: Tuple[str, ...]

    def normalized(self) -> "AlternateKeySpec":
        return AlternateKeySpec(
            self.table,
            self.key_schema_name,
            tuple(c.lower() for c in self.columns),
        )

# -----------------------------
# Key create + wait Active
# -----------------------------
def ensure_alternate_key(client: DataverseClient, spec: AlternateKeySpec) -> None:
    spec = spec.normalized()
    keys = client.tables.get_alternate_keys(spec.table)

    # 1) If the exact schema name exists, validate columns and return
    by_name = next((k for k in keys if (k.schema_name or "").lower() == spec.key_schema_name.lower()), None)
    if by_name:
        existing_cols = tuple((by_name.key_attributes or []))
        if set(existing_cols) != set(spec.columns):
            raise RuntimeError(
                f"Key name exists but columns differ: {spec.table}.{spec.key_schema_name} "
                f"existing={existing_cols} expected={spec.columns}"
            )
        return

    # 2) If any key already uses the same attribute set, treat as satisfied
    for k in keys:
        existing_cols = tuple((k.key_attributes or []))
        if set(existing_cols) == set(spec.columns):
            # A key with these columns already exists under a different schema name.
            # Creating a duplicate is not allowed.
            return
    
    # 3) Otherwise create it
    print(f"[KEY CREATE] table={spec.table} key={spec.key_schema_name} cols={spec.columns}")
    client.tables.create_alternate_key(spec.table, spec.key_schema_name, list(spec.columns))


def wait_for_key_active(client: DataverseClient, table: str, key_schema_name: str, max_wait_s: int = 120) -> None:
    """
    Key index builds asynchronously; statuses include Pending/In Progress/Active/Failed.
    """
    start = time.time()
    while time.time() - start < max_wait_s:
        keys = client.tables.get_alternate_keys(table)
        k = next((x for x in keys if x.schema_name == key_schema_name), None)
        if not k:
            time.sleep(3)
            continue

        status = (k.status or "").lower()
        if status == "active":
            return
        if status == "failed":
            raise RuntimeError(f"Alternate key index failed: {table}.{key_schema_name}")

        time.sleep(5)

    raise TimeoutError(f"Key {table}.{key_schema_name} not Active within {max_wait_s}s")