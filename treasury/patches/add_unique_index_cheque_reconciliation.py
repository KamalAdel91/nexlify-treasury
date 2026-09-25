"""DB-level UNIQUE protection for Cheque Reconciliation, active documents only.

One cheque may have only ONE active (draft or submitted) Cheque Reconciliation,
to prevent double-reconciliation races. A cancelled one must NOT count: after
"Unreconcile" the cheque has to be reconcilable again.

Frappe cannot express this in meta (``unique`` is rejected on a Dynamic Link,
and it would count cancelled rows anyway), so it lives at the database layer:

- ``active_cheque``: a generated column = ``cheque`` while docstatus < 2,
  NULL once cancelled (MariaDB allows any number of NULLs in a UNIQUE index).
- UNIQUE index ``active_cheque`` on that column.
- The legacy UNIQUE index ``cheque`` (counted cancelled rows too) is dropped.

The column is not in the DocType meta, so schema sync never touches it.
``ensure_unique_index`` is idempotent and runs from the post_model_sync patch,
the after_migrate hook and on_doctype_update.
"""

import frappe

TABLE = "`tabCheque Reconciliation`"
COLUMN = "active_cheque"
INDEX_NAME = "active_cheque"
LEGACY_INDEX = "cheque"


def execute():
    """Patch entry point — called once by ``bench migrate`` (post_model_sync)."""
    ensure_unique_index()


def ensure_unique_index():
    """Idempotently create the generated column + UNIQUE index, drop the legacy one.

    No-op on non-MariaDB engines. Checks the schema before issuing any DDL.
    """
    if frappe.db.db_type != "mariadb":
        return

    columns = {row[0] for row in frappe.db.sql(f"SHOW COLUMNS FROM {TABLE}")}
    if COLUMN not in columns:
        frappe.db.sql_ddl(
            f"ALTER TABLE {TABLE} ADD COLUMN `{COLUMN}` VARCHAR(140) "
            f"AS (IF(`docstatus` < 2, `cheque`, NULL)) PERSISTENT"
        )

    rows = frappe.db.sql(f"SHOW INDEX FROM {TABLE}", as_dict=True)
    if any(r.get("Key_name") == LEGACY_INDEX and not r.get("Non_unique") for r in rows):
        frappe.db.sql_ddl(f"ALTER TABLE {TABLE} DROP INDEX `{LEGACY_INDEX}`")

    exists = any(
        r.get("Key_name") == INDEX_NAME
        and r.get("Column_name") == COLUMN
        and not r.get("Non_unique")
        for r in rows
    )
    if not exists:
        frappe.db.sql_ddl(f"ALTER TABLE {TABLE} ADD UNIQUE INDEX `{INDEX_NAME}` (`{COLUMN}`)")
