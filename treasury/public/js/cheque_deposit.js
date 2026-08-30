// Cheque Deposit form customizations.

frappe.ui.form.on("Cheque Deposit", {
	setup(frm) {
		// Suppress the "Cancel All Documents" dialog when cancelling a deposit.
		//
		// Before cancelling, the client asks the server for submitted docs
		// linked to this one (frappe.desk.form.linked_with.get_submitted_linked_docs)
		// and shows the "Cancel All" dialog when it finds any. The linked Cheque
		// Receipt must NOT be cancelled with the deposit: the deposit's server
		// on_cancel re-opens the receipt to "Cheques In Hand" via the lifecycle
		// sync, and the receipt stays submitted so it can still be cancelled
		// (or re-deposited) on its own.
		//
		// Listing the doctype here makes the pre-flight skip the Cheque Receipt
		// subtree entirely, so the form goes straight to a plain cancel.
		frm.ignore_doctypes_on_cancel_all = ["Cheque Receipt"];
	},
});
