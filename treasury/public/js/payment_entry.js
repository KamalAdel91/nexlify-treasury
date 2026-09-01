// Treasury Multi-Expense / Multi-Revenue — Payment Entry client-side.
//
// When `multi_expense` is ticked:
//   - Party & reference sections are hidden.
//   - The expense/revenue child table is shown.
//   - Labels switch: Pay  → "Expenses",  Receive → "Revenues".
//   - Account filter: Pay → Expense + Tax,  Receive → Income.

frappe.ui.form.on("Payment Entry", {
    refresh(frm) {
        _treasury_multi_refresh(frm);
    },

    payment_type(frm) {
        // On Receive/Internal Transfer we never force-reset multi_expense.
        _apply_multi_visibility(frm);
        _update_labels(frm);
    },

    multi_expense(frm) {
        _apply_multi_visibility(frm);
        _update_labels(frm);
        if (_treasury_feature_enabled(frm) && frm.doc.multi_expense) {
            _recalc_total(frm);
        }
    },

    before_save(frm) {
        if (_treasury_feature_enabled(frm) && frm.doc.multi_expense) {
            frm.doc.party_type = "";
            frm.doc.party = "";
        }
    },
});

// ── Grid row events ──

frappe.ui.form.on("Treasury Payment Entry Account", {
    account(frm, cdt, cdn) {
        if (!_treasury_feature_enabled(frm)) return;
        const row = frappe.get_doc(cdt, cdn);
        if (row.account && !row.cost_center && frm.doc.cost_center) {
            frappe.model.set_value(cdt, cdn, "cost_center", frm.doc.cost_center);
        }
    },

    amount(frm) {
        if (!_treasury_feature_enabled(frm)) return;
        _recalc_total(frm);
    },

    treasury_expense_items_remove(frm) {
        if (!_treasury_feature_enabled(frm)) return;
        _recalc_total(frm);
    },
});

// ── helpers ──

function _treasury_multi_refresh(frm) {
    // Load the master switch from Treasury Settings (async), then apply
    // visibility and account filters. Until the value resolves we keep the
    // current behaviour (feature treated as enabled) so nothing breaks.
    frappe.db
        .get_single_value("Treasury Settings", "enable_multi_expense_payment_entry")
        .then((value) => {
            frm._treasury_multi_enabled = cint(value) === 1;
            _setup_account_query(frm);
            _apply_multi_visibility(frm);
            _update_labels(frm);
        });
}

function _treasury_feature_enabled(frm) {
    // Before the async settings read resolves, keep current behaviour.
    return frm._treasury_multi_enabled === undefined ? true : frm._treasury_multi_enabled;
}

function _setup_account_query(frm) {
    // Never attach the account filter query when the feature is disabled.
    if (!_treasury_feature_enabled(frm)) return;
    if (frm.fields_dict.treasury_expense_items) {
        frm.fields_dict.treasury_expense_items.grid.get_field("account").get_query =
            function () {
                if (!frm.doc.company) return { filters: {} };
                const filters = {
                    company: frm.doc.company,
                    is_group: 0,
                };
                if (frm.doc.payment_type === "Pay") {
                    filters.root_type = "Expense";
                    filters.account_type = ["!=", "Tax"];
                } else {
                    // Receive → Income accounts
                    filters.root_type = "Income";
                }
                return { filters };
            };
    }
}

function _native_df(fieldname) {
	// The Payment Entry doctype's own unmodified field definition, read
	// fresh from meta every time - never a value we invented or a runtime
	// copy that our own set_df_property calls may have already mutated.
	// frappe.meta.get_docfield() is the long-established client-side API
	// for this (frappe.get_meta(...).get_field(...) does not exist here).
	return frappe.meta.get_docfield("Payment Entry", fieldname) || {};
}

function _restore_native(frm, fieldname, prop) {
	const native = _native_df(fieldname);
	frm.set_df_property(fieldname, prop, native[prop] || 0);
}

