"""Fabric / Collar / Cuff picking from the lot section → MTM against a Job Card.

Reuses the same doctypes as pranera_knit's Pick Order flow (Roll Pick
Assignment → scanned_rolls → Roll Wise Pick List + Stock Entry), with
production rules instead of knitting rules:

  * pick_type is "To Work Order" and custom_job_card is set — that is how
    a production assignment is told apart from a knitting one.
  * The Stock Entry is a Material Transfer for Manufacture (MTM series)
    against the Work Order AND the Job Card, into the Work Order's WIP
    (workstation) warehouse — not a plain Material Transfer.
  * A roll is validated on its EFFECTIVE state (current_item /
    current_batch / current_weight, falling back to the original greige
    values), so a dyed roll sitting in the lot section is picked by its
    dyed item + batch + weight.
  * The roll's item must be one of the Work Order's required items, and a
    roll that is already In Process somewhere else cannot be picked.
"""
import re

import frappe
from frappe import _
from frappe.utils import flt, cint, now_datetime, today

from pranera_production.api.common import (
    settings, get_roll, parse_scan, is_pcs, stock_entry_base, job_card_item_map,
    wo_operations, job_card_for_operation, first_job_card, assert_role,
    effective_roll, ROLL_FIELDS,
)
from pranera_production.roll_tracking import ENTRY_ROLL_PICK, ST_IN_PROCESS



def _save_execution(doc):
    """Save the execution state (execution warehouses, scanned_rolls) of a
    SUBMITTED Roll Pick Assignment. On erp.pranera.in these fields are
    allow-on-submit; a site whose doctype doesn't mark them so would refuse
    with "Not allowed to change ... after submission". Only those fields are
    changed here, so skip that check explicitly."""
    doc.flags.ignore_validate_update_after_submit = True
    doc.save()


def _is_transit(doc, target_warehouse):
    return (doc.get("pick_type") == "To Work Order"
            and (target_warehouse or "").strip().lower().startswith("in transit"))


def _transfer_kind(doc, target_warehouse):
    """(Stock Entry purpose, naming series) for a pick.

    * To an "In Transit…" warehouse (sent out to a dyeing unit): a plain
      Material Transfer, series MT/26/. Not against the Work Order / Job Card;
      the rolls stay In Stock in the transit warehouse and are picked again
      (MTM) when they reach the WIP.
    * Otherwise: Material Transfer for Manufacture against the Job Card,
      series MTM/26/."""
    s = settings()
    if _is_transit(doc, target_warehouse):
        return "Material Transfer", (s.get("transit_naming_series") or "MT/26/")
    return "Material Transfer for Manufacture", s.mtm_naming_series

def _tolerance():
    return (flt(settings().pick_tolerance_pct) or 3.0) / 100.0


def _assert_assigned_to_me(doc):
    if doc.assigned_to != frappe.session.user and "Production Supervisor" not in frappe.get_roles():
        frappe.throw(_("This Pick Order is not assigned to you"), frappe.PermissionError)


def _wo(work_order):
    return frappe.db.get_value(
        "Work Order", work_order,
        ["name", "production_item", "item_name", "qty", "project", "company", "wip_warehouse",
         "source_warehouse", "fg_warehouse", "stock_uom", "status", "docstatus",
         "material_transferred_for_manufacturing", "produced_qty", "commercial_name", "color",
         "width", "required_dia"],
        as_dict=True,
    )


def _required_items(work_order):
    return frappe.get_all(
        "Work Order Item",
        filters={"parent": work_order, "parenttype": "Work Order"},
        fields=["item_code", "item_name", "required_qty", "transferred_qty", "consumed_qty",
                "source_warehouse", "stock_uom", "operation"],
        order_by="idx asc",
    )


# ── Supervisor: plan a pick ──────────────────────────────────────────────────

