// Copyright (c) 2026, Alsadara and contributors
// For license information, please see license.txt

frappe.ui.form.on("Cheque Receipt", {
	setup(frm) {
		// Same candidate party types as Payment Entry (Customer, Supplier,
		// Employee, Shareholder, ...) driven dynamically by ERPNext boot info.
		frm.set_query("party_type", () => ({
			filters: {
				name: ["in", Object.keys(frappe.boot.party_account_types || {})],
			},
		}));

		frm.set_query("company", () => ({ filters: { is_group: 0 } }));

		// Leaf accounts only, scoped to the selected company.
		// ---- Child grid: DocTypes & Vouchers limited to the selected Party ----
		const PARTY_VOUCHER_MAP = {
			Customer: { "Sales Invoice": "customer", "Delivery Note": "customer", "Sales Order": "customer", "Journal Entry": "party" },
			Supplier: { "Purchase Invoice": "supplier", "Purchase Receipt": "supplier", "Journal Entry": "party" },
			Employee: { "Expense Claim": "employee", "Salary Slip": "employee", "Journal Entry": "party" },
			Shareholder: { "Journal Entry": "party" },
		};
		
		frm.set_query("doc_type", "table_wgxh", () => ({
			filters: { name: ["in", Object.keys(PARTY_VOUCHER_MAP[frm.doc.party_type] || {})] },
		}));
		
		frm.set_query("deduction_account", "table_wgxh", () => ({
			filters: {
				is_group: 0,
				disabled: 0,
				company: frm.doc.company,
			},
		}));

		frm.set_query("voucher_no", "table_wgxh", (doc, cdt, cdn) => {
			const row = frappe.get_doc(cdt, cdn);
			const fld = (PARTY_VOUCHER_MAP[frm.doc.party_type] || {})[row.doc_type];
			const filters = { docstatus: 1 };
			if (frm.doc.company) filters.company = frm.doc.company;
			if (!fld || !frm.doc.party) return { filters };
			if (fld === "party") {
				filters.party_type = frm.doc.party_type;
				filters.party = frm.doc.party;
			} else {
				filters[fld] = frm.doc.party;
			}
			return { filters };
		});
		
		frm.set_query("account", () => {
			const filters = { is_group: 0, disabled: 0 };
			if (frm.doc.company) filters.company = frm.doc.company;
			return { filters };
		});

		// Deduction rows: same account rules (leaf, company-scoped)
		frm.set_query("account", "deductions", () => {
			const filters = { is_group: 0, disabled: 0 };
			if (frm.doc.company) filters.company = frm.doc.company;
			return { filters };
		});

		// Cost Center: leaf nodes scoped to the selected company (parent + deduction rows)
		frm.set_query("cost_center", () => {
			const filters = { is_group: 0, disabled: 0 };
			if (frm.doc.company) filters.company = frm.doc.company;
			return { filters };
		});
		frm.set_query("cost_center", "deductions", () => {
			const filters = { is_group: 0, disabled: 0 };
			if (frm.doc.company) filters.company = frm.doc.company;
			return { filters };
		});
	},

	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Preview"), () => frm.events.preview_ledger(frm));
		} else if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("View Ledger"), () => {
				frappe.set_route("query-report", "General Ledger", {
					voucher_no: frm.doc.name,
					company: frm.doc.company,
				});
			});
		}
	},

	preview_ledger(frm) {
		frappe
			.call({
				method:
					"treasury.treasury.doctype.cheque_receipt.cheque_receipt.get_preview_ledger",
				args: {
					company: frm.doc.company,
					posting_date: frm.doc.posting_date,
					currency: frm.doc.currency,
					cheque_amount: frm.doc.cheque_amount,
					without_party: frm.doc.without_party,
					party_type: frm.doc.party_type,
					party: frm.doc.party,
					account: frm.doc.account,
					cheque_no: frm.doc.cheque_no,
					cheque_date: frm.doc.cheque_date,
					items: JSON.stringify(frm.doc.table_wgxh || []),
					deductions: JSON.stringify(frm.doc.deductions || []),
				},
			})
			.then((r) => frm.events.show_preview_dialog(frm, r.message));
	},

	show_preview_dialog(frm, rows) {
		const rows_html = rows
			.map(
				(row) => `<tr>
					<td>${row.account}</td>
					<td class="text-right">${frappe.utils.fmt_money(row.debit || 0)}</td>
					<td class="text-right">${frappe.utils.fmt_money(row.credit || 0)}</td>
					<td>${row.party_type ? row.party_type + ": " + row.party : ""}</td>
				</tr>`
			)
			.join("");

		const dialog = new frappe.ui.Dialog({
			title: __("Expected General Ledger Entry"),
			size: "large",
		});
		dialog.$body.html(`
			<p class="text-muted">
				${__("This entry will be posted on submission. Amount: {0} {1}", [
					frappe.utils.fmt_money(frm.doc.cheque_amount),
					frm.doc.currency,
				])}
			</p>
			<table class="table table-bordered">
				<thead>
					<tr>
						<th>${__("Account")}</th>
						<th class="text-right">${__("Debit")}</th>
						<th class="text-right">${__("Credit")}</th>
						<th>${__("Party")}</th>
					</tr>
				</thead>
				<tbody>${rows_html}</tbody>
			</table>
		`);
		dialog.show();
	},

	without_party(frm) {
		if (frm.doc.without_party) {
			["party", "party_type", "party_name"].forEach((f) => frm.set_value(f, ""));
			frm.clear_table("table_wgxh");
		} else {
			frm.set_value("account", "");
			frm.clear_table("table_wgxh");
		}
	},

	party(frm) {
		if (!frm.doc.party || !frm.doc.party_type) {
			frm.set_value("party_name", "");
			return;
		}

		frappe
			.call({
				method:
					"treasury.treasury.doctype.cheque_receipt.cheque_receipt.get_party_details",
				args: {
					party_type: frm.doc.party_type,
					party: frm.doc.party,
				},
			})
			.then((r) => {
				const details = r.message;
				if (details && details.party_name != null) {
					frm.set_value("party_name", details.party_name);
				}
			});
	},

	party_type(frm) {
		// party options change with its type, so drop stale selections.
		if (frm.doc.party) {
			frm.set_value("party", "");
		}
		frm.set_value("party_name", "");
	},

	update_difference(frm) {
		let alloc = 0;
		(frm.doc.table_wgxh || []).forEach((r) => {
			alloc += flt(r.allocated_amount);
		});
		let row_ded = 0;
		(frm.doc.table_wgxh || []).forEach((r) => {
			if (r.apply_deduction) row_ded += flt(r.deduction_amount);
		});
		let coll_ded = 0;
		(frm.doc.deductions || []).forEach((d) => {
			coll_ded += flt(d.amount);
		});
		const diff = flt((alloc - row_ded - coll_ded) - flt(frm.doc.cheque_amount), 2);
		frm.set_value("difference_amount", diff);
	},

	write_off_difference(frm) {
		const diff = flt(frm.doc.difference_amount);
		if (!diff) {
			frappe.msgprint(__("There is no difference to write off."));
			return;
		}
		if (diff < 0) {
			frappe.msgprint(
				__("Allocated is less than Cheque + Deductions by {0}. Increase allocations or reduce the cheque amount.", [
					frappe.utils.fmt_money(Math.abs(diff)),
				])
			);
			return;
		}
		frappe.db
			.get_value("Cheque Settings Account", { parent: "Cheque Settings", company: frm.doc.company }, "write_off_account")
			.then((r) => {
				const acct = r.message && r.message.write_off_account;
				if (!acct) {
					frappe.msgprint(__("Set a Write Off Account for Company {0} in Cheque Settings.", [frm.doc.company]));
					return;
				}
				frm.add_child("deductions", { account: acct, amount: diff, description: "Write off difference" });
				frm.refresh_field("deductions");
				frm.events.update_difference(frm);
			});
	},

	cheque_amount(frm) {
		frm.events.update_difference(frm);
	},

	company(frm) {
		// pull the Company default Cost Center as soon as a company is chosen
		if (frm.doc.company && !frm.doc.cost_center) {
			frappe.db.get_value("Company", frm.doc.company, "cost_center").then((r) => {
				if (r.message && r.message.cost_center) {
					frm.set_value("cost_center", r.message.cost_center);
				}
			});
		}
	},
});

