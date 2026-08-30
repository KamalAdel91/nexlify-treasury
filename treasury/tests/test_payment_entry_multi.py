"""T5 — Treasury Payment Entry Multi-Expense / Multi-Revenue tests.

Covers:
- Pay  (Debit expense lines  / Credit bank)
- Receive (Credit revenue lines / Debit bank)
- Cancel (GL reversal)
- Regression: normal Payment Entry with party + references still works.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from treasury.tests.utils import (
    TreasuryFixtures,
    safe_cancel_delete,
)


def _make_pe(fx, payment_type, pay_to_receive_from, company, multi=False, lines=None):
    """Create a draft Payment Entry, optionally in multi-expense mode."""
    pe = frappe.get_doc(
        {
            "doctype": "Payment Entry",
            "payment_type": payment_type,
            "company": company,
            "posting_date": frappe.utils.today(),
            "cost_center": fx.cost_center,
            "mode_of_payment": fx.mode_of_payment,
            "paid_from": pay_to_receive_from if payment_type == "Pay" else fx.paid_to,
            "paid_to": pay_to_receive_from if payment_type == "Receive" else fx.paid_from,
            "paid_amount": 0,
            "received_amount": 0,
            "source_exchange_rate": 1,
            "target_exchange_rate": 1,
            "reference_no": "Treasury-Test",
            "reference_date": frappe.utils.today(),
        }
    )
    if multi:
        pe.multi_expense = 1
    pe.paid_amount = 0
    pe.received_amount = 0
    return pe


def _add_multi_line(pe, account, amount, cost_center=None):
    row = pe.append("treasury_expense_items", {})
    row.account = account
    row.amount = amount
    row.cost_center = cost_center or pe.cost_center
    return row


class TestMultiExpensePay(FrappeTestCase):
    """Pay → expense Debt / bank Credit."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls.fx = TreasuryFixtures()
        cls.company = cls.fx.company

    def test_pay_multi_expense_gl(self):
        pe = None
        try:
            pe = _make_pe(self.fx, "Pay", self.fx.paid_from, self.company, multi=True)
            _add_multi_line(pe, self.fx.expense_account, 100)
            _add_multi_line(pe, self.fx.expense_account, 50)
            pe.save()
            pe.submit()

            gl = frappe.get_all(
                "GL Entry",
                filters={"voucher_type": "Payment Entry", "voucher_no": pe.name},
                fields=["account", "debit", "credit"],
            )
            accts = {}
            for g in gl:
                accts.setdefault(g["account"], [0, 0])
                accts[g["account"]][0] += flt(g["debit"])
                accts[g["account"]][1] += flt(g["credit"])

            total_dr = sum(v[0] for v in accts.values())
            total_cr = sum(v[1] for v in accts.values())
            self.assertAlmostEqual(total_dr, total_cr, delta=0.01)
            self.assertAlmostEqual(total_dr, 150, delta=0.01)

            # Expense account is debited
            self.assertAlmostEqual(accts[self.fx.expense_account][0], 150, delta=0.01)
            # Bank account is credited
            self.assertAlmostEqual(accts[self.fx.paid_from][1], 150, delta=0.01)
        finally:
            safe_cancel_delete("Payment Entry", pe.name if pe else None)

    def test_pay_multi_cancel(self):
        pe = None
        try:
            pe = _make_pe(self.fx, "Pay", self.fx.paid_from, self.company, multi=True)
            _add_multi_line(pe, self.fx.expense_account, 200)
            pe.save()
            pe.submit()

            pe.cancel()
            gl = frappe.get_all(
                "GL Entry",
                filters={"voucher_type": "Payment Entry", "voucher_no": pe.name, "is_cancelled": 0},
                fields=["name"],
            )
            self.assertEqual(len(gl), 0, "All GL entries should be cancelled")
        finally:
            safe_cancel_delete("Payment Entry", pe.name if pe else None)


