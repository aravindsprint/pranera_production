"""Manufacture (MF) from rolls — supports partial MFs.

The operator picks which rolls (all, or part of the lot) go into this MF.

Weight rule per Work Order (decided with the user):
  * last operation is a "keep weight" operation (Dyeing etc., configurable
    in Production App Settings) → each roll keeps its previous weight;
  * last operation is INSPECTION → the weight captured on the roll's Roll
    Inspection is used (and, if the setting says so, every roll must be
    inspected first);
  * otherwise → the operator weighs every roll.

Stock rows:
  * fabric / collar / cuff consumed = each selected roll's effective item +
    batch, qty = previous weight (Kgs) or piece count (Pcs);
  * dyes & chemicals consumed = the share of what is still sitting in WIP
    for this Work Order, in proportion to the weight of rolls in this MF vs
    all rolls still in process (the last MF takes whatever is left). Only
    batches transferred against THIS Work Order are consumed.
  * finished good = Work Order production item, qty = new weights (or Pcs),
    into the Work Order's FG warehouse. Later partial MFs default to the
    batch the first MF created, so one lot stays one batch.

On submit, roll_tracking.on_stock_entry_submit moves every roll to the
finished item / batch / weight and creates the Roll Packing List.
"""
import frappe
from frappe import _
from frappe.utils import flt, cint, today

from pranera_production.api.common import (
    settings, floor3, is_pcs, stock_entry_base, effective_roll, ROLL_FIELDS, get_row_batch,
    wo_operations, job_card_for_operation, keep_weight_operations, is_inspection_operation,
    assert_role,
)
from pranera_production.roll_tracking import ENTRY_MF, ENTRY_ROLL_PICK, ST_IN_PROCESS


def _wo(work_order):
    wo = frappe.db.get_value(
        "Work Order", work_order,
        ["name", "production_item", "item_name", "qty", "produced_qty", "status", "docstatus",
         "project", "company", "wip_warehouse", "fg_warehouse", "stock_uom", "bom_no",
         "use_multi_level_bom", "color", "commercial_name"],
        as_dict=True,
    )
    if not wo:
        frappe.throw(_("Work Order {0} not found").format(work_order))
    return wo


def _weight_mode(last_op):
    op = (last_op or "").strip().upper()
    if op in keep_weight_operations():
        return "keep"
    if is_inspection_operation(op):
        return "inspection"
    return "enter"


def _latest_inspection(roll_no, work_order):
    rows = frappe.get_all(
        "Roll Inspection", filters={"roll": roll_no, "work_order": work_order},
        fields=["name", "grade", "roll_weight", "total_points", "point_percentage"],
        order_by="inspected_on desc, creation desc", limit=1,
    )
    return rows[0] if rows else None


def _rolls_in_process(work_order):
    rows = frappe.get_all("Roll", filters={"current_work_order": work_order, "current_status": ST_IN_PROCESS},
                          fields=ROLL_FIELDS, order_by="name asc", limit=5000)
    return [effective_roll(r) for r in rows]


def _roll_items_of_wo(work_order):
    """Item codes that came into this Work Order as rolls (fabric / collar /
    cuff). Everything else transferred against it is treated as chemicals."""
    names = frappe.get_all("Stock Entry",
                           filters={"work_order": work_order, "docstatus": 1,
                                    "custom_production_entry_type": ENTRY_ROLL_PICK}, pluck="name")
    items = set()
    if names:
        items |= set(frappe.get_all("Production Stock Entry Roll",
                                    filters={"parenttype": "Stock Entry", "parent": ["in", names]},
                                    pluck="item_code"))
    for r in _rolls_in_process(work_order):
        items.add(r.eff_item)
    return items


def _chemicals_remaining(work_order, wip_warehouse):
    """{(item_code, batch): qty} still in WIP for this Work Order and not
    yet consumed by an MF — chemicals only."""
    roll_items = _roll_items_of_wo(work_order)
    remaining = {}
    for se_name, purpose in frappe.get_all(
        "Stock Entry",
        filters={"work_order": work_order, "docstatus": 1,
                 "purpose": ["in", ["Material Transfer for Manufacture", "Manufacture"]]},
        fields=["name", "purpose"], as_list=True,
    ):
        for row in frappe.get_all(
            "Stock Entry Detail", filters={"parent": se_name},
            fields=["item_code", "batch_no", "serial_and_batch_bundle", "transfer_qty",
                    "s_warehouse", "t_warehouse", "is_finished_item", "is_scrap_item"],
        ):
            if row.item_code in roll_items or row.is_finished_item or row.is_scrap_item:
                continue
            key = (row.item_code, get_row_batch(row))
            if purpose == "Material Transfer for Manufacture" and row.t_warehouse == wip_warehouse:
                remaining[key] = remaining.get(key, 0.0) + flt(row.transfer_qty)
            elif purpose == "Manufacture" and row.s_warehouse == wip_warehouse:
                remaining[key] = remaining.get(key, 0.0) - flt(row.transfer_qty)
    return {k: flt(v, 3) for k, v in remaining.items() if flt(v, 3) > 0}