function _apply_multi_visibility(frm) {
	const enabled = _treasury_feature_enabled(frm);
	const on = enabled
		&& frm.doc.multi_expense == 1
		&& frm.doc.payment_type !== "Internal Transfer";

	// Toggle multi-expense checkbox visibility
	if (frm.fields_dict.multi_expense) {
		frm.set_df_property(
			"multi_expense", "hidden",
			(!enabled || frm.doc.payment_type === "Internal Transfer") ? 1 : 0
		);
	}

	// Feature switched OFF: behave exactly like standard ERPNext. Drop any
	// stale multi_expense flag on draft docs so the server-side overrides
	// never engage, and hide the whole treasury UI (party stays required).
	if (!enabled && frm.doc.docstatus === 0 && frm.doc.multi_expense) {
		frm.set_value("multi_expense", 0);
	}

	const party_fields = [
		"party_type", "party", "party_name",
		"party_bank_account", "contact_person", "contact_email",
	];
	const ref_sections = [
		"section_break_14",   // Reference
		"references",
		"section_break_34",   // Writeoff
		"total_allocated_amount", "base_total_allocated_amount",
		"unallocated_amount",
		"difference_amount", "write_off_difference_amount",
	];
	const extra_sections = [
		"deductions",
		"taxes", "total_taxes_and_charges", "base_total_taxes_and_charges",
		"paid_amount_after_tax", "base_paid_amount_after_tax",
		"received_amount_after_tax", "base_received_amount_after_tax",
	];

	const treasury_fields = [
		"treasury_expenses_section",
		"treasury_expense_items",
		"treasury_total_amount",
	];

	// party_type/party/party_name are genuinely required by vanilla
	// Payment Entry; the rest of party_fields are naturally optional.
	// Either way, when the feature is off we never invent a value -
	// we read Payment Entry's own native reqd/hidden back out of meta.
	for (const field of party_fields) {
		if (!frm.fields_dict[field]) continue;
		if (on) {
			frm.set_df_property(field, "hidden", 1);
			frm.set_df_property(field, "reqd", 0);
		} else {
			_restore_native(frm, field, "hidden");
			_restore_native(frm, field, "reqd");
		}
	}
	for (const field of ref_sections.concat(extra_sections)) {
		if (!frm.fields_dict[field]) continue;
		if (on) {
			frm.set_df_property(field, "hidden", 1);
		} else {
			_restore_native(frm, field, "hidden");
		}
	}
	for (const field of treasury_fields) {
		if (frm.fields_dict[field]) {
			frm.set_df_property(field, "hidden", on ? 0 : 1);
		}
	}

	// Make the paid_from / paid_to optional in multi mode; native reqd
	// otherwise (never a hardcoded 1 - read straight from meta).
	if (frm.fields_dict.paid_to) {
		if (on && frm.doc.payment_type === "Pay") {
			frm.set_df_property("paid_to", "reqd", 0);
		} else {
			_restore_native(frm, "paid_to", "reqd");
		}
	}
	if (frm.fields_dict.paid_from) {
		if (on && frm.doc.payment_type === "Receive") {
			frm.set_df_property("paid_from", "reqd", 0);
		} else {
			_restore_native(frm, "paid_from", "reqd");
		}
	}

	// Relax mandatory fields that are auto-populated or irrelevant in multi
	// mode; native reqd otherwise (never a hardcoded 1).
	const relaxPay = ["paid_to_account_currency", "target_exchange_rate"];
	const relaxReceive = ["paid_from_account_currency", "source_exchange_rate"];
	const relaxAll = ["paid_amount", "received_amount"];  // auto-calculated from the table

	for (const field of relaxPay.concat(relaxAll)) {
		if (!frm.fields_dict[field]) continue;
		if (on && frm.doc.payment_type === "Pay") {
			frm.set_df_property(field, "reqd", 0);
		} else {
			_restore_native(frm, field, "reqd");
		}
	}
	for (const field of relaxReceive.concat(relaxAll)) {
		if (!frm.fields_dict[field]) continue;
		if (on && frm.doc.payment_type === "Receive") {
			frm.set_df_property(field, "reqd", 0);
		} else {
			_restore_native(frm, field, "reqd");
		}
	}
}

function _update_labels(frm) {
    if (!frm.fields_dict.treasury_expenses_section) return;
    if (frm.doc.payment_type === "Receive") {
        frm.set_df_property("treasury_expenses_section", "label", "Company Revenues");
        if (frm.fields_dict.treasury_expense_items) {
            frm.fields_dict.treasury_expense_items.grid.update_docfield_property("account", "label", "Revenue Account");
        }
    } else {
        frm.set_df_property("treasury_expenses_section", "label", "Company Expenses");
        if (frm.fields_dict.treasury_expense_items) {
            frm.fields_dict.treasury_expense_items.grid.update_docfield_property("account", "label", "Expense Account");
        }
    }
}

function _recalc_total(frm) {
    let total = 0;
    if (frm.doc.treasury_expense_items) {
        for (const row of frm.doc.treasury_expense_items) {
            total += flt(row.amount);
        }
    }
    frm.set_value({
        paid_amount: total,
        received_amount: total,
        treasury_total_amount: total,
    });
    frm.refresh_field("treasury_total_amount");
    frm.refresh_field("paid_amount");
    frm.refresh_field("received_amount");
}
