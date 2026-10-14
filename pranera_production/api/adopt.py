"""Adopt rolls that moved BEFORE go-live (no process history yet).

Before this app, MTMs were made from the desk by batch — a greige batch is
often split across several dyeing Work Orders (e.g. 597 kg of a 3,996 kg /
166-roll batch), and dyed batches (…-D) have no Roll records at all. So the
system cannot work out which physical rolls went where; a person scans them.

Two modes:

  WIP   — rolls sitting in a workstation WIP against a Work Order whose MTM was
          made before go-live. Pick the transferred row (item + batch), scan
          the rolls. Each roll gets an "Issued To Process" history row
          (document = the Work Order) and is placed at the Work Order's
          current operation (first operation whose Job Card isn't submitted).
          From then on Job Card completion, inspection and MF work normally.

  Stock — rolls processed before go-live and now in stock (e.g. in the lot
          section as a dyed …-D batch). Pick the batch + warehouse, scan the
          rolls, enter each roll's weight (defaults to its greige weight).
          Each roll gets an "Inward" history row and becomes that batch's
          item / batch / warehouse, so it can be picked for the next process.

Both modes cap the adopted quantity at what the ledger says is there (+ the
pick tolerance), refuse rolls already in process, and can be undone roll by
roll (only the adoption row is removed).
"""
import frappe
from frappe import _
from frappe.utils import flt, cint

from pranera_production.api.common import (
    settings, get_roll, parse_scan, is_pcs, wo_operations, job_card_for_operation,
    get_row_batch, assert_role,
)
from pranera_production.roll_tracking import (
    add_history, recompute_current, save_roll, remove_history_for, ST_IN_PROCESS, ST_IN_STOCK,
)

ADOPT_REMARK = "Adopted (moved before go-live)"


def _tol():
    return 1 + (flt(settings().pick_tolerance_pct) or 3) / 100.0


def _qty_of(roll):
    return cint(roll.total_qty) if is_pcs(roll.uom) else flt(roll.eff_weight)


def _assert_last_row(roll_no, document_name):
    rows = frappe.get_all("Roll Tracking Entries", filters={"parenttype": "Roll", "parent": roll_no},
                          fields=["document_name", "remarks"], order_by="idx desc", limit=1)
    if not rows or rows[0].document_name != document_name or rows[0].remarks != ADOPT_REMARK:
        frappe.throw(_("Roll {0} has moved on since it was adopted — cancel the later document first").format(roll_no))


# ── WIP mode ────────────────────────────────────────────────────────────────

def _current_operation(work_order):
    """First operation whose Job Card is not submitted (else the last)."""
    ops = wo_operations(work_order)
    chosen = None
    for op in ops:
        jc = job_card_for_operation(work_order, op.name)
        if not jc or frappe.db.get_value("Job Card", jc, "docstatus") != 1:
            chosen = (op, jc)
            break
    if not chosen and ops:
        chosen = (ops[-1], job_card_for_operation(work_order, ops[-1].name))
    return chosen or (None, None)


def _transferred_rows(work_order):
    wip = frappe.db.get_value("Work Order", work_order, "wip_warehouse")
    rows = {}
    for se in frappe.get_all("Stock Entry", filters={"work_order": work_order, "docstatus": 1,
                                                     "purpose": "Material Transfer for Manufacture"}, pluck="name"):
        for d in frappe.get_all("Stock Entry Detail", filters={"parent": se},
                                fields=["item_code", "batch_no", "serial_and_batch_bundle", "transfer_qty",
                                        "t_warehouse", "stock_uom"]):
            if d.t_warehouse != wip:
                continue
            key = (d.item_code, get_row_batch(d))
            r = rows.setdefault(key, {"item_code": d.item_code, "batch_no": key[1], "uom": d.stock_uom,
                                      "qty": 0.0, "mtms": set()})
            r["qty"] += flt(d.transfer_qty)
            r["mtms"].add(se)
    return rows


def _adopted_wip(work_order):
    """{(item, batch): (rolls, qty)} adopted or picked into this Work Order."""
    rows = frappe.db.sql(
        """select h.target_item item, h.target_batch batch, count(*) n, sum(h.custom_weight_before) w,
                  sum(r.total_qty) pcs, max(r.stock_uom) uom
           from `tabRoll Tracking Entries` h join `tabRoll` r on r.name = h.parent
           where h.parenttype='Roll' and h.custom_event='Issued To Process' and h.custom_work_order=%s
           group by h.target_item, h.target_batch""", work_order, as_dict=True,
    )
    return {(r.item, r.batch): (r.n, cint(r.pcs) if is_pcs(r.uom) else flt(r.w)) for r in rows}


