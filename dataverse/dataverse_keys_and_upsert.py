import logging

from typing import Any, Dict, List, Sequence

from PowerPlatform.Dataverse.client import DataverseClient
from PowerPlatform.Dataverse.models.upsert import UpsertItem

from utils.metering import AzureLikeExecutionMeter
from dataverse.alt_key import AlternateKeySpec, ensure_alternate_key, wait_for_key_active
from utils.datatable_helpers import strip_nones, sanitize_schema_name


def build_upsert_items(rows: List[Dict[str, Any]], key_cols: Sequence[str]) -> List[UpsertItem]:
    """
    Best practice: when identifying a record by alternate key, don't include those key columns in the body.
    """
    key_cols = [c.lower() for c in key_cols]
    items: List[UpsertItem] = []

    for r in rows:
        ak = {c: r.get(c) for c in key_cols}
        if any(v is None for v in ak.values()):
            raise RuntimeError(f"Null key value in row for key {key_cols}: {r}")

        record = dict(r)
        for c in key_cols:
            record.pop(c, None)

        items.append(UpsertItem(alternate_key=ak, record=strip_nones(record)))

    return items


def upsert_table(client: DataverseClient, table: str, rows: List[Dict[str, Any]], key_cols: Sequence[str], batch_size: int = 250) -> None:
    # Bulk upsert tables to dataverse
    items = build_upsert_items(rows, key_cols)
    for i in range(0, len(items), batch_size):
        client.records.upsert(table, items[i:i + batch_size])


# -----------------------------
# Main orchestration
# -----------------------------
def ensure_keys_and_upsert_all(
    dataverse_url: str,
    tables: Dict[str, Any],
    table_map: Dict[str, str],          # extractor_key -> dataverse_table_logical_name
    key_plan: Dict[str, Sequence[str]], # extractor_key -> key columns
    client,
) -> None:
    
    with AzureLikeExecutionMeter("dataverse-uploader") as m:
        # 1) Ensure keys exist
        specs: List[AlternateKeySpec] = []
        for extractor_name, dv_table in table_map.items():
            cols = key_plan.get(extractor_name)
            if not cols:
                raise RuntimeError(f"No key_plan entry for '{extractor_name}'. Required for upsert.")
            key_name = sanitize_schema_name(f"{dv_table}_{'_'.join([c.lower() for c in cols])}_key")
            specs.append(AlternateKeySpec(dv_table, key_name, tuple(cols)))

        for spec in specs:
            ensure_alternate_key(client, spec)

        # 2) Wait keys Active (index creation is async).
        for spec in specs:
            wait_for_key_active(client, spec.table, spec.key_schema_name)

        # 3) Upsert data
        for extractor_name, dv_table in table_map.items():
            rows = tables.get(extractor_name, []) or []
            upsert_table(client, dv_table, rows, key_plan[extractor_name])
            logging.info(f"{extractor_name} -> {dv_table}: upserted {len(rows)} rows")

    r = m.result()
    logging.info(
        f"COST[{r.name}] executions={r.billed_executions} duration_s={r.duration_s:.6f} "
        f"peak_rss_mb={r.peak_rss_mb:.1f} gb_seconds={r.sampled_gb_seconds:.6f}"
    )
