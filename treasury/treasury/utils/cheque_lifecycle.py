# Copyright (c) 2026, Alsadara and contributors
# For license information, please see license.txt

"""Cheque lifecycle registry ("All Cheques").

One All Cheques record per cheque (named after its source document). The
record holds the cheque identity, its current status and quick links to every
stage document. The lifecycle timeline itself is NOT stored: it is computed
live from the real documents (receipt -> deposit -> reconciliation -> bank
transaction) so it can never drift out of sync.
"""

import frappe
from frappe import _
from frappe.utils import flt, formatdate

SOURCE_DOCTYPES = ("Cheque Receipt", "Cheque Payment")

# registry field that points back to the source document
SOURCE_LINK_FIELD = {
    "Cheque Receipt": "cheque_receipt",
    "Cheque Payment": "cheque_payment",
}


def _registry_exists(source_docname):
    return bool(frappe.db.exists("All Cheques", source_docname))


def upsert_from_source(doc, method=None):
    """doc_event: on_submit of Cheque Receipt / Cheque Payment."""
    if doc.doctype not in SOURCE_DOCTYPES or doc.docstatus != 1:
        return

    if _registry_exists(doc.name):
        reg = frappe.get_doc("All Cheques", doc.name)
    else:
        reg = frappe.new_doc("All Cheques")
        reg.source_doctype = doc.doctype
        reg.source_doc = doc.name

    reg.direction = "Incoming" if doc.doctype == "Cheque Receipt" else "Outgoing"
    reg.company = doc.company
    reg.cheque_no = doc.cheque_no
    reg.cheque_date = doc.cheque_date
    reg.drawn_bank = getattr(doc, "drawn_bank", None) or getattr(doc, "bank", None) or ""
    reg.amount = flt(doc.cheque_amount)
    reg.currency = doc.currency
    reg.party_type = doc.party_type or ""
    reg.party = doc.party or ""
    reg.current_status = doc.cheque_status
    setattr(reg, SOURCE_LINK_FIELD[doc.doctype], doc.name)
    if doc.doctype == "Cheque Receipt":
        reg.cheque_deposit = doc.cheque_deposit or None

    reg.flags.treasury_lifecycle = True
    reg.flags.ignore_permissions = True
    reg.save()

    # link back from the source document (field has allow_on_submit);
    # update_modified=False so the source doc's timestamp is not bumped
    # (avoids TimestampMismatchError on an immediate cancel/amend)
    frappe.db.set_value(
        doc.doctype, doc.name, "all_cheques", reg.name, update_modified=False
    )



def on_source_cancelled(doc, method=None):
    """doc_event: on_cancel of Cheque Receipt / Cheque Payment.

    A source document can only be cancelled while no further stage happened
    (later stages are guarded), so the registry record is simply removed.
    """
    if _registry_exists(doc.name):
        # drop the back-link first, then delete ignoring any residual links
        frappe.db.set_value(doc.doctype, doc.name, "all_cheques", None)
        frappe.delete_doc(
            "All Cheques", doc.name, ignore_permissions=True, flags={"ignore_links": True}
        )


# --- computed lifecycle state (single source of truth) ---------------------

STATUS_IN_HAND = "Cheques In Hand"
STATUS_UNDER_COLLECTION = "Under Collection"
STATUS_ISSUED = "Issued"
STATUS_RECONCILED = "Reconciled"

INITIAL_STATUS = {
    "Cheque Receipt": STATUS_IN_HAND,
    "Cheque Payment": STATUS_ISSUED,
}


def compute_cheque_state(doctype, name):
    """Derive a cheque's TRUE state from its submitted stage documents.

    Priority: submitted Cheque Reconciliation > submitted Cheque Deposit
    > initial status. Used everywhere a stage is cancelled/deleted so stale
    states can never survive.
    """
    state = {
        "cheque_status": INITIAL_STATUS[doctype],
        "reconciliation_doc": None,
        "bank_transaction": None,
        "clearance_date": None,
    }

    if doctype == "Cheque Receipt":
        state["cheque_deposit"] = None
        deposit = frappe.db.get_value(
            "Cheque Deposit Items",
            {"cheque_receipt": name, "docstatus": 1, "parenttype": "Cheque Deposit"},
            "parent",
            order_by="modified desc",
        )
        if deposit:
            state["cheque_status"] = STATUS_UNDER_COLLECTION
            state["cheque_deposit"] = deposit

    rcn = frappe.db.get_value(
        "Cheque Reconciliation",
        {"cheque": name, "docstatus": 1},
        ["name", "bank_transaction"],
        as_dict=True,
        order_by="modified desc",
    )
    if rcn:
        state["cheque_status"] = STATUS_RECONCILED
        state["reconciliation_doc"] = rcn.name
        state["bank_transaction"] = rcn.bank_transaction
        if rcn.bank_transaction:
            state["clearance_date"] = frappe.db.get_value(
                "Bank Transaction", rcn.bank_transaction, "date"
            )

    return state


def sync_cheque_state(doctype, name):
    """Recompute a cheque's state from reality, apply it, mirror the registry."""
    if doctype not in SOURCE_DOCTYPES or not frappe.db.exists(doctype, name):
        return None

    state = compute_cheque_state(doctype, name)
    current = frappe.db.get_value(doctype, name, fieldname=list(state.keys()), as_dict=True)
    if any(str(current[k] or "") != str(state[k] or "") for k in state):
        frappe.db.set_value(doctype, name, state)

    _mirror_registry(doctype, name, state)
    return state


