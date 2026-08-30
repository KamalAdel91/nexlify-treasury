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
        if (frm.doc.multi_expense) {
            _recalc_total(frm);
        }
    },

    before_save(frm) {
        if (frm.doc.multi_expense) {
            frm.doc.party_type = "";
            frm.doc.party = "";
        }
    },
});

// ── Grid row events ──

frappe.ui.form.on("Treasury Payment Entry Account", {
    account(frm, cdt, cdn) {
        const row = frappe.get_doc(cdt, cdn);
        if (row.account && !row.cost_center && frm.doc.cost_center) {
            frappe.model.set_value(cdt, cdn, "cost_center", frm.doc.cost_center);
        }
    },

    amount(frm) {
        _recalc_total(frm);
    },

    treasury_expense_items_remove(frm) {
        _recalc_total(frm);
    },
});

// ── helpers ──

function _treasury_multi_refresh(frm) {
    // Set account filter for new rows based on payment type.
    if (frm.fields_dict.treasury_expense_items) {
        frm.fields_dict.treasury_expense_items.grid.get_field("account").get_query =
            function () {
                if (!frm.doc.company) return { filters: [] };
                const filters = { company: frm.doc.company, is_group: 0 };
                if (frm.doc.payment_type === "Pay") {
                    return { filters: [
                        ["root_type", "=", "Expense"],
                        ["account_type", "!=", "Tax"],
                        ...Object.entries(filters),
                    ]};
                }
                // Receive → Income accounts
                return { filters: [
                    ["root_type", "=", "Income"],
                    ...Object.entries(filters),
                ]};
            };

        // Allow Tax accounts for Pay via Link search
        const orig_query = frm.fields_dict.treasury_expense_items.grid.get_field("account").get_query;
        frm.fields_dict.treasury_expense_items.grid.get_field("account").get_query = function () {
            if (frm.doc.payment_type !== "Pay") return orig_query.call(this);
            return {
                filters: [
                    ["company", "=", frm.doc.company],
                    ["is_group", "=", 0],
                    ["root_type", "in", ["Expense"]],
                ],
            };
        };
    }
    _apply_multi_visibility(frm);
    _update_labels(frm);
}

function _apply_multi_visibility(frm) {
    const on = frm.doc.multi_expense == 1
        && frm.doc.payment_type !== "Internal Transfer";

    // Toggle multi-expense checkbox visibility
    if (frm.fields_dict.multi_expense) {
        frm.set_df_property(
            "multi_expense", "hidden",
            frm.doc.payment_type === "Internal Transfer" ? 1 : 0
        );
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

    for (const field of party_fields) {
        if (frm.fields_dict[field]) {
            frm.set_df_property(field, "hidden", on ? 1 : 0);
            frm.set_df_property(field, "reqd", on ? 0 : 1);
        }
    }
    for (const field of ref_sections) {
        if (frm.fields_dict[field]) {
            frm.set_df_property(field, "hidden", on ? 1 : 0);
        }
    }
    for (const field of extra_sections) {
        if (frm.fields_dict[field]) {
            frm.set_df_property(field, "hidden", on ? 1 : 0);
        }
    }
    for (const field of treasury_fields) {
        if (frm.fields_dict[field]) {
            frm.set_df_property(field, "hidden", on ? 0 : 1);
        }
    }

    // Make the paid_from / paid_to optional in multi mode
    if (on && frm.doc.payment_type === "Pay" && frm.fields_dict.paid_to) {
        frm.set_df_property("paid_to", "reqd", 0);
    }
    if (on && frm.doc.payment_type === "Receive" && frm.fields_dict.paid_from) {
        frm.set_df_property("paid_from", "reqd", 0);
    }

    // Relax mandatory fields that are auto-populated or irrelevant in multi mode
    const relaxPay = ["paid_to_account_currency", "target_exchange_rate"];
    const relaxReceive = ["paid_from_account_currency", "source_exchange_rate"];
    const relaxAll = ["paid_amount", "received_amount"];  // auto-calculated from the table

    for (const field of relaxPay.concat(relaxAll)) {
        if (frm.fields_dict[field]) {
            frm.set_df_property(field, "reqd", on && frm.doc.payment_type === "Pay" ? 0 : 1);
        }
    }
    for (const field of relaxReceive.concat(relaxAll)) {
        if (frm.fields_dict[field]) {
            frm.set_df_property(field, "reqd", on && frm.doc.payment_type === "Receive" ? 0 : 1);
        }
    }
}

function _update_labels(frm) {
    if (!frm.fields_dict.treasury_expenses_section) return;
    if (frm.doc.payment_type === "Receive") {
        frm.set_df_property("treasury_expenses_section", "label", "Company Revenues");
        if (frm.fields_dict.treasury_expense_items) {
            frm.fields_dict.treasury_expense_items.grid.set_column_label("account", "Revenue Account");
        }
    } else {
        frm.set_df_property("treasury_expenses_section", "label", "Company Expenses");
        if (frm.fields_dict.treasury_expense_items) {
            frm.fields_dict.treasury_expense_items.grid.set_column_label("account", "Expense Account");
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
