"""Roll process history + document event handlers.

Every movement of a roll through production appends ONE row to the roll's
Process History (Roll.roll_tracking_entries, child doctype "Roll Tracking
Entries"). The roll's current_* fields are never written directly — they
are always recomputed from the LAST history row (recompute_current). That
makes cancelling anything trivial and safe: delete the rows the cancelled
document created, recompute, done.

Events
  Issued To Process   MTM (Roll Pick) submitted — roll is now in the
                      workstation WIP against a Work Order / Job Card.
  Process Completed   An intermediate Job Card of a multi-operation Work
                      Order was submitted — roll moves on to the next
                      operation (process only, weight unchanged).
  Manufactured        MF submitted — roll becomes the finished item /
                      batch, new weight, process loss recorded.
"""
import frappe
from frappe import _
from frappe.utils import flt, now_datetime, today

from pranera_production.api.common import (
    get_row_batch, wo_operations, job_card_for_operation,
)

ENTRY_ROLL_PICK = "Roll Pick"
ENTRY_CHEMICAL = "Chemical Issue"
ENTRY_MF = "Production MF"

EV_ISSUED = "Issued To Process"
EV_PROCESS_DONE = "Process Completed"
EV_MANUFACTURED = "Manufactured"
EV_TRANSFERRED = "Transferred"

ST_IN_PROCESS = "In Process"
ST_IN_STOCK = "In Stock"


# ── Core helpers ─────────────────────────────────────────────────────────────

def add_history(roll_doc, **row):
    row.setdefault("date", today())
    row.setdefault("custom_posting_datetime", now_datetime())
    row["roll_no"] = roll_doc.name
    roll_doc.append("roll_tracking_entries", row)


def recompute_current(roll_doc):
    rows = sorted(roll_doc.get("roll_tracking_entries") or [], key=lambda r: r.idx or 0)
    if not rows:
        for f in ("current_status", "current_process", "current_work_order", "current_job_card",
                  "current_warehouse", "current_item", "current_batch"):
            roll_doc.set(f, None)
        roll_doc.current_weight = 0
        roll_doc.current_process_loss = 0
        return
    last = rows[-1]
    roll_doc.current_status = last.get("custom_roll_status")
    roll_doc.current_process = last.get("operation")
    roll_doc.current_work_order = last.get("custom_work_order")
    roll_doc.current_job_card = last.get("custom_job_card")
    roll_doc.current_warehouse = last.get("target_warehouse")
    roll_doc.current_item = last.get("target_item")
    roll_doc.current_batch = last.get("target_batch")
    roll_doc.current_weight = flt(last.get("custom_weight_after"), 3)
    roll_doc.current_process_loss = flt(sum(flt(r.get("custom_process_loss")) for r in rows), 3)


def save_roll(roll_doc):
    roll_doc.flags.ignore_permissions = True
    roll_doc.flags.ignore_mandatory = True
    roll_doc.save()


def remove_history_for(roll_name, document_name):
    roll_doc = frappe.get_doc("Roll", roll_name)
    keep = [r for r in (roll_doc.get("roll_tracking_entries") or []) if r.document_name != document_name]
    if len(keep) == len(roll_doc.get("roll_tracking_entries") or []):
        return
    for i, r in enumerate(keep, 1):
        r.idx = i
    roll_doc.set("roll_tracking_entries", keep)
    recompute_current(roll_doc)
    save_roll(roll_doc)


# ── Stock Entry ──────────────────────────────────────────────────────────────

def on_stock_entry_submit(doc, method=None):
    entry_type = doc.get("custom_production_entry_type")
    if not entry_type or not doc.get("custom_production_rolls"):
        return
    if entry_type == ENTRY_ROLL_PICK:
        from pranera_production.api.pick import set_transferred_lot_qty
        set_transferred_lot_qty(doc)
        _issue_rolls_to_process(doc)
    elif entry_type == ENTRY_MF:
        _manufacture_rolls(doc)


def _issue_rolls_to_process(doc):
    if doc.purpose == "Material Transfer":
        return _transfer_rolls(doc)
    job_card = doc.get("job_card")
    operation = frappe.db.get_value("Job Card", job_card, "operation") if job_card else None
    # source / target warehouse per (item, batch) from the actual SE rows
    wh = {}
    for it in doc.items:
        wh[(it.item_code, get_row_batch(it))] = (it.s_warehouse, it.t_warehouse)
    for r in doc.custom_production_rolls:
        roll_doc = frappe.get_doc("Roll", r.roll_no)
        s_wh, t_wh = wh.get((r.item_code, r.batch_no)) or (doc.from_warehouse, doc.to_warehouse)
        add_history(
            roll_doc,
            custom_event=EV_ISSUED,
            operation=operation,
            source_item=r.item_code, target_item=r.item_code,
            source_batch=r.batch_no, target_batch=r.batch_no,
            source_warehouse=s_wh, target_warehouse=t_wh,
            qty=r.weight_before,
            custom_weight_before=r.weight_before, custom_weight_after=r.weight_before,
            custom_process_loss=0,
            custom_work_order=doc.work_order, custom_job_card=job_card,
            custom_roll_status=ST_IN_PROCESS,
            document_type="Stock Entry", document_name=doc.name,
            remarks=_("Issued to {0} ({1})").format(operation or "process", job_card or doc.work_order),
        )
        recompute_current(roll_doc)
        save_roll(roll_doc)


