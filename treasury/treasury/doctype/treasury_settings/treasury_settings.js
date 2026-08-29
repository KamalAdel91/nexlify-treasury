// Copyright (c) 2026, Alsadara and contributors
// For license information, please see license.txt

frappe.ui.form.on("Treasury Settings", {
	setup(frm) {
		// Default cash/bank pickers: active leaf accounts scoped to the
		// company chosen on the same row.
		for (const field of ["default_cash_account", "default_bank_account"]) {
			frm.set_query(field, "accounts", (doc, cdt, cdn) => {
				const row = frappe.get_doc(cdt, cdn);
				const filters = { is_group: 0, disabled: 0 };
				if (row.company) {
					filters.company = row.company;
				}
				return { filters };
			});
		}

		// Default cost center scoped to the row company too
		frm.set_query("default_cost_center", "accounts", (doc, cdt, cdn) => {
			const row = frappe.get_doc(cdt, cdn);
			const filters = {};
			if (row.company) {
				filters.company = row.company;
			}
			return { filters };
		});
	},
});