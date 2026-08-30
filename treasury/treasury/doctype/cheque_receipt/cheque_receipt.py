# Copyright (c) 2026, Alsadara and contributors
# For license information, please see license.txt

import json

import frappe
from erpnext import get_default_cost_center
from erpnext.accounts.general_ledger import make_gl_entries, make_reverse_gl_entries
from erpnext.accounts.utils import get_account_currency
from erpnext.controllers.accounts_controller import AccountsController
from erpnext.setup.utils import get_exchange_rate
from frappe import _
from frappe.utils import cint, flt, formatdate, getdate, nowdate
from treasury.treasury.utils.cheque_shared import resolve_difference_account, resolve_party_name


PARTY_ACCOUNT_TYPE_MAP = {
	"Customer": "Receivable",
	"Supplier": "Payable",
}

VOUCHER_PARTY_FIELDS = {
	"Sales Invoice": "customer",
	"Delivery Note": "customer",
	"Sales Order": "customer",
	"Purchase Invoice": "supplier",
	"Purchase Receipt": "supplier",
	"Expense Claim": "employee",
	"Salary Slip": "employee",
	"Journal Entry": "party",
}

PARTY_TYPE_VOUCHERS = {
	"Customer": ("Sales Invoice", "Delivery Note", "Sales Order"),
	"Supplier": ("Purchase Invoice", "Purchase Receipt"),
	"Employee": ("Expense Claim", "Salary Slip"),
	"Shareholder": (),
}


