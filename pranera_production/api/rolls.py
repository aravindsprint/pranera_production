"""Roll lookup / trace — a roll's live state and full process history."""
import frappe
from frappe import _
from frappe.utils import cint

from pranera_production.api.common import get_roll, parse_scan


@frappe.whitelist()
def search_rolls(txt=None, status=None, process=None, work_order=None, warehouse=None, limit=100):
    filters = []
    if status:
        filters.append(["Roll", "current_status", "=", status])
    if process:
        filters.append(["Roll", "current_process", "=", process])
    if work_order:
        filters.append(["Roll", "current_work_order", "=", work_order])
    if warehouse:
        filters.append(["Roll", "current_warehouse", "=", warehouse])
    or_filters = None
    if txt:
        txt = parse_scan(txt)
        or_filters = [["Roll", "name", "like", f"{txt}%"], ["Roll", "current_batch", "like", f"%{txt}%"],
                      ["Roll", "batch", "like", f"%{txt}%"], ["Roll", "current_work_order", "like", f"%{txt}%"]]
    return frappe.get_all(
        "Roll", filters=filters, or_filters=or_filters,
        fields=["name", "item_code", "batch", "roll_weight", "stock_uom", "total_qty",
                "current_status", "current_process", "current_item", "current_batch", "current_weight",
                "current_warehouse", "current_work_order", "current_grade", "current_process_loss", "modified"],
        order_by="modified desc", limit=cint(limit) or 100,
    )


@frappe.whitelist()
def get_roll_trace(roll_no):
    roll_no = parse_scan(roll_no)
    r = get_roll(roll_no)
    doc = frappe.get_doc("Roll", r.name)
    history = [
        {
            "idx": h.idx, "date": h.date, "datetime": h.get("custom_posting_datetime"),
            "event": h.get("custom_event"), "operation": h.operation,
            "work_order": h.get("custom_work_order"), "job_card": h.get("custom_job_card"),
            "source_item": h.source_item, "target_item": h.target_item,
            "source_batch": h.source_batch, "target_batch": h.target_batch,
            "source_warehouse": h.source_warehouse, "target_warehouse": h.target_warehouse,
            "weight_before": h.get("custom_weight_before"), "weight_after": h.get("custom_weight_after"),
            "process_loss": h.get("custom_process_loss"), "status": h.get("custom_roll_status"),
            "document_type": h.document_type, "document_name": h.document_name, "remarks": h.remarks,
        }
        for h in sorted(doc.get("roll_tracking_entries") or [], key=lambda x: x.idx)
    ]
    inspections = frappe.get_all(
        "Roll Inspection", filters={"roll": r.name},
        fields=["name", "job_card", "work_order", "inspection_type", "grade", "roll_weight", "width", "gsm",
                "total_points", "point_percentage", "checker_name", "inspected_on"],
        order_by="inspected_on desc",
    )
    for i in inspections:
        i.mistakes = frappe.get_all("Roll Inspection Mistake", filters={"parent": i.name},
                                    fields=["mistake", "total_points"], order_by="idx")
    packing = frappe.db.sql(
        """select p.name, p.posting_date, p.stock_entry, p.transaction_type, i.batch, i.roll_weight
           from `tabRoll Packing List Item` i join `tabRoll Packing List` p on p.name = i.parent
           where i.roll_no=%s and p.docstatus=1 order by p.creation""", r.name, as_dict=True,
    )
    cuts = frappe.get_all("Roll", filters={"name": ["like", f"{r.name}-%"]},
                          fields=["name", "roll_weight", "current_weight", "current_status"], order_by="name")
    return {
        "roll": {
            "name": r.name, "item_code": r.item_code, "item_name": r.item_name, "batch": r.batch,
            "roll_weight": r.roll_weight, "total_qty": r.total_qty, "stock_uom": r.uom,
            "project": r.project, "knitting_work_order": r.work_order, "knitting_job_card": r.job_card,
            "knitting_machine_no": r.knitting_machine_no, "purchase_order": r.purchase_order,
            "subcontracting_order": r.subcontracting_order,
            "current_status": r.current_status, "current_process": r.current_process,
            "current_item": r.eff_item, "current_batch": r.eff_batch, "current_weight": r.eff_weight,
            "current_warehouse": r.eff_warehouse, "current_work_order": r.current_work_order,
            "current_job_card": r.current_job_card, "current_process_loss": r.current_process_loss,
            "current_grade": r.current_grade, "current_total_points": r.current_total_points,
        },
        "history": history,
        "inspections": inspections,
        "packing_lists": packing,
        "cut_rolls": cuts,
    }


