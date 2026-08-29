// Copyright (c) 2026, Alsadara and contributors
// For license information, please see license.txt

frappe.ui.form.on("All Cheques", {
    refresh(frm) {
        render_lifecycle(frm);
    },
});

function render_lifecycle(frm) {
    if (!frm.fields_dict.lifecycle_html) return;
    const wrap = frm.fields_dict.lifecycle_html.$wrapper;
    wrap.html('<div class="text-muted" style="padding:12px 0">Loading lifecycle…</div>');

    frappe
        .call({
            method: "treasury.treasury.utils.cheque_lifecycle.get_lifecycle",
            args: { all_cheques: frm.doc.name },
        })
        .then((r) => {
            const events = (r.message && r.message.events) || [];
            if (!events.length) {
                wrap.html('<div class="text-muted" style="padding:12px 0">No lifecycle events yet.</div>');
                return;
            }
            const meta = r.message;
            let html =
                '<div style="padding:8px 4px">' +
                '<div style="margin-bottom:10px">Current status: <span class="indicator ' +
                status_color(meta.current_status) +
                '">' +
                frappe.utils.escape_html(meta.current_status || "") +
                "</span></div>";

            html += '<div style="border-left:2px solid var(--border-color);margin-left:10px">';
            events.forEach((ev) => {
                const badge = ev.cancelled
                    ? '<span class="indicator red">Cancelled</span>'
                    : '<span class="indicator ' + status_color(ev.status) + '">' + frappe.utils.escape_html(ev.status || "") + "</span>";
                html +=
                    '<div style="position:relative;padding:2px 0 14px 16px">' +
                    '<span style="position:absolute;left:-7px;top:4px;width:12px;height:12px;border-radius:50%;background:var(--blue-500);display:inline-block"></span>' +
                    '<div style="font-weight:600">' + frappe.utils.escape_html(ev.event) + " · " + frappe.utils.escape_html(ev.date || "") + "</div>" +
                    '<div style="margin-top:2px">' +
                    '<a href="/app/' + ev.route + "/" + frappe.utils.escape_html(ev.document) + '">' +
                    frappe.utils.escape_html(ev.doctype_label) + " " + frappe.utils.escape_html(ev.document) + "</a> " +
                    badge +
                    "</div>" +
                    (ev.note ? '<div class="text-muted" style="margin-top:2px">' + frappe.utils.escape_html(ev.note) + "</div>" : "") +
                    "</div>";
            });
            html += "</div></div>";
            wrap.html(html);
        });
}

function status_color(status) {
    switch (status) {
        case "Reconciled":
            return "green";
        case "Under Collection":
        case "Issued":
            return "orange";
        case "Cheques In Hand":
            return "blue";
        default:
            return "gray";
    }
}
