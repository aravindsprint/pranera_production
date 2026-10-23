"""Fabric and Collar/Cuff inspection on an INSPECTION Job Card.

Replaces QI Report Details / QI CC Report Details (decided with the user):
  * lot-level checks (WPI/CPI, shade, samples, stretch, approval …) are
    custom fields on the Inspection Job Card;
  * each roll's result is a Roll Inspection record (4-point mistakes,
    width / GSM / length, points %, grade) — one per roll per Job Card,
    saving again updates the same record, so an offline retry is safe;
  * the roll keeps its GREIGE roll number all the way to billing — no new
    finish roll numbers are generated any more;
  * the grade-wise summary on the Job Card is recomputed on every save.

Formulas are ported from the Ionic inspection app:
  width_cm   = width_inch × 2.54
  g_per_mtr  = width_cm / 100 × GSM
  length_mtr = roll_weight / g_per_mtr × 1000
  area_sqm   = length_mtr × width_cm / 100
  points %   = total_points / area_sqm × 100            (fabric)
  points %   = rejected_pcs / total_pcs × 100           (collar / cuff,
                                                          rejected = points)
  grade      = 3 if points % > grade_3 (100) or a "force grade 3" mistake
               2 if points % ≥ grade_2 (40)
               Direct if marked direct, else 1
"""
import frappe
from frappe import _
from frappe.utils import flt, cint, today

from pranera_production.api.common import (
    settings, get_roll, parse_scan, is_pcs, is_inspection_operation, assert_role,
)
from pranera_production.roll_tracking import ST_IN_PROCESS

LOT_FIELDS = [
    "custom_fabric_required_width", "custom_fabric_required_gsm", "custom_wpi", "custom_wpi_actual",
    "custom_cpi", "custom_cpi_actual", "custom_approved_sample_checked", "custom_gold_seal_sample_checked",
    "custom_shade", "custom_within_roll_shade_variation", "custom_roll_to_roll_shade_variation",
    "custom_csv", "custom_hand_feel", "custom_length_stretch", "custom_width_stretch", "custom_design",
    "custom_testing", "custom_inspect_approval",
]

ROLL_INSPECTION_INPUT = [
    "inspection_type", "roll_weight", "width", "gsm", "wpi_actual", "cpi_actual", "total_qty",
    "direct", "grade_override", "machine_no", "dyeing_machine", "dyeing_chamber_no", "sample", "scrap",
    "approved_sample_checked", "gold_seal_sample_checked", "shade_checked", "wicking", "crow_feet",
    "patta_problem", "vertical_line", "rope_mark", "knurling", "mild_snagging", "remarks",
]

DEFECT_FLAGS = ["vertical_line", "rope_mark", "knurling", "mild_snagging", "crow_feet", "patta_problem"]


# ── Calculation (called from Roll Inspection.validate) ──────────────────────

def compute_roll_inspection(doc):
    mistakes = {m.name: m for m in frappe.get_all(
        "Inspection Mistake", fields=["name", "one_point", "two_point", "four_point", "force_grade_3"])}
    total, force3 = 0, False
    keep = []
    for row in doc.get("mistakes") or []:
        m = mistakes.get(row.mistake) or frappe._dict(one_point=1, two_point=2, four_point=4, force_grade_3=0)
        row.total_points = (cint(row.one_qty) * cint(m.one_point or 1)
                            + cint(row.two_qty) * cint(m.two_point or 2)
                            + cint(row.four_qty) * cint(m.four_point or 4)
                            + cint(row.custom_points) * 4)
        if row.total_points <= 0:
            continue
        keep.append(row)
        total += row.total_points
        if m.force_grade_3:
            force3 = True
    for i, row in enumerate(keep, 1):
        row.idx = i
    doc.set("mistakes", keep)
    doc.total_points = total

    if doc.inspection_type == "Collar Cuff":
        doc.rejected_qty = cint(total)
        doc.accepted_qty = max(0, cint(doc.total_qty) - cint(total))
        doc.point_percentage = flt(total / cint(doc.total_qty) * 100, 2) if cint(doc.total_qty) else 0
        doc.length_mtr = doc.total_mtr = 0
    else:
        width_cm = flt(doc.width) * 2.54
        g_per_mtr = width_cm / 100.0 * flt(doc.gsm)
        if g_per_mtr > 0 and flt(doc.roll_weight) > 0:
            doc.length_mtr = flt(flt(doc.roll_weight) / g_per_mtr * 1000, 2)
            doc.total_mtr = flt(doc.length_mtr * width_cm / 100.0, 2)
        else:
            doc.length_mtr = doc.total_mtr = 0
        doc.point_percentage = flt(total / doc.total_mtr * 100, 2) if flt(doc.total_mtr) else 0

    s = settings()
    g3, g2 = flt(s.grade_3_min_points) or 100, flt(s.grade_2_min_points) or 40
    if force3 or flt(doc.point_percentage) > g3:
        grade = "3"
    elif flt(doc.point_percentage) >= g2:
        grade = "2"
    else:
        grade = "Direct" if cint(doc.direct) else "1"
    doc.grade = doc.grade_override or grade


