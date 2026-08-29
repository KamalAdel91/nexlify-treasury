// Copyright (c) 2026, Alsadara and contributors
// For license information, please see license.txt

frappe.ui.form.on("Cheque Deposit", {
	setup(frm) {
		frm.set_query("company", () => ({ filters: { is_group: 0 } }));

		// The bank where the cheques are being deposited: only Bank Accounts of this company
		frm.set_query("bank", () => {
			const filters = { disabled: 0 };
			if (frm.doc.company) filters.company = frm.doc.company;
			return { filters };
		});

		// Only submitted, non-deposited cheques of this company/currency
		frm.set_query("cheque_receipt", "cheque_deposit_items", () => {
			const filters = { docstatus: 1, cheque_status: "Cheques In Hand" };
			if (frm.doc.company) filters.company = frm.doc.company;
			if (frm.doc.currency) filters.currency = frm.doc.currency;
			return { filters };
		});
	},

	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Add Pending Cheques"), () => frm.events.add_pending_cheques(frm));
			frm.add_custom_button(__("Preview"), () => frm.events.preview_ledger(frm));
		} else if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("View Ledger"), () => {
				frappe.set_route("query-report", "General Ledger", {
					voucher_no: frm.doc.name,
					company: frm.doc.company,
				});
			});
		}
		frm.events.update_total(frm);
	},

	add_pending_cheques(frm) {
		if (!frm.doc.company) {
			frappe.msgprint(__("Select a Company first."));
			return;
		}
		frappe.call({
			method: "treasury.treasury.doctype.cheque_deposit.cheque_deposit.get_pending_cheques",
			args: { company: frm.doc.company, currency: frm.doc.currency },
		}).then((r) => {
			const existing = {};
			(frm.doc.cheque_deposit_items || []).forEach((it) => {
				if (it.cheque_receipt) existing[it.cheque_receipt] = true;
			});
			const pending = (r.message || []).filter((c) => !existing[c.name]);
			if (!pending.length) {
				frappe.msgprint(__("No pending cheques found for this company."));
				return;
			}
			pending.forEach((c) => {
				const row = frm.add_child("cheque_deposit_items");
				Object.assign(row, {
					cheque_receipt: c.name,
					party_type: c.party_type,
					party: c.party,
					party_name: c.party_name,
					cheque_no: c.cheque_no,
					drawn_bank: c.drawn_bank,
					amount: c.cheque_amount,
				});
			});
			frm.refresh_field("cheque_deposit_items");
			frm.events.update_total(frm);
		});
	},

	preview_ledger(frm) {
		if (!frm.doc.company) {
			frappe.msgprint(__("Select a Company first."));
			return;
		}
		const items = (frm.doc.cheque_deposit_items || []).map((it) => ({
			cheque_receipt: it.cheque_receipt,
		}));
		frappe.call({
			method: "treasury.treasury.doctype.cheque_deposit.cheque_deposit.get_preview_ledger",
			args: {
				company: frm.doc.company,
				posting_date: frm.doc.posting_date,
				currency: frm.doc.currency,
				bank: frm.doc.bank,
				items,
			},
		}).then((r) => {
			const rows = r.message || [];
			if (!rows.length) {
				frappe.msgprint(__("Nothing to preview — add cheque rows first."));
				return;
			}
			let html =
				'<div style="max-height:300px;overflow:auto"><table class="table table-bordered table-hover">' +
				"<thead><tr><th>Account</th><th class='text-right'>Debit</th><th class='text-right'>Credit</th></tr></thead><tbody>";
			rows.forEach((leg) => {
				html +=
					"<tr><td>" +
					leg.account +
					"</td><td class='text-right'>" +
					(leg.debit ? frappe.utils.fmt_money(leg.debit, 2) : "") +
					"</td><td class='text-right'>" +
					(leg.credit ? frappe.utils.fmt_money(leg.credit, 2) : "") +
					"</td></tr>";
			});
			html += "</tbody></table></div>";
			frappe.msgprint({ title: __("Ledger Preview"), message: html });
		});
	},

	update_total(frm) {
		let total = 0;
		(frm.doc.cheque_deposit_items || []).forEach((it) => {
			total += flt(it.amount);
		});
		frm.set_value("total_amount", flt(total, 2));
	},

	company(frm) {
		if (frm.doc.company && !frm.doc.currency) {
			frappe.db.get_value("Company", frm.doc.company, "default_currency").then((r) => {
				if (r.message && r.message.default_currency) {
					frm.set_value("currency", r.message.default_currency);
				}
			});
		}
	},
});

frappe.ui.form.on("Cheque Deposit Items", {
	cheque_receipt(frm, cdt, cdn) {
		const row = frappe.get_doc(cdt, cdn);
		if (!row.cheque_receipt) {
			frappe.model.set_value(cdt, cdn, "amount", 0);
		}
		frm.events.update_total(frm);
	},

	amount(frm, cdt, cdn) {
		frm.events.update_total(frm);
	},
});