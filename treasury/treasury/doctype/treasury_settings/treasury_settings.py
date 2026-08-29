# Copyright (c) 2026, Alsadara and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class TreasurySettings(Document):
	def validate(self):
		self.validate_rows()

	def validate_rows(self):
		"""One row per company, with valid default accounts/center."""
		seen = set()
		for idx, row in enumerate(self.get("accounts") or [], start=1):
			row_no = _("Row #{0}").format(idx)

			if not row.company:
				frappe.throw(_("{0}: Company is required").format(row_no))
			if row.company in seen:
				frappe.throw(_("{0}: Duplicate row for Company {1}").format(row_no, frappe.bold(row.company)))
			seen.add(row.company)

			for field, label in (
				("default_cash_account", "Default Cash Account"),
				("default_bank_account", "Default Bank Account"),
			):
				acct = row.get(field)
				if not acct:
					continue
				acct_row = frappe.db.get_value(
					"Account", acct, ["is_group", "disabled", "company"], as_dict=True
				)
				if not acct_row:
					frappe.throw(_("{0}: Account {1} does not exist").format(row_no, frappe.bold(acct)))
				if acct_row.is_group or acct_row.disabled:
					frappe.throw(
						_("{0}: {1} ({2}) must be an active leaf account").format(
							row_no, frappe.bold(acct), _(label)
						)
					)
				if acct_row.company != row.company:
					frappe.throw(
						_("{0}: {1} ({2}) belongs to another company ({3})").format(
							row_no, frappe.bold(acct), _(label), frappe.bold(acct_row.company)
						)
					)

			if row.get("default_cost_center"):
				if not frappe.db.exists("Cost Center", row.default_cost_center):
					frappe.throw(_("{0}: Cost Center {1} does not exist").format(row_no, frappe.bold(row.default_cost_center)))

