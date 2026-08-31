// Copyright (c) 2026, Alsadara and contributors
// For license information, please see license.txt

frappe.provide("frappe.treasury");

// Only long-established, universally-supported indicator color names are
// used here (green, cyan, blue, orange, yellow, gray, red, purple, ...).
// The newer Espresso theme names (amber, violet) and the frappe.ui.badge
// component are NOT used - they depend on a very recent Frappe frontend
// build that this site's currently-loaded bundle does not yet include.
frappe.treasury.STATUS_COLORS = {
	"Cheques In Hand": "orange",
	"Issued": "orange",
	"Under Collection": "purple",
	Reconciled: "blue",
	Cancelled: "red",
};

frappe.treasury.DIRECTION_COLORS = {
	Incoming: "green",
	Outgoing: "cyan",
};

frappe.treasury.get_status_color = function (status) {
	return frappe.treasury.STATUS_COLORS[status] || "gray";
};

frappe.treasury.get_direction_color = function (direction) {
	return frappe.treasury.DIRECTION_COLORS[direction] || "gray";
};