class TestMultiExpenseReceive(FrappeTestCase):
    """Receive → revenue Credit / bank Debit."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls.fx = TreasuryFixtures()
        cls.company = cls.fx.company

    def test_receive_multi_expense_gl(self):
        pe = None
        try:
            pe = _make_pe(self.fx, "Receive", self.fx.paid_to, self.company, multi=True)
            _add_multi_line(pe, self.fx.income_account, 300)
            _add_multi_line(pe, self.fx.income_account, 200)
            pe.save()
            pe.submit()

            gl = frappe.get_all(
                "GL Entry",
                filters={"voucher_type": "Payment Entry", "voucher_no": pe.name},
                fields=["account", "debit", "credit"],
            )
            accts = {}
            for g in gl:
                accts.setdefault(g["account"], [0, 0])
                accts[g["account"]][0] += flt(g["debit"])
                accts[g["account"]][1] += flt(g["credit"])

            total_dr = sum(v[0] for v in accts.values())
            total_cr = sum(v[1] for v in accts.values())
            self.assertAlmostEqual(total_dr, total_cr, delta=0.01)
            self.assertAlmostEqual(total_dr, 500, delta=0.01)

            # Income account is credited
            self.assertAlmostEqual(accts[self.fx.income_account][1], 500, delta=0.01)
            # Bank account is debited
            self.assertAlmostEqual(accts[self.fx.paid_to][0], 500, delta=0.01)
        finally:
            safe_cancel_delete("Payment Entry", pe.name if pe else None)

    def test_receive_multi_cancel(self):
        pe = None
        try:
            pe = _make_pe(self.fx, "Receive", self.fx.paid_to, self.company, multi=True)
            _add_multi_line(pe, self.fx.income_account, 400)
            pe.save()
            pe.submit()

            pe.cancel()
            gl = frappe.get_all(
                "GL Entry",
                filters={"voucher_type": "Payment Entry", "voucher_no": pe.name, "is_cancelled": 0},
                fields=["name"],
            )
            self.assertEqual(len(gl), 0)
        finally:
            safe_cancel_delete("Payment Entry", pe.name if pe else None)


class TestNormalPaymentEntryRegression(FrappeTestCase):
    """Sanity: normal Payment Entry (party + references) is untouched."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls.fx = TreasuryFixtures()
        cls.company = cls.fx.company
        cls.supplier = cls.fx.party("Supplier", "Treasury Test Supplier")

    def test_normal_pay_with_party(self):
        pe = None
        try:
            pe = frappe.get_doc(
                {
                    "doctype": "Payment Entry",
                    "payment_type": "Pay",
                    "company": self.company,
                    "posting_date": frappe.utils.today(),
                    "mode_of_payment": self.fx.mode_of_payment,
                    "paid_from": self.fx.paid_from,
                    "paid_to": self.fx.paid_to,
                    "party_type": "Supplier",
                    "party": self.supplier,
                    "paid_amount": 100,
                    "received_amount": 100,
                    "reference_no": "Treasury-Test",
                    "reference_date": frappe.utils.today(),
                }
            )
            pe.save()
            pe.submit()

            gl = frappe.get_all(
                "GL Entry",
                filters={"voucher_type": "Payment Entry", "voucher_no": pe.name, "is_cancelled": 0},
                fields=["account", "debit", "credit"],
            )
            # Must have GL entries
            self.assertGreater(len(gl), 0)
            accts = {}
            for g in gl:
                accts.setdefault(g["account"], [0, 0])
                accts[g["account"]][0] += flt(g["debit"])
                accts[g["account"]][1] += flt(g["credit"])
            total_dr = sum(v[0] for v in accts.values())
            total_cr = sum(v[1] for v in accts.values())
            self.assertAlmostEqual(total_dr, total_cr, delta=0.01)
            # Pay: Bank (paid_from) credited, Payable (paid_to) debited
            bank_account_gl = accts.get(self.fx.paid_from)
            self.assertTrue(bank_account_gl and bank_account_gl[1] > 0,
                            f"Bank account {self.fx.paid_from} should be credited. GL: {accts}")
        finally:
            safe_cancel_delete("Payment Entry", pe.name if pe else None)



# ── Bonus: mandatory-field relaxation guard (UI regression catcher) ──