def _previous_fg_batch(work_order, production_item):
    for se in frappe.get_all("Stock Entry",
                             filters={"work_order": work_order, "docstatus": 1, "purpose": "Manufacture"},
                             pluck="name", order_by="creation asc"):
        for row in frappe.get_all("Stock Entry Detail",
                                  filters={"parent": se, "is_finished_item": 1, "item_code": production_item},
                                  fields=["batch_no", "serial_and_batch_bundle"]):
            b = get_row_batch(row)
            if b:
                return b
    return None


def _operations_ready(wo, fg_qty):
    """Mirror of ERPNext's check_if_operations_completed so the operator gets
    a clear message (which Job Card to complete) before the MF is built."""
    allowance = flt(frappe.db.get_single_value("Manufacturing Settings", "overproduction_percentage_for_work_order"))
    pending = []
    total = flt(fg_qty) + flt(wo.produced_qty)
    for op in wo_operations(wo.name):
        allowed = flt(op.completed_qty) * (1 + allowance / 100.0)
        if total > allowed + 0.0005:
            pending.append({"operation": op.operation, "job_card": job_card_for_operation(wo.name, op.name),
                            "completed_qty": op.completed_qty})
    return pending


@frappe.whitelist()
def get_mf_work_orders(txt=None):
    """Work Orders that have rolls in process."""
    cond, params = "", {"st": ST_IN_PROCESS}
    if txt:
        cond = "and (r.current_work_order like %(txt)s or wo.production_item like %(txt)s)"
        params["txt"] = f"%{txt}%"
    return frappe.db.sql(
        f"""select r.current_work_order work_order, wo.production_item, wo.item_name, wo.qty,
                   wo.produced_qty, wo.color, count(*) rolls, sum(r.current_weight) weight,
                   group_concat(distinct r.current_process) processes
            from `tabRoll` r join `tabWork Order` wo on wo.name = r.current_work_order
            where r.current_status=%(st)s {cond}
            group by r.current_work_order order by max(r.modified) desc limit 100""",
        params, as_dict=True,
    )


@frappe.whitelist()
def get_mf_context(work_order):
    wo = _wo(work_order)
    ops = wo_operations(work_order)
    last = ops[-1] if ops else None
    last_jc = job_card_for_operation(work_order, last.name) if last else None
    mode = _weight_mode(last.operation if last else None)
    rolls = []
    for r in _rolls_in_process(work_order):
        insp = _latest_inspection(r.name, work_order) if mode == "inspection" else None
        at_last = bool(last) and (r.current_process or "") == last.operation
        rolls.append({
            "roll_no": r.name, "item_code": r.eff_item, "batch_no": r.eff_batch, "uom": r.uom,
            "total_qty": cint(r.total_qty), "weight_before": r.eff_weight,
            "current_process": r.current_process, "current_job_card": r.current_job_card,
            "eligible": at_last,
            "not_eligible_reason": None if at_last else _("Still at {0}").format(r.current_process or "-"),
            "inspection": insp,
            "weight_after": (r.eff_weight if mode == "keep" else (flt(insp.roll_weight) if insp else None)),
        })
    chems = _chemicals_remaining(work_order, wo.wip_warehouse)
    return {
        "work_order": wo,
        "operations": ops,
        "last_operation": last.operation if last else None,
        "last_job_card": last_jc,
        "last_job_card_status": frappe.db.get_value("Job Card", last_jc, "status") if last_jc else None,
        "weight_mode": mode,
        "require_inspection": cint(settings().require_inspection_before_mf),
        "fg_item": wo.production_item,
        "fg_uom": wo.stock_uom,
        "fg_warehouse": wo.fg_warehouse,
        "default_fg_batch": _previous_fg_batch(work_order, wo.production_item),
        "rolls": rolls,
        "chemicals_in_wip": [{"item_code": k[0], "batch_no": k[1], "qty": v} for k, v in chems.items()],
    }


