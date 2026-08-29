# Copyright (c) 2026, Alsadara and contributors
# For license information, please see license.txt

"""Bank Reconciliation integration (ERPNext v16).

- `bank_reconciliation_doctypes` hook: registers "Cheque Receipt" and
  "Cheque Payment" as checkboxes in the reconcile dialog.
- `get_matching_queries` hook: proposes pending cheques for a Bank
  Transaction (deposited "Under Collection" receipts via their Cheque
  Deposit's bank, and "Issued" payments via their own bank field).
- `override_whitelisted_methods` replaces `reconcile_vouchers` with a
  wrapper that, for each selected Treasury cheque, creates and submits a
  *Cheque Reconciliation* document. That document posts an independent
  GL journal under its own voucher type/number (Dr Bank / Cr Under
  Collection for deposits, Dr Cheques Issued / Cr Bank for issued
  cheques) with `posting_date` = the Bank Transaction date. The Bank
  Transaction is then manually allocated (pre-set amounts) so ERPNext's
  allocation routine skips these rows.
- `doc_events` on Bank Transaction cancel the linked Cheque
  Reconciliation documents (reverse GL + restore cheque statuses) when
  the transaction is cancelled or a cheque row is removed.
"""

import json

import frappe
from erpnext.accounts.general_ledger import make_reverse_gl_entries
from frappe import _
from frappe.utils import flt, getdate

OUR_DOCTYPES = ("Cheque Receipt", "Cheque Payment")

STATUS_RECONCILED = "Reconciled"
STATUS_UNDER_COLLECTION = "Under Collection"
STATUS_ISSUED = "Issued"


def _constant_column(value):
	from frappe.query_builder.custom import ConstantColumn

	return ConstantColumn(value)


def _ours_selected(document_types):
	if not document_types:
		return True
	# the browser can send a real list, a plain string, or a JSON-encoded
	# list string (e.g. '["cheque_receipt"]') depending on the client
	if isinstance(document_types, str):
		try:
			parsed = json.loads(document_types)
			if isinstance(parsed, list):
				document_types = parsed
			elif isinstance(parsed, str):
				document_types = [parsed]
		except (ValueError, TypeError):
			document_types = [document_types]
	slugs = {frappe.scrub(d) for d in document_types}
	return bool(slugs & {"cheque_receipt", "cheque_payment"})


def get_matching_queries_hook(
	bank_account,
	company,
	transaction,
	document_types=None,
	exact_match=None,
	account_from_to=None,
	from_date=None,
	to_date=None,
	filter_by_reference_date=None,
	from_reference_date=None,
	to_reference_date=None,
	common_filters=None,
):
	"""`get_matching_queries` hook implementation.

	Rows follow the ERPNext candidate contract: rank, doctype, name,
	paid_amount, reference_no, reference_date, party, party_type,
	posting_date, currency.

	Any unexpected exception is fully logged (not just a bare form-dict)
	so the reconcile dialog never silently shows an empty list.
	"""
	queries = []
	try:
		if _ours_selected(document_types):
			if flt(transaction.deposit) > 0:
				q = _get_receipt_matching_query(transaction, exact_match)
				if from_date:
					q = q.where(cr.posting_date >= from_date)
				if to_date:
					q = q.where(cr.posting_date <= to_date)
				queries.append(q)
			if flt(transaction.withdrawal) > 0:
				q = _get_payment_matching_query(transaction, exact_match)
				if from_date:
					q = q.where(cp.posting_date >= from_date)
				if to_date:
					q = q.where(cp.posting_date <= to_date)
				queries.append(q)
	except Exception:
		# write to a dedicated file: the Error Log table silently drops
		# oversized records ("Data too long for column 'method'")
		try:
			with open(frappe.get_site_path("logs", "treasury_br.log"), "a") as f:
				f.write("\n==== %s | BT %s ====\n" % (frappe.utils.now_datetime(), transaction.name))
				f.write(frappe.get_traceback())
				f.write("\nARGS: " + json.dumps(
					{
						"document_types": document_types,
						"exact_match": exact_match,
						"deposit": transaction.deposit,
						"withdrawal": transaction.withdrawal,
						"bank_account": bank_account,
					},
					default=str,
				))
		except Exception:
			pass
		raise
	return queries


