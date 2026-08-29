# Copyright (c) 2026, Alsadara and contributors
# For license information, please see license.txt
"""Shared logic used by both Cheque Receipt and Cheque Payment."""

import json

import frappe
from erpnext import get_default_cost_center
from frappe import _
from frappe.utils import cint, flt


def resolve_party_name(party_type, party):
	_pn = "title" if party_type == "Shareholder" else party_type.lower() + "_name"
	if frappe.db.has_column(party_type, _pn):
		return frappe.db.get_value(party_type, party, _pn)
	return frappe.db.get_value(party_type, party, "name")


def get_party_documents(doctype, party_type, party_type_vouchers):
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(_("Not permitted to read {0}").format(_(doctype)), frappe.PermissionError)
	return list(party_type_vouchers.get(party_type, ()))


def get_party_details(doctype, party_type, party):
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(_("Not permitted to read {0}").format(_(doctype)), frappe.PermissionError)
	if not frappe.db.exists(party_type, party):
		frappe.throw(_("{0} {1} does not exist").format(_(party_type), _(party)))
	return {"party_name": resolve_party_name(party_type, party)}


def get_voucher_summary(doctype, doc_type, voucher_no):
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(_("Not permitted to read {0}").format(_(doctype)), frappe.PermissionError)
	if not doc_type or not voucher_no or not frappe.db.exists(doc_type, voucher_no):
		return {}
	ref = frappe.db.get_value(
		doc_type, voucher_no, ["grand_total", "outstanding_amount"], as_dict=True)
	if not ref:
		return {}
	return {
		"grand_total": flt(ref.get("grand_total")),
		"outstanding": flt(ref.get("outstanding_amount")),
	}


def get_preview_ledger(
	doctype, items_fieldname, company, posting_date, currency, cheque_amount,
	without_party=0, party_type=None, party=None, account=None,
	cheque_no=None, cheque_date=None, items=None, deductions=None,
):
	if not frappe.has_permission(doctype, "read"):
		frappe.throw(_("Not permitted to read {0}").format(_(doctype)), frappe.PermissionError)

	def _rows(value):
		if not value:
			return []
		if isinstance(value, str):
			value = json.loads(value)
		return value

	fake = frappe.new_doc(doctype)
	fake.update({
		"company": company,
		"posting_date": posting_date or frappe.utils.nowdate(),
		"currency": currency,
		"cheque_amount": cheque_amount,
		"without_party": cint(without_party),
		"party_type": party_type,
		"party": party,
		"account": account,
		"cheque_no": cheque_no,
		"cheque_date": cheque_date,
	})
	for it in _rows(items):
		fake.append(items_fieldname, it)
	for dd in _rows(deductions):
		fake.append("deductions", dd)

	if not fake.cost_center:
		fake.cost_center = get_default_cost_center(fake.company)
	rows = fake.get_gl_entries()

	out = []
	for row in rows:
		out.append({
			"account": row.account,
			"debit": row.get("debit", 0),
			"credit": row.get("credit", 0),
			"party_type": row.get("party_type") or "",
			"party": row.get("party") or "",
			"currency": row.get("account_currency"),
		})
	return out


# ── validation helpers ─────────────────────────────────────────