class ChequeReceipt(AccountsController):
	def on_trash(self):
		from treasury.treasury.utils.ledger import delete_voucher_ledger_entries
		delete_voucher_ledger_entries(self)

	def validate(self):
		self.set_missing_values()
		self._validate_frozen_accounting()
		self.validate_currency()
		self.validate_booking_mode()
		self.validate_basic_data()
		self.validate_items()
		self.validate_deductions()

	def set_missing_values(self):
		if frappe.in_test and not self.posting_date:
			self.posting_date = frappe.utils.today()
		if self.get("party"):
			self.party_name = resolve_party_name(self.party_type, self.party)
		else:
			self.set("party_name", None)
		if not self.cost_center:
			self.cost_center = get_default_cost_center(self.company)

	def _validate_frozen_accounting(self):
		if not self.company or not self.posting_date:
			return
		frozen_till = frappe.db.get_value("Company", self.company, "accounts_frozen_till_date")
		if not frozen_till:
			return
		if getdate(self.posting_date) <= getdate(frozen_till):
			modifier_role = frappe.db.get_value(
				"Accounts Settings", "Accounts Settings", "frozen_accounts_modifier")
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

	def validate_booking_mode(self):
		"""Book either against a Party or directly against an Account."""
		if self.without_party:
			for f in ("party_type", "party", "party_name"):
				self.set(f, None)
			if not self.account:
				frappe.throw(_("Account is required when booking without a Party"))
		else:
			if self.party and not self.party_type:
				frappe.throw(_("Party Type is required to fetch Party Name"))

	def validate_basic_data(self):
		if not self.company:
			frappe.throw(_("Company is required"))
		if flt(self.cheque_amount) <= 0:
			frappe.throw(_("Cheque Amount must be greater than zero"))
		self.currency = self.currency or frappe.db.get_value("Company", self.company, "default_currency")

	def validate_items(self):
		"""Validate allocation rows (shared)."""
		from treasury.treasury.utils.cheque_shared import validate_items
		return validate_items(self, "table_wgxh", PARTY_TYPE_VOUCHERS, VOUCHER_PARTY_FIELDS)



	def validate_deductions(self):
		"""Validate deductions (shared); receipts accept cheque surplus as advance."""
		from treasury.treasury.utils.cheque_shared import validate_deductions
		return validate_deductions(self, "table_wgxh", "Cheque Receipt", allow_cheque_surplus=True)




	def _get_receiving_account(self):
		row = frappe.get_all(
			"Cheque Settings Account",
			filters={"parent": "Cheque Settings", "company": self.company},
			fields=["cheque_receiving_account"],
			limit_page_length=1,
		)
		account = row[0].cheque_receiving_account if row else None
		if not account:
			frappe.throw(
				_("Set a Cheque Receiving Account for Company {0} in Cheque Settings").format(frappe.bold(self.company))
			)
		acct = frappe.db.get_value("Account", account, "account_type")
		if acct in ("Receivable", "Payable"):
			frappe.throw(_("Cheque Receiving Account cannot be a {0} control account").format(acct))
		return account

	def _get_party_account(self):
		cache = getattr(frappe.local, "treasury_party_accounts", None) or {}
		key = (self.party_type, self.party, self.company)
		if key not in cache:
			account_type = PARTY_ACCOUNT_TYPE_MAP.get(self.party_type, self.party_type)
			filters = {"account_type": account_type, "is_group": 0, "company": self.company}
			result = frappe.get_all("Account", filters=filters, limit_page_length=1, pluck="name")
			if not result:
				frappe.throw(_("No {0} account found for {1} in {2}").format(account_type, self.party_name or self.party, self.company))
			cache[key] = result[0]
			frappe.local.treasury_party_accounts = cache
		return cache[key]

	def _exchange_rate(self):
		company_ccy = frappe.db.get_value("Company", self.company, "default_currency")
		rate = 1.0
		if self.currency != company_ccy:
			rate = get_exchange_rate(self.currency, company_ccy, self.posting_date)
			if not rate:
				frappe.throw(_("Could not determine exchange rate for {0}").format(self.currency))
		return flt(rate)

	def get_gl_entries(self):
		receiving = self._get_receiving_account()
		rate = self._exchange_rate()

		base = frappe._dict({
			"company": self.company,
			"posting_date": getdate(self.posting_date),
			"voucher_type": "Cheque Receipt",
			"voucher_no": self.name or "",
			"remarks": "Cheque Receipt for cheque {0} dated {1}".format(self.cheque_no or "-", formatdate(self.cheque_date)),
			"cost_center": self.cost_center or get_default_cost_center(self.company),
		})

		rows = []
		items = self.get("table_wgxh") or []
		deductions = self.get("deductions") or []

		# ---- Without Party: flat bank-to-account transfer ----
		if self.without_party:
			company_amount = flt(self.cheque_amount) * rate
			debit = frappe._dict({**base})
			debit.account = receiving
			debit.debit = company_amount
			debit.credit = 0
			debit.debit_in_account_currency = company_amount
			debit.credit_in_account_currency = 0
			debit.account_currency = get_account_currency(receiving)
			debit.against_account = self.account
			rows.append(debit)

			total_ded = sum(flt(d.amount or 0) for d in deductions)
			# Dr each collection-level deduction account
			for ded in deductions:
				d_row = frappe._dict({**base})
				d_row.account = ded.account
				d_row.debit = flt(ded.amount) * rate
				d_row.credit = 0
				d_row.debit_in_account_currency = flt(ded.amount) * rate
				d_row.credit_in_account_currency = 0
				d_row.account_currency = get_account_currency(ded.account)
				d_row.against_account = self.account
				d_row.cost_center = ded.get("cost_center") or base.get("cost_center")
				d_row.user_remark = _("Deduction: {0}").format(ded.description or ded.account)
				rows.append(d_row)

			credit = frappe._dict({**base})
			credit.account = self.account
			credit.debit = 0
			credit.credit = (company_amount + total_ded * rate)
			credit.debit_in_account_currency = 0
			credit.credit_in_account_currency = (company_amount + total_ded * rate)
			credit.account_currency = get_account_currency(self.account)
			credit.against_account = receiving
			rows.append(credit)
			return rows

		# ---- With Party: allocations + row deductions + collection deductions ----
		party_acct = self._get_party_account()

		total_ded = sum(flt(d.amount or 0) for d in deductions)
		company_amount = flt(self.cheque_amount) * rate

		# Dr receiving account: the actual cheque amount (what reaches the bank)
		debit = frappe._dict({**base})
		debit.account = receiving
		debit.debit = company_amount
		debit.credit = 0
		debit.debit_in_account_currency = company_amount
		debit.credit_in_account_currency = 0
		debit.account_currency = get_account_currency(receiving)
		debit.against_account = party_acct
		rows.append(debit)

		# Dr per-row deduction account (each allocation row's own deduction account)
		for item in items:
			ded_amt = flt(item.deduction_amount or 0)
			if not item.apply_deduction or not ded_amt:
				continue
			d_row = frappe._dict({**base})
			d_row.account = item.deduction_account
			d_row.debit = ded_amt * rate
			d_row.credit = 0
			d_row.debit_in_account_currency = ded_amt * rate
			d_row.credit_in_account_currency = 0
			d_row.account_currency = get_account_currency(item.deduction_account)
			d_row.against_account = party_acct
			d_row.user_remark = _("Row deduction on {0} {1}").format(_(item.doc_type), item.voucher_no)
			rows.append(d_row)

		# Dr each collection-level deduction account
		for ded in deductions:
			d_row = frappe._dict({**base})
			d_row.account = ded.account
			d_row.debit = flt(ded.amount) * rate
			d_row.credit = 0
			d_row.debit_in_account_currency = flt(ded.amount) * rate
			d_row.credit_in_account_currency = 0
			d_row.account_currency = get_account_currency(ded.account)
			d_row.against_account = party_acct
			d_row.cost_center = ded.get("cost_center") or base.get("cost_center")
			d_row.user_remark = _("Deduction: {0}").format(ded.description or ded.account)
			rows.append(d_row)

		# Cr party per allocation row: the allocated amount settles the voucher (PE style)
		for item in items:
			alloc = flt(item.allocated_amount)
			credit = frappe._dict({**base})
			credit.account = party_acct
			credit.debit = 0
			credit.credit = alloc * rate
			credit.debit_in_account_currency = 0
			credit.credit_in_account_currency = alloc * rate
			credit.account_currency = get_account_currency(party_acct)
			credit.party_type = self.party_type
			credit.party = self.party
			credit.against_voucher_type = item.doc_type
			credit.against_voucher = item.voucher_no
			credit.against_account = receiving
			credit.user_remark = _("Allocation against {0} {1}").format(_(item.doc_type), item.voucher_no)
			rows.append(credit)

		# Cr surplus (cheque > allocations) as an on-account advance
		surplus = -flt(self.difference_amount) * rate
		if surplus > 0.005:
			adv_account = (
				getattr(self, "_difference_account", None)
				or resolve_difference_account(self.company)
			)
			adv = frappe._dict({**base})
			adv.account = adv_account
			adv.debit = 0
			adv.credit = surplus
			adv.debit_in_account_currency = 0
			adv.credit_in_account_currency = surplus
			adv.account_currency = get_account_currency(adv_account)
			adv.party_type = self.party_type
			adv.party = self.party
			adv.against_account = receiving
			adv.user_remark = _("Cheque surplus booked as advance")
			rows.append(adv)

		return rows

	def on_submit(self):
		make_gl_entries(self.get_gl_entries(), merge_entries=False)

	def on_cancel(self):
		make_reverse_gl_entries(voucher_type="Cheque Receipt", voucher_no=self.name)
		# a cancelled source voids the cheque entirely - never present it as
		# being back in hand.
		frappe.db.set_value("Cheque Receipt", self.name, "cheque_status", "Cancelled", update_modified=False)

	def before_cancel(self):
		self.set("ignore_linked_doctypes", ["GL Entry", "Payment Ledger Entry"])
		if self.get("cheque_status") not in (None, "", "Cheques In Hand"):
			frappe.throw(
				_(
					"Cannot cancel {0}: the cheque has already been deposited (status: {1}). "
					"Cancel the linked Cheque Deposit {2} first."
				).format(frappe.bold(self.name), self.get("cheque_status"), frappe.bold(self.cheque_deposit or "-"))
			)


