"""Cheques in the Connections tab of Sales / Purchase Invoice.

Cheque Receipt / Cheque Payment link to the invoice from their allocation table
(voucher_no, like Payment Entry's reference_name); Cheque Allocation links from
its own "invoice" field (allocations made later from Payment Reconciliation).
"""

from frappe import _


def _add_cheques(data, cheque_doctype):
    data.setdefault("non_standard_fieldnames", {}).update(
        {cheque_doctype: "voucher_no", "Cheque Allocation": "invoice"}
    )
    data.setdefault("transactions", []).append(
        {"label": _("Cheques"), "items": [cheque_doctype, "Cheque Allocation"]}
    )
    return data


def sales_invoice(data):
    return _add_cheques(data, "Cheque Receipt")


def purchase_invoice(data):
    return _add_cheques(data, "Cheque Payment")
