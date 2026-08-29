// Copyright (c) 2026, Alsadara and contributors
// For license information, please see license.txt

frappe.ui.form.on("Cheque Settings", {
	setup(frm) {
		// Receiving account picker: active leaf accounts only, scoped to the
		// company chosen on the same row.
		frm.set_query("write_off_account", "accounts", (doc, cdt, cdn) => {
			const row = frappe.get_doc(cdt, cdn);
			const filters = { is_group: 0, disabled: 0 };
			if (row.company) {
				filters.company = row.company;
			}
			return { filters };
		});

		frm.set_query("cheque_receiving_account", "accounts", (doc, cdt, cdn) => {
			const row = frappe.get_doc(cdt, cdn);
			const filters = { is_group: 0, disabled: 0 };
			if (row.company) {
				filters.company = row.company;
			}
			return { filters };
		});

		frm.set_query("cheque_issuing_account", "accounts", (doc, cdt, cdn) => {
			const row = frappe.get_doc(cdt, cdn);
			const filters = { is_group: 0, disabled: 0 };
			if (row.company) {
				filters.company = row.company;
			}
			return { filters };
		});

		frm.set_query("under_collection_account", "accounts", (doc, cdt, cdn) => {
			const row = frappe.get_doc(cdt, cdn);
			const filters = { is_group: 0, disabled: 0 };
			if (row.company) {
				filters.company = row.company;
			}
			return { filters };
		});
	},
});