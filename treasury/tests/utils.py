"""Shared fixtures/helpers for treasury integration tests.

Creates (or reuses) the minimal ERPNext setup needed to run real submit/cancel
lifecycle tests: company, GL accounts, Bank/Bank Account, Cheque Settings,
parties, and (for multi-currency) Currency Exchange.
"""
import json

import frappe
from frappe.utils import today, flt


def _group_like(fragment, company):
	return frappe.get_value(
		"Account",
		{"company": company, "account_name": ["like", f"%{fragment}%"], "is_group": 1},
		"name",
	)


def get_or_create_account(account_name, parent, company, account_type=None, root_type=None):
	abbr = frappe.get_value("Company", company, "abbr")
	name = f"{account_name} - {abbr}"
	if not frappe.db.exists("Account", name):
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": account_name,
				"company": company,
				"parent_account": parent,
				"account_type": account_type or "",
				"is_group": 0,
				"root_type": root_type or "Asset",
			}
		).insert(ignore_permissions=True)
	return name


def _get_or_create_income_account(company):
	for candidate in frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0, "root_type": "Income", "account_name": ["like", "%Interest Income%"]},
		pluck="name",
		limit=1,
	):
		return candidate
	abbr = frappe.get_value("Company", company, "abbr")
	name = f"Treasury Test Income - {abbr}"
	if not frappe.db.exists("Account", name):
		parent = frappe.get_value(
			"Account", {"company": company, "is_group": 1, "root_type": "Income"}, "name"
		)
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": "Treasury Test Income",
				"company": company,
				"parent_account": parent,
				"is_group": 0,
				"root_type": "Income",
			}
		).insert(ignore_permissions=True)
	return name


class TreasuryFixtures:
	"""Resolve/create the shared fixture set once per test class."""

	def __init__(self):
		self.company = frappe.get_all("Company", limit=1, pluck="name")[0]
		self.currency = frappe.get_value("Company", self.company, "default_currency")
		abbr = frappe.get_value("Company", self.company, "abbr")

		ca_group = _group_like("Current Assets", self.company)
		bank_group = _group_like("Bank Accounts", self.company)

		self.receiving = get_or_create_account("Cheques In Hand", ca_group, self.company)
		self.under_collection = get_or_create_account("Under Collection", ca_group, self.company)
		self.income = _get_or_create_income_account(self.company)
		self.bank_gl = get_or_create_account("Treasury Test Bank", bank_group, self.company, account_type="Bank")

		# Payment Entry fixtures
		expense_group = _group_like("Expenses", self.company)
		self.expense_account = get_or_create_account("Treasury Test Expense", expense_group, self.company, root_type="Expense")
		liability_group = _group_like("Current Liabilities", self.company)
		self.payable_account = get_or_create_account("Treasury Test Payable", liability_group, self.company, root_type="Liability")
		self.paid_from = self.bank_gl  # for Pay: debit bank
		self.paid_to = self.payable_account  # for Pay: credit payable / for Receive: debit = bank
		self.income_account = self.income  # alias for Receive revenue account

		# Cost center
		if not frappe.db.exists("Cost Center", "Main - " + abbr):
			cc_name = "Main - " + abbr
			root = frappe.get_value("Cost Center", {"company": self.company, "is_group": 1}, "name")
			frappe.get_doc({
				"doctype": "Cost Center",
				"cost_center_name": cc_name,
				"company": self.company,
				"parent_cost_center": root,
				"is_group": 0,
			}).insert(ignore_permissions=True)
		self.cost_center = frappe.get_value("Cost Center", {"company": self.company, "is_group": 0}, "name")

		# Mode of Payment (Cash for test simplicity)
		self.mode_of_payment = frappe.get_value("Mode of Payment", {"enabled": 1}, "name")
		if not self.mode_of_payment:
			self.mode_of_payment = frappe.get_doc({
				"doctype": "Mode of Payment",
				"mode_of_payment": "Treasury Test Cash",
				"enabled": 1,
				"type": "Cash",
			}).insert(ignore_permissions=True).name

		bank_name = f"Treasury Test Bank - {abbr}"
		if not frappe.db.exists("Bank", bank_name):
			frappe.get_doc({"doctype": "Bank", "bank_name": bank_name}).insert(ignore_permissions=True)

		self.bank_account = frappe.get_value("Bank Account", {"account": self.bank_gl}, "name")
		if not self.bank_account:
			frappe.get_doc(
				{
					"doctype": "Bank Account",
					"account_name": f"Treasury Test Bank Account - {abbr}",
					"bank": bank_name,
					"account": self.bank_gl,
					"company": self.company,
					"is_default": 1,
					"account_currency": self.currency,
				}
			).insert(ignore_permissions=True)
			self.bank_account = frappe.get_value("Bank Account", {"account": self.bank_gl}, "name")

		if not frappe.db.exists("Cheque Settings", "Cheque Settings"):
			frappe.get_doc({"doctype": "Cheque Settings"}).insert(ignore_permissions=True)
		cs = frappe.get_doc("Cheque Settings", "Cheque Settings")
		if not any(r.get("company") == self.company for r in cs.get("accounts") or []):
			cs.append(
				"accounts",
				{
					"company": self.company,
					"cheque_receiving_account": self.receiving,
					"under_collection_account": self.under_collection,
					"cheque_issuing_account": self.under_collection,
				},
			)
			cs.flags.ignore_permissions = True
			cs.save()

	def party(self, doctype, name):
		if not frappe.db.exists(doctype, name):
			payload = {
				"doctype": doctype,
				"customer_name" if doctype == "Customer" else "supplier_name": name,
			}
			if doctype == "Customer":
				payload["customer_group"] = "Commercial"
			else:
				payload["supplier_group"] = "All Supplier Groups"
			frappe.get_doc(payload).insert(ignore_permissions=True)
		return name

	def ensure_currency_exchange(self, from_currency, to_currency, rate):
		"""Create (or reuse) a Currency Exchange; returns the effective rate."""
		existing = frappe.db.get_value(
			"Currency Exchange",
			{"from_currency": from_currency, "to_currency": to_currency},
			"exchange_rate",
		)
		if existing is not None:
			return flt(existing)
		frappe.get_doc(
			{
				"doctype": "Currency Exchange",
				"from_currency": from_currency,
				"to_currency": to_currency,
				"exchange_rate": rate,
				"date": today(),
				"for_buying": 1,
				"for_selling": 1,
			}
		).insert(ignore_permissions=True)
		return rate


