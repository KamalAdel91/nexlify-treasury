# Copyright (c) 2026, Alsadara and contributors
# For license information, please see license.txt

"""Central validation-rule engine for the Treasury app.

Every rule in Cheque Settings is a Select: None / Warn / Stop.
`enforce()` is the single choke point: it reads the configured level and
either blocks (Stop), notifies (Warn) or skips (None).
"""

from functools import lru_cache

import frappe
from frappe import _

DEFAULT_LEVELS = {
    "enforce_single_currency": "Stop",
    "prevent_partial_deposit": "Stop",
    "prevent_negative_gl": "Stop",
    "reconcile_require_exact_bank": "Stop",
    "enforce_cheque_date_chain": "Stop",
    "block_rcn_without_deposit": "Stop",
    "freeze_linked_deposit": "Stop",
    "validate_duplicate_rcn": "Stop",
    "warn_party_mismatch": "Warn",
    "warn_reference_mismatch": "Warn",
}


@lru_cache(maxsize=1)
def _cached_levels():
    # read tabSingles directly (Singles is not a registered DocType)
    rows = frappe.db.sql(
        """select field, value from `tabSingles` where doctype = 'Cheque Settings'""",
        as_dict=True,
    )
    vals = {r["field"]: (r["value"] or "") for r in rows}
    return {k: (vals.get(k) or DEFAULT_LEVELS[k]) for k in DEFAULT_LEVELS}


def get_level(rule):
    """Return the configured level for a rule ('None'/'Warn'/'Stop')."""
    if rule not in DEFAULT_LEVELS:
        return "None"
    return _cached_levels().get(rule) or DEFAULT_LEVELS[rule]


def enrich(rule, condition_broken, message, allow_warn=True):
    """Apply a rule.

    condition_broken: bool — the bad state is present.
    message: str — user-facing description of the violation.
    allow_warn: if False and level is Warn, keep notifying only.
    Returns True if the action should proceed (Warn/None), False if blocked (Stop).
    """
    level = get_level(rule)
    if level == "None":
        return True
    if not condition_broken:
        return True
    if level == "Stop":
        frappe.throw(_(message), frappe.ValidationError)
    if level == "Warn" and allow_warn:
        frappe.msgprint(_(message + " — Warning only (configured as Warn)."), indicator="orange")
    return True


def clear_cache():
    _cached_levels.cache_clear()
    frappe.db.value_cache = {}

TREASURY_ADMIN_ROLES = ("System Manager", "Accounts Manager")

def require_treasury_role():
    """Gate whitelisted endpoints that touch financial data: only System
    Manager / Accounts Manager may invoke them directly."""
    if not (set(frappe.get_roles()) & set(TREASURY_ADMIN_ROLES)):
        frappe.throw(
            _("Insufficient permissions: this action requires the {0} role.").format(
                " or ".join(TREASURY_ADMIN_ROLES)
            ),
            frappe.PermissionError,
        )