@frappe.whitelist()
def get_party_documents(party_type):
	"""DocTypes (voucher types) selectable for a given party type."""
	if not frappe.has_permission("Cheque Receipt", "read"):
		frappe.throw(_("Not permitted to read Cheque Receipt"), frappe.PermissionError)
	return list(PARTY_TYPE_VOUCHERS.get(party_type, ()))


@frappe.whitelist()
def get_party_details(party_type, party):
	if not frappe.has_permission("Cheque Receipt", "read"):
		frappe.throw(_("Not permitted to read Cheque Receipt"), frappe.PermissionError)

	if not frappe.db.exists(party_type, party):
		frappe.throw(_("{0} {1} does not exist").format(_(party_type), _(party)))
	return {"party_name": resolve_party_name(party_type, party)}



@frappe.whitelist()
def get_voucher_summary(doc_type, voucher_no):
	"""Return Grand Total & Outstanding for a voucher row."""
	if not frappe.has_permission("Cheque Receipt", "read"):
		frappe.throw(_("Not permitted to read Cheque Receipt"), frappe.PermissionError)

	if not doc_type or not voucher_no or not frappe.db.exists(doc_type, voucher_no):
		return {}
	ref = frappe.db.get_value(
		doc_type,
		voucher_no,
		["grand_total", "outstanding_amount"],
		as_dict=True,
	)
	if not ref:
		return {}
	return {
		"grand_total": flt(ref.get("grand_total")),
		"outstanding": flt(ref.get("outstanding_amount")),
	}


@frappe.whitelist()
def get_preview_ledger(
	company,
	posting_date,
	currency,
	cheque_amount,
	without_party=0,
	party_type=None,
	party=None,
	account=None,
	cheque_no=None,
	cheque_date=None,
	items=None,
	deductions=None,
):
	"""Return exactly how the GL entry will look WITHOUT saving anything."""
	if not frappe.has_permission("Cheque Receipt", "read"):
		frappe.throw(_("Not permitted to read Cheque Receipt"), frappe.PermissionError)

	def _rows(value):
		if not value:
			return []
		if isinstance(value, str):
			value = json.loads(value)
		return value

	fake = frappe.new_doc("Cheque Receipt")
	fake.update(
		{
			"company": company,
			"posting_date": posting_date or nowdate(),
			"currency": currency,
			"cheque_amount": cheque_amount,
			"without_party": cint(without_party),
			"party_type": party_type,
			"party": party,
			"account": account,
			"cheque_no": cheque_no,
			"cheque_date": cheque_date,
		}
	)
	for it in _rows(items):
		fake.append("table_wgxh", it)
	for dd in _rows(deductions):
		fake.append("deductions", dd)

	# soft mode: the preview must render even while unbalanced
	if not fake.cost_center:
		fake.cost_center = get_default_cost_center(fake.company)
	rows = fake.get_gl_entries()

	out = []
	for row in rows:
		out.append(
			{
				"account": row.account,
				"debit": row.get("debit", 0),
				"credit": row.get("credit", 0),
				"party_type": row.get("party_type") or "",
				"party": row.get("party") or "",
				"currency": row.get("account_currency"),
			}
		)
	return out