@frappe.whitelist()
def create_mf(work_order, rolls, fg_batch=None, posting_date=None, submit_stock_entry=1, remarks=None):
    assert_role("Process Operator", "Inspection Checker")
    rolls_in = frappe.parse_json(rolls) if isinstance(rolls, str) else (rolls or [])
    if not rolls_in:
        frappe.throw(_("Select at least one roll"))
    ctx = get_mf_context(work_order)
    wo = frappe._dict(ctx["work_order"])
    mode = ctx["weight_mode"]
    by_roll = {r["roll_no"]: r for r in ctx["rolls"]}

    selected = []
    for item in rolls_in:
        rn = item.get("roll_no")
        r = by_roll.get(rn)
        if not r:
            frappe.throw(_("Roll {0} is not in process for Work Order {1}").format(rn, work_order))
        if not r["eligible"]:
            frappe.throw(_("Roll {0}: {1} — complete the earlier operation first").format(rn, r["not_eligible_reason"]))
        insp = r.get("inspection")
        if mode == "keep":
            w_after = flt(r["weight_before"])
        else:
            w_after = flt(item.get("weight_after")) or (flt(insp.get("roll_weight")) if insp else 0)
            if mode == "inspection" and ctx["require_inspection"] and not insp:
                frappe.throw(_("Roll {0} has not been inspected yet").format(rn))
            if w_after <= 0:
                frappe.throw(_("Enter the weight of roll {0}").format(rn))
        selected.append({**r, "weight_after": flt(w_after, 3)})

    # FG qty in the FG UOM
    if is_pcs(ctx["fg_uom"]):
        fg_qty = sum(cint(r["total_qty"]) for r in selected)
    else:
        fg_qty = flt(sum(r["weight_after"] for r in selected if not is_pcs(r["uom"])), 3)
    if fg_qty <= 0:
        frappe.throw(_("Finished quantity is zero"))

    pending_ops = _operations_ready(wo, fg_qty)
    if pending_ops:
        frappe.throw(_("Complete these operations before the MF: {0}").format(
            ", ".join(f"{p['operation']} ({p['job_card'] or '-'})" for p in pending_ops)))

    se = stock_entry_base("Manufacture", settings().mf_naming_series, wo.company, posting_date or today())
    se.work_order = work_order
    se.custom_job_card = ctx["last_job_card"]
    se.project = wo.project
    se.bom_no = wo.bom_no
    se.from_bom = 1
    se.use_multi_level_bom = wo.use_multi_level_bom
    se.fg_completed_qty = fg_qty
    se.from_warehouse = wo.wip_warehouse
    se.to_warehouse = wo.fg_warehouse
    se.custom_production_entry_type = ENTRY_MF
    se.fabric_name = wo.commercial_name
    se.colour = wo.color
    if remarks:
        se.remarks = remarks

    # roll material consumed
    groups = {}
    for r in selected:
        key = (r["item_code"], r["batch_no"])
        g = groups.setdefault(key, {"qty": 0.0, "uom": r["uom"]})
        g["qty"] += cint(r["total_qty"]) if is_pcs(r["uom"]) else flt(r["weight_before"])
    for (item_code, batch_no), g in groups.items():
        row = {"s_warehouse": wo.wip_warehouse, "item_code": item_code, "qty": flt(g["qty"], 3),
               "transfer_qty": flt(g["qty"], 3), "uom": g["uom"], "stock_uom": g["uom"],
               "conversion_factor": 1}
        if batch_no:
            row.update({"batch_no": batch_no, "use_serial_batch_fields": 1})
        se.append("items", row)

    # chemicals: proportional share of what's left in WIP
    all_w = sum(flt(r["weight_before"]) for r in ctx["rolls"] if not is_pcs(r["uom"]))
    sel_w = sum(flt(r["weight_before"]) for r in selected if not is_pcs(r["uom"]))
    is_final = len(selected) == len(ctx["rolls"])
    share = 1.0 if (is_final or not all_w) else min(1.0, sel_w / all_w)
    for (item_code, batch_no), qty in _chemicals_remaining(work_order, wo.wip_warehouse).items():
        take = flt(qty, 3) if share >= 1 else floor3(qty * share)
        if take <= 0:
            continue
        uom = frappe.db.get_value("Item", item_code, "stock_uom")
        row = {"s_warehouse": wo.wip_warehouse, "item_code": item_code, "qty": take,
               "transfer_qty": take, "uom": uom, "stock_uom": uom, "conversion_factor": 1}
        if batch_no:
            row.update({"batch_no": batch_no, "use_serial_batch_fields": 1})
        se.append("items", row)

    # finished good — batch, in this order: the one the user typed; the batch
    # an earlier MF of this Work Order made (one lot stays one batch); the
    # batch_automation rule for this item / process; ERPNext's own series;
    # else one made here (_new_fg_batch).
    fg_batch = fg_batch or ctx["default_fg_batch"]
    fg_row = se.append("items", {"t_warehouse": wo.fg_warehouse, "item_code": wo.production_item, "qty": fg_qty,
              "transfer_qty": fg_qty, "uom": wo.stock_uom, "stock_uom": wo.stock_uom,
              "conversion_factor": 1, "is_finished_item": 1, "bom_no": wo.bom_no})
    if not fg_batch:
        fg_batch = _batch_from_rules(se, fg_row) or _new_fg_batch(wo)
    if fg_batch:
        fg_row.update({"batch_no": fg_batch, "use_serial_batch_fields": 1})

    for r in selected:
        insp = r.get("inspection") or {}
        se.append("custom_production_rolls", {
            "roll_no": r["roll_no"], "item_code": r["item_code"], "batch_no": r["batch_no"],
            "uom": r["uom"], "total_qty": cint(r["total_qty"]),
            "weight_before": flt(r["weight_before"], 3), "weight_after": r["weight_after"],
            "process_loss": flt(flt(r["weight_before"]) - r["weight_after"], 3),
            "grade": insp.get("grade"), "roll_inspection": insp.get("name"),
        })

    se.flags.ignore_permissions = True
    frappe.db.savepoint("pp_mf")
    try:
        se.insert()
        if cint(submit_stock_entry):
            se.submit()
    except frappe.ValidationError as e:
        # The finished batch was left to ERPNext / batch_automation and neither
        # made one ("Serial No / Batch No are mandatory for Item <FG>"): make it
        # here and build the MF again.
        if fg_batch or "are mandatory for Item" not in str(e) or wo.production_item not in str(e):
            raise
        frappe.db.rollback(save_point="pp_mf")
        frappe.clear_messages()
        return create_mf(work_order, rolls, fg_batch=_new_fg_batch(wo, force=True),
                         posting_date=posting_date, submit_stock_entry=submit_stock_entry, remarks=remarks)
    frappe.db.commit()
    fg_batch_after = None
    for it in se.items:
        if it.is_finished_item:
            fg_batch_after = get_row_batch(it)
    return {
        "stock_entry": se.name,
        "submitted": bool(cint(submit_stock_entry)),
        "fg_item": wo.production_item,
        "fg_batch": fg_batch_after,
        "fg_qty": fg_qty,
        "rolls": [{"roll_no": r["roll_no"], "weight": r["weight_after"]} for r in selected],
        "packing_list": frappe.db.get_value("Roll Packing List", {"stock_entry": se.name, "docstatus": 1}, "name"),
    }


