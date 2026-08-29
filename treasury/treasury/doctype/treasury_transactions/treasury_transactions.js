// Copyright (c) 2026, Alsadara and contributors
// For license information, please see license.txt

frappe.ui.form.on("Treasury Transactions", {
	setup(frm) {
		frm.set_query("account", function () {
			return {
				filters: {
					company: frm.doc.company,
					is_group: 0,
					disabled: 0,
					account_type: ["in", ["Cash", "Bank"]],
				},
			};
		});
		frm.set_query("from_account", function () {
			return { filters: { company: frm.doc.company, is_group: 0, disabled: 0 } };
		});
		frm.set_query("to_account", function () {
			return { filters: { company: frm.doc.company, is_group: 0, disabled: 0 } };
		});
	},

	refresh(frm) {
		frm.trigger("transaction_type");

		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("View Ledger"), () => {
				frappe.set_route("query-report", "General Ledger", {
					voucher_no: frm.doc.name,
					company: frm.doc.company,
				});
			});
		}
	},

	transaction_type(frm) {
		const t = frm.doc.transaction_type;
		const is_transfer = t === "Transfer";

		// Amount is read-only (sum of the Transactions table) except for
		// a Transfer, where it is typed manually.
		frm.set_df_property("amount", "read_only", is_transfer ? 0 : 1);

		// Transactions table not relevant for Transfer
		frm.set_df_property("adjust_section", "hidden", is_transfer ? 1 : 0);
		frm.set_df_property("transactions", "hidden", is_transfer ? 1 : 0);

		// Filter doc_type options in the items grid by direction
		if (t === "Money In") {
			frm.fields_dict.items.grid.update_docfield_property(
				"doc_type", "options", "\nSales Invoice\nJournal Entry");
		} else if (t === "Money Out") {
			frm.fields_dict.items.grid.update_docfield_property(
				"doc_type", "options", "\nPurchase Invoice\nExpense Claim\nJournal Entry");
		}
		frm.trigger("update_totals");
	},

	// ---- live totals ----
	update_totals(frm) {
		const t = frm.doc.transaction_type;
		const alloc = (frm.doc.items || []).reduce(
			(s, r) => s + flt(r.allocated_amount), 0);
		const total = (frm.doc.transactions || []).reduce(
			(s, r) => s + flt(r.amount), 0);
		if (t !== "Transfer") {
			frm.set_value("amount", total);
		}
		frm.set_value("total_allocated", alloc);
		frm.set_value("difference_amount", t === "Transfer" ? 0 : total - alloc);
	},
});

frappe.ui.form.on("Treasury Transaction Item", {
	items_add(frm) { frm.trigger("update_totals"); },
	items_remove(frm) { frm.trigger("update_totals"); },
	allocated_amount(frm) { frm.trigger("update_totals"); },
});

frappe.ui.form.on("Treasury Transaction Line", {
	transactions_add(frm) { frm.trigger("update_totals"); },
	transactions_remove(frm) { frm.trigger("update_totals"); },
	amount(frm, cdt, cdn) { frm.trigger("update_totals"); },
});