def _get_receipt_matching_query(transaction, exact_match):
	"""Deposited cheques ("Under Collection") banked at this Bank Account.

	The bank is resolved through the cheque's submitted Cheque Deposit,
	which stores the receiving Bank Account in its `bank` field.
	"""
	from frappe.query_builder import Case

	cr = frappe.qb.DocType("Cheque Receipt")
	cd = frappe.qb.DocType("Cheque Deposit")

	exact = flt(remaining_unallocated)
	amount_equality = cr.cheque_amount == exact
	party_condition = (cr.party == transaction.party) & cr.party.isnotnull()
	rank = Case().when(amount_equality, 2).when(party_condition, 1).else_(0) + 1

	query = (
		frappe.qb.from_(cr)
		.join(cd)
		.on(cr.cheque_deposit == cd.name)
		.select(
			rank.as_("rank"),
			_constant_column("Cheque Receipt").as_("doctype"),
			cr.name,
			cr.cheque_amount.as_("paid_amount"),
			cr.cheque_no.as_("reference_no"),
			cr.cheque_date.as_("reference_date"),
			cr.party,
			cr.party_type,
			cr.posting_date,
			cr.currency,
		)
		.where(cr.docstatus == 1)
		.where(cr.cheque_status == STATUS_UNDER_COLLECTION)
		.where(cr.company == transaction.company)
		.where(cr.currency == transaction.currency)
		.where(cd.docstatus == 1)
		.where(cd.bank == transaction.bank_account)
		.where(cr.cheque_amount > 0)
	)
	if exact_match:
		query = query.where(amount_equality)
	return query.limit(20)


def _get_payment_matching_query(transaction, exact_match):
	"""Issued cheques ("Issued") drawn on this Bank Account.

	The Cheque Payment carries its own `bank` field (the company's
	chequebook bank) which is matched against the Bank Transaction.
	"""
	from frappe.query_builder import Case

	cp = frappe.qb.DocType("Cheque Payment")

	exact = flt(remaining_unallocated)
	amount_equality = cp.cheque_amount == exact
	party_condition = (cp.party == transaction.party) & cp.party.isnotnull()
	rank = Case().when(amount_equality, 2).when(party_condition, 1).else_(0) + 1

	query = (
		frappe.qb.from_(cp)
		.select(
			rank.as_("rank"),
			_constant_column("Cheque Payment").as_("doctype"),
			cp.name,
			cp.cheque_amount.as_("paid_amount"),
			cp.cheque_no.as_("reference_no"),
			cp.cheque_date.as_("reference_date"),
			cp.party,
			cp.party_type,
			cp.posting_date,
			cp.currency,
		)
		.where(cp.docstatus == 1)
		.where(cp.cheque_status == STATUS_ISSUED)
		.where(cp.company == transaction.company)
		.where(cp.currency == transaction.currency)
		.where(cp.bank == transaction.bank_account)
		.where(cp.cheque_amount > 0)
	)
	if exact_match:
		query = query.where(amount_equality)
	return query.limit(20)


# ------------------------------------------------- reconcile wrapper