def _mirror_registry(doctype, name, state):
    """Keep the All Cheques record in step (create it if it is missing —
    e.g. cheques created before the registry existed)."""
    reg_name = frappe.db.get_value("All Cheques", {"source_doctype": doctype, "source_doc": name})
    if not reg_name:
        if not frappe.db.exists(doctype, name) or frappe.db.get_value(doctype, name, "docstatus") != 1:
            return
        src = frappe.get_doc(doctype, name)
        upsert_from_source(src)
        reg_name = frappe.db.get_value("All Cheques", {"source_doctype": doctype, "source_doc": name})
        if not reg_name:
            return
        state = dict(state)
        state["cheque_status"] = frappe.db.get_value(doctype, name, "cheque_status")

    frappe.db.set_value(
        "All Cheques",
        reg_name,
        {
            "current_status": state["cheque_status"],
            "cheque_deposit": state.get("cheque_deposit"),
            "cheque_reconciliation": state["reconciliation_doc"],
            "bank_transaction": state["bank_transaction"],
        },
        update_modified=False,
    )


def sync_stage(doc, method=None):
    """doc_event: on_submit / on_cancel / on_trash of Cheque Deposit and
    Cheque Reconciliation. Recomputes every affected cheque from reality."""
    cheques = []
    if doc.doctype == "Cheque Deposit":
        cheques = [("Cheque Receipt", it.cheque_receipt) for it in (doc.get("cheque_deposit_items") or [])]
    elif doc.doctype == "Cheque Reconciliation":
        if doc.cheque:
            cheques = [(doc.cheque_type or "Cheque Receipt", doc.cheque)]

    for doctype, name in cheques:
        sync_cheque_state(doctype, name)


@frappe.whitelist()
def backfill_lifecycles():
    """Heal every submitted cheque: recompute state + ensure registry exists."""

    from treasury.treasury.utils.validations import require_treasury_role

    require_treasury_role()
    created, synced = 0, 0
    for doctype in SOURCE_DOCTYPES:
        for name in frappe.get_all(doctype, filters={"docstatus": 1}, pluck="name"):
            before = frappe.db.get_value(doctype, name, "cheque_status")
            state = sync_cheque_state(doctype, name)
            synced += 1
            if state and state["cheque_status"] != before:
                created += 1
    frappe.db.commit()
    return {"cheques_synced": synced, "statuses_corrected": created}


# --- timeline below ---



@frappe.whitelist()
def get_lifecycle(all_cheques):
    """Build the cheque's full story live from its real documents."""

    if not frappe.has_permission("All Cheques", "read"):
        frappe.throw(_("Not permitted to read All Cheques"), frappe.PermissionError)
    reg = frappe.get_doc("All Cheques", all_cheques)
    events = []

    src = frappe.get_doc(reg.source_doctype, reg.source_doc)
    cancelled = src.docstatus == 2
    if reg.source_doctype == "Cheque Receipt":
        events.append(
            _event(
                "Received (Cheques In Hand)",
                src.posting_date,
                "Cheque Receipt",
                src.name,
                "cheque-receipt",
                src.cheque_status,
                cancelled,
                "From {0} {1} · cheque {2} drawn on {3}".format(
                    src.party_type or "Party", src.party or "-", src.cheque_no or "-", src.drawn_bank or "-"
                ),
            )
        )
    else:
        events.append(
            _event(
                "Issued",
                src.posting_date,
                "Cheque Payment",
                src.name,
                "cheque-payment",
                src.cheque_status,
                cancelled,
                "To {0} {1} · cheque {2} on {3}".format(
                    src.party_type or "Party", src.party or "-", src.cheque_no or "-",
                    getattr(src, "drawn_bank", None) or getattr(src, "bank", None) or "-"
                ),
            )
        )

    if reg.source_doctype == "Cheque Receipt" and reg.cheque_deposit:
        dep = frappe.get_doc("Cheque Deposit", reg.cheque_deposit)
        events.append(
            _event(
                "Deposited (Under Collection)",
                dep.posting_date,
                "Cheque Deposit",
                dep.name,
                "cheque-deposit",
                "Under Collection",
                dep.docstatus == 2,
                "Banked at {0}".format(dep.bank or "-"),
            )
        )

    if reg.cheque_reconciliation:
        rcn = frappe.get_doc("Cheque Reconciliation", reg.cheque_reconciliation)
        events.append(
            _event(
                "Reconciled",
                rcn.posting_date,
                "Cheque Reconciliation",
                rcn.name,
                "cheque-reconciliation",
                "Reconciled",
                rcn.docstatus == 2,
                "Bank Transaction {0}".format(rcn.bank_transaction or "-"),
            )
        )

    return {"current_status": reg.current_status, "events": events}


def _event(event, date, doctype_label, document, route, status, cancelled, note):
    return {
        "event": event,
        "date": formatdate(date) if date else "",
        "doctype_label": doctype_label,
        "document": document,
        "route": route,
        "status": status,
        "cancelled": bool(cancelled),
        "note": _(note) if note else "",
    }

