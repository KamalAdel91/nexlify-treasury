"""T3 — Submit/Cancel lifecycle for every treasury doctype (company currency).

Verifies, with REAL submits and cancels:
- submit posts balanced GL of exactly the cheque amount
- cancel removes the posted GL entries
- cancel restores the previous cheque status through the chain
"""
import frappe
from frappe.tests.utils import FrappeTestCase

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


class TestCancelWorkflowRules(FrappeTestCase):
	"""Standard (non configurable) cancel rules across the chain.

	- A cancelled source cheque becomes "Cancelled" (never "Cheques In Hand").
	- Cancelling a reconciliation un-reconciles the linked Bank Transaction
	  and restores the cheque to its prior stage (deposit stays intact).
	- A deposit that has a linked reconciliation cannot be cancelled: it is
	  blocked with a message that links to the reconciliation to cancel first.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.fx = TreasuryFixtures()
		cls.party = cls.fx.party("Customer", "Treasury Test Customer")

	def test_source_cancel_sets_cancelled_status(self):
		cr = make_receipt(self.fx, CHQ, cheque_no="T3-CAN-REC", party=self.party)
		try:
			self.assertEqual(cr.cheque_status, "Cheques In Hand")
			cr.cancel()
			cr.reload()
			self.assertEqual(cr.docstatus, 2)
			self.assertEqual(
				cr.cheque_status, "Cancelled",
				"a cancelled source cheque must show Cancelled, not Cheques In Hand",
			)
		finally:
			safe_cancel_delete("Cheque Receipt", cr.name)

	def test_payment_source_cancel_sets_cancelled_status(self):
		pay = make_payment(self.fx, CHQ, cheque_no="T3-CAN-PAY", party=self.fx.party("Supplier", "Treasury Test Supplier"))
		try:
			self.assertEqual(pay.cheque_status, "Issued")
			pay.cancel()
			pay.reload()
			self.assertEqual(pay.docstatus, 2)
			self.assertEqual(pay.cheque_status, "Cancelled")
		finally:
			safe_cancel_delete("Cheque Payment", pay.name)

	def test_recon_cancel_unreconciles_bank_transaction(self):
		cr = make_receipt(self.fx, CHQ, cheque_no="T3-RC-BT", party=self.party)
		dep = bt = None
		try:
			dep = make_deposit(self.fx, cr.name)
			cr.reload()
			self.assertEqual(cr.cheque_status, "Under Collection")

			bt = make_bank_transaction(self.fx, "deposit", CHQ, "T3-RC-BT-X")
			reconcile(self.fx, bt.name, "Cheque Receipt", cr.name, CHQ)
			rcn = frappe.db.get_value("Cheque Reconciliation", {"cheque": cr.name}, "name")
			self.assertTrue(rcn)
			bt.reload()
			self.assertEqual(bt.status, "Reconciled")

			# cancel the reconciliation alone -> bank transaction un-reconciled
			frappe.get_doc("Cheque Reconciliation", rcn).cancel()
			cr.reload()
			self.assertEqual(cr.cheque_status, "Under Collection", "cheque returns to Under Collection")
			self.assertEqual(gl_totals("Cheque Reconciliation", rcn)[2], 0, "recon GL reversed")
			bt.reload()
			self.assertEqual(bt.payment_entries, [], "bank transaction payment entry removed")
			self.assertNotEqual(bt.status, "Reconciled", "bank transaction is un-reconciled")
		finally:
			rcn = frappe.db.get_value("Cheque Reconciliation", {"cheque": cr.name}, "name")
			safe_cancel_delete("Cheque Reconciliation", rcn)
			safe_cancel_delete("Bank Transaction", bt.name if bt else None)
			safe_cancel_delete("Cheque Deposit", dep.name if dep else None)
			safe_cancel_delete("Cheque Receipt", cr.name)

	def test_deposit_linked_to_recon_cannot_cancel(self):
		cr = make_receipt(self.fx, CHQ, cheque_no="T3-DEP-REC", party=self.party)
		dep = bt = None
		try:
			dep = make_deposit(self.fx, cr.name)
			bt = make_bank_transaction(self.fx, "deposit", CHQ, "T3-DEP-REC-X")
			reconcile(self.fx, bt.name, "Cheque Receipt", cr.name, CHQ)
			rcn = frappe.db.get_value("Cheque Reconciliation", {"cheque": cr.name}, "name")
			self.assertTrue(rcn)

			# deposit cannot be cancelled while a reconciliation is linked
			dep.reload()
			with self.assertRaises(frappe.ValidationError) as cm:
				dep.cancel()
			msg = str(cm.exception)
			self.assertIn(rcn, msg, "message must name the linked reconciliation")
			self.assertIn("Cancel that reconciliation", msg, "message must direct the user to cancel it first")
		finally:
			rcn = frappe.db.get_value("Cheque Reconciliation", {"cheque": cr.name}, "name")
			safe_cancel_delete("Cheque Reconciliation", rcn)
			safe_cancel_delete("Bank Transaction", bt.name if bt else None)
			safe_cancel_delete("Cheque Deposit", dep.name if dep else None)
			safe_cancel_delete("Cheque Receipt", cr.name)


class TestChequeLifecycle(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.fx = TreasuryFixtures()
		cls.party = cls.fx.party("Customer", "Treasury Test Customer")
		cls.supplier = cls.fx.party("Supplier", "Treasury Test Supplier")

	def _assert_balanced(self, voucher_type, voucher_no, expected):
		debit, credit, count = gl_totals(voucher_type, voucher_no)
		self.assertEqual(count, 2, f"{voucher_type} {voucher_no}: expected 2 GL rows, got {count}")
		self.assertAlmostEqual(debit, expected, places=2)
		self.assertAlmostEqual(credit, expected, places=2)

	def _assert_no_gl(self, voucher_type, voucher_no):
		_, _, count = gl_totals(voucher_type, voucher_no)
		self.assertEqual(count, 0, f"{voucher_type} {voucher_no}: GL entries still exist after cancel")

	def test_receipt_submit_and_cancel(self):
		cr = make_receipt(self.fx, CHQ, cheque_no="T3-REC-1", party=self.party)
		try:
			self._assert_balanced("Cheque Receipt", cr.name, CHQ)
			self.assertEqual(cr.cheque_status, "Cheques In Hand")
			cr.cancel()
			self._assert_no_gl("Cheque Receipt", cr.name)
		finally:
			safe_cancel_delete("Cheque Receipt", cr.name)

	def test_deposit_submit_and_cancel(self):
		cr = make_receipt(self.fx, CHQ, cheque_no="T3-REC-2", party=self.party)
		dep = None
		try:
			dep = make_deposit(self.fx, cr.name)
			self._assert_balanced("Cheque Deposit", dep.name, CHQ)
			cr.reload()
			self.assertEqual(cr.cheque_status, "Under Collection")

			dep.cancel()
			self._assert_no_gl("Cheque Deposit", dep.name)
			cr.reload()
			self.assertEqual(cr.cheque_status, "Cheques In Hand", "receipt status not restored on deposit cancel")
			# Regression: cancelling a deposit must be standalone — the receipt
			# stays SUBMITTED (no forced "cancel all linked documents" chain),
			# and its back-link to the deposit is cleared by sync_stage.
			self.assertEqual(cr.docstatus, 1, "receipt must not be cancelled along with the deposit")
			self.assertFalse(cr.cheque_deposit, "receipt link to deposit must be cleared")

		finally:
			safe_cancel_delete("Cheque Deposit", dep.name if dep else None)
			safe_cancel_delete("Cheque Receipt", cr.name)

	def test_cancel_preflight_skips_receipt_with_ignore_list(self):
		"""The UI's pre-cancel pre-flight (get_submitted_linked_docs) must return
		no docs for a deposit when the client sends ignore_doctypes_on_cancel_all
		["Cheque Receipt"] — that is exactly how the "Cancel All Documents" dialog
		is suppressed so the deposit cancels standalone (public/js/cheque_deposit.js)."""
		from frappe.desk.form.linked_with import get_submitted_linked_docs

		cr = make_receipt(self.fx, CHQ, cheque_no="T3-REC-2B", party=self.party)
		dep = None
		try:
			dep = make_deposit(self.fx, cr.name)
			cr.reload()
			self.assertEqual(cr.cheque_status, "Under Collection")

			without_ignore = get_submitted_linked_docs("Cheque Deposit", dep.name)
			self.assertIn(
				{"doctype": "Cheque Receipt", "name": cr.name, "docstatus": 1},
				without_ignore["docs"],
				"pre-flight must normally see the linked receipt (dialog trigger)",
			)

			with_ignore = get_submitted_linked_docs(
				"Cheque Deposit", dep.name, ignore_doctypes_on_cancel_all=["Cheque Receipt"]
			)
			self.assertEqual(
				with_ignore["docs"], [], "ignore list must suppress the dialog trigger"
			)

			dep.cancel()
			cr.reload()
			self.assertEqual(cr.docstatus, 1, "receipt must stay submitted after deposit cancel")
			self.assertEqual(cr.cheque_status, "Cheques In Hand")
		finally:
			safe_cancel_delete("Cheque Deposit", dep.name if dep else None)
			safe_cancel_delete("Cheque Receipt", cr.name)

	def test_payment_submit_and_cancel(self):
		cp = make_payment(self.fx, CHQ, cheque_no="T3-PAY-1", party=self.supplier)
		try:
			self._assert_balanced("Cheque Payment", cp.name, CHQ)
			self.assertEqual(cp.cheque_status, "Issued")
			cp.cancel()
			self._assert_no_gl("Cheque Payment", cp.name)
		finally:
			safe_cancel_delete("Cheque Payment", cp.name)

	def test_reconciliation_submit_and_cancel(self):
		cp = make_payment(self.fx, CHQ, cheque_no="T3-PAY-2", party=self.supplier)
		bt = None
		try:
			bt = make_bank_transaction(self.fx, "withdrawal", CHQ, "T3-PAY-2", party=self.supplier, party_type="Supplier")
			reconcile(self.fx, bt.name, "Cheque Payment", cp.name, CHQ)

			rcns = frappe.get_all("Cheque Reconciliation", filters={"cheque": cp.name}, pluck="name")
			self.assertEqual(len(rcns), 1, "expected exactly one Cheque Reconciliation")
			self._assert_balanced("Cheque Reconciliation", rcns[0], CHQ)
			cp.reload()
			self.assertEqual(cp.cheque_status, "Reconciled")

			frappe.get_doc("Cheque Reconciliation", rcns[0]).cancel()
			self._assert_no_gl("Cheque Reconciliation", rcns[0])
			cp.reload()
			self.assertEqual(cp.cheque_status, "Issued", "payment status not restored on RCN cancel")
			safe_cancel_delete("Cheque Reconciliation", rcns[0])
		finally:
			if bt:
				safe_cancel_delete("Bank Transaction", bt.name)
			safe_cancel_delete("Cheque Payment", cp.name)
