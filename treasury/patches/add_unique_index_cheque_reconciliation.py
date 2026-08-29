"""DB-level UNIQUE protection for Cheque Reconciliation.cheque.

The DocType field ``cheque`` (a Dynamic Link) must be unique per cheque to
prevent double-reconciliation races, but Frappe's ``check_unique_and_text``
rejects ``unique`` on Dynamic Link fields — marking it would lock the
"Edit DocType" form.  The UNIQUE index is therefore maintained at the
database layer only:

1. ``execute`` — ``post_model_sync`` patch entry point (runs once after the
   schema sync on first upgrade).
2. ``ensure_unique_index`` — idempotent re-assert, also registered as the
   app's ``after_migrate`` hook so every future ``bench migrate`` rebuilds
   the index that schema sync drops (the meta no longer declares it unique).
"""

import frappe

DOC_TYPE = "Cheque Reconciliation"
INDEX_NAME = "cheque"
COLUMN = "cheque"


def execute():
    """Patch entry point — called once by ``bench migrate`` (post_model_sync)."""
    ensure_unique_index()


def ensure_unique_index():
    """Idempotently create UNIQUE index ``cheque`` on ``Cheque Reconciliation.cheque``.

    No-op on non-MariaDB engines. Safe to call any number of times — checks
    ``SHOW INDEX`` before issuing any DDL.
    """
    if frappe.db.db_type != "mariadb":
        return

    table = f"`tab{DOC_TYPE}`"
    rows = frappe.db.sql(f"SHOW INDEX FROM {table}", as_dict=True)
    exists = any(
        row.get("Key_name") == INDEX_NAME
        and row.get("Column_name") == COLUMN
        and not row.get("Non_unique")
        for row in rows
    )
    if not exists:
        frappe.db.sql_ddl(
            f"ALTER TABLE {table} ADD UNIQUE INDEX `{INDEX_NAME}` (`{COLUMN}`)"
        )