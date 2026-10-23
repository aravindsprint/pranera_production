"""Settings page: run every page's main read API on this site and report which
fail (usually "Unknown column ..." on a bench restored from an older backup).

Each check calls the same whitelisted function the page calls, so a pass here
means the page loads. Detail pages are checked with the first record their
list returned. Nothing here writes, and every check runs inside a savepoint
that is rolled back.
"""
import time

import frappe

from pranera_production.api import (
    adopt, chemical, dashboard, inspection, manufacture, pick, process, report, rolls,
)


def _first(rows, key="name"):
    for r in rows or []:
        v = r.get(key) if isinstance(r, dict) else None
        if v:
            return v
    return None


def _run(label, page, fn, *args, **kwargs):
    t0 = time.time()
    sp = "prod_health"
    frappe.db.savepoint(sp)
    try:
        out = fn(*args, **kwargs)
        status, error = "ok", ""
    except Exception as e:
        out, status = None, "error"
        error = str(e) or e.__class__.__name__
        frappe.clear_messages()
    finally:
        frappe.db.rollback(save_point=sp)
    return out, {"page": page, "check": label, "status": status, "error": error,
                 "ms": int((time.time() - t0) * 1000)}


def _skip(page, label, why):
    return {"page": page, "check": label, "status": "skipped", "error": why, "ms": 0}


@frappe.whitelist()
def check_pages():
    results = []

    def run(label, page, fn, *a, **k):
        out, row = _run(label, page, fn, *a, **k)
        results.append(row)
        return out

    # Pick
    run("My pick orders", "My Pick Orders", pick.get_my_pick_orders)
    frappe.form_dict["all"] = 1
    out = run("Pick orders (everyone)", "My Pick Orders", pick.get_my_pick_orders)
    frappe.form_dict.pop("all", None)
    po = _first(out)
    if po:
        run(f"Pick order {po}", "Pick Execution", pick.get_pick_order_detail, po)
    else:
        results.append(_skip("Pick Execution", "Pick order detail", "no open pick order"))
    wos = run("Search work orders", "Create Pick Order", pick.search_work_orders, "")
    wo = _first(wos)
    if wo:
        run(f"Pick context {wo}", "Create Pick Order", pick.get_work_order_pick_context, wo)
    else:
        results.append(_skip("Create Pick Order", "Pick context", "no open work order"))

    # Chemicals
    jcs = run("Job cards with a dye chart", "Chemical Issue", chemical.get_chemical_job_cards)
    jc = _first(jcs)
    if jc:
        run(f"Issue context {jc}", "Chemical Issue", chemical.get_chemical_issue_context, jc)
    else:
        results.append(_skip("Chemical Issue", "Issue context", "no job card with a dye chart"))

    # Job cards
    jcs = run("Job cards (rolls in process)", "Job Cards", process.get_job_cards)
    all_jcs = run("Job cards (all open)", "Job Cards", process.get_job_cards, include_completed=1)
    jc = _first(jcs) or _first(all_jcs)
    if jc:
        run(f"Job card {jc}", "Job Card detail", process.get_job_card_detail, jc)
    else:
        results.append(_skip("Job Card detail", "Job card detail", "no job card"))

    # Manufacture
    mfs = run("Work orders ready for MF", "Manufacture", manufacture.get_mf_work_orders)
    mwo = _first(mfs) or wo
    if mwo:
        run(f"MF context {mwo}", "Manufacture", manufacture.get_mf_context, mwo)
    else:
        results.append(_skip("Manufacture", "MF context", "no work order"))

    # Inspection
    ijcs = run("Inspection job cards", "Inspection", inspection.get_inspection_job_cards, None, 1)
    ijc = _first(ijcs)
    if ijc:
        run(f"Inspection {ijc}", "Inspection", inspection.get_inspection_context, ijc)
    else:
        results.append(_skip("Inspection", "Inspection context", "no INSPECTION job card"))
    run("Mistakes (Fabric)", "Inspection", inspection.get_mistakes, "Fabric")

    # Reports
    rjcs = run("Inspected job cards", "Lot Inspection Report", report.search_inspection_job_cards)
    rjc = _first(rjcs)
    if rjc:
        run(f"Lot report {rjc}", "Lot Inspection Report", report.get_lot_report, rjc)
    else:
        results.append(_skip("Lot Inspection Report", "Lot report", "no inspected job card yet"))
    run("Dashboard", "Dashboard", dashboard.get_dashboard)
    run("Pivot (inspection)", "Pivot Analysis", dashboard.get_pivot_data, "inspection")
    run("Pivot (production)", "Pivot Analysis", dashboard.get_pivot_data, "production")

    # Rolls
    rl = run("Search rolls", "Roll Trace", rolls.search_rolls, None, None, None, None, None, 20)
    roll = _first(rl)
    if roll:
        run(f"Roll trace {roll}", "Roll Trace", rolls.get_roll_trace, roll)
    else:
        results.append(_skip("Roll Trace", "Roll trace", "no roll"))

    # Adopt
    if wo:
        run(f"WIP context {wo}", "Adopt Rolls", adopt.get_wip_context, wo)
    batches = run("Search batches", "Adopt Rolls", adopt.search_batches, "")
    b = _first(batches)
    if b:
        run(f"Stock context {b}", "Adopt Rolls", adopt.get_stock_context, b)

    return {
        "results": results,
        "failed": sum(1 for r in results if r["status"] == "error"),
        "passed": sum(1 for r in results if r["status"] == "ok"),
    }


@frappe.whitelist(methods=["POST"])
def fix_schema():
    """Settings → "Create missing fields now": the same thing migrate does."""
    frappe.only_for("System Manager")
    from pranera_production.install import after_migrate, ensure_roles
    from pranera_production.schema import ensure_fields

    ensure_roles()
    result = ensure_fields(verbose=False)
    try:
        after_migrate()  # seeds Production App Settings
    except Exception as e:
        result["skipped"].append(f"Production App Settings ({e})")
    return result
