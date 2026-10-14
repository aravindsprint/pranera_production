"""Lot Inspection Report — port of the Ionic "Pivot" page (QI report pivot +
External / Internal PDF), now built from an INSPECTION Job Card and its
Roll Inspections instead of a QI Report Details document.

Layout (same as the Ionic PDF):
  header   Commercial Name, Report No, Item Code, No of Rolls, Batch No,
           Date, Fb Width & GSM, Description, Total Rolls Weight,
           DC Weight, Diff Weight, Avg Point In Lot
           + (internal only) Knitting / Dyeing / Stentering
  defects  mistake × roll matrix (points), 8 rolls per table, followed by
           Roll Weight, GSM, Width, Length Mtr, Point / 100 Per Sqm, Grade
           and the Patta / Crow Feet / Vertical Line / Rope Mark /
           Knurling / Mild Snagging flags
  summary  grade-wise rolls / weight / % (+ defect counts on internal)

Avg Point In Lot = total points × 3900 / (total sq mtr × avg width) — the
same formula the Ionic app used.
"""
import frappe
from frappe import _
from frappe.utils import flt, cint

from pranera_production.api.common import settings, is_pcs, get_row_batch

FLAGS = [("patta_problem", "Patta Problem"), ("crow_feet", "Crow Feet"), ("vertical_line", "Vertical Line"),
         ("rope_mark", "Rope Mark"), ("knurling", "Knurling"), ("mild_snagging", "Mild Snagging")]


@frappe.whitelist()
def search_inspection_job_cards(txt=None):
    op = settings().inspection_operation or "INSPECTION"
    or_filters = None
    if txt:
        or_filters = [["Job Card", "name", "like", f"%{txt}%"], ["Job Card", "work_order", "like", f"%{txt}%"],
                      ["Job Card", "production_item", "like", f"%{txt}%"]]
    return frappe.get_all(
        "Job Card",
        filters=[["Job Card", "operation", "=", op], ["Job Card", "docstatus", "<", 2],
                 ["Job Card", "custom_inspected_rolls", ">", 0]],
        or_filters=or_filters,
        fields=["name", "work_order", "production_item", "color", "status", "custom_inspected_rolls",
                "custom_inspected_weight", "modified"],
        order_by="modified desc", limit=50,
    )


def _workstations_by_operation(roll_names):
    """Workstations the rolls actually went through, from their process
    history (works across chained single-operation Work Orders)."""
    if not roll_names:
        return {}
    rows = frappe.db.sql(
        """select distinct h.operation, jc.workstation
           from `tabRoll Tracking Entries` h
           join `tabJob Card` jc on jc.name = h.custom_job_card
           where h.parenttype='Roll' and h.parent in %(rolls)s and ifnull(h.operation,'') != ''""",
        {"rolls": roll_names}, as_dict=True,
    )
    out = {}
    for r in rows:
        out.setdefault((r.operation or "").upper(), set()).add(r.workstation)
    return {k: ", ".join(sorted(v)) for k, v in out.items()}


def _knitting_source(roll_names):
    rows = frappe.get_all("Roll", filters={"name": ["in", roll_names]},
                          fields=["knitting_machine_no", "purchase_order", "subcontracting_order"])
    sources = set()
    for r in rows:
        if r.subcontracting_order:
            sources.add(frappe.db.get_value("Subcontracting Order", r.subcontracting_order, "supplier") or r.subcontracting_order)
        elif r.purchase_order:
            sources.add(frappe.db.get_value("Purchase Order", r.purchase_order, "supplier") or r.purchase_order)
        elif r.knitting_machine_no:
            sources.add("In-house")
    return ", ".join(sorted(sources))


def _finished_batch(work_order, production_item):
    for se in frappe.get_all("Stock Entry", filters={"work_order": work_order, "docstatus": 1, "purpose": "Manufacture"},
                             pluck="name", order_by="creation asc"):
        for row in frappe.get_all("Stock Entry Detail", filters={"parent": se, "is_finished_item": 1,
                                                                  "item_code": production_item},
                                  fields=["batch_no", "serial_and_batch_bundle"]):
            b = get_row_batch(row)
            if b:
                return b
    return None


