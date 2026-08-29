# Copyright (c) 2026, Alsadara and contributors
# For license information, please see license.txt

import json

import frappe
from erpnext import get_default_cost_center
from erpnext.accounts.general_ledger import make_gl_entries, make_reverse_gl_entries
from erpnext.accounts.utils import get_account_currency
from erpnext.setup.utils import get_exchange_rate
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, formatdate, getdate, nowdate
from treasury.treasury.utils.cheque_shared import resolve_party_name


PARTY_ACCOUNT_TYPE_MAP = {
	"Customer": "Receivable",
	"Supplier": "Payable",
}

VOUCHER_PARTY_FIELDS = {
	"Purchase Invoice": "supplier",
	"Expense Claim": "employee",
	"Journal Entry": "party",
}

PARTY_TYPE_VOUCHERS = {
	"Supplier": ("Purchase Invoice", "Journal Entry"),
	"Employee": ("Expense Claim", "Journal Entry"),
	"Customer": ("Journal Entry",),
	"Shareholder": ("Journal Entry",),
}


VOUCHER_PARTY_ACCOUNT_FIELD = {
	"Purchase Invoice": "credit_to",
	"Expense Claim": "payable_account",
}


def resolve_party_name(party_type, party):
	_party_name = "title" if party_type == "Shareholder" else party_type.lower() + "_name"
	if frappe.db.has_column(party_type, _party_name):
		return frappe.db.get_value(party_type, party, _party_name)
	return frappe.db.get_value(party_type, party, "name")


