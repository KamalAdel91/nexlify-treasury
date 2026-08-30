# Copyright (c) 2026, Alsadara and contributors
# For license information, please see license.txt

import frappe
from erpnext.accounts.general_ledger import make_gl_entries, make_reverse_gl_entries
from erpnext.accounts.utils import get_account_currency
from erpnext.controllers.accounts_controller import AccountsController
from erpnext.setup.utils import get_exchange_rate
from frappe import _
from frappe.utils import flt, formatdate, getdate


CHEQUE_STATUS_IN_HAND = "Cheques In Hand"
CHEQUE_STATUS_UNDER_COLLECTION = "Under Collection"


class ChequeDeposit(AccountsController):
	def on_trash(self):
		from treasury.treasury.utils.ledger import delete_voucher_ledger_entries
		delete_voucher_ledger_entries(self)
	def validate(self):
		self.set_missing_values()
		self._validate_frozen_accounting()
		self.validate_currency()
		if not self.company:
			frappe.throw(_("Company is required"))
		if not self.bank:
			frappe.throw(_("Bank is required"))
		self.currency = self.currency or frappe.db.get_value("Company", self.company, "default_currency")
		self.validate_items()

	def set_missing_values(self):
		if frappe.in_test and not self.posting_date:
			self.posting_date = frappe.utils.today()

	def _validate_frozen_accounting(self):
		if not self.company or not self.posting_date:
			return
		frozen_till = frappe.db.get_value("Company", self.company, "accounts_frozen_till_date")
		if not frozen_till:
			return
		if getdate(self.posting_date) <= getdate(frozen_till):
			modifier_role = frappe.db.get_value(
				"Accounts Settings", "Accounts Settings", "frozen_accounts_modifier"
			)
			if modifier_role not in frappe.get_roles() and frappe.session.user != "Administrator":
				frappe.throw(
					_("Posting date {0} falls before Accounts Frozen Till {1} for Company {2}. "
					  "Only users with role {3} can post.").format(
						formatdate(self.posting_date), formatdate(frozen_till),
						self.company, modifier_role or "Accounts Manager"))

	def validate_currency(self):
		if not self.currency:
			return
		party_type, party = super().get_party()
		if not party_type or not party:
			return
		super().validate_currency()

	def validate_items(self):
		"""Each row must reference a submitted, in-hand cheque of this company/currency.
		The same cheque cannot appear twice in this document or in any other active deposit."""
		seen = set()
		total = 0
		for idx, item in enumerate(self.get("cheque_deposit_items") or [], start=1):
			row_no = _("Row #{0}").format(idx)
			cr = item.cheque_receipt
			if not cr:
				frappe.throw(_("{0}: Cheque Receipt is required").format(row_no))
			if cr in seen:
				frappe.throw(_("{0}: Cheque Receipt {1} is already in this deposit").format(row_no, frappe.bold(cr)))
			seen.add(cr)

			info = frappe.db.get_value(
				"Cheque Receipt",
				cr,
				["docstatus", "company", "currency", "cheque_status", "cheque_amount"],
				as_dict=True,
			)
			if not info or info.docstatus != 1:
				frappe.throw(
				_("{0}: Cheque Receipt {1} must be submitted before it can be deposited").format(row_no, frappe.bold(cr))
				)
			if info.company != self.company:
				frappe.throw(_("{0}: {1} belongs to another company ({2})").format(row_no, frappe.bold(cr), frappe.bold(info.company)))
			if info.currency != self.currency:
				from treasury.treasury.utils.validations import enrich

				enrich(
					"enforce_single_currency",
					True,
					"{0}: {1} is in {2} while this deposit is in {3}".format(
						row_no, frappe.bold(cr), frappe.bold(info.currency), frappe.bold(self.currency)
					),
				)
			if info.cheque_status != CHEQUE_STATUS_IN_HAND:
				frappe.throw(_("{0}: {1} is not in '{2}' (current status: {3}). Only cheques in hand can be deposited.").format(row_no, frappe.bold(cr), CHEQUE_STATUS_IN_HAND, frappe.bold(info.cheque_status)))

			conflict = frappe.db.sql(
				"""select d.name
					from `tabCheque Deposit` d
					join `tabCheque Deposit Items` i on i.parent = d.name
					where i.cheque_receipt = %s and d.docstatus < 2 and d.name != %s
					limit 1""",
				(cr, self.name or ""),
			)
			if conflict:
				frappe.throw(_("{0}: {1} is already selected in Cheque Deposit {2}").format(row_no, frappe.bold(cr), frappe.bold(conflict[0][0])))

			item.amount = flt(info.cheque_amount or 0)
			total += flt(info.cheque_amount or 0)

		self.total_amount = flt(total)

	def _get_settings_accounts(self):
		row = frappe.db.get_value(
			"Cheque Settings Account",
			{"parent": "Cheque Settings", "company": self.company},
			["cheque_receiving_account", "under_collection_account"],
			as_dict=True,
		) or {}
		receiving = row.get("cheque_receiving_account")
		under_collection = row.get("under_collection_account")
		if not receiving or not under_collection:
			frappe.throw(_("Set Cheque Receiving Account and Under Collection Account for Company {0} in Cheque Settings").format(frappe.bold(self.company)))
		return receiving, under_collection

	def _exchange_rate(self):
		"""Foreign->company currency rate for GL posting (mirrors Cheque Receipt)."""
		company_ccy = frappe.db.get_value("Company", self.company, "default_currency")
		rate = 1.0
		if self.currency != company_ccy:
			rate = get_exchange_rate(self.currency, company_ccy, self.posting_date)
			if not rate:
				frappe.throw(_("Could not determine exchange rate for {0}").format(self.currency))
		return flt(rate)

	def get_gl_entries(self):
		"""Stage-2 posting: move each cheque from the Cheque Receiving Account
		to the Under Collection Account.
		
		Dr Under Collection Account (per cheque)
		Cr Cheque Receiving Account  (per cheque, closing the stage-1 GL)
		"""
		receiving, under_collection = self._get_settings_accounts()
		rate = self._exchange_rate()
		base = frappe._dict(
			{
				"company": self.company,
				"posting_date": getdate(self.posting_date),
				"voucher_type": "Cheque Deposit",
				"voucher_no": self.name or "",
				"remarks": "Cheque Deposit to bank {0}".format(self.bank or "-"),
			}
		)
		rows = []
		for item in self.get("cheque_deposit_items") or []:
			amt = flt(item.amount) * rate
			if amt <= 0:
				continue

			dr = frappe._dict({**base})
			dr.account = under_collection
			dr.debit = amt
			dr.credit = 0
			dr.debit_in_account_currency = amt
			dr.credit_in_account_currency = 0
			dr.account_currency = get_account_currency(under_collection)
			dr.against_account = receiving
			dr.against_voucher_type = "Cheque Receipt"
			dr.against_voucher = item.cheque_receipt
			dr.user_remark = _("Deposit of {0}").format(item.cheque_receipt)
			rows.append(dr)

			cr = frappe._dict({**base})
			cr.account = receiving
			cr.debit = 0
			cr.credit = amt
			cr.debit_in_account_currency = 0
			cr.credit_in_account_currency = amt
			cr.account_currency = get_account_currency(receiving)
			cr.against_account = under_collection
			cr.against_voucher_type = "Cheque Receipt"
			cr.against_voucher = item.cheque_receipt
			cr.user_remark = _("Deposit of {0}").format(item.cheque_receipt)
			rows.append(cr)

		return rows

	def on_submit(self):
		# enforce chronological order (cheque date <= deposit date) as configured
		from treasury.treasury.utils.validations import enrich

		for item in self.get("cheque_deposit_items") or []:
			cheque_date = frappe.db.get_value("Cheque Receipt", item.cheque_receipt, "cheque_date")
			if cheque_date and self.posting_date:
				cheque_date = getdate(cheque_date)
				deposit_date = getdate(self.posting_date)
				if cheque_date > deposit_date:
					enrich(
						"enforce_cheque_date_chain",
						True,
						"Cheque {0} is dated {1} after this deposit date {2}.".format(
							frappe.bold(item.cheque_receipt), cheque_date, deposit_date
						),
					)
		make_gl_entries(self.get_gl_entries(), merge_entries=False)
		for item in self.get("cheque_deposit_items") or []:
			frappe.db.set_value(
				"Cheque Receipt",
				item.cheque_receipt,
				{
				"cheque_status": CHEQUE_STATUS_UNDER_COLLECTION,
				"cheque_deposit": self.name,
				},
			)

	def on_cancel(self):
		make_reverse_gl_entries(voucher_type="Cheque Deposit", voucher_no=self.name)
		# restore each cheque's state from reality (deposit is being cancelled)
		from treasury.treasury.utils.cheque_lifecycle import sync_stage

		sync_stage(self)

	def before_cancel(self):
		# Standard, always-enforced rule: a deposit that has a submitted linked
		# Cheque Reconciliation cannot be cancelled. The user can only reverse
		# the top stage first - so the message offers a direct link to open that
		# reconciliation, cancel/delete it, then come back here to cancel.
		linked = frappe.db.sql(
			"""select r.name
				from `tabCheque Reconciliation` r
				join `tabCheque Deposit Items` i on i.cheque_receipt = r.cheque
				where i.parent = %s and r.docstatus = 1
				limit 1""",
			(self.name,),
		)
		if linked:
			rcn_name = linked[0][0]
			frappe.throw(
				_(
					"Cheque Deposit {0} is linked to Cheque Reconciliation {1}. "
					"Cancel that reconciliation from the Reconciliation field or All Cheques "
					"first, then cancel this deposit."
				).format(frappe.bold(self.name), frappe.bold(rcn_name)),
				frappe.ValidationError,
			)

		self.ignore_linked_doctypes = ["GL Entry", "Payment Ledger Entry"]
		# Cancelling a deposit must NOT force cancelling its Cheque Receipts:
		# on_cancel re-derives each cheque from reality (sync_stage -> back to
		# "Cheques In Hand" and cheque_deposit = None), so the receipts' link
		# must not block this cancel. The real business guard is the
		# reconciliation freeze enforced above, therefore skip the framework's
		# back-link check entirely (document.check_no_back_links_exist honours
		# flags.ignore_links) — this keeps cancel working standalone regardless
		# of where the frappe version runs the check relative to on_cancel.
		self.flags.ignore_links = True