// Child table row handlers: instant Grand Total & Outstanding on voucher selection
frappe.ui.form.on("Cheque Receipt Items", {
voucher_no(frm, cdt, cdn) {
const row = frappe.get_doc(cdt, cdn);
if (!row.doc_type || !row.voucher_no) {
frappe.model.set_value(cdt, cdn, "grand_total", 0);
frappe.model.set_value(cdt, cdn, "outstanding", 0);
return;
}
frappe.call({
method:
"treasury.treasury.doctype.cheque_receipt.cheque_receipt.get_voucher_summary",
args: { doc_type: row.doc_type, voucher_no: row.voucher_no },
}).then((r) => {
const s = r.message || {};
frappe.model.set_value(
cdt,
cdn,
"grand_total",
s.grand_total != null ? s.grand_total : 0
);
frappe.model.set_value(cdt, cdn, "outstanding", s.outstanding != null ? s.outstanding : 0);
// Payment Entry style: default the allocation to the invoice outstanding
if (!flt(row.allocated_amount) && s.outstanding) {
frappe.model.set_value(cdt, cdn, "allocated_amount", s.outstanding);
}
});
},

apply_deduction(frm, cdt, cdn) {
const row = frappe.get_doc(cdt, cdn);
if (!row.apply_deduction) {
frappe.model.set_value(cdt, cdn, "deduction_amount", 0);
frappe.model.set_value(cdt, cdn, "deduction_account", "");
}
frm.events.update_difference(frm);
},

deduction_amount(frm, cdt, cdn) {
frm.events.update_difference(frm);
},

allocated_amount(frm, cdt, cdn) {
frm.events.update_difference(frm);
},

doc_type(frm, cdt, cdn) {
// reset totals if the user switches document type mid-row
const row = frappe.get_doc(cdt, cdn);
if (!row.doc_type) {
frappe.model.set_value(cdt, cdn, "grand_total", 0);
frappe.model.set_value(cdt, cdn, "outstanding", 0);
}
},
});

// Collection-level deduction rows affect the difference
frappe.ui.form.on("Cheque Receipt Deduction", {
	amount(frm) {
		frm.events.update_difference(frm);
	},
});

// Jump to the cheque's full lifecycle record
frappe.ui.form.on("Cheque Receipt", {
	refresh(frm) {
		if (frm.doc.all_cheques && frm.doc.docstatus == 1) {
			frm.add_custom_button(__("Full History"), () => {
				frappe.set_route("Form", "All Cheques", frm.doc.all_cheques);
			});
		}
	},
});