def _batch_from_rules(se, fg_row):
    """The finished batch named by the batch_automation app's Batch Naming
    Rules (item type + process + Work Order / dyeing references), when that
    app is installed and enabled and a rule matches. Done here, before the
    entry is saved, so the row carries the batch the way ERPNext needs it
    (use_serial_batch_fields); batch_automation's own before_submit hook then
    sees the batch already set and leaves it alone. None if no rule applies."""
    if "batch_automation" not in frappe.get_installed_apps():
        return None
    try:
        from batch_automation.batch_naming import resolver
    except ImportError:
        return None
    try:
        resolver.lock_batches(se)
    except Exception:
        # a rule problem must not stop the MF — fall back to the app's naming
        frappe.log_error(frappe.get_traceback(), "Production MF: batch_automation naming failed")
        frappe.clear_messages()
        fg_row.batch_no = None
        return None
    return fg_row.get("batch_no") or None


def _new_fg_batch(wo, force=False):
    """A batch for the finished item when ERPNext won't make one itself.

    ERPNext auto-creates the finished batch only if the Item has "Automatically
    Create New Batch" with a Batch Number Series (as DKF… items do). For an
    item without it the MF fails with "Serial No / Batch No are mandatory".
    Then create the Batch here: the Item's Batch Number Series if it has one,
    else Stock Settings' batch naming, else <Work Order>/<n>. Only used when
    no batch_automation rule named the batch (see _batch_from_rules)."""
    item = frappe.db.get_value("Item", wo.production_item,
                               ["has_batch_no", "create_new_batch", "batch_number_series"], as_dict=True)
    if not item or not cint(item.has_batch_no):
        return None
    if not force and cint(item.create_new_batch) and item.batch_number_series:
        return None  # ERPNext names it
    from frappe.model.naming import make_autoname
    batch = frappe.new_doc("Batch")
    batch.item = wo.production_item
    batch.reference_doctype = "Work Order"
    batch.reference_name = wo.name
    # Batch ID is mandatory for an item without "Automatically Create New Batch"
    if item.batch_number_series:
        series = item.batch_number_series
    elif cint(frappe.db.get_single_value("Stock Settings", "use_naming_series")):
        series = (frappe.db.get_single_value("Stock Settings", "naming_series_prefix") or "BATCH-") + ".#####"
    else:
        series = None
    n = frappe.db.count("Batch", {"batch_id": ["like", f"{wo.name}/%"]})
    while not batch.batch_id or frappe.db.exists("Batch", batch.batch_id):
        if series:
            batch.batch_id = make_autoname(series, "Batch")
        else:
            n += 1
            batch.batch_id = f"{wo.name}/{n}"
    batch.flags.ignore_permissions = True
    batch.insert()
    return batch.name
