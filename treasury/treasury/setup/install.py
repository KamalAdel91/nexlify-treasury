"""Install custom fields for the Treasury Multi-Expense/Revenue feature.

Called by after_install and after_migrate hooks.
"""
import frappe

CUSTOM_FIELDS = {
    "Payment Entry": [
        {
            "fieldname": "multi_expense",
            "fieldtype": "Check",
            "label": "Multi Expense / Revenue",
            "insert_after": "mode_of_payment",
            "description": "Enable company expense/revenue table (no party required)",
            "depends_on": "eval:doc.payment_type != 'Internal Transfer'",
        },
        {
            "fieldname": "treasury_expenses_section",
            "fieldtype": "Section Break",
            "label": "Company Expenses / Revenues",
            "insert_after": "multi_expense",
            "depends_on": "eval:doc.multi_expense == 1",
        },
        {
            "fieldname": "treasury_expense_items",
            "fieldtype": "Table",
            "label": "Expense / Revenue Items",
            "options": "Treasury Payment Entry Account",
            "insert_after": "treasury_expenses_section",
        },
        {
            "fieldname": "treasury_total_amount",
            "fieldtype": "Currency",
            "label": "Total Amount",
            "insert_after": "treasury_expense_items",
            "read_only": 1,
            "depends_on": "eval:doc.multi_expense == 1",
        },
    ],
}


def before_install():
    """Add custom fields to Payment Entry."""
    _ensure_fields()


def after_migrate():
    """Re-apply custom fields on every migrate (idempotent)."""
    _ensure_fields()


def _ensure_fields():
    for doctype, fields in CUSTOM_FIELDS.items():
        for field_def in fields:
            fieldname = field_def["fieldname"]
            existing = frappe.get_all(
                "Custom Field",
                filters={"dt": doctype, "fieldname": fieldname},
                pluck="name",
            )
            if existing:
                # Field already exists (e.g. from an earlier release) - keep
                # its insert_after in sync with this file so a corrected
                # position (like this one, moved out of the middle of
                # column_break_5's native layout) actually takes effect on
                # sites that installed the field before the fix, not just
                # on fresh installs.
                current = frappe.db.get_value("Custom Field", existing[0], "insert_after")
                if current != field_def.get("insert_after"):
                    frappe.db.set_value(
                        "Custom Field", existing[0], "insert_after", field_def["insert_after"]
                    )
                continue
            cf = frappe.get_doc(
                {"doctype": "Custom Field", "dt": doctype, **field_def}
            )
            cf.insert(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache(doctype="Payment Entry")
