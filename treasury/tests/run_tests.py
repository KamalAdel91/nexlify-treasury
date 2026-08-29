"""Direct runner for treasury integration tests.

Usage from within the bench directory:
    bench --site SITE_NAME execute treasury.tests.run_tests.run_all

Or from shell:
    cd sites && ../env/bin/python -c "from treasury.tests.run_tests import run_all; run_all()"

WHY THIS EXISTS (and not 'bench run-tests')
============================================
'bench run-tests --module treasury.tests.test_cheque_lifecycle' fails on any site
that has pre-existing Price List records (like "Standard Buying").

Root cause: erpnext/tests/utils.py contains BootStrapTestData() which runs at
MODULE IMPORT TIME. Its make_price_list() calls make_records() with
ignore_if_duplicate=False. On a site with live data, the exists() check uses
translated names and compound filters that don't match the existing Price List,
so insert() fails with DuplicateEntryError.

This is a systemic limitation — the ERPNext test bootstrapper assumes a
clean test-only site. Until the upstream code is fixed (or a dedicated test
site is created), this runner bypasses the bootstrap entirely by:
  1. Initializing frappe BEFORE importing any test module
  2. Setting frappe.flags.in_test = True (triggers test DB rollback per test)
  3. Using unittest directly without touching ERPNext's BootStrapTestData
"""

import sys
import unittest
import os

import frappe

# ---- site defaults (override with environment variables) ----
SITE = os.environ.get("TREASURY_TEST_SITE", "alsadara.new")
_SITES_PATH_OPTIONS = [
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "sites"),
    os.path.join(os.path.dirname(__file__), "..", "..", "sites"),
    os.environ.get("FRAPPE_SITES_PATH", ""),
]
SITES_PATH = os.environ.get("FRAPPE_SITES_PATH") or next(
    (p for p in _SITES_PATH_OPTIONS if p and os.path.isdir(p)),
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "sites"),
)


def run_all():
    """Discover and run all treasury test modules."""
    frappe.init(site=SITE, sites_path=SITES_PATH)
    frappe.connect()
    frappe.set_user("Administrator")
    frappe.flags.in_test = True

    from treasury.tests import test_cheque_lifecycle, test_cheque_multicurrency  # noqa: E402

    suite = unittest.TestSuite()
    for module in (test_cheque_lifecycle, test_cheque_multicurrency):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))

    result = unittest.TextTestRunner(verbosity=2).run(suite)

    failures = [t.id() for t, _ in result.failures + result.errors]
    print("\n==== TEST SUMMARY ====")
    print(f"run: {result.testsRun} | failures: {len(result.failures)} | errors: {len(result.errors)}")
    for f in failures:
        print("  FAILED:", f)
    print("RESULT:", "ALL PASSED" if result.wasSuccessful() else "FAILED")

    frappe.destroy()
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    run_all()