def validate_items(self, items_fieldname, allowed_vouchers, voucher_party_fields):
	if self.without_party:
		self.set(items_fieldname, [])
		return 0

	allowed = allowed_vouchers.get(self.party_type or "", ())
	total_allocated = 0

	for idx, item in enumerate(self.get(items_fieldname) or [], start=1):
		row_no = _("Row #{0}").format(idx)
		if item.doc_type not in allowed:
			frappe.throw(_("{0}: {1} is not valid for {2}").format(
				row_no, frappe.bold(item.doc_type), _(self.party_type)))

		ref = frappe.get_doc(item.doc_type, item.voucher_no)
		if not ref or ref.docstatus != 1:
			frappe.throw(_("{0}: {1} {2} must be an existing submitted document").format(
				row_no, _(item.doc_type), frappe.bold(item.voucher_no)))
		if ref.company != self.company:
			frappe.throw(_("{0}: {1} belongs to another company ({2})").format(
				row_no, frappe.bold(item.voucher_no), frappe.bold(ref.company)))

		field_name = voucher_party_fields.get(item.doc_type, "party")
		if field_name == "party":
			owner_ok = ref.party_type == self.party_type and ref.party == self.party
		elif field_name == "customer":
			owner_ok = ref.customer == self.party and self.party_type == "Customer"
		elif field_name == "supplier":
			owner_ok = ref.supplier == self.party and self.party_type == "Supplier"
		elif field_name == "employee":
			owner_ok = ref.employee == self.party and self.party_type == "Employee"
		else:
			owner_ok = ref.get(field_name) == self.party
		if not owner_ok:
			frappe.throw(_("{0}: {1} {2} does not belong to {3}").format(
				row_no, _(item.doc_type), frappe.bold(item.voucher_no), frappe.bold(self.party)))

		item.grand_total = flt(getattr(ref, "grand_total", 0) or 0)
		item.outstanding = flt(getattr(ref, "outstanding_amount", 0) or 0)
		if flt(item.allocated_amount) <= 0:
			frappe.throw(_("{0}: Allocated Amount must be greater than zero").format(row_no))
		if (frappe.db.has_column(item.doc_type, "outstanding_amount")
				and flt(item.allocated_amount) > item.outstanding + 0.005):
			frappe.throw(_("{0}: Allocated ({1}) exceeds Outstanding ({2}) for {3} {4}").format(
				row_no,
				frappe.utils.fmt_money(item.allocated_amount, currency=self.currency),
				frappe.utils.fmt_money(item.outstanding, currency=self.currency),
				_(item.doc_type), frappe.bold(item.voucher_no)))

		if not item.apply_deduction:
			item.deduction_amount = 0
			item.deduction_account = None
		else:
			if flt(item.deduction_amount or 0) <= 0:
				frappe.throw(_("{0}: Deduction Amount mandatory when Apply Deduction checked").format(row_no))
			if not item.deduction_account:
				frappe.throw(_("{0}: Deduction Account mandatory when Apply Deduction checked").format(row_no))
			wa = frappe.db.get_value("Account", item.deduction_account,
				["company", "is_group", "disabled", "account_type"], as_dict=True)
			if not wa:
				frappe.throw(_("{0}: Deduction Account {1} does not exist").format(
					row_no, frappe.bold(item.deduction_account)))
			if wa.disabled or wa.is_group:
				frappe.throw(_("{0}: {1} must be an active leaf account").format(
					row_no, frappe.bold(item.deduction_account)))
			if wa.company != self.company:
				frappe.throw(_("{0}: {1} belongs to another company ({2})").format(
					row_no, frappe.bold(item.deduction_account), frappe.bold(wa.company)))
		total_allocated += flt(item.allocated_amount)
	return total_allocated


def validate_deductions(self, items_fieldname, doctype_label):
	for idx, ded in enumerate(self.get("deductions") or [], start=1):
		row_no = _("Row #{0}").format(idx)
		acct = frappe.db.get_value("Account", ded.account,
			["company", "is_group", "disabled", "account_type", "report_type"], as_dict=True)
		if not acct:
			frappe.throw(_("{0}: Account {1} does not exist").format(row_no, frappe.bold(ded.account)))
		if acct.disabled or acct.is_group:
			frappe.throw(_("{0}: {1} must be an active leaf account").format(row_no, frappe.bold(ded.account)))
		if acct.company != self.company:
			frappe.throw(_("{0}: {1} belongs to another company ({2})").format(
				row_no, frappe.bold(ded.account), frappe.bold(acct.company)))
		if acct.account_type in ("Receivable", "Payable"):
			frappe.throw(_("{0}: Deductions cannot be booked on a {1} control account ({2})").format(
				row_no, acct.account_type, frappe.bold(ded.account)))
		if acct.report_type == "Profit and Loss" and not (
			ded.get("cost_center") or self.cost_center or get_default_cost_center(self.company)):
			frappe.throw(_("{0}: Cost Center is required for Profit and Loss account {1}. "
				"Set it in the Deduction row, in the {2}, or as the Company default.").format(
				row_no, frappe.bold(ded.account), doctype_label))
		if flt(ded.amount) <= 0:
			frappe.throw(_("{0}: Deduction Amount must be greater than zero").format(row_no))

	if self.without_party:
		self.difference_amount = 0
	else:
		items = self.get(items_fieldname) or []
		row_deductions = sum(flt(it.deduction_amount or 0) for it in items if it.apply_deduction)
		collection_deductions = sum(flt(d.amount or 0) for d in self.get("deductions") or [])
		total_allocated = sum(flt(it.allocated_amount) for it in items)
		cheque_amount = flt(self.cheque_amount)
		self.difference_amount = flt(
			(total_allocated - row_deductions - collection_deductions) - cheque_amount, 2)
		if abs(self.difference_amount) > 0.005:
			frappe.throw(_(
				"Cheque Amount ({0}) must equal Allocated ({1})"
				" minus Row Deductions ({2}) minus Deductions ({3})."
				" Current difference is {4}."
			).format(
				frappe.utils.fmt_money(cheque_amount, currency=self.currency),
				frappe.utils.fmt_money(total_allocated, currency=self.currency),
				frappe.utils.fmt_money(row_deductions, currency=self.currency),
				frappe.utils.fmt_money(collection_deductions, currency=self.currency),
				frappe.utils.fmt_money(self.difference_amount, currency=self.currency),
			))