class ChequePayment(Document):
	def on_trash(self):
		from treasury.treasury.utils.ledger import delete_voucher_ledger_entries
		delete_voucher_ledger_entries(self)
	def validate(self):
		self.validate_booking_mode()
		self.set_missing_values()
		self.validate_basic_data()
		self.validate_items()
		self.validate_deductions()

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

	def set_missing_values(self):
		if self.get("party"):
			self.party_name = resolve_party_name(self.party_type, self.party)
		else:
			self.set("party_name", None)
		if not self.cost_center:
			self.cost_center = get_default_cost_center(self.company)

	def validate_basic_data(self):
		if not self.company:
			frappe.throw(_("Company is required"))
		if flt(self.cheque_amount) <= 0:
			frappe.throw(_("Cheque Amount must be greater than zero"))
		self.currency = self.currency or frappe.db.get_value("Company", self.company, "default_currency")

	def validate_items(self):
		"""Validate allocation rows (shared)."""
		from treasury.treasury.utils.cheque_shared import validate_items
		return validate_items(self, "cheque_payment_items", PARTY_TYPE_VOUCHERS, VOUCHER_PARTY_FIELDS)



	def validate_deductions(self):
		"""Validate deductions (shared)."""
		from treasury.treasury.utils.cheque_shared import validate_deductions
		return validate_deductions(self, "cheque_payment_items", "Cheque Payment")



	def _get_issuing_account(self):
		row = frappe.get_all(
			"Cheque Settings Account",
			filters={"parent": "Cheque Settings", "company": self.company},
			fields=["cheque_issuing_account"],
			limit_page_length=1,
		)
		account = row[0].cheque_issuing_account if row else None
		if not account:
			frappe.throw(
				_("Set a Cheque Issuing Account for Company {0} in Cheque Settings").format(frappe.bold(self.company))
			)
		acct = frappe.db.get_value("Account", account, "account_type")
		if acct in ("Receivable", "Payable"):
			frappe.throw(_("Cheque Issuing Account cannot be a {0} control account").format(acct))
		return account

	def _get_party_account(self, doc_type=None, voucher_no=None):
		"""Resolve the party control account FROM the referenced voucher itself
		(e.g. PI.credit_to, Expense Claim.payable_account, JE party row) so the
		payment lands on the exact account the voucher was booked against."""
		if doc_type and voucher_no:
			cache = getattr(frappe.local, "treasury_party_accounts", None) or {}
			key = (self.party_type, self.party, self.company, doc_type, voucher_no)
			if key not in cache:
				field = VOUCHER_PARTY_ACCOUNT_FIELD.get(doc_type)
				if field:
					account = frappe.db.get_value(doc_type, voucher_no, field)
				elif doc_type == "Journal Entry":
					rows = frappe.get_all(
						"Journal Entry Account",
						filters={"parent": voucher_no, "party_type": self.party_type, "party": self.party},
						pluck="account",
						limit_page_length=1,
					)
					account = rows[0] if rows else None
				else:
					account = None
				if not account:
					frappe.throw(
						_("No party account found on {0} {1} for {2} {3}").format(
							_(doc_type), frappe.bold(voucher_no), _(self.party_type), frappe.bold(self.party)
						)
					)
				cache[key] = account
				frappe.local.treasury_party_accounts = cache
			return cache[key]

		# Fallback: lookup by party account type (used when no specific voucher)
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

	# __ANCHOR_GL__

	def get_gl_entries(self):
		issuing = self._get_issuing_account()
		rate = self._exchange_rate()

		base = frappe._dict({
			"company": self.company,
			"posting_date": getdate(self.posting_date),
			"voucher_type": "Cheque Payment",
			"voucher_no": self.name or "",
			"remarks": "Cheque Payment for cheque {0} dated {1}".format(self.cheque_no or "-", formatdate(self.cheque_date)),
			"cost_center": self.cost_center or get_default_cost_center(self.company),
		})

		rows = []
		items = self.get("cheque_payment_items") or []
		deductions = self.get("deductions") or []

		# ---- Without Party: flat account-to-cheque transfer (mirror of Receipt) ----
		if self.without_party:
			company_amount = flt(self.cheque_amount) * rate

			debit = frappe._dict({**base})
			debit.account = self.account
			debit.debit = company_amount
			debit.credit = 0
			debit.debit_in_account_currency = company_amount
			debit.credit_in_account_currency = 0
			debit.account_currency = get_account_currency(self.account)
			debit.against_account = issuing
			rows.append(debit)

			# Cr each collection-level deduction account
			for ded in deductions:
				c_row = frappe._dict({**base})
				c_row.account = ded.account
				c_row.debit = 0
				c_row.credit = flt(ded.amount) * rate
				c_row.debit_in_account_currency = 0
				c_row.credit_in_account_currency = flt(ded.amount) * rate
				c_row.account_currency = get_account_currency(ded.account)
				c_row.against_account = self.account
				c_row.cost_center = ded.get("cost_center") or base.get("cost_center")
				c_row.user_remark = _("Deduction: {0}").format(ded.description or ded.account)
				rows.append(c_row)

			credit = frappe._dict({**base})
			credit.account = issuing
			credit.debit = 0
			credit.credit = company_amount
			credit.debit_in_account_currency = 0
			credit.credit_in_account_currency = company_amount
			credit.account_currency = get_account_currency(issuing)
			credit.against_account = self.account
			rows.append(credit)
			return rows

		# __ANCHOR_GL_PARTY__
		company_amount = flt(self.cheque_amount) * rate
		first_party_acct = None

		# Dr party per allocation row: the allocated amount settles the voucher (PE style)
		for item in items:
			alloc = flt(item.allocated_amount)
			party_acct = self._get_party_account(item.doc_type, item.voucher_no)
			if not first_party_acct:
				first_party_acct = party_acct
			debit = frappe._dict({**base})
			debit.account = party_acct
			debit.debit = alloc * rate
			debit.credit = 0
			debit.debit_in_account_currency = alloc * rate
			debit.credit_in_account_currency = 0
			debit.account_currency = get_account_currency(party_acct)
			debit.party_type = self.party_type
			debit.party = self.party
			debit.against_voucher_type = item.doc_type
			debit.against_voucher = item.voucher_no
			debit.against_account = issuing
			debit.user_remark = _("Allocation against {0} {1}").format(_(item.doc_type), item.voucher_no)
			rows.append(debit)

		# Cr issuing account: the actual cheque face value
		credit = frappe._dict({**base})
		credit.account = issuing
		credit.debit = 0
		credit.credit = company_amount
		credit.debit_in_account_currency = 0
		credit.credit_in_account_currency = company_amount
		credit.account_currency = get_account_currency(issuing)
		credit.against_account = first_party_acct or issuing
		rows.append(credit)

		# Cr per-row deduction account (each allocation row's own deduction account)
		for item in items:
			ded_amt = flt(item.deduction_amount or 0)
			if not item.apply_deduction or not ded_amt:
				continue
			d_row = frappe._dict({**base})
			d_row.account = item.deduction_account
			d_row.debit = 0
			d_row.credit = ded_amt * rate
			d_row.debit_in_account_currency = 0
			d_row.credit_in_account_currency = ded_amt * rate
			d_row.account_currency = get_account_currency(item.deduction_account)
			d_row.against_account = first_party_acct
			d_row.user_remark = _("Row deduction on {0} {1}").format(_(item.doc_type), item.voucher_no)
			rows.append(d_row)

		# Cr each collection-level deduction account
		for ded in deductions:
			d_row = frappe._dict({**base})
			d_row.account = ded.account
			d_row.debit = 0
			d_row.credit = flt(ded.amount) * rate
			d_row.debit_in_account_currency = 0
			d_row.credit_in_account_currency = flt(ded.amount) * rate
			d_row.account_currency = get_account_currency(ded.account)
			d_row.against_account = first_party_acct
			d_row.cost_center = ded.get("cost_center") or base.get("cost_center")
			d_row.user_remark = _("Deduction: {0}").format(ded.description or ded.account)
			rows.append(d_row)

		return rows

	def on_submit(self):
		make_gl_entries(self.get_gl_entries(), merge_entries=False)

	def on_cancel(self):
		make_reverse_gl_entries(voucher_type="Cheque Payment", voucher_no=self.name)

	def before_cancel(self):
		self.set("ignore_linked_doctypes", ["GL Entry", "Payment Ledger Entry"])
		if self.get("cheque_status") not in (None, "", "Issued"):
			frappe.throw(
				_(
					"Cannot cancel {0}: the cheque has already moved past the Issued stage (status: {1}). "
					"Revert its later stage first."
				).format(frappe.bold(self.name), self.get("cheque_status"))
			)


