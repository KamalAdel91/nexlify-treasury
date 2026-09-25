# Copyright (c) 2026, Alsadara and contributors
# For license information, please see license.txt
"""Open cheque balances for Payment Reconciliation / Cheque Allocation.

A cheque amount that was not allocated to an invoice is booked on the party as
an advance against the cheque itself (Payment Ledger against_voucher = cheque).
"""

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import flt, getdate

CHEQUE_DOCTYPES = ("Cheque Receipt", "Cheque Payment")


def open_amount(against_type, against_no, account, party_type, party, advance=False):
	"""Open amount on the Payment Ledger. Its amounts are already signed per account
	type (receivable: debit - credit, payable: credit - debit), so an invoice is
	open when the sum is positive and a cheque advance when it is negative."""
	total = frappe.db.sql(
		"""select sum(amount_in_account_currency) from `tabPayment Ledger Entry`
		where against_voucher_type=%s and against_voucher_no=%s and account=%s
			and party_type=%s and party=%s and delinked=0""",
		(against_type, against_no, account, party_type, party),
	)[0][0]
	return flt((-1 if advance else 1) * flt(total), 2)


def get_open_cheques(pr):
	"""Cheques of the Payment Reconciliation's party with an open balance, shaped
	like the journal rows ERPNext puts in the Payments table. reference_row carries
	the account the balance sits on (receivable/payable or advance account)."""
	if not (pr.company and pr.party_type and pr.party and pr.receivable_payable_account):
		return []

	accounts = [a for a in (pr.receivable_payable_account, pr.get("default_advance_account")) if a]
	ple = frappe.qb.DocType("Payment Ledger Entry")
	query = (
		frappe.qb.from_(ple)
		.select(
			ple.against_voucher_type.as_("reference_type"),
			ple.against_voucher_no.as_("reference_name"),
			ple.account,
			Sum(ple.amount_in_account_currency).as_("balance"),
		)
		.where(
			(ple.company == pr.company)
			& (ple.party_type == pr.party_type)
			& (ple.party == pr.party)
			& (ple.delinked == 0)
			& ple.account.isin(accounts)
			& ple.against_voucher_type.isin(CHEQUE_DOCTYPES)
		)
		.groupby(ple.against_voucher_type, ple.against_voucher_no, ple.account)
	)
	if pr.get("payment_name"):
		query = query.where(ple.against_voucher_no.like(f"%{pr.payment_name}%"))

	rows = []
	for r in query.run(as_dict=True):
		amount = flt(-flt(r.balance), 2)
		if amount <= 0:
			continue
		cheque = frappe.db.get_value(
			r.reference_type, r.reference_name,
			["docstatus", "posting_date", "cheque_no", "cost_center"], as_dict=True,
		)
		if not cheque or cheque.docstatus != 1:
			continue
		if pr.get("from_payment_date") and getdate(cheque.posting_date) < getdate(pr.from_payment_date):
			continue
		if pr.get("to_payment_date") and getdate(cheque.posting_date) > getdate(pr.to_payment_date):
			continue
		if pr.get("minimum_payment_amount") and amount < flt(pr.minimum_payment_amount):
			continue
		if pr.get("maximum_payment_amount") and amount > flt(pr.maximum_payment_amount):
			continue
		if pr.get("cost_center") and cheque.cost_center != pr.cost_center:
			continue
		rows.append(
			frappe._dict(
				reference_type=r.reference_type,
				reference_name=r.reference_name,
				reference_row=r.account,
				posting_date=cheque.posting_date,
				amount=amount,
				currency=frappe.get_cached_value("Account", r.account, "account_currency"),
				exchange_rate=1,
				book_advance_payments_in_separate_party_account=int(r.account != pr.receivable_payable_account),
				cost_center=cheque.cost_center,
				remarks=_("Cheque No {0}").format(cheque.cheque_no or "-"),
			)
		)
	return rows


ITEMS_FIELD = {"Cheque Receipt": "table_wgxh", "Cheque Payment": "cheque_payment_items"}


def unlink_cheque_from_voucher(cheque_type, cheque_name, ref_type, ref_no):
	"""Undo an allocation made on the cheque itself (its allocation table), the way
	ERPNext undoes a Payment Entry reference: the cheque's ledger rows against the
	voucher move back onto the cheque as an open balance. The allocation row is
	kept for history and flagged "unlinked"; difference_amount grows by the same
	amount, so the cheque shows the new unallocated balance."""
	from erpnext.accounts.utils import update_accounting_ledgers_after_reference_removal

	update_accounting_ledgers_after_reference_removal(ref_type, ref_no, cheque_name)

	cheque = frappe.get_doc(cheque_type, cheque_name)
	moved = 0
	for row in cheque.get(ITEMS_FIELD[cheque_type]) or []:
		if row.doc_type == ref_type and row.voucher_no == ref_no and not row.get("unlinked"):
			row.db_set("unlinked", 1, update_modified=False)
			moved += flt(row.allocated_amount)
	if moved:
		cheque.db_set("difference_amount", flt(cheque.difference_amount) - moved, update_modified=False)

