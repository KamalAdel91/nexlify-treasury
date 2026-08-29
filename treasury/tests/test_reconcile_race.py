"""T1 — Double-reconcile race protection tests.

B1 (sequential): reconcile same cheque against two different Bank Transactions
in rapid succession — the second MUST be rejected with a friendly message.

B2 (schema): verify that the UNIQUE index on Cheque Reconciliation.cheque
exists in the database.

A (threading, DISABLED): simulate true concurrent double-reconcile under load.
Kept as a manual diagnostic tool; unstable in CI due to timing sensitivity.
"""
import threading
import time
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from treasury.tests.utils import (
	TreasuryFixtures,
	make_bank_transaction,
	make_payment,
	make_receipt,
	reconcile,
	safe_cancel_delete,
)

CHQ = 5000.0


class TestDoubleReconcileProtection(FrappeTestCase):
	"""B1 + B2: sequential + schema-level verification."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.fx = TreasuryFixtures()
		cls.supplier = cls.fx.party("Supplier", "Treasury Test Supplier")
		cls.party = cls.fx.party("Customer", "Treasury Test Customer")

	# ── B1: sequential duplicate ──

	def test_double_reconcile_sequential(self):
		"""Reconcile same cheque twice -> second must fail with unique violation."""
		cp, bt1, bt2 = None, None, None
		rcn_name = None
		try:
			cp = make_payment(self.fx, CHQ, cheque_no="T1-SEQ", party=self.supplier)
			bt1 = make_bank_transaction(
				self.fx, "withdrawal", CHQ, "T1-SEQ-1",
				party=self.supplier, party_type="Supplier")
			bt2 = make_bank_transaction(
				self.fx, "withdrawal", CHQ, "T1-SEQ-2",
				party=self.supplier, party_type="Supplier")

			# First reconcile — must succeed
			reconcile(self.fx, bt1.name, "Cheque Payment", cp.name, CHQ)
			rcns = frappe.get_all("Cheque Reconciliation",
				filters={"cheque": cp.name, "docstatus": 1}, pluck="name")
			self.assertEqual(len(rcns), 1)
			rcn_name = rcns[0]
			cp.reload()
			self.assertEqual(cp.cheque_status, "Reconciled")

			# Second reconcile — must be blocked
			with self.assertRaises(frappe.exceptions.ValidationError) as cm:
				reconcile(self.fx, bt2.name, "Cheque Payment", cp.name, CHQ)
			msg = str(cm.exception)
			self.assertIn("already reconciled", msg.lower(),
				f"Expected 'already reconciled', got: {msg}")

			# Still only one active RCN
			self.assertEqual(
				frappe.db.count("Cheque Reconciliation",
					{"cheque": cp.name, "docstatus": 1}), 1)
		finally:
			safe_cancel_delete("Cheque Reconciliation", rcn_name)
			safe_cancel_delete("Bank Transaction", bt2.name if bt2 else None)
			safe_cancel_delete("Bank Transaction", bt1.name if bt1 else None)
			safe_cancel_delete("Cheque Payment", cp.name if cp else None)

	def test_double_reconcile_receipt_sequential(self):
		"""Receipt chain version: deposit first, then double-reconcile."""
		from treasury.tests.utils import make_deposit
		cr, dep, bt1, bt2 = None, None, None, None
		rcn_name = None
		try:
			cr = make_receipt(self.fx, CHQ, cheque_no="T1-SEQ-REC", party=self.party)
			dep = make_deposit(self.fx, cr.name)
			bt1 = make_bank_transaction(
				self.fx, "deposit", CHQ, "T1-SEQ-REC-1",
				party=self.party, party_type="Customer")
			bt2 = make_bank_transaction(
				self.fx, "deposit", CHQ, "T1-SEQ-REC-2",
				party=self.party, party_type="Customer")

			reconcile(self.fx, bt1.name, "Cheque Receipt", cr.name, CHQ)
			rcns = frappe.get_all("Cheque Reconciliation",
				filters={"cheque": cr.name, "docstatus": 1}, pluck="name")
			self.assertEqual(len(rcns), 1)
			rcn_name = rcns[0]

			with self.assertRaises(frappe.exceptions.ValidationError):
				reconcile(self.fx, bt2.name, "Cheque Receipt", cr.name, CHQ)
		finally:
			safe_cancel_delete("Cheque Reconciliation", rcn_name)
			safe_cancel_delete("Bank Transaction", bt2.name if bt2 else None)
			safe_cancel_delete("Bank Transaction", bt1.name if bt1 else None)
			safe_cancel_delete("Cheque Deposit", dep.name if dep else None)
			safe_cancel_delete("Cheque Receipt", cr.name if cr else None)

	# ── B2: schema verification ──

	def test_unique_constraint_exists_on_schema(self):
		"""Verify UNIQUE index on Cheque Reconciliation.cheque in the DB."""
		indexes = frappe.db.sql(
			"""SHOW INDEX FROM `tabCheque Reconciliation`
			   WHERE Column_name = 'cheque' AND Non_unique = 0""",
			as_dict=True,
		)
		self.assertTrue(
			len(indexes) >= 1,
			"Expected a UNIQUE index on tabCheque Reconciliation.cheque, none found",
		)
		for idx in indexes:
			self.assertEqual(idx["Column_name"], "cheque")
			self.assertEqual(idx["Non_unique"], 0)


# ── Threading race test (DISABLED — manual diagnostic only) ──

RACE_RESULTS = []


def _reconcile_in_thread(site, site_path, cheque_dt, cheque_name, bt_name, amt, worker_id):
	"""Reconcile inside an independent frappe connection (runs in a thread)."""
	try:
		frappe.init(site=site, sites_path=site_path)
		frappe.connect()
		frappe.set_user("Administrator")
		frappe.flags.in_test = True
		from treasury.treasury.utils.bank_reconciliation import reconcile_vouchers_with_cheques
		reconcile_vouchers_with_cheques(bt_name, frappe.as_json([
			{"payment_doctype": cheque_dt, "payment_name": cheque_name, "amount": amt}]))
		RACE_RESULTS.append(f"worker-{worker_id}: OK (unexpected)")
	except Exception as e:
		RACE_RESULTS.append(f"worker-{worker_id}: BLOCKED ({type(e).__name__})")
	finally:
		frappe.destroy()


@unittest.skip("run manually to verify race protection under concurrent load")
class TestDoubleReconcileRace(FrappeTestCase):
	"""Threading-based concurrent duplicate (manual only — timing-sensitive)."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.fx = TreasuryFixtures()
		cls.supplier = cls.fx.party("Supplier", "Treasury Test Supplier")

	def test_concurrent_reconcile_blocked(self):
		SITE = "alsadara.new"
		SITE_PATH = "/home/kamal/frappe/alsadara-bench/frappe-bench/sites"
		cp = bt1 = bt2 = None
		rcn_name = None
		try:
			cp = make_payment(self.fx, CHQ, cheque_no="T1-RACE", party=self.supplier)
			bt1 = make_bank_transaction(
				self.fx, "withdrawal", CHQ, "T1-RACE-1",
				party=self.supplier, party_type="Supplier")
			bt2 = make_bank_transaction(
				self.fx, "withdrawal", CHQ, "T1-RACE-2",
				party=self.supplier, party_type="Supplier")

			barrier = threading.Barrier(2, timeout=10)
			RACE_RESULTS.clear()

			def w1():
				barrier.wait()
				_reconcile_in_thread(SITE, SITE_PATH, "Cheque Payment", cp.name, bt1.name, CHQ, 1)

			def w2():
				barrier.wait()
				time.sleep(0.001)
				_reconcile_in_thread(SITE, SITE_PATH, "Cheque Payment", cp.name, bt2.name, CHQ, 2)

			t1 = threading.Thread(target=w1)
			t2 = threading.Thread(target=w2)
			t1.start(); t2.start()
			t1.join(timeout=15); t2.join(timeout=15)

			print("\n  Race results:", RACE_RESULTS)

			active = frappe.db.count("Cheque Reconciliation",
				{"cheque": cp.name, "docstatus": 1})
			self.assertEqual(active, 1,
				f"Expected 1 active RCN after race, got {active}. Results: {RACE_RESULTS}")

			blocked = sum(1 for r in RACE_RESULTS if "BLOCKED" in r)
			self.assertGreaterEqual(blocked, 1,
				f"Expected >=1 BLOCKED worker. Results: {RACE_RESULTS}")

			rcn_name = frappe.db.get_value("Cheque Reconciliation",
				{"cheque": cp.name, "docstatus": 1}, "name")
		finally:
			safe_cancel_delete("Cheque Reconciliation", rcn_name)
			safe_cancel_delete("Bank Transaction", bt2.name if bt2 else None)
			safe_cancel_delete("Bank Transaction", bt1.name if bt1 else None)
			safe_cancel_delete("Cheque Payment", cp.name if cp else None)