@frappe.whitelist()
def get_wip_context(work_order):
    wo = frappe.db.get_value("Work Order", work_order,
                             ["name", "production_item", "item_name", "qty", "status", "wip_warehouse", "project"],
                             as_dict=True)
    if not wo:
        frappe.throw(_("Work Order {0} not found").format(work_order))
    op, jc = _current_operation(work_order)
    adopted = _adopted_wip(work_order)
    rows = []
    for key, r in _transferred_rows(work_order).items():
        n, q = adopted.get(key, (0, 0))
        rows.append({
            "item_code": r["item_code"], "batch_no": r["batch_no"], "uom": r["uom"],
            "transferred_qty": flt(r["qty"], 3), "adopted_rolls": n, "adopted_qty": flt(q, 3),
            "mtms": sorted(r["mtms"]),
            "rolls_in_batch": frappe.db.count("Roll", {"batch": r["batch_no"]}) if r["batch_no"] else 0,
        })
    rows.sort(key=lambda x: (x["item_code"], x["batch_no"] or ""))
    rolls = frappe.get_all(
        "Roll Tracking Entries",
        filters={"parenttype": "Roll", "custom_work_order": work_order, "custom_event": "Issued To Process",
                 "document_type": "Work Order"},
        fields=["parent as roll_no", "target_item as item_code", "target_batch as batch_no",
                "custom_weight_before as weight"], order_by="parent",
    )
    return {"work_order": wo, "operation": op.operation if op else None, "job_card": jc,
            "rows": rows, "adopted_rolls": rolls}


@frappe.whitelist()
def adopt_wip_roll(work_order, item_code, batch_no, roll_no, weight=None):
    assert_role("Production Supervisor")
    roll_no = parse_scan(roll_no)
    roll = get_roll(roll_no)
    if roll.current_status == ST_IN_PROCESS:
        frappe.throw(_("Roll {0} is already in process for {1}").format(roll_no, roll.current_work_order))
    rows = _transferred_rows(work_order)
    key = (item_code, batch_no or None)
    if key not in rows:
        frappe.throw(_("{0} / {1} was not transferred to Work Order {2}").format(item_code, batch_no, work_order))
    # the roll must be of that batch (original or current), unless the batch has
    # no Roll records at all (purchased / dyed-before-go-live) — then trust the scan
    batch_has_rolls = batch_no and frappe.db.exists("Roll", {"batch": batch_no})
    if batch_has_rolls and batch_no not in (roll.batch, roll.current_batch):
        frappe.throw(_("Roll {0} is batch {1}, not {2}").format(roll_no, roll.eff_batch, batch_no))

    qty = flt(weight) if flt(weight) > 0 else flt(roll.eff_weight)
    if is_pcs(roll.uom):
        this_qty = cint(roll.total_qty)
    else:
        this_qty = qty
    done = _adopted_wip(work_order).get(key, (0, 0))[1]
    limit = rows[key]["qty"] * _tol()
    if done + this_qty > limit + 0.0005:
        frappe.throw(_("Adopting {0} would exceed what was transferred for {1}: {2} of {3}").format(
            roll_no, batch_no or item_code, flt(done + this_qty, 3), flt(rows[key]["qty"], 3)))

    op, jc = _current_operation(work_order)
    wip = frappe.db.get_value("Work Order", work_order, "wip_warehouse")
    doc = frappe.get_doc("Roll", roll_no)
    add_history(
        doc, custom_event="Issued To Process", operation=op.operation if op else None,
        source_item=roll.eff_item, target_item=item_code,
        source_batch=roll.eff_batch, target_batch=batch_no,
        source_warehouse=roll.eff_warehouse, target_warehouse=wip,
        qty=qty, custom_weight_before=qty, custom_weight_after=qty, custom_process_loss=0,
        custom_work_order=work_order, custom_job_card=jc, custom_roll_status=ST_IN_PROCESS,
        document_type="Work Order", document_name=work_order, remarks=ADOPT_REMARK,
    )
    recompute_current(doc)
    save_roll(doc)
    frappe.db.commit()
    return {"roll_no": roll_no, "weight": qty, "operation": op.operation if op else None, "job_card": jc}


@frappe.whitelist()
def unadopt_wip_roll(work_order, roll_no):
    assert_role("Production Supervisor")
    roll_no = parse_scan(roll_no)
    _assert_last_row(roll_no, work_order)
    remove_history_for(roll_no, work_order)
    frappe.db.commit()
    return {"success": True}


