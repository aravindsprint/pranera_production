"""Roll creation APIs the Create Rolls and Rolls pages use.

These were Server Scripts on erp.pranera.in (knit_get_po_items,
knit_get_so_items, knit_create_po_so_roll, knit_create_roll,
knit_save_roll_data, knit_delete_roll), shared with the Knit app. A site
without those scripts — or with server scripts disabled, as on most local
benches — gave the pages nothing (e.g. "No matches" for an order's items).
Same logic, now shipped with this app.
"""
import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime, today


def _next_roll_no():
    result = frappe.db.sql("""
        SELECT MAX(CAST(name AS UNSIGNED)) as max_no
        FROM `tabRoll`
        WHERE name REGEXP '^[0-9]+$'
    """, as_dict=True)
    max_no = int(result[0].max_no or 0)
    next_no = str(max_no + 1)
    while frappe.db.exists("Roll", next_no):
        max_no += 1
        next_no = str(max_no + 1)
    return next_no


def _with_item_details(rows):
    for r in rows:
        item = frappe.db.get_value("Item", r.item_code, ["commercial_name", "color", "width", "stock_uom"],
                                   as_dict=True) or {}
        r.update(item)
    return rows


@frappe.whitelist()
def get_po_items(purchase_order=None):
    if not purchase_order:
        frappe.throw(_("purchase_order is required"))
    return _with_item_details(frappe.db.sql("""
        SELECT poi.item_code, poi.item_name, poi.material_request as project, poi.warehouse
        FROM `tabPurchase Order Item` poi
        WHERE poi.parent = %s
        ORDER BY poi.idx asc
    """, (purchase_order,), as_dict=True))


@frappe.whitelist()
def get_so_items(subcontracting_order=None):
    if not subcontracting_order:
        frappe.throw(_("subcontracting_order is required"))
    return _with_item_details(frappe.db.sql("""
        SELECT soi.item_code, soi.item_name, soi.project as project, soi.warehouse
        FROM `tabSubcontracting Order Item` soi
        WHERE soi.parent = %s
        ORDER BY soi.idx asc
    """, (subcontracting_order,), as_dict=True))


@frappe.whitelist()
def create_po_so_roll(**kw):
    fd = frappe._dict(kw)
    if not fd.item_code:
        frappe.throw(_("item_code is required"))
    if not fd.purchase_order and not fd.subcontracting_order:
        frappe.throw(_("purchase_order or subcontracting_order is required"))
    roll = frappe.new_doc("Roll")
    roll.roll_no = _next_roll_no()
    roll.purchase_order = fd.purchase_order or ""
    roll.subcontracting_order = fd.subcontracting_order or ""
    roll.item_code = fd.item_code
    roll.item_name = fd.item_name or ""
    roll.commercial_name = fd.commercial_name or ""
    roll.color = fd.color or ""
    roll.width = fd.width or ""
    roll.actual_width = fd.actual_width or ""
    roll.project = fd.project or ""
    roll.stock_uom = fd.stock_uom or ""
    roll.batch = fd.batch or ""
    roll.roll_weight = fd.roll_weight or 0
    roll.total_qty = fd.total_qty or 0
    roll.mistake_qty = fd.mistake_qty or 0
    roll.correct_qty = fd.ok_qty or 0
    roll.avg_weight_per_pcs = fd.avg_weight_per_pcs or 0
    roll.name_of_the_operator = frappe.session.user
    roll.datetime = now_datetime()
    roll.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"name": roll.name, "roll_no": roll.roll_no}


@frappe.whitelist()
def create_roll(job_card=None, batch_no=None):
    if not job_card:
        frappe.throw(_("job_card is required"))
    jc = frappe.get_doc("Job Card", job_card)
    roll = frappe.new_doc("Roll")
    roll.roll_no = _next_roll_no()
    roll.job_card = job_card
    roll.work_order = jc.work_order
    roll.item_code = jc.production_item
    roll.item_name = jc.item_name or ""
    roll.batch = batch_no or ""
    roll.start_time = now_datetime()
    roll.insert(ignore_permissions=True)
    frappe.db.commit()
    return [{"name": roll.name, "idx": roll.name, "start_time": str(roll.start_time), "batch_no": batch_no or ""}]