# ── Cut a roll (process-aware) ──────────────────────────────────────────────
# Same naming + behaviour as the knit_cut_roll Server Script used by the
# pranera_knit / pranera_roll Create Rolls page (<root>-<n>, never nested),
# but aware of a roll's processed state: for a roll that has already been
# through a process, the cut is taken from its CURRENT weight / pieces, and
# the new roll inherits the parent's process history so it carries the
# same current item / batch / warehouse / grade.

@frappe.whitelist()
def cut_roll(source_roll, qty, roll_weight=None, avg_weight_per_pcs=None,
             knit_machine_no=None, knit_shift_no=None):
    from frappe.utils import flt, now_datetime
    from pranera_production.roll_tracking import add_history, recompute_current, save_roll, ST_IN_PROCESS

    qty = flt(qty)
    if qty <= 0:
        frappe.throw(_("Qty must be greater than 0"))
    src = frappe.get_doc("Roll", source_roll)
    if src.get("current_status") == ST_IN_PROCESS:
        frappe.throw(_("Roll {0} is in process ({1}) — it can't be cut until it is manufactured").format(
            source_roll, src.get("current_process")))
    is_pcs = (src.stock_uom or "").strip().lower() == "pcs"
    processed = bool(src.get("roll_tracking_entries"))
    cur_weight = flt(src.get("current_weight")) if processed else flt(src.roll_weight)
    available = flt(src.total_qty) if is_pcs else cur_weight
    if qty > available + 0.0005:
        frappe.throw(_("Qty {0} exceeds available qty {1} on roll {2}").format(qty, available, source_roll))

    if is_pcs:
        cut_weight = flt(roll_weight)
        if cut_weight <= 0:
            frappe.throw(_("Roll Weight is required when cutting a Pcs roll"))
        if cut_weight > cur_weight + 0.0005:
            frappe.throw(_("Roll Weight {0} exceeds available weight {1}").format(cut_weight, cur_weight))
    else:
        cut_weight = qty

    root = source_roll.split("-")[0]
    max_suffix = 0
    for name in frappe.get_all("Roll", filters={"name": ["like", f"{root}-%"]}, pluck="name"):
        suffix = name[len(root) + 1:]
        if suffix.isdigit():
            max_suffix = max(max_suffix, int(suffix))
    next_no = f"{root}-{max_suffix + 1}"
    while frappe.db.exists("Roll", next_no):
        max_suffix += 1
        next_no = f"{root}-{max_suffix + 1}"

    # Original (greige) weight is split in the same proportion as the cut,
    # so knitting totals stay intact.
    ratio = (cut_weight / cur_weight) if cur_weight else 0
    greige_cut = flt(flt(src.roll_weight) * ratio, 3) if processed else cut_weight

    new = frappe.new_doc("Roll")
    for f in ("item_code", "item_name", "commercial_name", "color", "width", "actual_width", "stock_uom",
              "project", "batch", "work_order", "purchase_order", "subcontracting_order", "job_card",
              "warehouse", "knit_operator", "knit_operator_name", "knitting_machine_no", "shift"):
        if src.meta.has_field(f):
            new.set(f, src.get(f))
    new.roll_no = next_no
    new.name_of_the_operator = frappe.session.user
    if knit_machine_no:
        new.knitting_machine_no = knit_machine_no
    if knit_shift_no:
        new.shift = knit_shift_no
    new.datetime = now_datetime()
    new.roll_weight = greige_cut
    if is_pcs:
        new.total_qty = int(qty)
        if avg_weight_per_pcs:
            new.avg_weight_per_pcs = flt(avg_weight_per_pcs)
    new.current_grade = src.get("current_grade")
    new.current_total_points = src.get("current_total_points")
    new.last_roll_inspection = src.get("last_roll_inspection")
    if processed:
        for h in sorted(src.roll_tracking_entries, key=lambda x: x.idx):
            row = h.as_dict(no_default_fields=True)
            for k in ("name", "parent", "parentfield", "parenttype", "idx", "doctype"):
                row.pop(k, None)
            new.append("roll_tracking_entries", row)
        new.flags.name_set = True
        new.name = next_no
        add_history(
            new, custom_event="Cut", operation=src.current_process,
            source_item=src.current_item, target_item=src.current_item,
            source_batch=src.current_batch, target_batch=src.current_batch,
            source_warehouse=src.current_warehouse, target_warehouse=src.current_warehouse,
            qty=cut_weight, custom_weight_before=cur_weight, custom_weight_after=cut_weight,
            custom_process_loss=0, custom_work_order=src.current_work_order,
            custom_job_card=src.current_job_card, custom_roll_status=src.current_status,
            document_type="Roll", document_name=source_roll,
            remarks=_("Cut {0} from roll {1}").format(cut_weight, source_roll),
        )
        recompute_current(new)
        # recompute sums process loss over the copied rows too, which is right:
        # the cut piece went through the same processes.
    new.flags.ignore_permissions = True
    new.insert()
    for h in new.get("roll_tracking_entries") or []:
        h.db_set("roll_no", new.name, update_modified=False)

    remaining = flt(available - qty, 3)
    if processed:
        remaining_weight = flt(cur_weight - cut_weight, 3)
        add_history(
            src, custom_event="Cut", operation=src.current_process,
            source_item=src.current_item, target_item=src.current_item,
            source_batch=src.current_batch, target_batch=src.current_batch,
            source_warehouse=src.current_warehouse, target_warehouse=src.current_warehouse,
            qty=remaining_weight, custom_weight_before=cur_weight, custom_weight_after=remaining_weight,
            custom_process_loss=0, custom_work_order=src.current_work_order,
            custom_job_card=src.current_job_card, custom_roll_status=src.current_status,
            document_type="Roll", document_name=new.name,
            remarks=_("Cut {0} into roll {1}").format(cut_weight, new.name),
        )
        recompute_current(src)
        src.roll_weight = flt(flt(src.roll_weight) - greige_cut, 3)
        if is_pcs:
            src.total_qty = int(remaining)
        save_roll(src)
    else:
        if is_pcs:
            frappe.db.set_value("Roll", source_roll, {"total_qty": remaining,
                                                      "roll_weight": max(0.0, flt(src.roll_weight) - cut_weight)})
        else:
            frappe.db.set_value("Roll", source_roll, "roll_weight", remaining)
    frappe.db.commit()
    return {"name": new.name, "roll_no": new.roll_no, "remaining_qty": remaining, "source_roll": source_roll}


