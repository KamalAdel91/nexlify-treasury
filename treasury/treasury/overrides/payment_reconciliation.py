"""Treasury cheques in Payment Reconciliation and Unreconcile Payment.

ERPNext's Payment Reconciliation lists Payment Entries, Journal Entries and return
invoices only, and Unreconcile Payment accepts Payment Entry / Journal Entry only,
so a cheque's unallocated balance (an advance against the cheque itself) was
invisible to both. Activated via extend_doctype_class (hooks.py):

- the Payments table also lists every cheque of the party with an open balance,
- reconciling a cheque row adds the invoice to the cheque's own allocation table
  (like a Payment Entry reference) and rebuilds the cheque's Payment Ledger,
- Unreconcile Payment undoes it: the row is flagged "unlinked" and the amount is
  back on the cheque as an open balance.

Every other row falls through to ERPNext unchanged.
"""

import frappe
from erpnext.accounts.utils import update_voucher_outstanding
from frappe.utils import flt

from treasury.treasury.utils.cheque_allocation import (
    CHEQUE_DOCTYPES,
    allocate_cheque_to_voucher,
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
            account = allocate_cheque_to_voucher(
                row.reference_type, row.reference_name, row.invoice_type, row.invoice_number,
                flt(row.allocated_amount),
                # get_open_cheques carries the account the cheque balance sits on
                cheque_account=row.reference_row,
            )
            update_voucher_outstanding(row.invoice_type, row.invoice_number, account, self.party_type, self.party)

        others = [row for row in self.get("allocation") if row not in cheque_rows]
        self.set("allocation", others)
        if others:
            super().reconcile_allocations(skip_ref_details_update_for_pe)


class TreasuryUnreconcilePaymentMixin:
    def validate(self):
        if self.voucher_type in CHEQUE_DOCTYPES:
            return
        super().validate()

    def on_submit(self):
        if self.voucher_type not in CHEQUE_DOCTYPES:
            return super().on_submit()
        for row in self.allocations:
            unlink_cheque_from_voucher(self.voucher_type, self.voucher_no, row.reference_doctype, row.reference_name)
            update_voucher_outstanding(row.reference_doctype, row.reference_name, row.account, row.party_type, row.party)
            frappe.db.set_value("Unreconcile Payment Entries", row.name, "unlinked", True)
