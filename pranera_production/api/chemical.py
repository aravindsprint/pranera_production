"""Dyes & Chemicals issue from Chemical Stores → MTM against the Job Card.

The quantity to issue comes from the Dye Chart linked to the Job Card
(Job Card.custom_dye_chart, or a Dye Chart whose jobcard is this Job Card).
Issued = every submitted MTM row of that item against this Job Card, so an
older combined fabric + chemical MTM still counts. Batches are allocated
FIFO (oldest batch first) from the selected store warehouse.

This is a separate MTM from the fabric pick (decided with the user), so the
lot section and the chemical store can issue independently.
"""
import frappe
from frappe import _
from frappe.utils import flt, cint, today

from pranera_production.api.common import (
    settings, floor3, stock_entry_base, job_card_item_map, assert_role,
)
from pranera_production.roll_tracking import ENTRY_CHEMICAL


def _dye_chart_for(job_card, jc_dye_chart=None):
    if jc_dye_chart and frappe.db.exists("Dye Chart", jc_dye_chart):
        return jc_dye_chart
    names = frappe.get_all(
        "Dye Chart", filters={"jobcard": job_card, "docstatus": ["<", 2]},
        pluck="name", order_by="docstatus desc, creation desc", limit=1,
    )
    return names[0] if names else None


def _issued_by_item(job_card):
    rows = frappe.db.sql(
        """select d.item_code, sum(d.transfer_qty) qty
           from `tabStock Entry Detail` d join `tabStock Entry` se on se.name = d.parent
           where se.job_card = %s and se.docstatus = 1
             and se.purpose = 'Material Transfer for Manufacture'
           group by d.item_code""",
        job_card, as_dict=True,
    )
    return {r.item_code: flt(r.qty) for r in rows}


