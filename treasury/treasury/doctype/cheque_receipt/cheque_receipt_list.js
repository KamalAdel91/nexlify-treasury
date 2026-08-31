// Copyright (c) 2026, Alsadara and contributors
// For license information, please see license.txt

frappe.listview_settings["Cheque Receipt"] = {
	formatters: {
		cheque_status: function (value) {
			if (!value) return "";
			const color = frappe.treasury.get_status_color(value);
			return (
				'<span class="indicator-pill ' +
				color +
				' filterable" data-filter="cheque_status,=,' +
				value +
				'"><span class="ellipsis">' +
				__(value) +
				"</span></span>"
			);
		},
	},
};