@frappe.whitelist()
def get_work_order_pick_context(work_order):
    """Everything the Create Pick Order screen needs for one Work Order:
    operations + their Job Cards, required items, and the lot-section
    batches that hold rolls of those items right now."""
    wo = _wo(work_order)
    if not wo:
        frappe.throw(_("Work Order {0} not found").format(work_order))
    ops = []
    for op in wo_operations(work_order):
        ops.append({**op, "job_card": job_card_for_operation(work_order, op.name)})
    req = _required_items(work_order)
    roll_items = [r.item_code for r in req]

    batches = []
    if roll_items:
        batches = frappe.db.sql(
            """
            select ifnull(nullif(r.current_item,''), r.item_code) as item_code,
                   ifnull(nullif(r.current_batch,''), r.batch)     as batch,
                   ifnull(nullif(r.current_warehouse,''), r.warehouse) as warehouse,
                   r.stock_uom,
                   count(*) as rolls,
                   sum(case when ifnull(r.current_weight,0) > 0 then r.current_weight else r.roll_weight end) as weight,
                   sum(ifnull(r.total_qty,0)) as pcs
            from `tabRoll` r
            where ifnull(nullif(r.current_item,''), r.item_code) in %(items)s
              and ifnull(r.current_status,'') != %(in_process)s
            group by 1, 2, 3, 4
            order by 2
            limit 200
            """,
            {"items": roll_items, "in_process": ST_IN_PROCESS},
            as_dict=True,
        )

    picked = frappe.db.sql(
        """select count(*) rolls, sum(current_weight) weight from `tabRoll`
           where current_work_order=%s and current_status=%s""",
        (work_order, ST_IN_PROCESS), as_dict=True,
    )[0]
    return {
        "work_order": wo,
        "operations": ops,
        "default_job_card": first_job_card(work_order),
        "required_items": req,
        "available_batches": batches,
        "in_process": picked,
    }


@frappe.whitelist()
def search_work_orders(txt=None):
    filters = {"docstatus": 1, "status": ["not in", ["Completed", "Stopped", "Closed", "Cancelled"]]}
    or_filters = None
    if txt:
        or_filters = {"name": ["like", f"%{txt}%"], "production_item": ["like", f"%{txt}%"],
                      "project": ["like", f"%{txt}%"]}
    return frappe.get_all(
        "Work Order", filters=filters, or_filters=or_filters,
        fields=["name", "production_item", "item_name", "qty", "status", "project", "color"],
        limit=40, order_by="modified desc",
    )


@frappe.whitelist()
def create_pick_order(work_order, job_card, assigned_to, source_warehouse, pick_qty=None,
                      batch_items=None, remarks=None, target_warehouse=None):
    assert_role("Production Supervisor")
    wo = _wo(work_order)
    if not wo or wo.docstatus != 1:
        frappe.throw(_("Work Order {0} must be submitted").format(work_order))
    jc = frappe.db.get_value("Job Card", job_card, ["work_order", "docstatus", "operation"], as_dict=True)
    if not jc or jc.work_order != work_order:
        frappe.throw(_("Job Card {0} does not belong to Work Order {1}").format(job_card, work_order))
    if jc.docstatus == 2:
        frappe.throw(_("Job Card {0} is cancelled").format(job_card))
    if not assigned_to:
        frappe.throw(_("Assigned To is required"))

    batch_items = frappe.parse_json(batch_items) if isinstance(batch_items, str) else (batch_items or [])
    batch_items = [b for b in batch_items if b.get("batch")]
    if batch_items:
        for b in batch_items:
            if flt(b.get("qty")) <= 0:
                frappe.throw(_("Each batch row needs a Qty greater than zero"))
        pick_qty = sum(flt(b.get("qty")) for b in batch_items)
    else:
        pick_qty = flt(pick_qty)
        if pick_qty <= 0:
            frappe.throw(_("Pick Qty must be greater than zero"))

    doc = frappe.new_doc("Roll Pick Assignment")
    doc.company = wo.company
    doc.status = "Pending"
    doc.pick_type = "To Work Order"
    doc.work_order = work_order
    doc.custom_job_card = job_card
    doc.project = wo.project
    doc.posting_date = today()
    doc.source_warehouse = source_warehouse
    doc.target_warehouse = target_warehouse or wo.wip_warehouse
    doc.assigned_to = assigned_to
    doc.pick_qty = pick_qty
    if doc.meta.has_field("roll_source"):
        doc.roll_source = "Roll"
    for b in batch_items:
        doc.append("batch_items", {"batch": b.get("batch"), "qty": flt(b.get("qty"))})
    if remarks:
        doc.remarks = remarks
    doc.insert()
    doc.submit()
    frappe.db.commit()
    return {"name": doc.name}


# ── Worker: execute a pick ───────────────────────────────────────────────────