def _transfer_rolls(doc):
    """MT (pick to an In Transit warehouse): the rolls just change warehouse.
    They stay In Stock, not tied to a Work Order, and are picked again (MTM)
    from the transit warehouse when they reach the WIP."""
    wh = {}
    for it in doc.items:
        wh[(it.item_code, get_row_batch(it))] = (it.s_warehouse, it.t_warehouse)
    ref_wo = doc.get("work_order") or doc.get("custom_reference_dyeing_work_order")
    for r in doc.custom_production_rolls:
        roll_doc = frappe.get_doc("Roll", r.roll_no)
        s_wh, t_wh = wh.get((r.item_code, r.batch_no)) or (doc.from_warehouse, doc.to_warehouse)
        add_history(
            roll_doc,
            custom_event=EV_TRANSFERRED,
            operation=roll_doc.get("current_process"),
            source_item=r.item_code, target_item=r.item_code,
            source_batch=r.batch_no, target_batch=r.batch_no,
            source_warehouse=s_wh, target_warehouse=t_wh,
            qty=r.weight_before,
            custom_weight_before=r.weight_before, custom_weight_after=r.weight_before,
            custom_process_loss=0,
            custom_roll_status=ST_IN_STOCK,
            document_type="Stock Entry", document_name=doc.name,
            remarks=_("Transferred to {0}").format(t_wh) + (_(" for {0}").format(ref_wo) if ref_wo else ""),
        )
        recompute_current(roll_doc)
        save_roll(roll_doc)


def _manufacture_rolls(doc):
    fg_rows = [it for it in doc.items if it.is_finished_item]
    if not fg_rows:
        frappe.throw(_("Production MF {0} has no finished item row").format(doc.name))
    fg = fg_rows[0]
    fg_batch = get_row_batch(fg)
    job_card = doc.get("custom_job_card") or doc.get("job_card")
    operation = frappe.db.get_value("Job Card", job_card, "operation") if job_card else None
    wip = {it.item_code: it.s_warehouse for it in doc.items if it.s_warehouse}

    for r in doc.custom_production_rolls:
        roll_doc = frappe.get_doc("Roll", r.roll_no)
        loss = flt(flt(r.weight_before) - flt(r.weight_after), 3)
        add_history(
            roll_doc,
            custom_event=EV_MANUFACTURED,
            operation=operation or roll_doc.get("current_process"),
            source_item=r.item_code, target_item=fg.item_code,
            source_batch=r.batch_no, target_batch=fg_batch,
            source_warehouse=wip.get(r.item_code) or doc.from_warehouse,
            target_warehouse=fg.t_warehouse,
            qty=r.weight_after,
            custom_weight_before=r.weight_before, custom_weight_after=r.weight_after,
            custom_process_loss=loss,
            custom_work_order=doc.work_order, custom_job_card=job_card,
            custom_roll_status=ST_IN_STOCK,
            document_type="Stock Entry", document_name=doc.name,
            remarks=_("Manufactured {0}").format(fg.item_code),
        )
        recompute_current(roll_doc)
        save_roll(roll_doc)
        r.db_set("process_loss", loss, update_modified=False)

    if fg_batch:
        _create_roll_packing_list(doc, fg, fg_batch, job_card)


def _create_roll_packing_list(doc, fg, fg_batch, job_card):
    """Same shape as the knitting MF packing list (document_type Job Card,
    transaction_type Outward, linked to the MF Stock Entry) so every
    downstream consumer — pick scanning's "packed against a Stock Entry"
    check, Verify Rolls, dispatch — treats processed rolls exactly like
    freshly knitted ones."""
    rpl = frappe.new_doc("Roll Packing List")
    rpl.posting_date = doc.posting_date
    rpl.document_type = "Job Card" if job_card else "Work Order"
    rpl.document_name = job_card or doc.work_order
    rpl.stock_entry = doc.name
    rpl.transaction_type = "Outward"
    total_w, total_q = 0.0, 0
    for r in doc.custom_production_rolls:
        total_qty = frappe.db.get_value("Roll", r.roll_no, "total_qty") or 0
        rpl.append("roll_packing_list_item", {
            "roll_no": r.roll_no,
            "item_code": fg.item_code,
            "uom": fg.stock_uom or fg.uom,
            "batch": fg_batch,
            "roll_weight": r.weight_after,
            "total_qty": total_qty,
        })
        total_w += flt(r.weight_after)
        total_q += int(total_qty or 0)
    rpl.total_roll_weight = flt(total_w, 3)
    rpl.total_pcs_qty = total_q
    rpl.flags.ignore_permissions = True
    rpl.insert()
    rpl.submit()