# ---------------- document factories ----------------

def make_receipt(fx, amount, currency=None, cheque_no="TST-REC", party=None, party_type="Customer", without_party=1):
	doc = frappe.get_doc(
		{
			"doctype": "Cheque Receipt",
			"company": fx.company,
			"posting_date": today(),
			"currency": currency or fx.currency,
			"cheque_no": cheque_no,
			"cheque_date": today(),
			"cheque_amount": amount,
			"drawn_bank": frappe.get_value("Bank Account", fx.bank_account, "bank"),
			"bank_account": fx.bank_account,
			"without_party": without_party,
			"account": fx.income,
			"party_type": party_type,
			"party": party or "",
		}
	)
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc


def make_payment(fx, amount, currency=None, cheque_no="TST-PAY", party=None, party_type="Supplier", without_party=1):
	doc = frappe.get_doc(
		{
			"doctype": "Cheque Payment",
			"company": fx.company,
			"posting_date": today(),
			"currency": currency or fx.currency,
			"cheque_no": cheque_no,
			"cheque_date": today(),
			"cheque_amount": amount,
			"bank": fx.bank_account,
			"without_party": without_party,
			"account": fx.income,
			"party_type": party_type,
			"party": party or "",
		}
	)
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc


def make_deposit(fx, receipt_name, currency=None):
	doc = frappe.get_doc(
		{
			"doctype": "Cheque Deposit",
			"company": fx.company,
			"posting_date": today(),
			"bank": fx.bank_account,
			"currency": currency or fx.currency,
			"cheque_deposit_items": [{"cheque_receipt": receipt_name}],
		}
	)
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc


def make_bank_transaction(fx, direction, amount, reference, party=None, party_type=None):
	doc = frappe.get_doc(
		{
			"doctype": "Bank Transaction",
			"bank_account": fx.bank_account,
			"date": today(),
			direction: amount,
			"reference_number": reference,
			"party_type": party_type or "",
			"party": party or "",
			"description": f"treasury test {reference}",
		}
	)
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc


def reconcile(fx, bank_transaction_name, cheque_doctype, cheque_name, amount):
	from treasury.treasury.utils.bank_reconciliation import reconcile_vouchers_with_cheques

	return reconcile_vouchers_with_cheques(
		bank_transaction_name,
		json.dumps([{"payment_doctype": cheque_doctype, "payment_name": cheque_name, "amount": amount}]),
	)


# ---------------- assertion helpers ----------------

def gl_entries(voucher_type, voucher_no):
	return frappe.db.sql(
		"""SELECT account, debit, credit, debit_in_account_currency,
			      credit_in_account_currency, account_currency
		   FROM `tabGL Entry`
		   WHERE voucher_type=%s AND voucher_no=%s AND is_cancelled=0""",
		(voucher_type, voucher_no),
		as_dict=True,
	)


def gl_totals(voucher_type, voucher_no):
	rows = gl_entries(voucher_type, voucher_no)
	debit = sum(flt(r.debit) for r in rows)
	credit = sum(flt(r.credit) for r in rows)
	return debit, credit, len(rows)


def safe_cancel_delete(doctype, name):
	"""Cancel + delete a doc, tolerating already-deleted docs."""
	if not name or not frappe.db.exists(doctype, name):
		return
	try:
		doc = frappe.get_doc(doctype, name)
		if doc.docstatus == 1:
			doc.cancel()
		frappe.delete_doc(doctype, name, force=1, ignore_permissions=True)
	except Exception:
		frappe.db.rollback()