@frappe.whitelist()
def get_my_pick_orders():
    filters = {
        "docstatus": 1,
        "status": ["in", ["Pending", "In Progress"]],
        "custom_job_card": ["is", "set"],
    }
    if "Production Supervisor" not in frappe.get_roles() or not frappe.form_dict.get("all"):
        filters["assigned_to"] = frappe.session.user
    rows = frappe.get_all(
        "Roll Pick Assignment", filters=filters,
        fields=["name", "posting_date", "work_order", "custom_job_card as job_card", "project",
                "source_warehouse", "target_warehouse", "pick_qty", "status", "assigned_to"],
        order_by="posting_date desc, creation desc",
    )
    if not rows:
        return rows
    scans = frappe.get_all(
        "Roll Pick Assignment Scan",
        filters={"parenttype": "Roll Pick Assignment", "parent": ["in", [r.name for r in rows]]},
        fields=["parent", "qty"],
    )
    prog = {}
    for s in scans:
        p = prog.setdefault(s.parent, [0.0, 0])
        p[0] += flt(s.qty)
        p[1] += 1
    for r in rows:
        p = prog.get(r.name, [0.0, 0])
        r.picked_qty, r.picked_rolls = round(p[0], 3), p[1]
        r.production_item, r.operation = None, None
        if r.work_order:
            r.production_item = frappe.db.get_value("Work Order", r.work_order, "production_item")
        if r.job_card:
            r.operation = frappe.db.get_value("Job Card", r.job_card, "operation")
    return rows


def _targets_by_uom(doc):
    targets = {}
    if doc.batch_items:
        for b in doc.batch_items:
            item = frappe.db.get_value("Batch", b.batch, "item")
            uom = frappe.db.get_value("Item", item, "stock_uom") if item else "Kgs"
            targets[uom or "Kgs"] = targets.get(uom or "Kgs", 0.0) + flt(b.qty)
    else:
        uom = frappe.db.get_value("Work Order", doc.work_order, "stock_uom") or "Kgs"
        targets[uom] = flt(doc.pick_qty)
    return targets


def _prior_picked(doc):
    lists = frappe.get_all("Roll Wise Pick List",
                           filters={"roll_pick_assignment": doc.name, "docstatus": 1}, pluck="name")
    if not lists:
        return []
    return frappe.get_all(
        "Roll Wise Pick Item",
        filters={"parenttype": "Roll Wise Pick List", "parent": ["in", lists]},
        fields=["roll_no", "item_code", "batch", "warehouse", "qty", "uom"],
    )


@frappe.whitelist()
def get_pick_order_detail(name):
    doc = frappe.get_doc("Roll Pick Assignment", name)
    _assert_assigned_to_me(doc)
    tol = _tolerance()
    prior = _prior_picked(doc)
    prior_by_uom = {}
    for r in prior:
        prior_by_uom[r.uom or "Kgs"] = prior_by_uom.get(r.uom or "Kgs", 0.0) + flt(r.qty)
    summary = [
        {
            "uom": uom, "total_qty": round(t, 3),
            "already_picked_qty": round(prior_by_uom.get(uom, 0.0), 3),
            "tolerance_min": round(t * (1 - tol), 3), "tolerance_max": round(t * (1 + tol), 3),
        }
        for uom, t in _targets_by_uom(doc).items()
    ]
    wo = _wo(doc.work_order) if doc.work_order else {}
    return {
        "name": doc.name,
        "status": doc.status,
        "posting_date": doc.posting_date,
        "work_order": doc.work_order,
        "job_card": doc.custom_job_card,
        "operation": frappe.db.get_value("Job Card", doc.custom_job_card, "operation") if doc.custom_job_card else None,
        "production_item": wo.get("production_item") if wo else None,
        "project": doc.project,
        "source_warehouse": doc.source_warehouse,
        "target_warehouse": doc.target_warehouse,
        "execution_source_warehouse": doc.get("execution_source_warehouse") or doc.source_warehouse,
        "execution_target_warehouse": doc.get("execution_target_warehouse") or doc.target_warehouse,
        "pick_qty": flt(doc.pick_qty),
        "tolerance_pct": tol * 100,
        "pick_qty_summary": summary,
        "batch_items": [{"batch": b.batch, "qty": b.qty} for b in (doc.batch_items or [])],
        "already_picked_rolls": prior,
        "scanned_rolls": [
            {"roll_no": r.roll_no, "item_code": r.item_code, "warehouse": r.warehouse,
             "batch_no": r.batch_no, "qty": r.qty, "uom": r.uom, "roll_weight": r.roll_weight}
            for r in (doc.scanned_rolls or [])
        ],
        "remarks": doc.remarks,
    }


