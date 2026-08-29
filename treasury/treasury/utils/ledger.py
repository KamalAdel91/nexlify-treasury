# Copyright (c) 2026, Alsadara and contributors
# For license information, please see license.txt

import frappe
from frappe.query_builder import DocType


def delete_voucher_ledger_entries(doc):
    """Mirror of ERPNext's AccountsController.on_trash: honor Accounts Settings
    "Delete Accounting and Stock Ledger Entries on deletion of Transaction".

    Treasury vouchers inherit plain Document (not AccountsController), so the
    ledger cleanup must be done here for Delete to pass the link check.
    Runs from on_trash, which frappe executes BEFORE the linked-docs check.
    """
    if not frappe.get_single_value("Accounts Settings", "delete_linked_ledger_entries"):
        return

    gle = DocType("GL Entry")
    frappe.qb.from_(gle).delete().where(
        (gle.voucher_type == doc.doctype) & (gle.voucher_no == doc.name)
    ).run()

    ple = DocType("Payment Ledger Entry")
    frappe.qb.from_(ple).delete().where(
        (ple.voucher_type == doc.doctype) & (ple.voucher_no == doc.name)
    ).run()