@frappe.whitelist()
def get_pending_cheques(company, currency=None):
	"""Submitted Cheque Receipts still in 'Cheques In Hand' and not reserved
	by any other active Cheque Deposit — resolved in a single query."""

	if not frappe.has_permission("Cheque Receipt", "read"):
		frappe.throw(_("Not permitted to read Cheque Receipt"), frappe.PermissionError)

	cr = frappe.qb.DocType("Cheque Receipt")
	cdi = frappe.qb.DocType("Cheque Deposit Items")
	cd = frappe.qb.DocType("Cheque Deposit")

	query = (
		frappe.qb.from_(cr)
		.left_join(cdi)
		.on((cdi.cheque_receipt == cr.name) & (cdi.parenttype == "Cheque Deposit"))
		.left_join(cd)
		.on((cd.name == cdi.parent) & (cd.docstatus < 2))
		.select(
			cr.name, cr.party_type, cr.party, cr.party_name,
			cr.cheque_no, cr.drawn_bank, cr.cheque_date, cr.cheque_amount,
		)
		.where(cr.docstatus == 1)
		.where(cr.company == company)
		.where(cr.cheque_status == CHEQUE_STATUS_IN_HAND)
		.where(cd.name.isnull())  # no active deposit reservation
		.orderby(cr.posting_date, cr.creation)
	)
	if currency:
		query = query.where(cr.currency == currency)

	return query.run(as_dict=True)


@frappe.whitelist()
def get_preview_ledger(company, posting_date, currency, bank, items=None):
	"""Return exactly how the GL entry will look WITHOUT saving anything."""
	if not frappe.has_permission("Cheque Deposit", "read"):
		frappe.throw(_("Not permitted to read Cheque Deposit"), frappe.PermissionError)

	def _rows(value):
		if not value:
			return []
		if isinstance(value, str):
			value = frappe.parse_json(value)
		return value

	fake = frappe.new_doc("Cheque Deposit")
	fake.update(
		{
			"company": company,
			"posting_date": posting_date,
			"currency": currency,
			"bank": bank,
		}
	)
	for it in _rows(items):
		fake.append("cheque_deposit_items", it)

	fake.validate()
	rows = fake.get_gl_entries()

	out = []
	for row in rows:
		out.append(
			{
				"account": row.account,
				"debit": row.get("debit", 0),
				"credit": row.get("credit", 0),
				"currency": row.get("account_currency"),
			}
		)
	return out