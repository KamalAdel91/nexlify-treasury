# Copyright (c) 2026, Alsadara and contributors
# For license information, please see license.txt

import frappe
from erpnext import get_default_cost_center
from erpnext.accounts.general_ledger import make_gl_entries, make_reverse_gl_entries
from erpnext.accounts.utils import get_account_currency
from erpnext.setup.utils import get_exchange_rate
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from treasury.treasury.utils.ledger import delete_voucher_ledger_entries

VOUCHER_PARTY_ACCOUNT_FIELD = {
	"Sales Invoice": "debit_to",
	"Purchase Invoice": "credit_to",
	"Expense Claim": "payable_account",
}

PARTY_TYPE_FOR = {
	"Sales Invoice": "Customer",
	"Purchase Invoice": "Supplier",
	"Expense Claim": "Employee",
}

ALLOWED_DOC_TYPES = {
	"Money In": {"Sales Invoice", "Journal Entry"},
	"Money Out": {"Purchase Invoice", "Expense Claim", "Journal Entry"},
	"Transfer": set(),
}


class TreasuryTransactions(Document):
	def validate(self):
		self.validate_type_setup()
		self.validate_accounts()
		self.validate_items()
		self.sync_transactions_from_items()
		self.validate_transactions()
		self.update_totals()

	# ---------- validations ----------

	def validate_type_setup(self):
		ttype = self.transaction_type
		if ttype == "Transfer":
			if self.party or self.items or self.transactions:
				frappe.throw(_("Transfer must not have a Party, Voucher Allocations or Transactions"))
			if not self.from_account or not self.to_account:
				frappe.throw(_("From Account and To Account are required for a Transfer"))
			if self.from_account == self.to_account:
				frappe.throw(_("From Account and To Account must be different"))
			if flt(self.amount) <= 0:
				frappe.throw(_("Amount is required for a Transfer"))
		else:
			if not self.account:
				frappe.throw(_("Cash / Bank Account is required for {0}").format(ttype))
			if self.without_party:
				if self.items or self.party:
					frappe.throw(_("Clear the Party / Voucher Allocations or uncheck Without Party"))
			else:
				if not self.party_type or not self.party:
					frappe.throw(_("Party Type and Party are required (or check Without Party)"))
				if not self.items:
					frappe.throw(_("Allocate at least one voucher in the Match & Apply table"))

	def _validate_single_account(self, name, check_bank=False):
		company, is_group, disabled, acct_type = frappe.db.get_value(
			"Account", name, ["company", "is_group", "disabled", "account_type"]
		)
		if company != self.company:
			frappe.throw(_("Account {0} does not belong to company {1}").format(name, self.company))
		if is_group:
			frappe.throw(_("Account {0} is a group account").format(name))
		if disabled:
			frappe.throw(_("Account {0} is disabled").format(name))
		if check_bank and acct_type not in ("Cash", "Bank"):
			frappe.throw(
				_("Cash / Bank Account must be a Cash or Bank account (got {0})").format(name)
			)

	def validate_accounts(self):
		for field in ("account", "from_account", "to_account"):
			name = self.get(field)
			if not name:
				continue
			check_bank = field == "account" and self.transaction_type != "Transfer"
			self._validate_single_account(name, check_bank=check_bank)

	def validate_transactions(self):
		if self.transaction_type == "Transfer":
			return
		if not self.transactions:
			frappe.throw(_("Add at least one row in the Transactions table"))
		for row in self.transactions:
			if flt(row.amount) <= 0:
				frappe.throw(_("Row {0}: Amount must be greater than zero").format(row.idx))
			self._validate_single_account(row.account)

	def validate_items(self):
		if self.transaction_type == "Transfer" or self.without_party:
			return
		allowed = ALLOWED_DOC_TYPES.get(self.transaction_type, set())
		for item in self.items:
			if item.doc_type not in allowed:
				frappe.throw(
					_("Document Type {0} is not allowed for {1}").format(item.doc_type, self.transaction_type)
				)
			meta_field = VOUCHER_PARTY_ACCOUNT_FIELD.get(item.doc_type)
			if meta_field:
				party_field = "customer" if item.doc_type == "Sales Invoice" else "supplier"
				voucher_party = frappe.db.get_value(item.doc_type, item.voucher_no, party_field)
				if voucher_party and voucher_party != self.party:
					frappe.throw(
						_("Row {0}: voucher {1} belongs to {2}, not {3}").format(
							item.idx, item.voucher_no, voucher_party, self.party
						)
					)

	# ---------- totals ----------

	def update_totals(self):
		# Amount (read-only) = total of the Transactions table.
		# For a Transfer the user types the amount manually.
		if self.transaction_type != "Transfer":
			self.amount = sum(flt(t.amount) for t in (self.transactions or []))
		self.total_allocated = sum(flt(i.allocated_amount) for i in (self.items or []))
		self.difference_amount = (
			flt(self.amount) - self.total_allocated if self.transaction_type != "Transfer" else 0
		)

	def sync_transactions_from_items(self):
		"""Flatten voucher allocations into the Transactions table.

		Manual rows (no voucher reference) are kept untouched; one row per
		allocated voucher is (re)built from the Match & Apply table so the
		GL engine always books the legs from the Transactions table alone.
		"""
		if self.transaction_type == "Transfer":
			return
		manual = [r for r in self.get("transactions") if not r.against_voucher]
		self.set("transactions", manual)
		if self.without_party or not self.items:
			return
		for item in self.items:
			party_acct = self._party_account_for(item.doc_type, item.voucher_no)
			self.append(
				"transactions",
				{
					"account": party_acct,
					"amount": item.allocated_amount,
					"party_type": PARTY_TYPE_FOR.get(item.doc_type, self.party_type),
					"party": self.party,
					"against_voucher_type": item.doc_type,
					"against_voucher": item.voucher_no,
					"description": _("Allocation against {0} {1}").format(_(item.doc_type), item.voucher_no),
				},
			)

	# ---------- GL ----------

	def _source_currency(self):
		"""All amounts are entered in the treasury account currency."""
		if self.transaction_type == "Transfer":
			return get_account_currency(self.from_account)
		return get_account_currency(self.account)

	def _party_account_for(self, doc_type, voucher_no):
		field = VOUCHER_PARTY_ACCOUNT_FIELD.get(doc_type)
		if field:
			account = frappe.db.get_value(doc_type, voucher_no, field)
			if account:
				return account
		rows = frappe.get_all(
			"Journal Entry Account",
			filters={"parent": voucher_no, "party_type": self.party_type, "party": self.party},
			pluck="account",
			limit_page_length=1,
		)
		if not rows:
			frappe.throw(_("No party account found on {0} {1}").format(doc_type, voucher_no))
		return rows[0]

	def get_gl_entries(self):
		src_currency = self._source_currency()
		company_currency = frappe.get_cached_value("Company", self.company, "default_currency")
		rate = 1.0 if src_currency == company_currency else get_exchange_rate(src_currency, company_currency)
		base = frappe._dict({
			"company": self.company,
			"posting_date": getdate(self.posting_date),
			"voucher_type": "Treasury Transactions",
			"voucher_no": self.name or "",
			"remarks": self.remarks or ("Treasury {0}".format(self.transaction_type)),
			"cost_center": self.cost_center or get_default_cost_center(self.company),
		})

		def _row(account, amount, side, against_account=None, party_type=None, party=None,
		         against_voucher=None, against_voucher_type=None):
			amount = flt(amount)
			account_currency = get_account_currency(account)
			base_amount = amount if src_currency == company_currency else amount * rate
			if account_currency == src_currency:
				acct_amount = amount
			elif account_currency == company_currency:
				acct_amount = base_amount
			else:
				acct_amount = amount * get_exchange_rate(src_currency, account_currency)
			row = frappe._dict({**base})
			row.account = account
			row.account_currency = account_currency
			if side == "debit":
				row.debit, row.credit = base_amount, 0
				row.debit_in_account_currency, row.credit_in_account_currency = acct_amount, 0
			else:
				row.debit, row.credit = 0, base_amount
				row.debit_in_account_currency, row.credit_in_account_currency = 0, acct_amount
			row.against_account = against_account
			row.against_voucher = against_voucher
			row.against_voucher_type = against_voucher_type
			row.party_type = party_type
			row.party = party
			return row

		rows = []
		ttype = self.transaction_type

		if ttype == "Transfer":
			rows.append(_row(self.to_account, flt(self.amount), "debit",
			                 against_account=self.from_account))
			rows.append(_row(self.from_account, flt(self.amount), "credit",
			                 against_account=self.to_account))
			return rows

		money_out = ttype == "Money Out"

		# Transactions table legs — the opposite side of the treasury account.
		# Money Out: every row is Debit (treasury is credited).
		# Money In: every row is Credit (treasury is debited).
		# All amounts are entered positive; the direction is derived from the type.
		first_row_acct = None
		for line in self.transactions:
			if not first_row_acct:
				first_row_acct = line.account
			rows.append(_row(
				line.account, flt(line.amount), "debit" if money_out else "credit",
				against_account=self.account,
				party_type=line.party_type, party=line.party,
				against_voucher=line.against_voucher,
				against_voucher_type=line.against_voucher_type,
			))

		# Treasury leg
		rows.append(_row(
			self.account, flt(self.amount), "credit" if money_out else "debit",
			against_account=first_row_acct,
		))
		return rows

	def on_submit(self):
		make_gl_entries(self.get_gl_entries(), merge_entries=False)

	def on_cancel(self):
		# GL / Payment Ledger entries reference this voucher via dynamic links;
		# exempt them from the back-link check (same pattern as Journal Entry).
		from_doc_events = getattr(self, "ignore_linked_doctypes", ())
		self.ignore_linked_doctypes = (
			"GL Entry",
			"Payment Ledger Entry",
			"Repost Payment Ledger",
			"Repost Payment Ledger Items",
			"Repost Accounting Ledger",
			"Repost Accounting Ledger Items",
			"Unreconcile Payment",
			"Unreconcile Payment Entries",
			"Advance Payment Ledger Entry",
		)
		if from_doc_events and from_doc_events != self.ignore_linked_doctypes:
			self.ignore_linked_doctypes = self.ignore_linked_doctypes + from_doc_events

		make_reverse_gl_entries(voucher_type="Treasury Transactions", voucher_no=self.name)

	def on_trash(self):
		delete_voucher_ledger_entries(self)

