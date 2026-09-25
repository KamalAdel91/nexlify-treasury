# Copyright (c) 2026, Alsadara and contributors
# For license information, please see license.txt
"""Cheque Allocation - settles a cheque's unallocated balance against an invoice.

Created by Payment Reconciliation (overrides/payment_reconciliation.py), one per
cheque + invoice pair, and cancelled by Unreconcile Payment. Posts two GL rows on
the party, in company currency:

	Receivable (Cheque Receipt):  Dr cheque_account  against the cheque
								  Cr account         against the invoice
	Payable    (Cheque Payment):  Cr cheque_account  against the cheque
								  Dr account         against the invoice

The Payment Ledger follows the GL: the cheque's open balance and the invoice
outstanding both go down by the allocated amount. Cancelling reverses both.
"""

import erpnext
import frappe
from erpnext.accounts.general_ledger import make_gl_entries, make_reverse_gl_entries
from erpnext.controllers.accounts_controller import AccountsController
from frappe import _
from frappe.utils import flt

from treasury.treasury.utils import cheque_shared
from treasury.treasury.utils.cheque_allocation import CHEQUE_DOCTYPES, open_amount


class ChequeAllocation(AccountsController):
	def validate(self):
		cheque_shared.validate_frozen_accounting(self)
		if self.cheque_type not in CHEQUE_DOCTYPES:
			frappe.throw(_("Cheque Type must be Cheque Receipt or Cheque Payment"))
		if flt(self.allocated_amount) <= 0:
			frappe.throw(_("Allocated Amount must be greater than zero"))

		company_currency = erpnext.get_company_currency(self.company)
		for account in (self.account, self.cheque_account):
			if frappe.get_cached_value("Account", account, "account_currency") != company_currency:
				frappe.throw(
					_("Account {0} is not in {1}. Cheque allocation supports company-currency party accounts only.").format(
						frappe.bold(account), company_currency
					)
				)

		if self.docstatus == 0 or getattr(self, "_action", None) == "submit":
			self._validate_open_amounts()

	def _validate_open_amounts(self):
		cheque_open = open_amount(self.cheque_type, self.cheque, self.cheque_account, self.party_type, self.party, advance=True)
		if flt(self.allocated_amount) - cheque_open > 0.009:
			frappe.throw(
				_("Allocated Amount {0} is more than the open balance {1} of {2} {3}").format(
					self.allocated_amount, cheque_open, _(self.cheque_type), frappe.bold(self.cheque)
				)
			)
		invoice_open = open_amount(self.invoice_type, self.invoice, self.account, self.party_type, self.party)
		if flt(self.allocated_amount) - invoice_open > 0.009:
			frappe.throw(
				_("Allocated Amount {0} is more than the outstanding {1} of {2} {3}").format(
					self.allocated_amount, invoice_open, _(self.invoice_type), frappe.bold(self.invoice)
				)
			)

	def get_gl_entries(self):
		receivable = erpnext.get_party_account_type(self.party_type) == "Receivable"
		amount = flt(self.allocated_amount, 2)
		currency = erpnext.get_company_currency(self.company)
		remarks = self.remarks or _("Cheque {0} allocated to {1} {2}").format(self.cheque, _(self.invoice_type), self.invoice)
		base = {
			"company": self.company,
			"posting_date": self.posting_date,
			"voucher_type": self.doctype,
			"voucher_no": self.name,
			"party_type": self.party_type,
			"party": self.party,
			"cost_center": self.cost_center,
			"account_currency": currency,
			"remarks": remarks,
		}
		cheque_side = frappe._dict(
			base, account=self.cheque_account, against_voucher_type=self.cheque_type,
			against_voucher=self.cheque, against=self.account,
		)
		invoice_side = frappe._dict(
			base, account=self.account, against_voucher_type=self.invoice_type,
			against_voucher=self.invoice, against=self.cheque_account,
		)
		debit_row, credit_row = (cheque_side, invoice_side) if receivable else (invoice_side, cheque_side)
		debit_row.update(debit=amount, debit_in_account_currency=amount, credit=0, credit_in_account_currency=0)
		credit_row.update(debit=0, debit_in_account_currency=0, credit=amount, credit_in_account_currency=amount)
		return [debit_row, credit_row]

	def on_submit(self):
		make_gl_entries(self.get_gl_entries(), merge_entries=False)

	def before_cancel(self):
		self.ignore_linked_doctypes = (
			"GL Entry", "Payment Ledger Entry", "Unreconcile Payment", "Unreconcile Payment Entries",
		)

	def on_cancel(self):
		make_reverse_gl_entries(voucher_type=self.doctype, voucher_no=self.name)

	def on_trash(self):
		from treasury.treasury.utils.ledger import delete_voucher_ledger_entries

		delete_voucher_ledger_entries(self)
