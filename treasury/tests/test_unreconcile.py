"""T2 - Unreconcile flow tests."""
import frappe
from frappe.tests.utils import FrappeTestCase

from treasury.treasury.utils.bank_reconciliation import on_bank_transaction_update
from treasury.tests.utils import (
    TreasuryFixtures,
    gl_totals,
    make_bank_transaction,
    make_deposit,
    make_payment,
    make_receipt,
    reconcile,
    safe_cancel_delete,
)

CHQ = 5000.0


def _count_active_rcns(cheque_name):
    return frappe.db.count("Cheque Reconciliation", {"cheque": cheque_name, "docstatus": 1})


class TestUnreconcile(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls.fx = TreasuryFixtures()
        cls.supplier = cls.fx.party("Supplier", "Treasury Test Supplier")
        cls.party = cls.fx.party("Customer", "Treasury Test Customer")

    def _prepare_receipt_chain(self, cheque_no):
        cr = make_receipt(self.fx, CHQ, cheque_no=cheque_no, party=self.party)
        dep = make_deposit(self.fx, cr.name)
        bt = make_bank_transaction(self.fx, "deposit", CHQ, cheque_no, party=self.party, party_type="Customer")
        reconcile(self.fx, bt.name, "Cheque Receipt", cr.name, CHQ)
        bt = frappe.get_doc("Bank Transaction", bt.name)
        cr.reload()
        rcns = frappe.get_all("Cheque Reconciliation", filters={"cheque": cr.name, "docstatus": 1}, pluck="name")
        return cr, dep, bt, rcns

    def _assert_reverted(self, cheque_dt, cheque_name, rcn_name, expected_status):
        if rcn_name and frappe.db.exists("Cheque Reconciliation", rcn_name):
            self.assertEqual(
                frappe.db.get_value("Cheque Reconciliation", rcn_name, "docstatus"),
                2,
                f"{rcn_name} should be cancelled after revert",
            )
        self.assertEqual(_count_active_rcns(cheque_name), 0, "no active RCNs should remain")
        _, _, active_cnt = gl_totals("Cheque Reconciliation", rcn_name)
        self.assertEqual(active_cnt, 0, f"RCN {rcn_name} active GL entries must be 0")
        self.assertEqual(
            frappe.db.get_value(cheque_dt, cheque_name, "cheque_status"),
            expected_status,
            f"{cheque_dt} status should be {expected_status}",
        )
        self.assertEqual(
            frappe.db.get_value("All Cheques", cheque_name, "current_status"),
            expected_status,
            "All Cheques registry should match",
        )
# === Unreconcile Transaction (remove payment entry -> on_update hook) ===

    def test_unreconcile_receipt(self):
        cr, dep, bt = None, None, None
        rcn_name = None
        try:
            cr, dep, bt, rcns = self._prepare_receipt_chain("T2-REC-UR")
            self.assertEqual(cr.cheque_status, "Reconciled")
            self.assertEqual(len(rcns), 1)
            rcn_name = rcns[0]
            _, _, cnt = gl_totals("Cheque Reconciliation", rcn_name)
            self.assertEqual(cnt, 2)

            # simulate Unreconcile: clear DB payment_entries, reload, hook
            frappe.db.sql(
                "DELETE FROM `tabBank Transaction Payments` WHERE parent=%s",
                bt.name,
            )
            frappe.db.commit()
            bt = frappe.get_doc("Bank Transaction", bt.name)
            on_bank_transaction_update(bt)
            frappe.db.commit()

            self._assert_reverted("Cheque Receipt", cr.name, rcn_name, "Under Collection")
        finally:
            safe_cancel_delete("Cheque Reconciliation", rcn_name)
            if bt and frappe.db.exists("Bank Transaction", bt.name):
                safe_cancel_delete("Bank Transaction", bt.name)
            safe_cancel_delete("Cheque Deposit", dep.name if dep else None)
            safe_cancel_delete("Cheque Receipt", cr.name if cr else None)

    def test_unreconcile_payment(self):
        cp, bt = None, None
        rcn_name = None
        try:
            cp = make_payment(self.fx, CHQ, cheque_no="T2-PAY-UR", party=self.supplier)
            bt = make_bank_transaction(
                self.fx, "withdrawal", CHQ, "T2-PAY-UR", party=self.supplier, party_type="Supplier"
            )
            reconcile(self.fx, bt.name, "Cheque Payment", cp.name, CHQ)
            cp.reload()
            rcns = frappe.get_all(
                "Cheque Reconciliation", filters={"cheque": cp.name, "docstatus": 1}, pluck="name"
            )
            self.assertEqual(len(rcns), 1)
            rcn_name = rcns[0]
            self.assertEqual(cp.cheque_status, "Reconciled")

            frappe.db.sql(
                "DELETE FROM `tabBank Transaction Payments` WHERE parent=%s",
                bt.name,
            )
            frappe.db.commit()
            bt = frappe.get_doc("Bank Transaction", bt.name)
            on_bank_transaction_update(bt)
            frappe.db.commit()

            self._assert_reverted("Cheque Payment", cp.name, rcn_name, "Issued")
        finally:
            safe_cancel_delete("Cheque Reconciliation", rcn_name)
            if bt and frappe.db.exists("Bank Transaction", bt.name):
                safe_cancel_delete("Bank Transaction", bt.name)
            safe_cancel_delete("Cheque Payment", cp.name if cp else None)
# === Cancel Bank Transaction (on_cancel hook) ===

    def test_cancel_bt_receipt(self):
        cr, dep, bt = None, None, None
        rcn_name = None
        try:
            cr, dep, bt, rcns = self._prepare_receipt_chain("T2-REC-CBT")
            rcn_name = rcns[0]
            self.assertEqual(cr.cheque_status, "Reconciled")

            bt.cancel()
            frappe.db.commit()

            self._assert_reverted("Cheque Receipt", cr.name, rcn_name, "Under Collection")
            self.assertEqual(frappe.db.get_value("Bank Transaction", bt.name, "docstatus"), 2)
        finally:
            safe_cancel_delete("Cheque Reconciliation", rcn_name)
            if bt and frappe.db.exists("Bank Transaction", bt.name):
                safe_cancel_delete("Bank Transaction", bt.name)
            safe_cancel_delete("Cheque Deposit", dep.name if dep else None)
            safe_cancel_delete("Cheque Receipt", cr.name if cr else None)

    def test_cancel_bt_payment(self):
        cp, bt = None, None
        rcn_name = None
        try:
            cp = make_payment(self.fx, CHQ, cheque_no="T2-PAY-CBT", party=self.supplier)
            bt = make_bank_transaction(
                self.fx, "withdrawal", CHQ, "T2-PAY-CBT", party=self.supplier, party_type="Supplier"
            )
            reconcile(self.fx, bt.name, "Cheque Payment", cp.name, CHQ)
            bt = frappe.get_doc("Bank Transaction", bt.name)
            cp.reload()
            rcns = frappe.get_all(
                "Cheque Reconciliation", filters={"cheque": cp.name, "docstatus": 1}, pluck="name"
            )
            rcn_name = rcns[0]
            self.assertEqual(cp.cheque_status, "Reconciled")

            bt.cancel()
            frappe.db.commit()

            self._assert_reverted("Cheque Payment", cp.name, rcn_name, "Issued")
        finally:
            safe_cancel_delete("Cheque Reconciliation", rcn_name)
            if bt and frappe.db.exists("Bank Transaction", bt.name):
                safe_cancel_delete("Bank Transaction", bt.name)
            safe_cancel_delete("Cheque Payment", cp.name if cp else None)