@frappe.whitelist()
def update_execution_warehouse(pick_order, source_warehouse=None, target_warehouse=None, client_id=None):
    doc = frappe.get_doc("Roll Pick Assignment", pick_order)
    _assert_assigned_to_me(doc)
    if source_warehouse and source_warehouse != doc.get("execution_source_warehouse"):
        doc.execution_source_warehouse = source_warehouse
        for r in doc.scanned_rolls or []:
            r.warehouse = source_warehouse
    if target_warehouse:
        doc.execution_target_warehouse = target_warehouse
    doc.flags.ignore_permissions = True
    _save_execution(doc)
    frappe.db.commit()
    return {"success": True}


@frappe.whitelist()
def get_pick_candidates(pick_order):
    """For scanning offline: every roll this pick order could accept, checked
    the same way scan_roll checks one roll (required item, allowed batch,
    not in process, packed / received, project). The device checks a scanned
    roll against this list; the server checks it again when the scan syncs."""
    doc = frappe.get_doc("Roll Pick Assignment", pick_order)
    _assert_assigned_to_me(doc)
    items = [r.item_code for r in _required_items(doc.work_order)]
    if not items:
        return {"rolls": [], "at": str(now_datetime())}
    allowed = sorted({b.batch for b in (doc.batch_items or []) if b.batch})
    cond = "and ifnull(nullif(current_batch,''), batch) in %(batches)s" if allowed else ""
    rows = frappe.db.sql(f"""
        select {", ".join(ROLL_FIELDS)} from `tabRoll`
        where ifnull(nullif(current_item,''), item_code) in %(items)s
          and ifnull(current_status,'') != %(in_process)s {cond}
        order by name limit 3000""",
        {"items": items, "batches": allowed or [""], "in_process": ST_IN_PROCESS}, as_dict=True)
    wo_project = frappe.db.get_value("Work Order", doc.work_order, "project")
    taken = {r.roll_no for r in _prior_picked(doc)}
    out = []
    for row in rows:
        r = effective_roll(row)
        if r.name in taken or (wo_project and r.project and r.project != wo_project):
            continue
        if not _is_packed_or_received(r):
            continue
        out.append({"roll_no": r.name, "item_code": r.eff_item, "batch_no": r.eff_batch,
                    "qty": r.eff_qty, "uom": r.uom, "roll_weight": r.eff_weight, "warehouse": r.eff_warehouse})
    return {"rolls": out, "at": str(now_datetime())}


def _roll_chain(roll_no):
    chain, base = [roll_no], roll_no
    while True:
        m = re.match(r"^(.*)-\d+$", base)
        if not m:
            break
        base = m.group(1)
        chain.append(base)
    return chain


def _is_packed_or_received(roll):
    """Same "real, moveable stock" rule as pranera_knit's scan: the roll (or
    the roll it was cut from) is in a submitted Roll Packing List linked to
    a Stock Entry, OR it came from a PO / Subcontracting Order whose batch
    was actually received."""
    if frappe.db.sql(
        """select 1 from `tabRoll Packing List Item` i
           join `tabRoll Packing List` p on p.name = i.parent
           where i.roll_no in %(chain)s and p.docstatus = 1 and ifnull(p.stock_entry,'') != ''
           limit 1""",
        {"chain": _roll_chain(roll.name)},
    ):
        return True
    if roll.batch and (roll.purchase_order or roll.subcontracting_order):
        return bool(frappe.db.sql(
            """select 1 from `tabSerial and Batch Entry` e
               join `tabSerial and Batch Bundle` b on b.name = e.parent
               where e.batch_no=%(batch)s and b.voucher_type in ('Subcontracting Receipt','Purchase Receipt')
                 and b.docstatus=1 and b.is_cancelled=0 and b.type_of_transaction='Inward' limit 1""",
            {"batch": roll.batch},
        ) or frappe.db.sql(
            """select 1 from `tabStock Ledger Entry` where batch_no=%(batch)s
               and voucher_type in ('Subcontracting Receipt','Purchase Receipt')
               and is_cancelled=0 and actual_qty>0 limit 1""",
            {"batch": roll.batch},
        ))
    return False


