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
            "insert_after": "payment_order_status",
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
                continue
            cf = frappe.get_doc(
                {"doctype": "Custom Field", "dt": doctype, **field_def}
            )
            cf.insert(ignore_permissions=True)
    frappe.db.commit()
    frappe.clear_cache(doctype="Payment Entry")