# ── Stock mode ──────────────────────────────────────────────────────────────

def _batch_stock(batch_no):
    from erpnext.stock.doctype.batch.batch import get_batch_qty
    rows = get_batch_qty(batch_no=batch_no) or []
    return {r.get("warehouse"): flt(r.get("qty")) for r in rows if flt(r.get("qty")) > 0}


def _adopted_stock(batch_no):
    return frappe.db.sql(
        """select name roll_no, current_weight weight, total_qty, stock_uom, current_warehouse warehouse
           from `tabRoll` where current_batch=%s and current_status=%s order by name""",
        (batch_no, ST_IN_STOCK), as_dict=True,
    )


@frappe.whitelist()
def search_batches(txt=None):
    filters = {"disabled": 0}
    or_filters = {"name": ["like", f"%{txt}%"], "item": ["like", f"%{txt}%"]} if txt else None
    return frappe.get_all("Batch", filters=filters, or_filters=or_filters,
                          fields=["name", "item", "batch_qty", "stock_uom"], limit=30, order_by="modified desc")


@frappe.whitelist()
def get_stock_context(batch_no):
    b = frappe.db.get_value("Batch", batch_no, ["name", "item", "batch_qty", "stock_uom"], as_dict=True)
    if not b:
        frappe.throw(_("Batch {0} not found").format(batch_no))
    stock = _batch_stock(batch_no)
    adopted = _adopted_stock(batch_no)
    return {
        "batch": b,
        "item_name": frappe.db.get_value("Item", b.item, "item_name"),
        "warehouses": [{"warehouse": w, "qty": flt(q, 3)} for w, q in stock.items()],
        "adopted": adopted,
        "adopted_qty": flt(sum((cint(r.total_qty) if is_pcs(r.stock_uom) else flt(r.weight)) for r in adopted), 3),
        "rolls_with_batch": frappe.db.count("Roll", {"batch": batch_no}),
    }


@frappe.whitelist()
def adopt_stock_roll(batch_no, warehouse, roll_no, weight=None):
    assert_role("Production Supervisor")
    roll_no = parse_scan(roll_no)
    roll = get_roll(roll_no)
    if roll.current_status == ST_IN_PROCESS:
        frappe.throw(_("Roll {0} is in process for {1} — finish it there").format(roll_no, roll.current_work_order))
    if roll.current_batch == batch_no:
        frappe.throw(_("Roll {0} is already on batch {1}").format(roll_no, batch_no))
    item = frappe.db.get_value("Batch", batch_no, "item")
    stock = _batch_stock(batch_no)
    if warehouse not in stock:
        frappe.throw(_("Batch {0} has no stock in {1}").format(batch_no, warehouse))
    w = flt(weight) if flt(weight) > 0 else flt(roll.eff_weight)
    this_qty = cint(roll.total_qty) if is_pcs(roll.uom) else w
    done = sum((cint(r.total_qty) if is_pcs(r.stock_uom) else flt(r.weight))
               for r in _adopted_stock(batch_no) if r.warehouse == warehouse)
    if done + this_qty > stock[warehouse] * _tol() + 0.0005:
        frappe.throw(_("Adopting {0} would exceed the stock of {1} in {2}: {3} of {4}").format(
            roll_no, batch_no, warehouse, flt(done + this_qty, 3), flt(stock[warehouse], 3)))

    doc = frappe.get_doc("Roll", roll_no)
    add_history(
        doc, custom_event="Inward", operation=None,
        source_item=roll.eff_item, target_item=item, source_batch=roll.eff_batch, target_batch=batch_no,
        source_warehouse=roll.eff_warehouse, target_warehouse=warehouse,
        qty=w, custom_weight_before=flt(roll.eff_weight), custom_weight_after=w,
        custom_process_loss=flt(flt(roll.eff_weight) - w, 3) if not doc.get("roll_tracking_entries") else 0,
        custom_roll_status=ST_IN_STOCK, document_type="Batch", document_name=batch_no, remarks=ADOPT_REMARK,
    )
    recompute_current(doc)
    save_roll(doc)
    frappe.db.commit()
    return {"roll_no": roll_no, "weight": w}


@frappe.whitelist()
def unadopt_stock_roll(batch_no, roll_no):
    assert_role("Production Supervisor")
    roll_no = parse_scan(roll_no)
    _assert_last_row(roll_no, batch_no)
    remove_history_for(roll_no, batch_no)
    frappe.db.commit()
    return {"success": True}