def _batch_stock(item_code, warehouse):
    """[(batch_no or None, qty)] oldest first."""
    has_batch = frappe.db.get_value("Item", item_code, "has_batch_no")
    if not has_batch:
        qty = flt(frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty"))
        return [(None, qty)] if qty > 0 else []
    from erpnext.stock.doctype.batch.batch import get_batch_qty
    rows = get_batch_qty(warehouse=warehouse, item_code=item_code) or []
    out = []
    for r in rows:
        if flt(r.get("qty")) <= 0:
            continue
        b = r.get("batch_no")
        created = frappe.db.get_value("Batch", b, ["manufacturing_date", "creation"], as_dict=True) or {}
        out.append((b, flt(r.get("qty")), created.get("manufacturing_date") or created.get("creation")))
    out.sort(key=lambda x: (str(x[2] or ""), x[0] or ""))
    return [(b, q) for b, q, _d in out]


@frappe.whitelist()
def get_chemical_job_cards(txt=None):
    """Open Job Cards that have a Dye Chart — the chemical store's queue."""
    cond = ""
    params = {}
    if txt:
        cond = "and (jc.name like %(txt)s or jc.work_order like %(txt)s or jc.production_item like %(txt)s)"
        params["txt"] = f"%{txt}%"
    rows = frappe.db.sql(
        f"""
        select * from (
            select jc.name, jc.work_order, jc.operation, jc.workstation, jc.status, jc.docstatus,
                   jc.production_item, jc.for_quantity, jc.color, jc.modified,
                   coalesce(nullif(jc.custom_dye_chart,''),
                            (select dc.name from `tabDye Chart` dc where dc.jobcard = jc.name and dc.docstatus < 2
                             order by dc.docstatus desc, dc.creation desc limit 1)) as dye_chart
            from `tabJob Card` jc
            where jc.docstatus < 2 and jc.status not in ('Completed', 'Cancelled')
              {cond}
        ) t
        where t.dye_chart is not null
        order by t.modified desc
        limit 100
        """,
        params, as_dict=True,
    )
    return rows


@frappe.whitelist()
def get_chemical_issue_context(job_card, source_warehouse=None):
    jc = frappe.db.get_value(
        "Job Card", job_card,
        ["name", "work_order", "operation", "workstation", "status", "docstatus", "for_quantity",
         "production_item", "custom_dye_chart", "wip_warehouse", "company"],
        as_dict=True,
    )
    if not jc:
        frappe.throw(_("Job Card {0} not found").format(job_card))
    dye_chart = _dye_chart_for(job_card, jc.custom_dye_chart)
    wo = frappe.db.get_value("Work Order", jc.work_order,
                             ["wip_warehouse", "project", "qty", "production_item"], as_dict=True)
    source_warehouse = source_warehouse or settings().chemical_store_warehouse
    items = []
    lot_weight = None
    if dye_chart:
        lot_weight = frappe.db.get_value("Dye Chart", dye_chart, "lot_weight")
        dc_rows = frappe.get_all(
            "Dye Chart Item", filters={"parent": dye_chart, "parenttype": "Dye Chart"},
            fields=["item", "total", "stock_uom", "chemicals", "bath_no", "dosage", "uom"],
            order_by="idx asc",
        )
        issued = _issued_by_item(job_card)
        by_item = {}
        for r in dc_rows:
            if not r.item:
                continue
            it = by_item.setdefault(r.item, {
                "item_code": r.item,
                "item_name": frappe.db.get_value("Item", r.item, "item_name"),
                "stock_uom": r.stock_uom or frappe.db.get_value("Item", r.item, "stock_uom"),
                "required_qty": 0.0, "baths": [],
            })
            it["required_qty"] += flt(r.total)
            it["baths"].append({"bath_no": r.bath_no, "chemicals": r.chemicals,
                                "dosage": r.dosage, "uom": r.uom, "total": r.total})
        for it in by_item.values():
            it["required_qty"] = flt(it["required_qty"], 3)
            it["issued_qty"] = flt(issued.get(it["item_code"]), 3)
            it["pending_qty"] = max(0.0, floor3(it["required_qty"] - it["issued_qty"]))
            it["available_qty"] = 0.0
            it["batches"] = []
            if source_warehouse:
                stock = _batch_stock(it["item_code"], source_warehouse)
                it["available_qty"] = flt(sum(q for _b, q in stock), 3)
                it["batches"] = [{"batch_no": b, "qty": flt(q, 3)} for b, q in stock[:5]]
            items.append(it)
    return {
        "job_card": jc,
        "work_order": jc.work_order,
        "wip_warehouse": (wo or {}).get("wip_warehouse") or jc.wip_warehouse,
        "dye_chart": dye_chart,
        "lot_weight": lot_weight,
        "source_warehouse": source_warehouse,
        "items": items,
        "issues": frappe.get_all(
            "Stock Entry",
            filters={"job_card": job_card, "custom_production_entry_type": ENTRY_CHEMICAL, "docstatus": ["<", 2]},
            fields=["name", "posting_date", "docstatus", "owner"], order_by="creation desc",
        ),
    }


@frappe.whitelist()
def issue_chemicals(job_card, source_warehouse, items, posting_date=None, submit_stock_entry=1):
    assert_role("Chemical Issuer")
    items = frappe.parse_json(items) if isinstance(items, str) else items
    items = [i for i in (items or []) if flt(i.get("qty")) > 0]
    if not items:
        frappe.throw(_("Enter a quantity for at least one item"))
    if not source_warehouse:
        frappe.throw(_("Select the Chemical Store warehouse"))

    ctx = get_chemical_issue_context(job_card, source_warehouse)
    jc = ctx["job_card"]
    pending = {i["item_code"]: i["pending_qty"] for i in ctx["items"]}
    is_supervisor = bool({"Production Supervisor", "System Manager"} & set(frappe.get_roles()))

    se = stock_entry_base("Material Transfer for Manufacture", settings().mtm_naming_series,
                          jc.company or frappe.db.get_value("Warehouse", source_warehouse, "company"),
                          posting_date or today())
    se.work_order = jc.work_order
    se.job_card = job_card
    se.custom_job_card = job_card
    se.project = frappe.db.get_value("Work Order", jc.work_order, "project")
    se.from_warehouse = source_warehouse
    se.to_warehouse = ctx["wip_warehouse"]
    se.fg_completed_qty = 0  # chemicals don't add to the lot quantity
    se.custom_production_entry_type = ENTRY_CHEMICAL
    se.custom_dye_chart = ctx["dye_chart"]
    jci = job_card_item_map(job_card)

    for it in items:
        code = it.get("item_code")
        qty = floor3(it.get("qty"))
        if code not in pending and not is_supervisor:
            frappe.throw(_("{0} is not on Dye Chart {1}").format(code, ctx["dye_chart"]))
        if code in pending and qty > pending[code] + 0.0005 and not is_supervisor:
            frappe.throw(_("{0}: issuing {1} is more than the pending {2} — ask a Production "
                           "Supervisor to issue extra").format(code, qty, pending[code]))
        uom = frappe.db.get_value("Item", code, "stock_uom")
        remaining = qty
        for batch_no, avail in _batch_stock(code, source_warehouse):
            if remaining <= 0:
                break
            take = floor3(min(avail, remaining))
            if take <= 0:
                continue
            row = {
                "s_warehouse": source_warehouse, "t_warehouse": ctx["wip_warehouse"],
                "item_code": code, "qty": take, "transfer_qty": take,
                "uom": uom, "stock_uom": uom, "conversion_factor": 1,
                "job_card_item": jci.get(code),
            }
            if batch_no:
                row.update({"batch_no": batch_no, "use_serial_batch_fields": 1})
            se.append("items", row)
            remaining = flt(remaining - take, 3)
        if remaining > 0.0005:
            frappe.throw(_("Not enough stock of {0} in {1}: short by {2}").format(code, source_warehouse, remaining))

    se.flags.ignore_permissions = True
    se.insert()
    if cint(submit_stock_entry):
        se.submit()
    frappe.db.commit()
    return {"stock_entry": se.name, "submitted": bool(cint(submit_stock_entry))}
