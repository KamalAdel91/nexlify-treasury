"""Regression tests for cheque_shared.validate_items voucher batch-loading.

Root cause fixed: the batch-load query selected party_type/party/customer/
supplier/employee unconditionally, but those columns don't exist on every
voucher doctype (Sales Invoice has no party_type/party — it has customer;
Journal Entry's parent has neither party nor grand_total/outstanding_amount),
which crashed saves with MySQL 1054 "Unknown column 'party_type' in 'SELECT'".
The fix builds the SELECT from the columns that actually exist per voucher
table and resolves Journal Entry party ownership via its Journal Entry
Account rows.
"""

import unittest

import frappe

from treasury.treasury.utils.cheque_shared import validate_items


class _FakeDoc(frappe._dict):
	"""Minimal doc duck-type covering everything validate_items uses:
	without_party, party_type, party, company, currency, get(items_fieldname)."""

	without_party = 0

	def __init__(self, items, party_type, party, company):
		super().__init__()
		self._items = items
		self.party_type = party_type
		self.party = party
		self.company = company
		self.currency = "EGP"

	def get(self, fieldname):
		if fieldname == "items":
			return self._items
		return super().get(fieldname)


def _row(doc_type, voucher_no="__NO_SUCH_VOUCHER__"):
	return frappe._dict(
		doc_type=doc_type,
		voucher_no=voucher_no,
		allocated_amount=1,
		apply_deduction=0,
	)


class TestVoucherBatchLoad(unittest.TestCase):
	"""The batch-load must adapt its SELECT to the columns that actually
	exist on each voucher table (never MySQL 1054) and must skip voucher
	types whose table is not installed — surfacing a clean ValidationError
	("must be an existing submitted document") instead of a crash."""

	def _validate(self, doc_type, party_field, party_type):
		fake = _FakeDoc(
			[_row(doc_type)], party_type, "__NO_SUCH_PARTY__", "__NO_SUCH_COMPANY__"
		)
		return validate_items(fake, "items", {party_type: (doc_type,)}, {doc_type: party_field})

	def test_sales_invoice_row_does_not_raise_sql_error(self):
		# regression: used to crash with OperationalError 1054 (no party_type col)
		with self.assertRaises(frappe.ValidationError):
			self._validate("Sales Invoice", "customer", "Customer")

	def test_purchase_invoice_row_does_not_raise_sql_error(self):
		with self.assertRaises(frappe.ValidationError):
			self._validate("Purchase Invoice", "supplier", "Supplier")

	def test_payment_entry_row_does_not_raise_sql_error(self):
		with self.assertRaises(frappe.ValidationError):
			self._validate("Payment Entry", "party", "Supplier")

	def test_journal_entry_row_does_not_raise_sql_error(self):
		# regression: parent JE has no party/grand_total/outstanding columns
		with self.assertRaises(frappe.ValidationError):
			self._validate("Journal Entry", "party", "Supplier")

	def test_uninstalled_voucher_table_skipped_not_crashed(self):
		# Expense Claim may not be installed on the site; either way the
		# outcome must be a clean ValidationError, never TableMissingError
		with self.assertRaises(frappe.ValidationError):
			self._validate("Expense Claim", "employee", "Employee")

	def test_journal_entry_party_matched_via_rows(self):
		row = frappe.get_all(
			"Journal Entry Account",
			filters={"docstatus": 1, "party_type": "Supplier"},
			fields=["parent", "party"],
			limit_page_length=1,
		)
		if not row:
			self.skipTest("no submitted Journal Entry with Supplier party rows")
		r = row[0]
		company = frappe.db.get_value("Journal Entry", r.parent, "company")
		fake = _FakeDoc([_row("Journal Entry", r.parent)], "Supplier", r.party, company)
		total = validate_items(
			fake, "items", {"Supplier": ("Journal Entry",)}, {"Journal Entry": "party"}
		)
		self.assertEqual(total, 1)

	def test_sales_invoice_party_match_and_amounts(self):
		row = frappe.get_all(
			"Sales Invoice",
			filters={"docstatus": 1, "outstanding_amount": [">", 0]},
			fields=["name", "customer", "company", "grand_total", "outstanding_amount"],
			limit_page_length=1,
		)
		if not row:
			self.skipTest("no submitted Sales Invoice on site")
		si = row[0]
		fake = _FakeDoc([_row("Sales Invoice", si.name)], "Customer", si.customer, si.company)
		total = validate_items(
			fake, "items", {"Customer": ("Sales Invoice",)}, {"Sales Invoice": "customer"}
		)
		self.assertEqual(total, 1)
		item = fake.get("items")[0]
		self.assertEqual(item.grand_total, si.grand_total or 0)
		self.assertEqual(item.outstanding, si.outstanding_amount or 0)