@frappe.whitelist()
def delete_roll(roll_name=None):
    if not roll_name:
        return {"success": False, "error": "roll_name is required"}
    roll = frappe.db.get_value("Roll", roll_name, ["name", "roll_weight", "docstatus"], as_dict=True)
    if not roll:
        return {"success": True, "deleted": roll_name, "note": "already gone"}
    if roll.docstatus == 1:
        return {"success": False, "error": "Cannot delete submitted roll"}
    if float(roll.roll_weight or 0) > 0:
        return {"success": False, "error": "Roll has weight, cannot delete"}
    frappe.delete_doc("Roll", roll_name, ignore_permissions=True, force=True)
    frappe.db.commit()
    return {"success": True, "deleted": roll_name}


def _blank(v):
    return not v or str(v) in ("null", "None", "")


def _parse_dt(val):
    if _blank(val):
        return None
    s = str(val).strip().replace("T", " ")
    for ch in ["Z", "+", "-"]:
        idx = s.rfind(ch)
        if ch in ["+", "-"] and idx > 10:
            s = s[:idx]
        elif ch == "Z":
            s = s.replace("Z", "")
    s = s.split(".")[0].strip()
    try:
        return get_datetime(s)
    except Exception:
        return None


@frappe.whitelist()
def save_roll_data(**kw):
    fd = frappe._dict(kw)
    if not fd.job_card:
        frappe.throw(_("job_card is required"))
    existing_name = None
    if fd.roll_no:
        try:
            rno = str(int(str(fd.roll_no)))
            if frappe.db.exists("Roll", rno):
                existing_name = rno
        except Exception:
            pass
    if existing_name:
        roll = frappe.get_doc("Roll", existing_name)
    else:
        roll = frappe.new_doc("Roll")
        roll.roll_no = _next_roll_no()
        roll.job_card = fd.job_card
        roll.work_order = fd.work_order

    roll.work_order = fd.work_order or roll.work_order
    roll.item_code = fd.item_code or ""
    roll.item_name = fd.item_name or ""
    roll.commercial_name = fd.commercial_name or ""
    roll.color = fd.color or ""
    roll.width = fd.width or ""
    roll.batch = fd.batch or ""
    roll.shift = fd.shift or ""
    roll.stock_uom = fd.stock_uom or "Kgs"
    roll.project = fd.project or ""
    roll.knitting_machine_no = fd.knitting_machine_no or ""
    roll.name_of_the_operator = fd.knit_operator_name or ""
    roll.knit_operator_name = fd.knit_operator_name or ""
    roll.roll_weight = 0.0 if _blank(fd.roll_weight) else float(fd.roll_weight)
    roll.total_qty = 0 if _blank(fd.total_qty) else int(float(fd.total_qty))
    roll.mistake_qty = 0 if _blank(fd.mistake_qty) else int(float(fd.mistake_qty))
    roll.correct_qty = roll.total_qty - roll.mistake_qty
    if roll.total_qty > 0:
        roll.avg_weight_per_pcs = roll.roll_weight / roll.total_qty

    st, et = _parse_dt(fd.start_time), _parse_dt(fd.end_time)
    existing_st = get_datetime(roll.start_time) if roll.get("start_time") else None
    if st and existing_st:
        roll.start_time = st if st < existing_st else existing_st
    elif st:
        roll.start_time = st
    roll.end_time = et or now_datetime()
    roll.datetime = today()

    def hms(secs):
        return f"{secs // 3600:02d}:{(secs % 3600) // 60:02d}:{secs % 60:02d}"
    roll.total_breakdown = hms(0 if _blank(fd.breakdown_time_seconds) else int(fd.breakdown_time_seconds))
    roll.net_production_time = hms(0 if _blank(fd.net_production_time_seconds) else int(fd.net_production_time_seconds))
    roll.efficiency = "0.0%" if _blank(fd.efficiency_percentage) else f"{fd.efficiency_percentage}%"

    try:
        roll.warehouse = frappe.db.get_value("Work Order", roll.work_order, "fg_warehouse") or ""
    except Exception:
        roll.warehouse = ""

    if roll.batch and not frappe.db.exists("Batch", roll.batch):
        try:
            b = frappe.new_doc("Batch")
            b.batch_id = roll.batch
            b.item = roll.item_code
            b.insert(ignore_permissions=True)
        except frappe.DuplicateEntryError:
            pass

    if existing_name:
        roll.save(ignore_permissions=True)
    else:
        roll.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"success": True, "name": roll.name}
