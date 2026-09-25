app_name = "treasury"
app_title = "Treasury"
app_publisher = "Alsadara"
app_description = "Treasury and cash management operations"
app_email = "admin@alsadara.com"
app_license = "mit"

# Each item in the list will be shown as an app in the apps page
add_to_apps_screen = [
	{
		"name": "treasury",
		"logo": "/assets/treasury/images/app_icon.png",
		"title": "Treasury",
		"route": "/app/treasury",
	}
]

# include js, css files in header of desk.html
app_include_js = [
    "/assets/treasury/js/treasury_status_colors.js",
    "/assets/treasury/js/treasury_bank_recon.js",
]

# include js in doctype views
doctype_js = {
    "Payment Entry": "public/js/payment_entry.js",
    "Cheque Deposit": "public/js/cheque_deposit.js",
    "Cheque Reconciliation": "public/js/cheque_reconciliation.js",
}

after_install = "treasury.treasury.setup.install._ensure_fields"
before_uninstall = "treasury.treasury.setup.install.before_uninstall"

# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
override_doctype_dashboards = {
    "Sales Invoice": "treasury.treasury.overrides.dashboards.sales_invoice",
    "Purchase Invoice": "treasury.treasury.overrides.dashboards.purchase_invoice",
}

# ── Treasury Payment Entry extension (multi-expense / multi-revenue) ──
# extend_doctype_class (not override_doctype_class): layers on top of
# whichever class actually controls Payment Entry on a given site instead
# of racing other apps (e.g. hrms) for a single "last one wins" slot - see
# the module docstring in overrides/payment_entry.py for the full reasoning.
extend_doctype_class = {
    "Payment Entry": ["treasury.treasury.overrides.payment_entry.TreasuryPaymentEntryMixin"],
    # cheques with an open balance in Payment Reconciliation / Unreconcile Payment
    "Payment Reconciliation": ["treasury.treasury.overrides.payment_reconciliation.TreasuryPaymentReconciliationMixin"],
    "Unreconcile Payment": ["treasury.treasury.overrides.payment_reconciliation.TreasuryUnreconcilePaymentMixin"],
}

# Cheques appear as checkboxes in the "Reconcile the Bank Transaction" dialog
bank_reconciliation_doctypes = ["Cheque Receipt", "Cheque Payment"]

# ERPNext adds every Accounting Dimension to these doctypes
accounting_dimension_doctypes = ["Treasury Payment Entry Account"]

# Propose pending cheques (Under Collection deposits / Issued payments) for a Bank Transaction
get_matching_queries = [
	"treasury.treasury.utils.bank_reconciliation.get_matching_queries_hook"
]

# Post the stage-3 closing GL when Treasury cheques are reconciled, then delegate to ERPNext
override_whitelisted_methods = {
	"erpnext.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool.reconcile_vouchers": "treasury.treasury.utils.bank_reconciliation.reconcile_vouchers_with_cheques"
}

# Revert GL + cheque statuses when a Bank Transaction is cancelled or a cheque is unreconciled
doc_events = {
	"Bank Transaction": {
		"on_cancel": "treasury.treasury.utils.bank_reconciliation.on_bank_transaction_cancel",
		"on_update": "treasury.treasury.utils.bank_reconciliation.on_bank_transaction_update",
	},
	# Cheque lifecycle registry ("All Cheques")
	"Cheque Receipt": {
		"on_submit": "treasury.treasury.utils.cheque_lifecycle.upsert_from_source",
		"on_cancel": "treasury.treasury.utils.cheque_lifecycle.on_source_cancelled",
	},
	"Cheque Payment": {
		"on_submit": "treasury.treasury.utils.cheque_lifecycle.upsert_from_source",
		"on_cancel": "treasury.treasury.utils.cheque_lifecycle.on_source_cancelled",
	},
	"Cheque Deposit": {
		"on_submit": "treasury.treasury.utils.cheque_lifecycle.sync_stage",
		"on_cancel": "treasury.treasury.utils.cheque_lifecycle.sync_stage",
		"on_trash": "treasury.treasury.utils.cheque_lifecycle.sync_stage",
	},
	"Cheque Reconciliation": {
		"on_submit": "treasury.treasury.utils.cheque_lifecycle.sync_stage",
		"on_cancel": "treasury.treasury.utils.cheque_lifecycle.sync_stage",
		"on_trash": "treasury.treasury.utils.cheque_lifecycle.sync_stage",
	},
}

# The lifecycle registry is a mirror: its links to stage documents must never
# block cancelling/deleting those documents.
ignore_links_on_delete = ["All Cheques"]

# Re-assert the DB-level UNIQUE index on Cheque Reconciliation.cheque after each
# migrate. The field is a Dynamic Link, so it cannot declare `unique: 1` in the
# DocType meta (Edit DocType validation rejects that combination); the index is
# maintained at the DB layer and rebuilt here whenever schema sync drops it.
after_migrate = [
	"treasury.patches.add_unique_index_cheque_reconciliation.ensure_unique_index",
	"treasury.treasury.setup.install.after_migrate",
]
