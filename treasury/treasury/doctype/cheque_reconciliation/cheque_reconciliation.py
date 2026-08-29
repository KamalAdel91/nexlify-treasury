# Copyright (c) 2026, Alsadara and contributors
# For license information, please see license.txt

import frappe
from erpnext.accounts.general_ledger import make_gl_entries, make_reverse_gl_entries
from erpnext.accounts.utils import get_account_currency
from erpnext.setup.utils import get_exchange_rate
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate


class ChequeReconciliation(Document):
	def on_trash(self):
		from treasury.treasury.utils.ledger import delete_voucher_ledger_entries
		delete_voucher_ledger_entries(self)
	"""Independent GL journal for the stage-3 bank clearance of a cheque.

	Posting date = the Bank Transaction date (not the deposit/receipt
	date). Posted under this document's own voucher type/number so it
	never mixes with the Cheque Deposit / Cheque Payment GL entries.
	"""

	def validate(self):
		self.gl_preview = self._gl_preview()

	def on_submit(self):
		make_gl_entries(self._gl_rows(), merge_entries=False)
		frappe.db.set_value(
			self.cheque_type,
			self.cheque,
			{
				"cheque_status": "Reconciled",
				"bank_transaction": self.bank_transaction,
				"clearance_date": getdate(self.posting_date),
				"reconciliation_doc": self.name,
			},
		)

	def on_cancel(self):
		self.ignore_linked_doctypes = ["GL Entry"]
		make_reverse_gl_entries(voucher_type=self.doctype, voucher_no=self.name)
		# restore the cheque's state from reality (this RCN is being cancelled)
		from treasury.treasury.utils.cheque_lifecycle import sync_stage

		sync_stage(self)
		self._delink_from_bank_transaction()

	# --------------------------------------------------------------- helpers

	def _settings_account(self, fieldname):
		account = frappe.db.get_value(
			"Cheque Settings Account",
			{"parent": "Cheque Settings", "company": self.company},
			fieldname,
		)
		if not account:
			frappe.throw(
				_("Set {0} for Company {1} in Cheque Settings").format(
					frappe.bold(fieldname.replace("_", " ").title()), frappe.bold(self.company)
				)
			)
		return account

	def _bank_gl(self):
		bank_gl = frappe.db.get_value("Bank Account", self.bank_account, "account")
		if not bank_gl:
			frappe.throw(_("Bank Account {0} has no GL account").format(frappe.bold(self.bank_account)))
		return bank_gl

	def _gl_detail(self):
		bank_gl = self._bank_gl()
		if self.cheque_type == "Cheque Receipt":
			other_gl = self._settings_account("under_collection_account")
			return bank_gl, other_gl
		other_gl = self._settings_account("cheque_issuing_account")
		return other_gl, bank_gl

	def _exchange_rate(self):
		"""Foreign->company currency rate for GL posting (mirrors Cheque Receipt)."""
		company_ccy = frappe.db.get_value("Company", self.company, "default_currency")
		rate = 1.0
		if self.currency != company_ccy:
			rate = get_exchange_rate(self.currency, company_ccy, self.posting_date)
			if not rate:
				frappe.throw(_("Could not determine exchange rate for {0}").format(self.currency))
		return flt(rate)

	def _gl_rows(self):
		debit_gl, credit_gl = self._gl_detail()
		remark = _("Cleared cheque {0} {1} via Bank Transaction {2}").format(
			_(self.cheque_type), self.cheque, self.bank_transaction
		)
		amount = flt(self.total_amount) * self._exchange_rate()
		return [
			self._gl_row(debit_gl, amount, 0, credit_gl, remark),
			self._gl_row(credit_gl, 0, amount, debit_gl, remark),
		]

	def _gl_row(self, account, debit, credit, against_account, remark):
		return frappe._dict(
			{
				"account": account,
				"account_currency": get_account_currency(account),
				"debit": flt(debit),
				"credit": flt(credit),
				"debit_in_account_currency": flt(debit),
				"credit_in_account_currency": flt(credit),
				"against_account": against_account,
				"company": self.company,
				"posting_date": self.posting_date,
				"transaction_date": self.posting_date,
				"voucher_type": self.doctype,
				"voucher_no": self.name,
				"remarks": remark,
				"user_remark": remark,
			}
		)

	def _gl_preview(self):
		if not self.bank_account or not self.cheque_type:
			return ""
		debit_gl, credit_gl = self._gl_detail()
		return _("Dr {0} {1}  /  Cr {2} {1}  ({3})").format(
			debit_gl, flt(self.total_amount), credit_gl, _(self.cheque_type)
		)

	def _restore_cheque(self):
		if not (self.cheque_type and self.cheque):
			return
		if not frappe.db.exists(self.cheque_type, self.cheque):
			return
		status = "Under Collection" if self.cheque_type == "Cheque Receipt" else "Issued"
		frappe.db.set_value(
			self.cheque_type,
			self.cheque,
			{"cheque_status": status, "bank_transaction": None, "clearance_date": None, "reconciliation_doc": None},
		)

	def _delink_from_bank_transaction(self):
		if not self.bank_transaction:
			return
		bt = frappe.get_doc("Bank Transaction", self.bank_transaction)
		if bt.docstatus != 1:
			return
		changed = False
		for pe in list(bt.payment_entries):
			if pe.payment_document == self.cheque_type and pe.payment_entry == self.cheque:
				bt.remove(pe)
				changed = True
		if changed:
			bt.flags.ignore_permissions = True
			bt.update_allocated_amount()
			bt.set_status()
			bt.save()