@frappe.whitelist()
def reconcile_vouchers_with_cheques(bank_transaction_name, vouchers):
	"""Overrides (via override_whitelisted_methods):
	erpnext...bank_reconciliation_tool.reconcile_vouchers

	For each Treasury cheque in the selection:
	  1. create + submit a Cheque Reconciliation document which posts an
	     independent GL journal (its own voucher type/number) at the
	     Bank Transaction date, and marks the cheque Reconciled;
	  2. add the cheque to the Bank Transaction's payment entries with a
	     pre-set allocated amount so ERPNext's allocation routine skips
	     it (it no longer needs a bank GL entry under the cheque itself).
	Any failure rolls everything back.
	"""
	from erpnext.accounts.doctype.bank_reconciliation_tool import bank_reconciliation_tool as brt

	if isinstance(vouchers, str):
		vouchers = json.loads(vouchers)

	selected = [v for v in (vouchers or []) if v.get("payment_doctype") in OUR_DOCTYPES]
	if not selected:
		# No Treasury cheques selected -> delegate to ERPNext's original
		# reconcile_vouchers. Keep ERPNext's native permissions intact
		# (a normal Accounts User doing a plain bank reconciliation is
		# NOT blocked by treasury's role gate).
		return brt.reconcile_vouchers(bank_transaction_name, json.dumps(vouchers))

	# Treasury cheques are present -> gate the rest on the treasury role.
	from treasury.treasury.utils.validations import require_treasury_role
	require_treasury_role()


	try:
		transaction = frappe.get_doc("Bank Transaction", bank_transaction_name)
		if transaction.docstatus != 1:
			frappe.throw(
				_("Bank Transaction {0} must be submitted to reconcile").format(frappe.bold(transaction.name))
			)

		remaining_unallocated = flt(transaction.unallocated_amount)

		for voucher in selected:
			_create_cheque_reconciliation_doc(transaction, voucher)

		for voucher in selected:
			cheque = frappe.get_doc(voucher["payment_doctype"], voucher["payment_name"])
			existing = [
				pe
				for pe in transaction.payment_entries
				if pe.payment_document == voucher["payment_doctype"] and pe.payment_entry == voucher["payment_name"]
			]
			if existing:
				continue
			# NOTE: the dialog's "amount" is a currency-FORMATTED string
			# (flt() -> 0), so read the authoritative amount from the DB:
			# with a non-zero allocated_amount ERPNext's
			# allocate_payment_entries() skips this row (no bank-GL-under-
			# cheque validation), since the GL lives under the independent
			# Cheque Reconciliation voucher instead.
			cheque_amount = flt(
				frappe.db.get_value(voucher["payment_doctype"], voucher["payment_name"], "cheque_amount")
			)
			from treasury.treasury.utils.validations import enrich

			enrich(
				"prevent_partial_deposit",
				cheque_amount > flt(remaining_unallocated),
				"{0} {1} amount {2} exceeds/unallocated {3} of Bank Transaction {4} — cannot partially allocate a cheque.".format(
					_(voucher["payment_doctype"]),
					frappe.bold(voucher["payment_name"]),
					cheque_amount,
					flt(remaining_unallocated),
					frappe.bold(transaction.name),
				),
			)
			cheque_amount = min(cheque_amount, flt(remaining_unallocated))
			remaining_unallocated -= cheque_amount

			# soft warnings for mismatches (bank transaction vs cheque)
			ref_mismatch = transaction.reference_number and cheque.cheque_no and transaction.reference_number != cheque.cheque_no
			party_mismatch = bool(
				transaction.party and cheque.party and transaction.party != cheque.party
			)
			if ref_mismatch:
				enrich(
					"warn_reference_mismatch",
					True,
					"Bank Transaction reference '{0}' differs from cheque '{1}'.".format(
						frappe.bold(transaction.reference_number), frappe.bold(cheque.cheque_no)
					),
				)
			if party_mismatch:
				enrich(
					"warn_party_mismatch",
					True,
					"Bank Transaction party '{0}' differs from cheque party '{1}'.".format(
						frappe.bold(transaction.party), frappe.bold(cheque.party)
					),
				)

			transaction.append(
				"payment_entries",
				{
					"payment_document": voucher["payment_doctype"],
					"payment_entry": voucher["payment_name"],
					"allocated_amount": cheque_amount,
					"clearance_date": getdate(transaction.date),
				},
			)

		transaction.flags.ignore_permissions = True
		transaction.update_allocated_amount()
		transaction.set_status()
		transaction.save()
		frappe.db.commit()
		return transaction
	except Exception:
		frappe.db.rollback()
		raise


