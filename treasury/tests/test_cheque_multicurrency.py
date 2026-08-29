"""T4 — Multi-currency (USD @ 48 -> EGP) through the full cheque chains.

Automates the scenarios verified manually earlier:
- Receipt (USD 1000) -> Deposit -> Reconciliation: every stage posts 48,000 EGP
- Payment (USD 1000) -> Reconciliation: both stages post 48,000 EGP
- Cheque Reconciliation carries the cheque currency (USD)
"""
import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

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

CHQ_USD = 1000.0
FX = 48.0
EXPECTED_EGP = CHQ_USD * FX


class TestChequeMulticurrency(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.fx = TreasuryFixtures()
		cls.rate = cls.fx.ensure_currency_exchange("USD", cls.fx.currency, FX)
		cls.expected = CHQ_USD * cls.rate
		cls.party = cls.fx.party("Customer", "Treasury Test Customer")
		cls.supplier = cls.fx.party("Supplier", "Treasury Test Supplier")

	def _assert_stage(self, voucher_type, voucher_no, expected=None):
		expected = expected if expected is not None else self.expected
		debit, credit, count = gl_totals(voucher_type, voucher_no)
		self.assertEqual(count, 2, f"{voucher_type} {voucher_no}: expected 2 GL rows, got {count}")
		self.assertAlmostEqual(debit, expected, places=2, msg=f"{voucher_type}: debit {debit} != {expected}")
		self.assertAlmostEqual(credit, expected, places=2, msg=f"{voucher_type}: credit {credit} != {expected}")

	def test_multicurrency_receipt_chain(self):
		cr = make_receipt(self.fx, CHQ_USD, currency="USD", cheque_no="T4-REC-USD", party=self.party)
		dep = bt = None
		try:
			self._assert_stage("Cheque Receipt", cr.name)

			dep = make_deposit(self.fx, cr.name, currency="USD")
			self._assert_stage("Cheque Deposit", dep.name)

			bt = make_bank_transaction(
				self.fx, "deposit", CHQ_USD, "T4-REC-USD", party=self.party, party_type="Customer"
			)
			reconcile(self.fx, bt.name, "Cheque Receipt", cr.name, CHQ_USD)

			rcns = frappe.get_all("Cheque Reconciliation", filters={"cheque": cr.name}, pluck="name")
			self.assertEqual(len(rcns), 1)
			self.assertEqual(
				frappe.db.get_value("Cheque Reconciliation", rcns[0], "currency"),
				"USD",
				"RCN must carry the cheque currency",
			)
			self._assert_stage("Cheque Reconciliation", rcns[0])

			for rcn in rcns:
				safe_cancel_delete("Cheque Reconciliation", rcn)
		finally:
			safe_cancel_delete("Bank Transaction", bt.name if bt else None)
			safe_cancel_delete("Cheque Deposit", dep.name if dep else None)
			safe_cancel_delete("Cheque Receipt", cr.name)

	def test_multicurrency_payment_chain(self):
		cp = make_payment(self.fx, CHQ_USD, currency="USD", cheque_no="T4-PAY-USD", party=self.supplier)
		bt = None
		try:
			self._assert_stage("Cheque Payment", cp.name)

			bt = make_bank_transaction(
				self.fx, "withdrawal", CHQ_USD, "T4-PAY-USD", party=self.supplier, party_type="Supplier"
			)
			reconcile(self.fx, bt.name, "Cheque Payment", cp.name, CHQ_USD)

			rcns = frappe.get_all("Cheque Reconciliation", filters={"cheque": cp.name}, pluck="name")
			self.assertEqual(len(rcns), 1)
			self.assertEqual(frappe.db.get_value("Cheque Reconciliation", rcns[0], "currency"), "USD")
			self._assert_stage("Cheque Reconciliation", rcns[0])

			for rcn in rcns:
				safe_cancel_delete("Cheque Reconciliation", rcn)
		finally:
			safe_cancel_delete("Bank Transaction", bt.name if bt else None)
			safe_cancel_delete("Cheque Payment", cp.name)
