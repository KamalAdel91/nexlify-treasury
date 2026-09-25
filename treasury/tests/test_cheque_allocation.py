"""T6 — Unallocated cheque balance reconciled from Payment Reconciliation and
undone from Unreconcile Payment (via Cheque Allocation)."""
import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from treasury.tests.utils import TreasuryFixtures, safe_cancel_delete
from treasury.treasury.utils.cheque_allocation import open_amount


class TestChequeAllocation(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.fx = TreasuryFixtures()
		cls.company = cls.fx.company
		cls.party = cls.fx.party("Customer", "Treasury Test Customer")
		cls.receivable = frappe.db.get_value("Company", cls.company, "default_receivable_account")
		frappe.db.set_value("Company", cls.company, "book_advance_payments_in_separate_party_account", 0)

	def _receipt(self, amount):
		"""Cheque Receipt on the party with nothing allocated. No "account": with a
		party, that field would take the unallocated amount instead of the party."""
		doc = frappe.get_doc({
			"doctype": "Cheque Receipt",
			"company": self.company,
			"posting_date": today(),
			"currency": self.fx.currency,
			"cheque_no": "T6-ALLOC-" + frappe.generate_hash(length=6),
			"cheque_date": today(),
			"cheque_amount": amount,
			"drawn_bank": frappe.get_value("Bank Account", self.fx.bank_account, "bank"),
			"bank_account": self.fx.bank_account,
			"without_party": 0,
			"party_type": "Customer",
			"party": self.party,
		})
		doc.insert(ignore_permissions=True)
		doc.submit()
		return doc

	def _ple(self, voucher_no):
		return frappe.get_all(
			"Payment Ledger Entry",
			filters={"voucher_no": voucher_no},
			fields=["account", "party", "against_voucher_type", "against_voucher_no", "amount", "delinked"],
		)

	def _journal(self, amount):
		je = frappe.get_doc({
			"doctype": "Journal Entry",
			"company": self.company,
			"posting_date": today(),
			"accounts": [
				{"account": self.receivable, "party_type": "Customer", "party": self.party,
				 "debit_in_account_currency": amount, "cost_center": self.fx.cost_center},
				{"account": self.fx.income, "credit_in_account_currency": amount,
				 "cost_center": self.fx.cost_center},
			],
		})
		je.insert(ignore_permissions=True)
		je.submit()
		return je

	def _reconciliation(self):
		pr = frappe.get_doc({
			"doctype": "Payment Reconciliation",
			"company": self.company,
			"party_type": "Customer",
			"party": self.party,
			"receivable_payable_account": self.receivable,
		})
		pr.get_unreconciled_entries()
		return pr

	def test_reconcile_and_unreconcile_cheque_balance(self):
		cr = je = None
		try:
			cr = self._receipt(1000)
			je = self._journal(600)
			self.assertAlmostEqual(
				open_amount("Cheque Receipt", cr.name, self.receivable, "Customer", self.party, advance=True), 1000,
				msg=f"receivable={self.receivable} PLE={self._ple(cr.name)}",
			)

			pr = self._reconciliation()
			payments = [p.as_dict() for p in pr.payments if p.reference_name == cr.name]
			invoices = [i.as_dict() for i in pr.invoices if i.invoice_number == je.name]
			self.assertEqual(len(payments), 1, "cheque with an open balance must be listed in Payments")
			self.assertAlmostEqual(payments[0].amount, 1000)
			self.assertEqual(len(invoices), 1)

			pr.allocate_entries(frappe._dict({"invoices": invoices, "payments": payments}))
			pr.reconcile()

			ca = frappe.get_all("Cheque Allocation", filters={"cheque": cr.name, "docstatus": 1}, pluck="name")
			self.assertEqual(len(ca), 1)
			self.assertAlmostEqual(open_amount("Journal Entry", je.name, self.receivable, "Customer", self.party), 0)
			self.assertAlmostEqual(open_amount("Cheque Receipt", cr.name, self.receivable, "Customer", self.party, advance=True), 400)

			# the reconciled cheque is still listed, with what is left of it
			pr = self._reconciliation()
			left = [p for p in pr.payments if p.reference_name == cr.name]
			self.assertAlmostEqual(left[0].amount, 400)

			from erpnext.accounts.doctype.unreconcile_payment.unreconcile_payment import (
				create_unreconcile_doc_for_selection,
			)

			create_unreconcile_doc_for_selection(json.dumps([{
				"company": self.company,
				"voucher_type": "Cheque Allocation",
				"voucher_no": ca[0],
				"against_voucher_type": "Journal Entry",
				"against_voucher_no": je.name,
			}]))
			self.assertEqual(frappe.db.get_value("Cheque Allocation", ca[0], "docstatus"), 2)
			self.assertAlmostEqual(open_amount("Journal Entry", je.name, self.receivable, "Customer", self.party), 600)
			self.assertAlmostEqual(open_amount("Cheque Receipt", cr.name, self.receivable, "Customer", self.party, advance=True), 1000)
		finally:
			for name in frappe.get_all("Cheque Allocation", filters={"cheque": cr.name if cr else ""}, pluck="name"):
				safe_cancel_delete("Cheque Allocation", name)
			safe_cancel_delete("Journal Entry", je.name if je else None)
			safe_cancel_delete("Cheque Receipt", cr.name if cr else None)

	def test_unreconcile_rejects_allocation_made_on_the_cheque(self):
		doc = frappe.new_doc("Unreconcile Payment")
		doc.company = self.company
		doc.voucher_type = "Cheque Receipt"
		doc.voucher_no = "ANY"
		with self.assertRaises(frappe.ValidationError):
			doc.validate()
