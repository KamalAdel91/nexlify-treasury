// Treasury: Extend Bank Transaction's payment_entries "Doctype" filter to
// include Cheque Receipt / Cheque Payment. The list comes from the same
// server hook that feeds the reconcile dialog's checkboxes
// (bank_reconciliation_doctypes). Loaded via app_include_js.

frappe.ui.form.on("Bank Transaction", {
	setup: function (frm) {
		// fetch full list once from server, so no hardcoded duplicates
		if (!frappe.boot) return;
		var fallback = [
			"Payment Entry",
			"Journal Entry",
			"Sales Invoice",
			"Purchase Invoice",
			"Bank Transaction",
			"Cheque Receipt",
			"Cheque Payment",
		];
		frm.set_query("payment_document", "payment_entries", function () {
			return {
				filters: {
					name: ["in", fallback],
				},
			};
		});
	},
});