def after_roll_inspection_saved(doc):
    _refresh_roll(doc.roll)
    recompute_job_card_summary(doc.job_card)


def after_roll_inspection_deleted(doc):
    frappe.flags.deleting_roll_inspection = doc.name
    _refresh_roll(doc.roll, exclude=doc.name)
    recompute_job_card_summary(doc.job_card, exclude=doc.name)


def _refresh_roll(roll_no, exclude=None):
    filters = {"roll": roll_no}
    if exclude:
        filters["name"] = ["!=", exclude]
    last = frappe.get_all("Roll Inspection", filters=filters,
                          fields=["name", "grade", "total_points"],
                          order_by="inspected_on desc, creation desc", limit=1)
    last = last[0] if last else frappe._dict()
    frappe.db.set_value("Roll", roll_no, {
        "current_grade": last.get("grade"),
        "current_total_points": last.get("total_points") or 0,
        "last_roll_inspection": last.get("name"),
    }, update_modified=False)


def recompute_job_card_summary(job_card, exclude=None):
    if not job_card:
        return
    filters = {"job_card": job_card}
    if exclude:
        filters["name"] = ["!=", exclude]
    rows = frappe.get_all(
        "Roll Inspection", filters=filters,
        fields=["roll", "grade", "roll_weight", "total_qty", "total_points", "point_percentage"] + DEFECT_FLAGS,
        order_by="inspected_on desc, creation desc",
    )
    latest = {}
    for r in rows:
        latest.setdefault(r.roll, r)
    rows = list(latest.values())
    total_w = sum(flt(r.roll_weight) for r in rows)
    buckets = {}
    for r in rows:
        g = r.grade or "1"
        b = buckets.setdefault(g, {"grade": g, "no_of_rolls": 0, "weight": 0.0, "qty_pcs": 0,
                                   **{f: 0 for f in DEFECT_FLAGS}})
        b["no_of_rolls"] += 1
        b["weight"] += flt(r.roll_weight)
        b["qty_pcs"] += cint(r.total_qty)
        for f in DEFECT_FLAGS:
            if (r.get(f) or "-") not in ("-", ""):
                b[f] += 1
    frappe.db.delete("Inspection Grade Summary", {"parent": job_card, "parenttype": "Job Card"})
    for i, g in enumerate(["1", "2", "3", "Direct"], 1):
        b = buckets.get(g)
        if not b:
            continue
        b["weight"] = flt(b["weight"], 3)
        b["percentage"] = flt(b["weight"] / total_w * 100, 2) if total_w else 0
        child = frappe.new_doc("Inspection Grade Summary")
        child.update({**b, "parent": job_card, "parenttype": "Job Card",
                      "parentfield": "custom_inspection_grade_summary", "idx": i})
        child.db_insert()
    frappe.db.set_value("Job Card", job_card, {
        "custom_inspected_rolls": len(rows),
        "custom_inspected_weight": flt(total_w, 3),
        "custom_inspection_total_points": sum(flt(r.total_points) for r in rows),
        "custom_avg_points_percentage": flt(sum(flt(r.point_percentage) for r in rows) / len(rows), 2) if rows else 0,
    }, update_modified=False)


