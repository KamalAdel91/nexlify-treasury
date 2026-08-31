// Copyright (c) 2026, Alsadara and contributors
// For license information, please see license.txt

// No get_indicator here on purpose: Frappe auto-adds a separate "Status"
// indicator column whenever get_indicator is defined, which duplicates our
// own real current_status column. Instead we color our own field directly
// via formatters - one real column, one source of truth, no shadow column.
frappe.listview_settings["All Cheques"] = {
	formatters: {
		current_status: function (value) {
			if (!value) return "";
			const color = frappe.treasury.get_status_color(value);
			return (
				'<span class="indicator-pill ' +
				color +
				' filterable" data-filter="current_status,=,' +
				value +
				'"><span class="ellipsis">' +
				__(value) +
				"</span></span>"
			);
		},
		direction: function (value) {
			if (!value) return "";
			const color = frappe.treasury.get_direction_color(value);
			return (
				'<span class="indicator-pill ' +
				color +
				' filterable" data-filter="direction,=,' +
				value +
				'"><span class="ellipsis">' +
				__(value) +
				"</span></span>"
			);
		},
	},
};