@frappe.whitelist()
def scan_roll(pick_order, roll_no, source_warehouse, client_id=None):
    """client_id: set when the scan was made offline and is being sent from
    the device's queue — a roll this order already has is then accepted as a
    re-send instead of an error."""
    doc = frappe.get_doc("Roll Pick Assignment", pick_order)
    _assert_assigned_to_me(doc)
    if client_id:
        rn = parse_scan(roll_no)
        hit = next((r for r in (doc.scanned_rolls or []) if r.roll_no == rn), None)
        if hit:
            return {"roll_no": hit.roll_no, "item_code": hit.item_code, "warehouse": hit.warehouse,
                    "batch_no": hit.batch_no, "qty": hit.qty, "uom": hit.uom, "roll_weight": hit.roll_weight,
                    "duplicate": True}
    if not doc.get("custom_job_card"):
        frappe.throw(_("{0} is not a production pick order").format(pick_order))
    if not source_warehouse:
        frappe.throw(_("Select a Source Warehouse first"))
    roll_no = parse_scan(roll_no)
    if not roll_no:
        frappe.throw(_("Empty scan"))
    roll = get_roll(roll_no)

    if roll.current_status == ST_IN_PROCESS:
        frappe.throw(_("Roll {0} is already in process for {1} ({2})").format(
            roll_no, roll.current_work_order, roll.current_process or ""))
    if not _is_packed_or_received(roll):
        frappe.throw(_("Roll {0} has not been packed against a Stock Entry or received — it is not "
                       "finished stock yet, so it can't be picked").format(roll_no))

    req_items = {r.item_code for r in _required_items(doc.work_order)}
    if roll.eff_item not in req_items:
        frappe.throw(_("Roll {0} is {1}, which is not a required item of Work Order {2}").format(
            roll_no, roll.eff_item, doc.work_order))

    if doc.batch_items:
        allowed = {b.batch for b in doc.batch_items if b.batch}
        if roll.eff_batch not in allowed:
            frappe.throw(_("Roll {0}'s batch {1} is not one of this Pick Order's batches ({2})").format(
                roll_no, roll.eff_batch or "-", ", ".join(sorted(allowed))))

    wo_project = frappe.db.get_value("Work Order", doc.work_order, "project")
    if wo_project and roll.project and wo_project != roll.project:
        frappe.throw(_("Roll {0} belongs to Project {1}, but Work Order {2} is Project {3}").format(
            roll_no, roll.project, doc.work_order, wo_project))

    if any(r.roll_no == roll_no for r in (doc.scanned_rolls or [])):
        frappe.throw(_("Roll {0} has already been scanned for this Order").format(roll_no))
    if any(r.roll_no == roll_no for r in _prior_picked(doc)):
        frappe.throw(_("Roll {0} has already been picked for this Order").format(roll_no))

    row = {
        "roll_no": roll_no,
        "item_code": roll.eff_item,
        "warehouse": source_warehouse,
        "batch_no": roll.eff_batch,
        "qty": roll.eff_qty,
        "uom": roll.uom,
        "roll_weight": roll.eff_weight,
    }
    doc.append("scanned_rolls", {**row, "scanned_by": frappe.session.user, "scanned_at": now_datetime()})
    doc.execution_source_warehouse = source_warehouse
    doc.flags.ignore_permissions = True
    _save_execution(doc)
    frappe.db.commit()
    return row


@frappe.whitelist()
def remove_scanned_roll(pick_order, roll_no, client_id=None):
    doc = frappe.get_doc("Roll Pick Assignment", pick_order)
    _assert_assigned_to_me(doc)
    before = len(doc.scanned_rolls or [])
    doc.set("scanned_rolls", [r for r in (doc.scanned_rolls or []) if r.roll_no != roll_no])
    if len(doc.scanned_rolls) == before:
        if client_id:
            return {"success": True, "duplicate": True}
        frappe.throw(_("Roll {0} was not found in this session").format(roll_no))
    doc.flags.ignore_permissions = True
    _save_execution(doc)
    frappe.db.commit()
    return {"success": True}