# ── Screens ─────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_inspection_job_cards(txt=None, include_completed=0):
    op = settings().inspection_operation or "INSPECTION"
    filters = [["Job Card", "operation", "=", op], ["Job Card", "docstatus", "<", 2]]
    if not cint(include_completed):
        filters.append(["Job Card", "status", "not in", ["Completed", "Cancelled"]])
    or_filters = None
    if txt:
        or_filters = [["Job Card", "name", "like", f"%{txt}%"], ["Job Card", "work_order", "like", f"%{txt}%"],
                      ["Job Card", "production_item", "like", f"%{txt}%"]]
    rows = frappe.get_all(
        "Job Card", filters=filters, or_filters=or_filters,
        fields=["name", "work_order", "workstation", "status", "docstatus", "production_item", "item_name",
                "for_quantity", "color", "custom_inspected_rolls", "custom_inspected_weight", "modified"],
        order_by="modified desc", limit=100,
    )
    for r in rows:
        r.rolls_in_process = frappe.db.count("Roll", {"current_work_order": r.work_order,
                                                      "current_status": ST_IN_PROCESS})
    return rows


@frappe.whitelist()
def get_inspection_context(job_card):
    jc = frappe.get_doc("Job Card", job_card)
    if not is_inspection_operation(jc.operation):
        frappe.throw(_("Job Card {0} is not an inspection operation ({1})").format(job_card, jc.operation))
    wo = frappe.db.get_value("Work Order", jc.work_order,
                             ["name", "production_item", "item_name", "qty", "project", "color", "width",
                              "required_gsm", "commercial_name", "stock_uom"], as_dict=True)
    rolls = frappe.get_all(
        "Roll", filters={"current_work_order": jc.work_order, "current_status": ST_IN_PROCESS},
        fields=["name", "current_item", "current_batch", "current_weight", "roll_weight", "total_qty",
                "stock_uom", "current_process", "knitting_machine_no"],
        order_by="name asc", limit=3000,
    )
    insp = {}
    for r in frappe.get_all("Roll Inspection", filters={"job_card": job_card},
                            fields=["name", "roll", "grade", "roll_weight", "total_points", "point_percentage",
                                    "inspected_on", "checker_name"],
                            order_by="inspected_on desc, creation desc"):
        insp.setdefault(r.roll, r)
    for r in rolls:
        r.inspection = insp.get(r.name)
        r.at_inspection = is_inspection_operation(r.current_process)
    is_cc = is_pcs(wo.stock_uom if wo else None)
    return {
        "job_card": {"name": jc.name, "status": jc.status, "docstatus": jc.docstatus,
                     "work_order": jc.work_order, "workstation": jc.workstation,
                     "for_quantity": jc.for_quantity,
                     "lot": {f: jc.get(f) for f in LOT_FIELDS},
                     "summary": {
                         "rolls": jc.get("custom_inspected_rolls"), "weight": jc.get("custom_inspected_weight"),
                         "total_points": jc.get("custom_inspection_total_points"),
                         "avg_points_percentage": jc.get("custom_avg_points_percentage"),
                         "grades": [g.as_dict() for g in (jc.get("custom_inspection_grade_summary") or [])],
                     }},
        "work_order": wo,
        "inspection_type": "Collar Cuff" if is_cc else "Fabric",
        "rolls": rolls,
        "mistakes": get_mistakes("Collar Cuff" if is_cc else "Fabric"),
    }


@frappe.whitelist()
def get_mistakes(inspection_type="Fabric"):
    return frappe.get_all(
        "Inspection Mistake",
        filters={"disabled": 0, "applies_to": ["in", ["Both", inspection_type]]},
        fields=["name", "one_point", "two_point", "four_point", "force_grade_3", "sequence",
                "show_on_board", "board", "column_no", "tile_point", "tile_color", "tile_height"],
        order_by="sequence asc, name asc",
    )


@frappe.whitelist()
def save_lot_checks(job_card, values):
    assert_role("Inspection Checker")
    values = frappe.parse_json(values) if isinstance(values, str) else (values or {})
    clean = {k: v for k, v in values.items() if k in LOT_FIELDS}
    if clean:
        frappe.db.set_value("Job Card", job_card, clean)
    frappe.db.commit()
    return {"success": True}


