frappe.ui.form.on("Cheque Reconciliation", {
	setup(frm) {
		// Cancelling a reconciliation is standalone: the linked Cheque Receipt /
		// Cheque Payment stays submitted — the lifecycle sync restores its
		// previous state ("Cheques In Hand" / "Issued") on cancel.
		frm.ignore_doctypes_on_cancel_all = ["Cheque Receipt", "Cheque Payment"];
	},
});