@frappe.whitelist()
def submit_pick_order(pick_order, posting_date=None, submit_stock_entry=1):
    """Builds the Roll Wise Pick List + MTM Stock Entry from what is
    persisted in scanned_rolls (never from a client payload)."""
    doc = frappe.get_doc("Roll Pick Assignment", pick_order)
    _assert_assigned_to_me(doc)
    if not doc.scanned_rolls:
        frappe.throw(_("Scan at least one roll before submitting"))
    posting_date = posting_date or today()
    source = doc.get("execution_source_warehouse") or doc.source_warehouse
    target = doc.get("execution_target_warehouse") or doc.target_warehouse
    job_card = doc.custom_job_card
    wo = _wo(doc.work_order)
    rolls = list(doc.scanned_rolls)

    # Re-validate every roll is still free (another order may have taken it)
    for r in rolls:
        st = frappe.db.get_value("Roll", r.roll_no, ["current_status", "current_work_order"], as_dict=True)
        if st and st.current_status == ST_IN_PROCESS:
            frappe.throw(_("Roll {0} was issued to {1} after you scanned it — remove it and rescan").format(
                r.roll_no, st.current_work_order))

    # ±tolerance per UOM, cumulative with any prior submitted session
    tol = _tolerance()
    prior_by_uom, this_by_uom = {}, {}
    for r in _prior_picked(doc):
        prior_by_uom[r.uom or "Kgs"] = prior_by_uom.get(r.uom or "Kgs", 0.0) + flt(r.qty)
    for r in rolls:
        this_by_uom[r.uom or "Kgs"] = this_by_uom.get(r.uom or "Kgs", 0.0) + flt(r.qty)
    for uom, target_qty in _targets_by_uom(doc).items():
        if not target_qty:
            continue
        total = prior_by_uom.get(uom, 0.0) + this_by_uom.get(uom, 0.0)
        if not (target_qty * (1 - tol) <= total <= target_qty * (1 + tol)):
            frappe.throw(_("Picked {0} {1} is outside the ±{2}% tolerance of the {1} target {3}").format(
                round(total, 3), uom, round(tol * 100, 2), round(target_qty, 3)))

    # ── Roll Wise Pick List ──
    pl = frappe.new_doc("Roll Wise Pick List")
    pl.posting_date = posting_date
    pl.warehouse = source
    pl.batch = rolls[0].batch_no
    groups = {}
    for r in rolls:
        g = groups.setdefault((r.item_code, r.batch_no), {
            "item_code": r.item_code, "batch": r.batch_no, "warehouse": r.warehouse or source,
            "qty": 0.0, "uom": r.uom, "rolls": 0,
        })
        g["qty"] += flt(r.qty)
        g["rolls"] += 1
        pl.append("roll_wise_pick_item", {
            "item_code": r.item_code, "warehouse": r.warehouse or source, "batch": r.batch_no,
            "roll_no": r.roll_no, "qty": flt(r.qty), "uom": r.uom, "roll_weight": flt(r.roll_weight),
        })
    for g in groups.values():
        pl.append("batch_wise_pick_item", {
            "item_code": g["item_code"], "warehouse": g["warehouse"], "batch": g["batch"],
            "qty": g["qty"], "uom": g["uom"],
        })
    pl.flags.ignore_permissions = True
    pl.insert()
    pl.submit()
    pl.db_set("roll_pick_assignment", doc.name, update_modified=False)

    # ── MTM Stock Entry against the Job Card ──
    purpose, series = _transfer_kind(doc, target)
    is_mtm = purpose == "Material Transfer for Manufacture"
    se = stock_entry_base(purpose, series, wo.company, posting_date)
    # Work Order on both. ERPNext keeps it on a plain Material Transfer but
    # counts transferred qty only for an MTM (and refuses a Job Card on an MT),
    # so an MT links to the WO without changing it.
    se.work_order = doc.work_order
    if is_mtm:
        se.job_card = job_card
    elif se.meta.has_field("custom_reference_dyeing_work_order"):
        se.custom_reference_dyeing_work_order = doc.work_order
    se.custom_job_card = job_card
    se.project = wo.project
    if is_mtm:
        se.bom_no = frappe.db.get_value("Work Order", doc.work_order, "bom_no")
        # ERPNext's Stock Entry.validate resets For Quantity (fg_completed_qty) to 0
        # unless From BOM is ticked — and the Work Order's "Material Transferred for
        # Manufacturing" is the sum of that For Quantity.
        # With "Validate Components and Quantities Per BOM" on, From BOM makes
        # ERPNext demand every BOM item (chemicals too) in this entry, so there
        # For Quantity is written after submit instead (see below).
        se.from_bom = 0 if _bom_qty_check_on() else 1
    se.from_warehouse = source
    se.to_warehouse = target
    se.custom_roll_wise_pick_list = pl.name
    se.custom_production_entry_type = ENTRY_ROLL_PICK
    se.fabric_name = wo.commercial_name
    se.colour = wo.color
    # For Quantity = the Work Order-UOM quantity moved (fabric Kgs). Pcs
    # trims (collar / cuff) travel with the lot but don't add to it.
    lot_qty = 0
    if is_mtm:
        se.fg_completed_qty = lot_qty = flt(sum(flt(g["qty"]) for g in groups.values()
                                      if (g["uom"] or "Kgs") == (wo.stock_uom or "Kgs")), 3)
    jci = job_card_item_map(job_card) if is_mtm else {}
    for g in groups.values():
        se.append("items", {
            "s_warehouse": g["warehouse"], "t_warehouse": target,
            "item_code": g["item_code"], "qty": g["qty"], "transfer_qty": g["qty"],
            "uom": g["uom"], "stock_uom": g["uom"], "conversion_factor": 1,
            "batch_no": g["batch"], "use_serial_batch_fields": 1,
            "job_card_item": jci.get(g["item_code"]),
        })
        # erp.pranera.in has this summary table on Stock Entry; a site
        # without it (older local copy) just skips it.
        if se.meta.has_field("custom_batch_wise_packing_summary"):
            se.append("custom_batch_wise_packing_summary", {
                "batch": g["batch"], "qty": g["qty"], "no_of_rolls": g["rolls"],
            })
    for r in rolls:
        se.append("custom_production_rolls", {
            "roll_no": r.roll_no, "item_code": r.item_code, "batch_no": r.batch_no,
            "uom": r.uom, "total_qty": cint(r.qty) if is_pcs(r.uom) else 0,
            "weight_before": flt(r.roll_weight), "weight_after": flt(r.roll_weight),
        })
    se.flags.ignore_permissions = True
    se.insert()
    if cint(submit_stock_entry):
        se.submit()  # roll_tracking.on_stock_entry_submit sets the WO transferred qty

    doc.reload()
    doc.set("scanned_rolls", [])
    doc.flags.ignore_permissions = True
    _save_execution(doc)
    frappe.db.set_value("Roll Pick Assignment", doc.name, "status",
                        "Completed" if cint(submit_stock_entry) else "In Progress")
    frappe.db.commit()
    return {
        "pick_list": pl.name,
        "stock_entry": se.name,
        "stock_entry_submitted": bool(cint(submit_stock_entry)),
        "rolls": len(rolls),
        "qty": round(sum(flt(r.qty) for r in rolls), 3),
    }