@frappe.whitelist()
def get_roll_for_inspection(job_card, roll_no):
    jc = frappe.db.get_value("Job Card", job_card, ["work_order", "operation"], as_dict=True)
    roll_no = parse_scan(roll_no)
    roll = get_roll(roll_no)
    if roll.current_work_order != jc.work_order or roll.current_status != ST_IN_PROCESS:
        frappe.throw(_("Roll {0} is not in process for Work Order {1} (it is at {2})").format(
            roll_no, jc.work_order, roll.current_work_order or roll.eff_warehouse or "-"))
    existing = frappe.db.get_value("Roll Inspection", {"roll": roll_no, "job_card": job_card}, "name")
    wo = frappe.db.get_value("Work Order", jc.work_order, ["required_gsm", "stock_uom"], as_dict=True) or {}
    data = {
        "roll_no": roll.name, "item_code": roll.eff_item, "batch_no": roll.eff_batch,
        "stock_uom": roll.uom, "roll_weight": roll.eff_weight, "total_qty": cint(roll.total_qty),
        "knitting_machine_no": roll.knitting_machine_no, "current_process": roll.current_process,
        "at_inspection": is_inspection_operation(roll.current_process),
        "inspection_type": "Collar Cuff" if is_pcs(roll.uom) else "Fabric",
        "default_gsm": wo.get("required_gsm"),
        "existing": None,
    }
    if existing:
        d = frappe.get_doc("Roll Inspection", existing)
        data["existing"] = d.as_dict()
    return data


@frappe.whitelist()
def save_roll_inspection(job_card, roll_no, data):
    """Create or update the Roll Inspection for (roll, job card).
    Idempotent: the offline queue may replay this safely."""
    assert_role("Inspection Checker")
    data = frappe.parse_json(data) if isinstance(data, str) else (data or {})
    jc = frappe.db.get_value("Job Card", job_card, ["work_order", "operation", "project"], as_dict=True)
    if not jc:
        frappe.throw(_("Job Card {0} not found").format(job_card))
    if not is_inspection_operation(jc.operation):
        frappe.throw(_("Job Card {0} is not an inspection operation").format(job_card))
    roll_no = parse_scan(roll_no)
    roll = get_roll(roll_no)
    if roll.current_work_order != jc.work_order:
        frappe.throw(_("Roll {0} is not in process for Work Order {1}").format(roll_no, jc.work_order))

    name = frappe.db.get_value("Roll Inspection", {"roll": roll_no, "job_card": job_card}, "name")
    doc = frappe.get_doc("Roll Inspection", name) if name else frappe.new_doc("Roll Inspection")
    doc.roll = roll_no
    doc.job_card = job_card
    doc.work_order = jc.work_order
    doc.project = roll.project or jc.project
    doc.item_code = roll.eff_item
    doc.batch_no = roll.eff_batch
    doc.stock_uom = roll.uom
    doc.knitting_machine_no = roll.knitting_machine_no
    if not doc.checker:
        doc.checker = frappe.session.user
    if data.get("inspected_on"):
        doc.inspected_on = data.get("inspected_on")
    for f in ROLL_INSPECTION_INPUT:
        if f in data:
            doc.set(f, data.get(f))
    if not doc.inspection_type:
        doc.inspection_type = "Collar Cuff" if is_pcs(roll.uom) else "Fabric"
    doc.set("mistakes", [])
    for m in data.get("mistakes") or []:
        if not m.get("mistake"):
            continue
        doc.append("mistakes", {
            "mistake": m.get("mistake"), "one_qty": cint(m.get("one_qty")), "two_qty": cint(m.get("two_qty")),
            "four_qty": cint(m.get("four_qty")), "custom_points": cint(m.get("custom_points")),
        })
    doc.flags.ignore_permissions = True
    doc.save()
    frappe.db.commit()
    return {
        "name": doc.name, "grade": doc.grade, "total_points": doc.total_points,
        "point_percentage": doc.point_percentage, "length_mtr": doc.length_mtr, "total_mtr": doc.total_mtr,
        "accepted_qty": doc.accepted_qty, "rejected_qty": doc.rejected_qty,
    }


@frappe.whitelist()
def delete_roll_inspection(name):
    assert_role("Inspection Checker")
    frappe.delete_doc("Roll Inspection", name, ignore_permissions=True)
    frappe.db.commit()
    return {"success": True}


@frappe.whitelist()
def mark_inspection_complete(job_card):
    assert_role("Inspection Checker")
    frappe.db.set_value("Job Card", job_card, "custom_inspection_completed_on", today())
    frappe.db.commit()
    return {"success": True}
