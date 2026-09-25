"""Treasury cheques in Payment Reconciliation and Unreconcile Payment.

ERPNext's Payment Reconciliation lists Payment Entries, Journal Entries and return
invoices only, and Unreconcile Payment accepts Payment Entry / Journal Entry only,
so a cheque's unallocated balance (an advance against the cheque itself) was
invisible to both. Activated via extend_doctype_class (hooks.py):

- the Payments table also lists every cheque of the party with an open balance,
- each reconciled cheque row becomes a Cheque Allocation (one per cheque +
  invoice pair) instead of going to reconcile_against_document,
- Unreconcile Payment cancels that Cheque Allocation.

Every other row falls through to ERPNext unchanged.
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from treasury.treasury.utils.cheque_allocation import CHEQUE_DOCTYPES, get_open_cheques


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
        if self.voucher_type == "Cheque Allocation":
            return
        if self.voucher_type in CHEQUE_DOCTYPES:
            frappe.throw(
                _("{0} {1} was allocated on the cheque itself. Cancel and amend the cheque to change that allocation.").format(
                    _(self.voucher_type), frappe.bold(self.voucher_no)
                )
            )
        super().validate()

    def on_submit(self):
        if self.voucher_type != "Cheque Allocation":
            return super().on_submit()
        allocation = frappe.get_doc("Cheque Allocation", self.voucher_no)
        if allocation.docstatus == 1:
            allocation.cancel()
        for row in self.allocations:
            frappe.db.set_value("Unreconcile Payment Entries", row.name, "unlinked", True)
