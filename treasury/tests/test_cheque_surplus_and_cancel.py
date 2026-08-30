"""T5 — Cheque surplus booked as advance + standalone Reconciliation cancel.

Covers two features:
1. Cheque Receipt with cheque_amount > allocated: accepted, surplus booked as
   an on-account advance on Company's Default Advance Received Account
   (when book_advance_payments_in_separate_party_account is on) or Default
   Receivable Account (otherwise). GL stays balanced.
2. Cancelling a Cheque Reconciliation is standalone — the pre-cancel
   pre-flight ignores the linked Cheque Receipt / Cheque Payment (same
   mechanism as the Cheque Deposit fix).
"""
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, today

from treasury.tests.utils import (
	TreasuryFixtures,
	gl_totals,
	make_bank_transaction,
	make_deposit,
	make_receipt,
	reconcile,
	safe_cancel_delete,
)
from treasury.treasury.utils.cheque_shared import (
	resolve_difference_account,
	validate_deductions,
)


class TestChequeSurplusAdvance(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.fx = TreasuryFixtures()
		cls.company = cls.fx.company
		cls.party = cls.fx.party("Customer", "Treasury Test Customer")

	@classmethod
	def tearDownClass(cls):
		# always restore the factory default for the master toggle scope
		frappe.db.set_value("Company", cls.company, "book_advance_payments_in_separate_party_account", 0)
		frappe.db.commit()
		super().tearDownClass()

	def _surplus_doc(self, cheque=10500.0, allocated=10000.0):
		"""In-memory Cheque Receipt (never inserted): cheque > allocation."""
		doc = frappe.get_doc({
			"doctype": "Cheque Receipt",
			"company": self.company,
			"posting_date": today(),
			"currency": self.fx.currency,
			"cheque_no": "T5-SURP",
			"cheque_date": today(),
			"cheque_amount": cheque,
			"bank_account": self.fx.bank_gl,
			"without_party": 0,
			"party_type": "Customer",
			"party": self.party,
			"table_wgxh": [{
				"doc_type": "Sales Invoice",
				"voucher_no": "FAKE-VCH",
				"allocated_amount": allocated,
				"apply_deduction": 0,
			}],
		})
		doc.set_missing_values()
		return doc

	def test_resolver_prefers_advance_account_when_flag_on(self):
		receivable = frappe.db.get_value("Company", self.company, "default_receivable_account")
		advance = frappe.db.get_value("Company", self.company, "default_advance_received_account")
		try:
			frappe.db.set_value("Company", self.company, "book_advance_payments_in_separate_party_account", 0)
			self.assertEqual(resolve_difference_account(self.company), receivable)
			if advance:
				frappe.db.set_value("Company", self.company, "book_advance_payments_in_separate_party_account", 1)
				self.assertEqual(resolve_difference_account(self.company), advance)
		finally:
			frappe.db.set_value("Company", self.company, "book_advance_payments_in_separate_party_account", 0)

	def test_surplus_accepted_and_gl_balanced(self):
		doc = self._surplus_doc(cheque=10500.0, allocated=10000.0)

		# validation accepts the surplus and resolves the advance account
		validate_deductions(doc, "table_wgxh", "Cheque Receipt", allow_cheque_surplus=True)
		self.assertAlmostEqual(doc.difference_amount, -500.0, places=2)
		self.assertTrue(getattr(doc, "_difference_account", None))

		# GL: Dr bank 10500 = Cr allocations 10000 + Cr advance 500
		rows = doc.get_gl_entries()
		debit = sum(flt(r.debit) for r in rows)
		credit = sum(flt(r.credit) for r in rows)
		self.assertAlmostEqual(debit, 10500.0, places=2)
		self.assertAlmostEqual(credit, 10500.0, places=2)
		# the surplus is the on-account credit row (no against_voucher) on the
		# difference account, worth the difference. when the flag is off this is
		# the SAME account as the party receivable (where allocations also post),
		# so we identify it by being on-account rather than by row count.
		surplus_rows = [
			r for r in rows
			if r.account == doc._difference_account
			and flt(r.credit) > 0
			and not r.get("against_voucher")
		]
		self.assertEqual(len(surplus_rows), 1, "exactly one on-account surplus credit row expected")
		self.assertAlmostEqual(flt(surplus_rows[0].credit), 500.0, places=2)
		# every on-account credit is the surplus; the allocations carry against_voucher
		on_account_total = sum(flt(r.credit) for r in rows if not r.get("against_voucher"))
		self.assertAlmostEqual(on_account_total, 500.0, places=2)

	def test_surplus_still_rejected_for_payment(self):
		"""The strict equation stays enforced on Cheque Payment."""
		doc = self._surplus_doc()
		doc.doctype = "Cheque Payment"
		with self.assertRaises(frappe.ValidationError):
			validate_deductions(doc, "cheque_payment_items", "Cheque Payment")

	def test_over_allocation_still_rejected_for_receipt(self):
		"""Allocation larger than the cheque stays forbidden on receipts."""
		doc = self._surplus_doc(cheque=9000.0, allocated=10000.0)
		with self.assertRaises(frappe.ValidationError):
			validate_deductions(doc, "table_wgxh", "Cheque Receipt", allow_cheque_surplus=True)


class TestReconciliationCancelPreflight(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.fx = TreasuryFixtures()
		cls.party = cls.fx.party("Customer", "Treasury Test Customer")

	def test_preflight_ignores_receipt_and_payment(self):
		from frappe.desk.form.linked_with import get_submitted_linked_docs

		cr = make_receipt(self.fx, 3000.0, cheque_no="T5-RCN", party=self.party)
		bt = None
		dep = None
		try:
			# a receipt only becomes reconcilable once deposited (Under Collection)
			dep = make_deposit(self.fx, cr.name)
			bt = make_bank_transaction(self.fx, "deposit", 3000.0, "T5-RCN-BT")
			reconcile(self.fx, bt.name, "Cheque Receipt", cr.name, 3000.0)
			rcn = frappe.db.get_value("Cheque Reconciliation", {"cheque": cr.name}, "name")
			self.assertTrue(rcn)

			without_ignore = get_submitted_linked_docs("Cheque Reconciliation", rcn)
			self.assertIn(
				{"doctype": "Cheque Receipt", "name": cr.name, "docstatus": 1},
				without_ignore["docs"],
				"pre-flight must normally see the linked receipt",
			)
			with_ignore = get_submitted_linked_docs(
				"Cheque Reconciliation",
				rcn,
				ignore_doctypes_on_cancel_all=["Cheque Receipt", "Cheque Payment"],
			)
			self.assertEqual(
				with_ignore["docs"], [], "ignore list must suppress the dialog trigger"
			)
		finally:
			rcn = frappe.db.get_value("Cheque Reconciliation", {"cheque": cr.name}, "name")
			safe_cancel_delete("Cheque Reconciliation", rcn)
			safe_cancel_delete("Bank Transaction", bt.name if bt else None)
			safe_cancel_delete("Cheque Deposit", dep.name if dep else None)
			safe_cancel_delete("Cheque Receipt", cr.name)