class TestMultiExpenseMandatoryRelaxation(FrappeTestCase):
    """T5-Bonus — mandatory fields (paid_to, etc.) must be relaxed in multi mode."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        frappe.set_user("Administrator")
        cls.fx = TreasuryFixtures()
        cls.company = cls.fx.company

    def test_pay_multi_skips_opposite_side_mandatory(self):
        """Without multi_expense, missing paid_to must fail. With it, must pass."""
        # A) Normal mode without multi — missing party + paid_to → ValidationError
        with self.assertRaises(frappe.exceptions.ValidationError):
            pe = frappe.get_doc({
                "doctype": "Payment Entry", "payment_type": "Pay",
                "company": self.company, "posting_date": frappe.utils.today(),
                "cost_center": self.fx.cost_center,
                "mode_of_payment": self.fx.mode_of_payment,
                "paid_from": self.fx.paid_from,
                # intentionally leave paid_to, paid_to_account_currency empty
                "paid_amount": 100, "received_amount": 100,
                "source_exchange_rate": 1, "target_exchange_rate": 1,
                "reference_no": "Test", "reference_date": frappe.utils.today(),
            })
            pe.save()

        # B) Multi mode — same missing fields → must pass via override
        pe = frappe.get_doc({
            "doctype": "Payment Entry", "payment_type": "Pay",
            "company": self.company, "posting_date": frappe.utils.today(),
            "cost_center": self.fx.cost_center,
            "mode_of_payment": self.fx.mode_of_payment,
            "paid_from": self.fx.paid_from,
            # same: no paid_to / paid_to_account_currency / exchange rates
            "paid_amount": 0, "received_amount": 0,
            "reference_no": "Multi-Test", "reference_date": frappe.utils.today(),
            "multi_expense": 1,
        })
        _add_multi_line(pe, self.fx.expense_account, 100)
        from treasury.treasury.overrides.payment_entry import TreasuryPaymentEntry
        self.assertTrue(isinstance(pe, TreasuryPaymentEntry))

        # Server-side parity of the JS reqd=0 relaxation: the meta still says
        # reqd=1 (we must NOT mutate shared meta), but our override must
        # filter these fields out of the missing-mandatory list while empty.
        self.assertEqual(frappe.get_meta("Payment Entry").get_field("paid_to").reqd, 1)
        missing_names = {item[0] for item in pe._get_missing_mandatory_fields()}
        for field in ("paid_to", "paid_to_account_currency", "target_exchange_rate"):
            self.assertNotIn(
                field, missing_names,
                f"{field} must be relaxed (treated as non-required) in multi mode",
            )
        # ...while genuinely-required fields stay enforced (selective relaxation).
        # paid_amount is auto-derived from the table in multi mode, so it is
        # intentionally relaxed together with the opposite-side account.
        self.assertNotIn("paid_amount", missing_names)

        pe.save()  # Must NOT raise MandatoryError
        self.assertEqual(pe.docstatus, 0)
        self.assertEqual(flt(pe.paid_amount), 100)
        self.assertEqual(flt(pe.target_exchange_rate), 1)

    def test_receive_multi_skips_paid_from_mandatory(self):
        """Receive + multi: paid_from side must be relaxed (JS/server parity)."""
        pe = frappe.get_doc({
            "doctype": "Payment Entry", "payment_type": "Receive",
            "company": self.company, "posting_date": frappe.utils.today(),
            "cost_center": self.fx.cost_center,
            "mode_of_payment": self.fx.mode_of_payment,
            "paid_to": self.fx.paid_from,  # bank account (debited)
            # no paid_from / paid_from_account_currency / exchange rates
            "paid_amount": 0, "received_amount": 0,
            "reference_no": "Multi-Recv", "reference_date": frappe.utils.today(),
            "multi_expense": 1,
        })
        _add_multi_line(pe, self.fx.income_account, 250)

        missing_names = {item[0] for item in pe._get_missing_mandatory_fields()}
        for field in ("paid_from", "paid_from_account_currency", "source_exchange_rate"):
            self.assertNotIn(
                field, missing_names,
                f"{field} must be relaxed in multi Receive mode",
            )
        # paid_amount is auto-derived from the table in multi mode, so it is
        # intentionally relaxed together with the opposite-side account.
        self.assertNotIn("paid_amount", missing_names)

        pe.save()  # Must NOT raise MandatoryError
        self.assertEqual(pe.docstatus, 0)
        self.assertEqual(flt(pe.received_amount), 250)
        self.assertEqual(flt(pe.source_exchange_rate), 1)
