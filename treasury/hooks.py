app_name = "treasury"
app_title = "Treasury"
app_publisher = "Alsadara"
app_description = "Treasury and cash management operations"
app_email = "admin@alsadara.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
add_to_apps_screen = [
	{
		"name": "treasury",
		"logo": "/assets/treasury/images/app_icon.png",
		"title": "Treasury",
		"route": "/app/treasury",
	}
]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/treasury/css/treasury.css"
app_include_js = "/assets/treasury/js/treasury_bank_recon.js"

# include js, css files in header of web template
# web_include_css = "/assets/treasury/css/treasury.css"
# web_include_js = "/assets/treasury/js/treasury.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "treasury/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
    "Payment Entry": "public/js/payment_entry.js",
    "Cheque Deposit": "public/js/cheque_deposit.js",
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "treasury/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "treasury.utils.jinja_methods",
# 	"filters": "treasury.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "treasury.install.before_install"
after_install = "treasury.treasury.setup.install._ensure_fields"

# Uninstallation
# ------------

# before_uninstall = "treasury.uninstall.before_uninstall"
# after_uninstall = "treasury.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "treasury.utils.before_app_install"
# after_app_install = "treasury.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "treasury.utils.before_app_uninstall"
# after_app_uninstall = "treasury.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "treasury.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "treasury.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"treasury.tasks.all"
# 	],
# 	"daily": [
# 		"treasury.tasks.daily"
# 	],
# 	"hourly": [
# 		"treasury.tasks.hourly"
# 	],
# 	"weekly": [
# 		"treasury.tasks.weekly"
# 	],
# 	"monthly": [
# 		"treasury.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "treasury.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "treasury.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "treasury.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "treasury.task.get_dashboard_data"
# }

# ── Treasury Payment Entry override (multi-expense / multi-revenue) ──
override_doctype_class = {
    "Payment Entry": "treasury.treasury.overrides.payment_entry.TreasuryPaymentEntry",
}

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["treasury.utils.before_request"]
# after_request = ["treasury.utils.after_request"]

# Job Events
# ----------
# before_job = ["treasury.utils.before_job"]
# after_job = ["treasury.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"treasury.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

# Bank Reconciliation (ERPNext) integration
# -----------------------------------------

# Cheques appear as checkboxes in the "Reconcile the Bank Transaction" dialog
bank_reconciliation_doctypes = ["Cheque Receipt", "Cheque Payment"]

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

