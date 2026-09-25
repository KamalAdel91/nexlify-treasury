"""Treasury cheques in Payment Reconciliation and Unreconcile Payment.

ERPNext's Payment Reconciliation lists Payment Entries, Journal Entries and return
invoices only, and Unreconcile Payment accepts Payment Entry / Journal Entry only,
so a cheque's unallocated balance (an advance against the cheque itself) was
invisible to both. Activated via extend_doctype_class (hooks.py):

- the Payments table also lists every cheque of the party with an open balance,
- each reconciled cheque row becomes a Cheque Allocation (one per cheque +
  invoice pair) instead of going to reconcile_against_document,
- Unreconcile Payment cancels that Cheque Allocation, and also undoes an
  allocation made on the cheque itself (its allocation table).

Every other row falls through to ERPNext unchanged.
"""

import frappe
from erpnext.accounts.utils import update_voucher_outstanding
from frappe.utils import flt, nowdate

from treasury.treasury.utils.cheque_allocation import (
    CHEQUE_DOCTYPES,
    get_open_cheques,
    unlink_cheque_from_voucher,
)


class TreasuryPaymentReconciliationMixin:
    def get_jv_entries(self):
        return list(super().get_jv_entries()) + get_open_cheques(self)

    def reconcile_allocations(self, skip_ref_details_update_for_pe=False):
        cheque_rows = [
            row for row in self.get("allocation")
            if row.reference_type in CHEQUE_DOCTYPES and row.invoice_number and flt(row.allocated_amount)
        ]
        if not cheque_rows:
            return super().reconcile_allocations(skip_ref_details_update_for_pe)

        for row in cheque_rows:
            self._make_cheque_allocation(row)

        others = [row for row in self.get("allocation") if row not in cheque_rows]
        self.set("allocation", others)
        if others:
            super().reconcile_allocations(skip_ref_details_update_for_pe)

    def _make_cheque_allocation(self, row):
        doc = frappe.get_doc({
            "doctype": "Cheque Allocation",
            "company": self.company,
            "posting_date": nowdate(),
            "party_type": self.party_type,
            "party": self.party,
            "cheque_type": row.reference_type,
            "cheque": row.reference_name,
            # get_open_cheques carries the account the balance sits on in reference_row
            "cheque_account": row.reference_row or self.receivable_payable_account,
            "invoice_type": row.invoice_type,
            "invoice": row.invoice_number,
            "account": self.receivable_payable_account,
            "allocated_amount": flt(row.allocated_amount),
            "cost_center": row.cost_center,
        })
        doc.insert()
        doc.submit()
        return doc


class TreasuryUnreconcilePaymentMixin:
    def validate(self):
        if self.voucher_type == "Cheque Allocation" or self.voucher_type in CHEQUE_DOCTYPES:
            return
        super().validate()

    def on_submit(self):
        if self.voucher_type == "Cheque Allocation":
            allocation = frappe.get_doc("Cheque Allocation", self.voucher_no)
            if allocation.docstatus == 1:
                allocation.cancel()
        elif self.voucher_type in CHEQUE_DOCTYPES:
            for row in self.allocations:
                unlink_cheque_from_voucher(self.voucher_type, self.voucher_no, row.reference_doctype, row.reference_name)
                update_voucher_outstanding(
                    row.reference_doctype, row.reference_name, row.account, row.party_type, row.party
                )
        else:
            return super().on_submit()
        for row in self.allocations:
            frappe.db.set_value("Unreconcile Payment Entries", row.name, "unlinked", True)