def _create_cheque_reconciliation_doc(transaction, voucher):
	doctype, name = voucher["payment_doctype"], voucher["payment_name"]
	cheque = frappe.get_doc(doctype, name)
	expected = STATUS_UNDER_COLLECTION if doctype == "Cheque Receipt" else STATUS_ISSUED
	_validate_cheque_for_reconciliation(cheque, doctype, name, transaction, expected)

	if doctype == "Cheque Receipt":
		if not cheque.cheque_deposit:
			from treasury.treasury.utils.validations import enrich

			enrich(
				"block_rcn_without_deposit",
				True,
				"Cheque Receipt {0} has no Cheque Deposit — it cannot be reconciled against a bank statement. Deposit it first.".format(
					frappe.bold(name)
				),
			)
		deposit_bank, deposit_docstatus = frappe.db.get_value(
			"Cheque Deposit", cheque.cheque_deposit, ["bank", "docstatus"]
		) or (None, None)
		if deposit_docstatus != 1:
			frappe.throw(_("Cheque Deposit {0} must be submitted").format(frappe.bold(cheque.cheque_deposit)))
		if deposit_bank != transaction.bank_account:
			from treasury.treasury.utils.validations import enrich

			enrich(
				"reconcile_require_exact_bank",
				True,
				"Cheque Receipt {0} was deposited in Bank Account {1}, not {2}".format(
					frappe.bold(name), frappe.bold(deposit_bank), frappe.bold(transaction.bank_account)
				),
			)
	else:
		if cheque.bank != transaction.bank_account:
			from treasury.treasury.utils.validations import enrich

			enrich(
				"reconcile_require_exact_bank",
				True,
				"Cheque Payment {0} was issued on Bank Account {1}, not {2}".format(
					frappe.bold(name), frappe.bold(cheque.bank), frappe.bold(transaction.bank_account)
				),
			)

	existing = frappe.db.get_value(doctype, name, "reconciliation_doc")
	if existing:
		if frappe.db.get_value("Cheque Reconciliation", existing, "bank_transaction") == transaction.name:
			return  # already reconciled for this very transaction
		from treasury.treasury.utils.validations import enrich

		enrich(
			"validate_duplicate_rcn",
			True,
			"{0} {1} is already reconciled ({2})".format(_(doctype), frappe.bold(name), existing),
		)

	doc = frappe.get_doc(
		{
			"doctype": "Cheque Reconciliation",
			"company": transaction.company,
			"posting_date": getdate(transaction.date),
			"currency": cheque.currency,
			"bank_transaction": transaction.name,
			"bank_account": transaction.bank_account,
			"total_amount": flt(cheque.cheque_amount),
			"cheque_type": doctype,
			"cheque": name,
			"cheque_no": cheque.cheque_no,
			"cheque_date": cheque.cheque_date,
			"party_type": cheque.party_type,
			"party": cheque.party,
			"party_name": cheque.party_name,
			"remarks": _("Cleared via Bank Transaction {0}").format(transaction.name),
		}
	)

	# enforce chronological order: deposit date <= transaction date (recon)
	if doctype == "Cheque Receipt" and cheque.cheque_deposit:
		dep_date = frappe.db.get_value("Cheque Deposit", cheque.cheque_deposit, "posting_date")
		if dep_date:
			from treasury.treasury.utils.validations import enrich

			enrich(
				"enforce_cheque_date_chain",
				getdate(transaction.date) < getdate(dep_date),
				"Bank Transaction {0} date {1} is before the cheque's deposit date {2} — cannot clear before it was deposited.".format(
					frappe.bold(transaction.name), getdate(transaction.date), getdate(dep_date)
				),
			)

	doc.flags.ignore_permissions = True
	try:
		doc.insert()
		doc.submit()
	except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
		frappe.db.rollback()
		frappe.throw(
			_(
				"Cheque {0} is already reconciled — only one Cheque Reconciliation is allowed per cheque (unique constraint)."
			).format(frappe.bold(name))
		)
	return doc