@frappe.whitelist()
def get_sticker_data(rolls=None, stock_entry=None):
    """What goes on a roll sticker, from the roll's CURRENT state — so a roll
    that has been dyed / finished prints its new item and batch, not the
    greige ones. Either a list of rolls, or every roll of a production MF
    (or any Stock Entry with a custom_production_rolls table)."""
    names = frappe.parse_json(rolls) if isinstance(rolls, str) else (rolls or [])
    if stock_entry:
        names = frappe.get_all("Production Stock Entry Roll",
                               filters={"parent": stock_entry, "parenttype": "Stock Entry"},
                               pluck="roll_no", order_by="idx asc")
    if not names:
        frappe.throw(_("No rolls to print"))
    out = []
    for name in names:
        r = get_roll(name, throw=False)
        if not r:
            continue
        wo = r.get("current_work_order") or r.get("work_order")
        item = r.eff_item
        out.append({
            "roll_no": r.name,
            "item_code": item,
            "commercial_name": frappe.db.get_value("Item", item, "commercial_name")
                if frappe.get_meta("Item").has_field("commercial_name") else "",
            "work_order": wo or "",
            "batch": r.eff_batch or "",
            "weight": r.eff_weight,
            "qty": cint(r.get("total_qty")) or None,
            "mistake_qty": cint(frappe.db.get_value("Roll", r.name, "mistake_qty")) or None
                if frappe.get_meta("Roll").has_field("mistake_qty") else None,
            "grade": r.get("current_grade") or "",
        })
    return out