def _bom_qty_check_on():
    meta = frappe.get_meta("Manufacturing Settings")
    return bool(meta.has_field("validate_components_quantities_per_bom")
                and cint(frappe.db.get_single_value("Manufacturing Settings", "validate_components_quantities_per_bom")))


def set_transferred_lot_qty(se, lot_qty=None):
    """Make sure a submitted pick MTM carries its lot qty as For Quantity, and
    that the Work Order's "Material Transferred for Manufacturing" (the sum of
    For Quantity over its MTMs) counts it. pranera_planning's T&A check won't
    let the Job Card start while that is 0."""
    if not se.work_order or se.purpose != "Material Transfer for Manufacture":
        return
    if lot_qty is None:  # Work Order-UOM qty moved (fabric Kgs, not Pcs trims)
        wo_uom = frappe.db.get_value("Work Order", se.work_order, "stock_uom") or "Kgs"
        lot_qty = sum(flt(d.transfer_qty) for d in se.items if (d.stock_uom or "Kgs") == wo_uom)
    lot_qty = flt(lot_qty, 3)
    if not lot_qty:
        return
    if flt(se.fg_completed_qty, 3) != lot_qty or not cint(se.from_bom):
        se.db_set({"from_bom": 1, "fg_completed_qty": lot_qty}, update_modified=False)
    wo = frappe.get_doc("Work Order", se.work_order)
    wo.update_work_order_qty()
    wo.update_status()