def _validate_cheque_for_reconciliation(cheque, doctype, name, transaction, expected_status):
	if cheque.docstatus != 1:
		frappe.throw(_("{0} {1} must be submitted").format(_(doctype), frappe.bold(name)))
	if cheque.company != transaction.company:
		frappe.throw(_("{0} {1} belongs to a different company").format(_(doctype), frappe.bold(name)))
	if cheque.cheque_status == STATUS_RECONCILED:
		existing = frappe.db.get_value(doctype, name, "bank_transaction")
		if existing and existing != transaction.name:
			frappe.throw(
				_("{0} {1} is already reconciled with Bank Transaction {2}").format(
					_(doctype), frappe.bold(name), frappe.bold(existing)
				)
			)
	elif cheque.cheque_status != expected_status:
		frappe.throw(
			_("{0} {1} must be in status {2} to be reconciled (current: {3})").format(
				_(doctype), frappe.bold(name), frappe.bold(expected_status), frappe.bold(cheque.cheque_status)
			)
		)


# ------------------------------------------------- revert hooks


def _revert_cheque(doctype, name):
	"""Cancel the linked Cheque Reconciliation (reverse GL + restore the
	cheque). Falls back to a direct reverse if no document exists."""
	if not frappe.db.exists(doctype, name):
		return

	reconciliation_doc = frappe.db.get_value(doctype, name, "reconciliation_doc")
	if reconciliation_doc and frappe.db.exists("Cheque Reconciliation", reconciliation_doc):
		rcn = frappe.get_doc("Cheque Reconciliation", reconciliation_doc)
		if rcn.docstatus == 1:
			rcn.cancel()
			return

	make_reverse_gl_entries(voucher_type=doctype, voucher_no=name)
	# legacy fallback: no reconciliation document — recompute from reality
	from treasury.treasury.utils.cheque_lifecycle import sync_cheque_state

	sync_cheque_state(doctype, name)


def on_bank_transaction_cancel(doc, method=None):
	"""Revert GL + cheque statuses when a Bank Transaction is cancelled."""
	for pe in doc.get("payment_entries") or []:
		if pe.payment_document in OUR_DOCTYPES:
			_revert_cheque(pe.payment_document, pe.payment_entry)


def on_bank_transaction_update(doc, method=None):
	"""Detect cheques removed from a saved Bank Transaction (e.g. the
	'Unreconcile Transaction' button) and revert them.

	At on_update the payment_entries child rows are already in their
	post-removal state (removed rows are gone from both the in-memory doc and
	the DB), so a diff of current-vs-previous rows can never see a removal.
	Instead we use the source of truth: any submitted Cheque Reconciliation
	still pointing at this Bank Transaction whose cheque is no longer a
	payment entry must be cancelled (reverse GL + restore the cheque state).
	"""
	if doc.docstatus != 1:
		return
	current = {
		(pe.payment_document, pe.payment_entry)
		for pe in (doc.get("payment_entries") or [])
		if pe.payment_document in OUR_DOCTYPES
	}
	linked = frappe.get_all(
		"Cheque Reconciliation",
		filters={
			"bank_transaction": doc.name,
			"docstatus": 1,
			"cheque_type": ("in", list(OUR_DOCTYPES)),
		},
		fields=["cheque_type", "cheque"],
	)
	for rcn in linked:
		if (rcn.cheque_type, rcn.cheque) not in current:
			_revert_cheque(rcn.cheque_type, rcn.cheque)
