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
	wrap.html(
		'<div class="text-muted" style="padding:12px 0">' + __("Loading lifecycle") + "…</div>"
	);

	frappe
		.call({
			method: "treasury.treasury.utils.cheque_lifecycle.get_lifecycle",
			args: { all_cheques: frm.doc.name },
		})
		.then((r) => {
			const events = (r.message && r.message.events) || [];
			if (!events.length) {
				wrap.html(
					'<div class="text-muted" style="padding:12px 0">' +
						__("No lifecycle events yet.") +
						"</div>"
				);
				return;
			}
			const meta = r.message;
			let html = "";

			const header_color = frappe.treasury.get_status_color(meta.current_status);
			html +=
				'<div class="lc-header">' +
				'<span class="lc-header-title">' + __("Lifecycle") + "</span>" +
				'<span class="lc-status-pill lc-color-' + header_color + '">' +
				'<span class="lc-status-dot"></span>' +
				frappe.utils.escape_html(meta.current_status || "") +
				"</span>" +
				"</div>";

			html += '<div class="lc-timeline">';
			events.forEach((ev, idx) => {
				const cancelled = ev.cancelled;
				const row_color = cancelled ? "red" : frappe.treasury.get_status_color(ev.status);
				const icon = stage_icon(ev.event);
				const icon_cls = "lc-icon-wrap lc-color-" + row_color;

				html += '<div class="lc-row">';
				html +=
					'<div class="lc-circle-col">' +
					'<span class="' + icon_cls + '">' +
					'<i class="fa ' + icon + '"></i>' +
					"</span>" +
					(idx < events.length - 1 ? '<span class="lc-line"></span>' : "") +
					"</div>";
				html += '<div class="lc-content">';
				html +=
					'<div class="lc-event-row">' +
					'<span class="lc-event-name">' + frappe.utils.escape_html(ev.event) + "</span>" +
					'<span class="lc-event-date">' + frappe.utils.escape_html(ev.date || "") + "</span>" +
					"</div>";
				html +=
					'<div class="lc-doc-row">' +
					'<a href="/app/' + ev.route + "/" + frappe.utils.escape_html(ev.document) + '">' +
					frappe.utils.escape_html(ev.doctype_label) + " " + frappe.utils.escape_html(ev.document) +
					"</a>" +
					(cancelled ? ' <span class="lc-cancelled-tag">' + __("Cancelled") + "</span>" : "") +
					"</div>";
				if (ev.note) {
					html +=
						'<div class="lc-event-note">' +
						frappe.utils.escape_html(ev.note) +
						"</div>";
				}
				html += "</div></div>";
			});
			html += "</div>";

			if (!document.getElementById("lc-styles")) {
				const style = document.createElement("style");
				style.id = "lc-styles";
				style.textContent = LIFECYCLE_CSS;
				document.head.appendChild(style);
			}

			wrap.html(html);
		});
}

function stage_icon(event_label) {
	if (event_label && event_label.startsWith("Received")) return "fa-inbox";
	if (event_label && event_label.startsWith("Deposited")) return "fa-university";
	if (event_label && event_label.startsWith("Reconciled")) return "fa-check";
	if (event_label && event_label.startsWith("Issued")) return "fa-paper-plane";
	return "fa-circle";
}

const LIFECYCLE_CSS = `
.lc-header {
	display: flex; justify-content: space-between; align-items: center;
	padding: 4px 0 16px 0;
}
.lc-header-title {
	font-size: var(--text-lg, 1.125rem);
	font-weight: var(--weight-semibold, 600);
	color: var(--text-color);
}
.lc-status-pill {
	display: inline-flex; align-items: center; gap: 6px;
	padding: 4px 14px 4px 10px; border-radius: 999px;
	font-size: var(--text-sm, 0.8125rem);
	font-weight: var(--weight-medium, 500); line-height: 1.5;
}
.lc-status-dot {
	width: 6px; height: 6px; border-radius: 50%;
	display: inline-block; flex-shrink: 0;
}
.lc-color-green  { background: var(--green-100); color: var(--green-700); }
.lc-color-red    { background: var(--red-100);   color: var(--red-700); }
.lc-color-gray   { background: var(--gray-100);  color: var(--gray-700); }
.lc-color-orange { background: #fdedd3; color: #b45309; }
.lc-color-purple { background: #ede9fe; color: #6d28d9; }
.lc-color-blue   { background: #dbeafe; color: #1d4ed8; }
.lc-color-cyan   { background: #cffafe; color: #0e7490; }
.lc-color-green  .lc-status-dot { background: var(--green-600); }
.lc-color-red    .lc-status-dot { background: var(--red-600); }
.lc-color-gray   .lc-status-dot { background: var(--gray-600); }
.lc-color-orange .lc-status-dot { background: #b45309; }
.lc-color-purple .lc-status-dot { background: #6d28d9; }
.lc-color-blue   .lc-status-dot { background: #1d4ed8; }
.lc-color-cyan   .lc-status-dot { background: #0e7490; }

.lc-timeline { padding: 0 0 0 4px; }
.lc-row { display: flex; align-items: flex-start; }
.lc-circle-col {
	position: relative; width: 40px; flex-shrink: 0;
	display: flex; flex-direction: column; align-items: center;
}
.lc-icon-wrap {
	width: 40px; height: 40px; border-radius: 50%;
	display: flex; align-items: center; justify-content: center;
	font-size: 16px; flex-shrink: 0;
}
.lc-line {
	width: 2px; flex: 1; min-height: 20px;
	background: var(--gray-300); margin: 0 auto;
}
.lc-row:last-child .lc-line { display: none; }

.lc-content { flex: 1; padding: 2px 0 18px 14px; min-width: 0; }
.lc-event-row { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.lc-event-name {
	font-weight: var(--weight-semibold, 600); color: var(--text-color);
	font-size: var(--text-base, 0.875rem);
}
.lc-event-date { color: var(--text-muted); font-size: var(--text-sm, 0.8125rem); white-space: nowrap; }
.lc-doc-row { margin-top: 2px; font-size: var(--text-sm, 0.8125rem); }
.lc-doc-row a { color: var(--text-color); font-weight: var(--weight-medium, 500); }
.lc-cancelled-tag {
	display: inline-block; padding: 1px 8px; border-radius: 999px;
	background: var(--red-100); color: var(--red-700);
	font-size: var(--text-xs, 0.75rem); font-weight: var(--weight-medium, 500);
	margin-left: 6px; vertical-align: middle;
}
.lc-event-note { color: var(--text-muted); font-size: var(--text-sm, 0.8125rem); margin-top: 2px; }
`;