@frappe.whitelist()
def get_lot_report(job_card):
    jc = frappe.get_doc("Job Card", job_card)
    wo = frappe.db.get_value(
        "Work Order", jc.work_order,
        ["name", "production_item", "item_name", "description", "commercial_name", "color", "width",
         "required_gsm", "stock_uom", "qty", "project"], as_dict=True,
    ) or frappe._dict()

    insp_rows = frappe.get_all(
        "Roll Inspection", filters={"job_card": job_card},
        fields=["name", "roll", "inspection_type", "roll_weight", "width", "gsm", "length_mtr", "total_mtr",
                "total_qty", "accepted_qty", "rejected_qty", "total_points", "point_percentage", "grade",
                "checker_name", "machine_no", "inspected_on", "batch_no"] + [f for f, _l in FLAGS],
        order_by="inspected_on desc, creation desc",
    )
    latest = {}
    for r in insp_rows:
        latest.setdefault(r.roll, r)

    def roll_sort_key(name):
        head = name.split("-")[0]
        return (cint(head) if head.isdigit() else 0, name)

    rolls = [latest[k] for k in sorted(latest, key=roll_sort_key)]
    if not rolls:
        frappe.throw(_("No rolls have been inspected on {0} yet").format(job_card))
    names = [r.name for r in rolls]

    mistakes = frappe.db.sql(
        """select parent, mistake, sum(total_points) pts from `tabRoll Inspection Mistake`
           where parent in %(p)s group by parent, mistake""", {"p": names}, as_dict=True,
    )
    by_insp = {}
    mistake_totals = {}
    for m in mistakes:
        by_insp.setdefault(m.parent, {})[m.mistake] = cint(m.pts)
        mistake_totals[m.mistake] = mistake_totals.get(m.mistake, 0) + cint(m.pts)

    is_cc = (rolls[0].inspection_type == "Collar Cuff") or is_pcs(wo.stock_uom)
    total_weight = sum(flt(r.roll_weight) for r in rolls)
    total_points = sum(flt(r.total_points) for r in rolls)
    total_mtrs = sum(flt(r.total_mtr) for r in rolls)
    avg_width = sum(flt(r.width) for r in rolls) / len(rolls)
    avg_point = (total_points * 3900 / (total_mtrs * avg_width)) if (total_mtrs and avg_width) else 0
    lot_weight = flt(jc.for_quantity)

    roll_names = [r.roll for r in rolls]
    ws = _workstations_by_operation(roll_names)

    def ws_for(word):
        return ", ".join(v for k, v in ws.items() if word in k)

    summary = []
    for g in ["1", "2", "3", "Direct"]:
        grp = [r for r in rolls if (r.grade or "1") == g]
        if not grp:
            continue
        w = sum(flt(r.roll_weight) for r in grp)
        row = {"grade": g, "no_of_rolls": len(grp), "weight": flt(w, 3),
               "qty_pcs": sum(cint(r.total_qty) for r in grp),
               "percentage": flt(w / total_weight * 100, 2) if total_weight else 0}
        for f, _l in FLAGS:
            row[f] = sum(1 for r in grp if (r.get(f) or "-") not in ("-", ""))
        summary.append(row)

    lot = {f: jc.get(f) for f in ("custom_fabric_required_width", "custom_fabric_required_gsm",
                                  "custom_wpi", "custom_wpi_actual", "custom_cpi", "custom_cpi_actual",
                                  "custom_inspect_approval")}
    dates = [r.inspected_on for r in rolls if r.inspected_on]
    return {
        "type": "Collar Cuff" if is_cc else "Fabric",
        "header": {
            "commercial_name": wo.commercial_name or wo.item_name,
            "report_no": jc.name,
            "work_order": jc.work_order,
            "item_code": wo.production_item,
            "no_of_rolls": len(rolls),
            "batch_no": _finished_batch(jc.work_order, wo.production_item) or rolls[0].batch_no,
            "date": str(jc.get("custom_inspection_completed_on") or (max(dates).date() if dates else "")),
            "fabric_required_width": lot["custom_fabric_required_width"] or wo.width,
            "fabric_required_gsm": lot["custom_fabric_required_gsm"] or wo.required_gsm,
            "description": frappe.utils.strip_html(wo.description or "") or wo.item_name,
            "color": wo.color,
            "total_rolls_weight": flt(total_weight, 3),
            "dc_weight": flt(lot_weight, 3),
            "diff_weight": flt(lot_weight - total_weight, 3),
            "avg_point_in_lot": flt(avg_point, 3),
            "total_points": total_points,
            "checker": ", ".join(sorted({r.checker_name for r in rolls if r.checker_name})),
            "knitting": _knitting_source(roll_names),
            "dyeing": ws_for("DYE") or ws_for("WASH"),
            "stentering": ws_for("STENT") or ws_for("HEAT"),
            "inspect_approval": lot["custom_inspect_approval"],
            "wpi": lot["custom_wpi"], "wpi_actual": lot["custom_wpi_actual"],
            "cpi": lot["custom_cpi"], "cpi_actual": lot["custom_cpi_actual"],
        },
        "rolls": [{
            "roll_no": r.roll, "inspection": r.name, "roll_weight": flt(r.roll_weight, 3), "gsm": r.gsm,
            "width": r.width, "length_mtr": r.length_mtr, "total_mtr": r.total_mtr,
            "total_qty": r.total_qty, "accepted_qty": r.accepted_qty, "rejected_qty": r.rejected_qty,
            "total_points": cint(r.total_points), "point_percentage": flt(r.point_percentage, 2),
            "grade": r.grade, "checker": r.checker_name,
            **{f: (r.get(f) or "-") for f, _l in FLAGS},
            "mistakes": by_insp.get(r.name, {}),
        } for r in rolls],
        "mistakes": [{"mistake": k, "total": v} for k, v in sorted(mistake_totals.items(), key=lambda x: (-x[1], x[0]))],
        "flags": [{"key": f, "label": l} for f, l in FLAGS],
        "summary": summary,
    }