@frappe.whitelist()
def get_party_documents(party_type):
	"""DocTypes (voucher types) selectable for a given party type."""
	if not frappe.has_permission("Cheque Payment", "read"):
		frappe.throw(_("Not permitted to read Cheque Payment"), frappe.PermissionError)
	return list(PARTY_TYPE_VOUCHERS.get(party_type, ()))


@frappe.whitelist()
def get_party_details(party_type, party):
	if not frappe.has_permission("Cheque Payment", "read"):
		frappe.throw(_("Not permitted to read Cheque Payment"), frappe.PermissionError)

	if not frappe.db.exists(party_type, party):
		frappe.throw(_("{0} {1} does not exist").format(_(party_type), _(party)))
	return {"party_name": resolve_party_name(party_type, party)}


@frappe.whitelist()
def get_voucher_summary(doc_type, voucher_no):
	"""Return Grand Total & Outstanding for a voucher row."""
	if not frappe.has_permission("Cheque Payment", "read"):
		frappe.throw(_("Not permitted to read Cheque Payment"), frappe.PermissionError)

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
	if not frappe.has_permission("Cheque Payment", "read"):
		frappe.throw(_("Not permitted to read Cheque Payment"), frappe.PermissionError)

	def _rows(value):
		if not value:
			return []
		if isinstance(value, str):
			value = json.loads(value)
		return value

	fake = frappe.new_doc("Cheque Payment")
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
		fake.append("cheque_payment_items", it)
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





