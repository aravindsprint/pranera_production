"""Job Card screens: list, detail (rolls in process, materials issued),
start and complete an operation.

Completing (submitting) an intermediate Job Card of a multi-operation Work
Order moves its rolls to the next operation — handled by the Job Card
on_submit doc_event in roll_tracking.py, so it works the same whether the
Job Card is completed here or from the desk.
"""
import frappe
from frappe import _
from frappe.utils import flt, now_datetime

from pranera_production.api.common import (
    wo_operations, job_card_for_operation, assert_role, is_inspection_operation,
)
from pranera_production.roll_tracking import ST_IN_PROCESS


def _rolls_for(filters):
    rows = frappe.get_all(
        "Roll", filters=filters,
        fields=["name", "item_code", "batch", "roll_weight", "total_qty", "stock_uom",
                "current_item", "current_batch", "current_weight", "current_process",
                "current_job_card", "current_work_order", "current_status", "current_grade",
                "current_total_points", "last_roll_inspection", "knitting_machine_no"],
        order_by="name asc", limit=2000,
    )
    return rows


@frappe.whitelist()
def get_job_cards(operation=None, workstation=None, status=None, txt=None, include_completed=0):
    filters = [["Job Card", "docstatus", "<", 2]]
    if not int(include_completed or 0):
        filters.append(["Job Card", "status", "not in", ["Completed", "Cancelled"]])
    if operation:
        filters.append(["Job Card", "operation", "=", operation])
    if workstation:
        filters.append(["Job Card", "workstation", "=", workstation])
    if status:
        filters.append(["Job Card", "status", "=", status])
    or_filters = None
    if txt:
        or_filters = [["Job Card", "name", "like", f"%{txt}%"],
                      ["Job Card", "work_order", "like", f"%{txt}%"],
                      ["Job Card", "production_item", "like", f"%{txt}%"]]
    rows = frappe.get_all(
        "Job Card", filters=filters, or_filters=or_filters,
        fields=["name", "work_order", "operation", "workstation", "status", "docstatus",
                "production_item", "item_name", "for_quantity", "total_completed_qty",
                "transferred_qty", "color", "commercial_name", "project", "modified"],
        order_by="modified desc", limit=200,
    )
    if rows:
        counts = frappe.db.sql(
            """select current_job_card jc, count(*) n, sum(current_weight) w from `tabRoll`
               where current_status=%(st)s and current_job_card in %(jcs)s group by current_job_card""",
            {"st": ST_IN_PROCESS, "jcs": [r.name for r in rows]}, as_dict=True,
        )
        cmap = {c.jc: c for c in counts}
        for r in rows:
            c = cmap.get(r.name)
            r.rolls_in_process = c.n if c else 0
            r.weight_in_process = flt(c.w, 3) if c else 0
            r.is_inspection = is_inspection_operation(r.operation)
    return rows


@frappe.whitelist()
def get_job_card_detail(job_card):
    jc = frappe.get_doc("Job Card", job_card)
    wo = frappe.db.get_value(
        "Work Order", jc.work_order,
        ["name", "production_item", "item_name", "qty", "produced_qty", "status", "project",
         "wip_warehouse", "fg_warehouse", "source_warehouse", "stock_uom", "color", "width",
         "required_gsm", "commercial_name"],
        as_dict=True,
    )
    ops = []
    for op in wo_operations(jc.work_order):
        ojc = job_card_for_operation(jc.work_order, op.name)
        ops.append({**op, "job_card": ojc,
                    "jc_status": frappe.db.get_value("Job Card", ojc, "status") if ojc else None,
                    "is_current": op.name == jc.operation_id})
    is_last = bool(ops) and ops[-1]["name"] == jc.operation_id

    issues = frappe.db.sql(
        """select se.name, se.custom_production_entry_type entry_type, se.posting_date, se.docstatus,
                  d.item_code, d.transfer_qty qty, d.stock_uom uom
           from `tabStock Entry` se join `tabStock Entry Detail` d on d.parent = se.name
           where se.job_card=%s and se.purpose='Material Transfer for Manufacture' and se.docstatus < 2
           order by se.creation""",
        job_card, as_dict=True,
    )
    mfs = frappe.get_all(
        "Stock Entry",
        filters={"work_order": jc.work_order, "purpose": "Manufacture", "docstatus": ["<", 2]},
        fields=["name", "posting_date", "fg_completed_qty", "docstatus", "custom_production_entry_type"],
        order_by="creation asc",
    )
    open_log = next((t for t in (jc.time_logs or []) if t.from_time and not t.to_time), None)
    return {
        "job_card": {
            "name": jc.name, "operation": jc.operation, "workstation": jc.workstation,
            "status": jc.status, "docstatus": jc.docstatus, "for_quantity": jc.for_quantity,
            "total_completed_qty": jc.total_completed_qty, "transferred_qty": jc.transferred_qty,
            "work_order": jc.work_order, "is_last_operation": is_last,
            "is_inspection": is_inspection_operation(jc.operation),
            "dye_chart": jc.get("custom_dye_chart"),
            "running_since": open_log.from_time if open_log else None,
            "time_logs": [{"from_time": t.from_time, "to_time": t.to_time, "completed_qty": t.completed_qty,
                           "employee": t.employee} for t in (jc.time_logs or [])],
        },
        "work_order": wo,
        "operations": ops,
        "rolls": _rolls_for({"current_job_card": job_card, "current_status": ST_IN_PROCESS}),
        "issues": issues,
        "manufactures": mfs,
    }


def _employee():
    return frappe.db.get_value("Employee", {"user_id": frappe.session.user, "status": "Active"}, "name")


@frappe.whitelist()
def start_job_card(job_card):
    assert_role("Process Operator", "Inspection Checker")
    jc = frappe.get_doc("Job Card", job_card)
    if jc.docstatus != 0:
        frappe.throw(_("Job Card {0} is already {1}").format(job_card, jc.status))
    if any(t.from_time and not t.to_time for t in jc.time_logs or []):
        return {"status": jc.status, "message": _("Already running")}
    jc.append("time_logs", {"from_time": now_datetime(), "employee": _employee()})
    jc.flags.ignore_permissions = True
    jc.save()
    frappe.db.commit()
    return {"status": jc.status}


@frappe.whitelist()
def complete_job_card(job_card, completed_qty=None, submit=1):
    """Closes the running time log (or adds one) with the completed qty and,
    by default, submits the Job Card."""
    assert_role("Process Operator", "Inspection Checker")
    jc = frappe.get_doc("Job Card", job_card)
    if jc.docstatus != 0:
        frappe.throw(_("Job Card {0} is already submitted").format(job_card))
    done = sum(flt(t.completed_qty) for t in jc.time_logs or [] if t.to_time)
    qty = flt(completed_qty) if completed_qty not in (None, "") else max(0.0, flt(jc.for_quantity) - done)
    now = now_datetime()
    open_log = next((t for t in (jc.time_logs or []) if t.from_time and not t.to_time), None)
    if open_log:
        open_log.to_time = now
        open_log.completed_qty = qty
    else:
        jc.append("time_logs", {"from_time": now, "to_time": now, "completed_qty": qty,
                                "employee": _employee()})
    jc.flags.ignore_permissions = True
    jc.save()
    if int(submit or 0):
        jc.submit()
    frappe.db.commit()
    return {"status": jc.status, "docstatus": jc.docstatus}
