# Copyright (c) 2026, Alsadara and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ChequeSettings(Document):
	def validate(self):
		self.validate_rows()

	def validate_rows(self):
		"""One row per company, each with a valid leaf receiving account."""
		seen = set()
		for idx, row in enumerate(self.get("accounts") or [], start=1):
			row_no = _("Row #{0}").format(idx)

			if not row.company:
				frappe.throw(_("{0}: Company is required").format(row_no))
			if row.company in seen:
				frappe.throw(_("{0}: Duplicate row for Company {1}").format(row_no, frappe.bold(row.company)))
			seen.add(row.company)

			if not row.cheque_receiving_account:
				frappe.throw(_("{0}: Cheque Receiving Account is required").format(row_no))
			if not frappe.db.exists("Account", row.cheque_receiving_account):
				frappe.throw(_("{0}: Account {1} does not exist").format(row_no, frappe.bold(row.cheque_receiving_account)))

			is_group, disabled, account_type, company = frappe.db.get_value(
				"Account", row.cheque_receiving_account, ["is_group", "disabled", "account_type", "company"]
			)
			if is_group or disabled:
				frappe.throw(_("{0}: {1} must be an active leaf account").format(row_no, frappe.bold(row.cheque_receiving_account)))
			if company != row.company:
				frappe.throw(
					_("{0}: {1} belongs to another company ({2})").format(
						row_no, frappe.bold(row.cheque_receiving_account), frappe.bold(company)
					)
				)
			if account_type in ("Receivable", "Payable"):
				frappe.throw(
					_(
						"{0}: {1} accounts require a Party on every entry. "
						"Use a holding account like 'Cheques in Hand' (Current Asset) instead."
					).format(row_no, _(account_type))
				)

			if row.get("write_off_account"):
				wo_is_group, wo_disabled, wo_type, wo_company = frappe.db.get_value(
					"Account", row.write_off_account, ["is_group", "disabled", "account_type", "company"]
				)
				if wo_is_group or wo_disabled:
					frappe.throw(_("{0}: {1} must be an active leaf account").format(row_no, frappe.bold(row.write_off_account)))
				if wo_company != row.company:
					frappe.throw(
						_("{0}: {1} belongs to another company ({2})").format(
							row_no, frappe.bold(row.write_off_account), frappe.bold(wo_company)
						)
					)
				if wo_type in ("Receivable", "Payable"):
					frappe.throw(
						_("{0}: {1} cannot be a {2} control account").format(
							row_no, frappe.bold(row.write_off_account), wo_type
						)
					)

			if not row.under_collection_account:
				frappe.throw(
					_("{0}: Under Collection Account is required for the Cheque Deposit (stage 2) posting").format(row_no)
				)
			uc_is_group, uc_disabled, uc_type, uc_company = frappe.db.get_value(
				"Account", row.under_collection_account, ["is_group", "disabled", "account_type", "company"]
			)
			if uc_is_group or uc_disabled:
				frappe.throw(_("{0}: {1} must be an active leaf account").format(row_no, frappe.bold(row.under_collection_account)))
			if uc_company != row.company:
				frappe.throw(
					_("{0}: {1} belongs to another company ({2})").format(
						row_no, frappe.bold(row.under_collection_account), frappe.bold(uc_company)
					)
				)
			if uc_type in ("Receivable", "Payable"):
				frappe.throw(
					_("{0}: {1} cannot be a {2} control account").format(
						row_no, frappe.bold(row.under_collection_account), uc_type
					)
				)

			if not row.cheque_issuing_account:
				frappe.throw(
					_("{0}: Cheque Issuing Account is required for the Cheque Payment (issued cheque) posting").format(row_no)
				)
			ci_is_group, ci_disabled, ci_type, ci_company = frappe.db.get_value(
				"Account", row.cheque_issuing_account, ["is_group", "disabled", "account_type", "company"]
			)
			if ci_is_group or ci_disabled:
				frappe.throw(_("{0}: {1} must be an active leaf account").format(row_no, frappe.bold(row.cheque_issuing_account)))
			if ci_company != row.company:
				frappe.throw(
					_("{0}: {1} belongs to another company ({2})").format(
						row_no, frappe.bold(row.cheque_issuing_account), frappe.bold(ci_company)
					)
				)
			if ci_type in ("Receivable", "Payable"):
				frappe.throw(
					_("{0}: {1} cannot be a {2} control account").format(
						row_no, frappe.bold(row.cheque_issuing_account), ci_type
					)
				)