def on_stock_entry_before_cancel(doc, method=None):
    if doc.get("custom_production_entry_type") != ENTRY_MF:
        return
    for name in frappe.get_all("Roll Packing List",
                               filters={"stock_entry": doc.name, "docstatus": 1}, pluck="name"):
        rpl = frappe.get_doc("Roll Packing List", name)
        rpl.flags.ignore_permissions = True
        rpl.cancel()


def on_stock_entry_cancel(doc, method=None):
    if doc.get("custom_production_entry_type") == ENTRY_CHEMICAL and doc.get("custom_dye_chart"):
        from pranera_production.api.dye import remove_additions_for
        remove_additions_for(doc.name)
    if not doc.get("custom_production_entry_type") or not doc.get("custom_production_rolls"):
        return
    for r in doc.custom_production_rolls:
        remove_history_for(r.roll_no, doc.name)


# ── Job Card (multi-operation Work Orders) ───────────────────────────────────

def on_job_card_validate(doc, method=None):
    """Work Orders that transfer material against the Work Order (the pick MTM)
    never fill a Job Card's Transferred Qty: ERPNext leaves it at 0 because
    such Job Cards normally have no item rows. The Dye Chart adds its chemicals
    as Job Card items, and with items ERPNext refuses to start or submit the
    Job Card until Transferred Qty reaches For Quantity ("Materials needs to be
    transferred to the work in progress warehouse"). Mirror the Work Order's
    transferred qty onto the Job Card instead."""
    if not doc.work_order or not doc.get("items"):
        return
    wo = frappe.db.get_value("Work Order", doc.work_order,
                             ["transfer_material_against", "skip_transfer",
                              "material_transferred_for_manufacturing"], as_dict=True)
    if not wo or (wo.transfer_material_against == "Job Card" and not wo.skip_transfer):
        return
    qty = flt(doc.for_quantity) if wo.skip_transfer else \
        min(flt(doc.for_quantity), flt(wo.material_transferred_for_manufacturing))
    if flt(doc.transferred_qty) != qty:
        doc.transferred_qty = qty


def on_job_card_submit(doc, method=None):
    rolls = frappe.get_all(
        "Roll", filters={"current_job_card": doc.name, "current_status": ST_IN_PROCESS}, pluck="name",
    )
    if not rolls:
        return
    ops = wo_operations(doc.work_order)
    idx = next((i for i, op in enumerate(ops) if op.name == doc.operation_id), None)
    if idx is None or idx >= len(ops) - 1:
        return  # last (or unknown) operation — the MF moves the rolls on
    nxt = ops[idx + 1]
    next_jc = job_card_for_operation(doc.work_order, nxt.name)
    for name in rolls:
        roll_doc = frappe.get_doc("Roll", name)
        add_history(
            roll_doc,
            custom_event=EV_PROCESS_DONE,
            operation=nxt.operation,
            source_item=roll_doc.current_item, target_item=roll_doc.current_item,
            source_batch=roll_doc.current_batch, target_batch=roll_doc.current_batch,
            source_warehouse=roll_doc.current_warehouse, target_warehouse=roll_doc.current_warehouse,
            qty=roll_doc.current_weight,
            custom_weight_before=roll_doc.current_weight, custom_weight_after=roll_doc.current_weight,
            custom_process_loss=0,
            custom_work_order=doc.work_order, custom_job_card=next_jc,
            custom_roll_status=ST_IN_PROCESS,
            document_type="Job Card", document_name=doc.name,
            remarks=_("{0} completed, moved to {1}").format(doc.operation, nxt.operation),
        )
        recompute_current(roll_doc)
        save_roll(roll_doc)


def on_job_card_cancel(doc, method=None):
    rolls = frappe.db.sql(
        """select distinct parent from `tabRoll Tracking Entries`
           where parenttype='Roll' and document_type='Job Card' and document_name=%s""",
        doc.name, pluck=True,
    )
    for name in rolls:
        remove_history_for(name, doc.name)


# ── Roll Wise Pick List ──────────────────────────────────────────────────────

def use_current_roll_weights(doc, method=None):
    rows = doc.get("roll_wise_pick_item") or []
    if not rows:
        return
    changed = False
    for row in rows:
        if not row.roll_no or row.get("qi_report"):
            continue
        cur = frappe.db.get_value("Roll", row.roll_no, ["current_weight", "current_item", "current_batch"], as_dict=True)
        if cur and (cur.current_item or cur.current_batch) and flt(cur.current_weight):
            if flt(row.roll_weight) != flt(cur.current_weight):
                row.roll_weight = flt(cur.current_weight)
                changed = True
    if not changed:
        return
    weights = {}
    for row in rows:
        key = (row.item_code, row.warehouse, row.batch)
        weights[key] = weights.get(key, 0.0) + flt(row.roll_weight)
    for b in doc.get("batch_wise_pick_item") or []:
        key = (b.item_code, b.warehouse, b.batch)
        if key in weights and b.meta.has_field("weight"):
            b.weight = round(weights[key], 3)
