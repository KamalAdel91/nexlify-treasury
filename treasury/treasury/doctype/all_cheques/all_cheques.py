# Copyright (c) 2026, Alsadara and contributors
# For license information, please see license.txt

import frappe
from frappe import _


class AllCheques(frappe.model.document.Document):
    def before_insert(self):
        # registry records are maintained exclusively by the lifecycle sync
        if not self.flags.treasury_lifecycle:
            frappe.throw(
                _("All Cheques records are created automatically from Cheque Receipt / Cheque Payment submissions")
            )
