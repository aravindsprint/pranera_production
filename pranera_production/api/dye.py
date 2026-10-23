"""Dye Chart (with Dye Receipe) and chemical additions during dyeing.

Uses the existing textiles_and_garments doctypes, so desk reports keep working:

* Dye Receipe (+ Dye Receipe Item): the recipe master.
* Dye Chart (+ Dye Chart Item): one per Job Card. Lot weight = Job Card qty
  + add-on qty. Totals use the same formula as Dye Chart.before_save:
  Percentage → lot × dosage / 100, GPL → lot × dosage / 1000 × MLR.
* Dye Chart.custom_additions (Dye Chart Addition, this app): every chemical
  added while the Job Card is running. Each addition is issued at once as its
  own MTM (entry type "Chemical Issue") against the Job Card, so the MF
  consumes it with the rest of the chemicals in WIP.

Saving a chart also writes its lines into the Job Card's items (what the
desk's "Update JobCard" button did), so MTM rows carry job_card_item.
"""
import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, today

from pranera_production.api.common import (
    assert_role, floor3, job_card_item_map, settings, stock_entry_base,
)
from pranera_production.api.chemical import _batch_stock, _dye_chart_for, default_chemical_store
from pranera_production.roll_tracking import ENTRY_CHEMICAL

ROLES = ("Process Operator", "Chemical Issuer")
UOMS = ("Percentage", "GPL")


def mlr_value(mlr):
    """MLR as "6" or "1:6" (liquor ratio) → 6."""
    t = str(mlr or "").strip()
    if ":" in t:
        t = t.split(":")[-1]
    return flt(t)


def line_total(lot_weight, dosage, uom, mlr):
    lot, dosage, mlr = flt(lot_weight), flt(dosage), mlr_value(mlr)
    if uom == "Percentage":
        return flt(lot * dosage / 100, 3)
    return flt(lot * dosage / 1000 * mlr, 3)


def _jc(job_card):
    jc = frappe.db.get_value(
        "Job Card", job_card,
        ["name", "work_order", "operation", "workstation", "status", "docstatus", "for_quantity",
         "production_item", "company", "wip_warehouse"],
        as_dict=True,
    )
    if not jc:
        frappe.throw(_("Job Card {0} not found").format(job_card))
    jc.add_on_qty = flt(frappe.db.get_value("Job Card", job_card, "custom_add_on_qty")) \
        if frappe.get_meta("Job Card").has_field("custom_add_on_qty") else 0.0
    jc.custom_dye_chart = frappe.db.get_value("Job Card", job_card, "custom_dye_chart") \
        if frappe.get_meta("Job Card").has_field("custom_dye_chart") else None
    jc.running = bool(frappe.db.sql(
        "select 1 from `tabJob Card Time Log` where parent=%s and from_time is not null and to_time is null limit 1",
        job_card))
    return jc


def _issued_by_item(job_card):
    rows = frappe.db.sql(
        """select d.item_code, sum(d.transfer_qty) qty
           from `tabStock Entry` se join `tabStock Entry Detail` d on d.parent = se.name
           where se.job_card=%s and se.docstatus=1 and se.custom_production_entry_type=%s
           group by d.item_code""",
        (job_card, ENTRY_CHEMICAL), as_dict=True,
    )
    return {r.item_code: flt(r.qty, 3) for r in rows}


# ── Recipes ────────────────────────────────────────────────────────────────

@frappe.whitelist()
def search_recipes(txt=None, item=None):
    """Dye Receipes, this item's first (default one on top)."""
    cond, params = "", {"item": item or ""}
    if txt:
        cond = "and (dr.name like %(txt)s or dr.item like %(txt)s)"
        params["txt"] = f"%{txt}%"
    return frappe.db.sql(
        f"""select dr.name, dr.item, dr.is_default, dr.docstatus,
                   (select count(*) from `tabDye Receipe Item` i where i.parent = dr.name) as line_count
            from `tabDye Receipe` dr
            where dr.docstatus < 2 {cond}
            order by (dr.item = %(item)s) desc, dr.is_default desc, dr.docstatus desc, dr.modified desc
            limit 30""",
        params, as_dict=True,
    )


def suggested_recipe(item):
    """The recipe to load automatically for this item: its default one, else
    its latest. Submitted recipes before drafts."""
    if not item:
        return None
    rows = frappe.db.sql(
        """select name from `tabDye Receipe`
           where item=%s and docstatus < 2
           order by is_default desc, docstatus desc, modified desc limit 1""",
        item,
    )
    return rows[0][0] if rows else None


@frappe.whitelist()
def get_recipe_lines(recipe):
    # backticks: `function` is an SQL keyword
    rows = frappe.db.sql(
        """select i.`bath_no`, i.`mlr`, i.`function` as chemicals, i.`item`, i.`dosage`, i.`uom`,
                  i.`stock_uom`, it.`item_name`
           from `tabDye Receipe Item` i left join `tabItem` it on it.name = i.`item`
           where i.parent = %s and i.parenttype = 'Dye Receipe'
           order by i.idx""",
        recipe, as_dict=True,
    )
    for r in rows:
        r["item_name"] = r.get("item_name") or ""
        r["stock_uom"] = r.get("stock_uom") or (frappe.db.get_value("Item", r["item"], "stock_uom") if r.get("item") else None)
    return rows


# ── Dye Chart ──────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_dye_chart_context(job_card):
    jc = _jc(job_card)
    dc_name = _dye_chart_for(job_card, jc.custom_dye_chart)
    dc = frappe.get_doc("Dye Chart", dc_name) if dc_name else None
    issued = _issued_by_item(job_card)
    lines, additions = [], []
    if dc:
        for r in dc.dye_chart_item:
            lines.append({
                "name": r.name, "bath_no": r.bath_no, "mlr": r.mlr, "chemicals": r.chemicals,
                "item": r.item, "item_name": frappe.db.get_value("Item", r.item, "item_name") if r.item else "",
                "dosage": r.dosage, "uom": r.uom, "total": r.total, "stock_uom": r.stock_uom,
            })
        for a in (dc.get("custom_additions") or []):
            additions.append({k: a.get(k) for k in (
                "name", "addition_no", "posting_datetime", "bath_no", "chemicals", "item", "item_name",
                "qty", "stock_uom", "batches", "stock_entry", "added_by", "remarks")})
    planned = {}
    for l in lines:
        planned[l["item"]] = flt(flt(planned.get(l["item"])) + flt(l["total"]), 3)
    added = {}
    for a in additions:
        added[a["item"]] = flt(flt(added.get(a["item"])) + flt(a["qty"]), 3)
    summary = []
    for code in list(dict.fromkeys(list(planned) + list(added) + list(issued))):
        if not code:
            continue
        summary.append({
            "item": code, "item_name": frappe.db.get_value("Item", code, "item_name"),
            "planned": planned.get(code, 0.0), "added": added.get(code, 0.0),
            "issued": issued.get(code, 0.0),
        })
    recipe = None if dc else suggested_recipe(jc.production_item)
    return {
        "job_card": jc,
        "suggested_recipe": recipe,
        "suggested_lines": get_recipe_lines(recipe) if recipe else [],
        "default_lot_weight": flt(flt(jc.for_quantity) + flt(jc.add_on_qty), 3),
        "chemical_store": default_chemical_store(job_card),
        "dye_chart": {
            "name": dc.name, "docstatus": dc.docstatus, "dye_receipe": dc.dye_receipe,
            "lot_weight": dc.lot_weight, "item": dc.item,
        } if dc else None,
        "lines": lines,
        "additions": additions,
        "summary": summary,
        "can_add": bool(dc) and jc.docstatus == 0 and jc.running,
    }


def _jci_fields(values):
    """Only the Job Card Item fields this site has (the custom_* dye fields
    come from textiles_and_garments and may be missing on a local copy)."""
    meta = frappe.get_meta("Job Card Item")
    keep = {"doctype", "parent", "parenttype", "parentfield", "idx"}
    return {k: v for k, v in values.items() if k in keep or meta.has_field(k)}


def _sync_job_card_items(dc, job_card):
    """Write the chart's lines into the Job Card items (desk "Update JobCard").
    Inserted / updated at row level so a running Job Card isn't re-validated.
    Rows already transferred against are never removed."""
    store = settings().get("chemical_store_warehouse")
    meta = frappe.get_meta("Job Card Item")
    existing = frappe.get_all(
        "Job Card Item", filters={"parent": job_card, "parenttype": "Job Card"},
        fields=["name", "item_code", "required_qty", "transferred_qty", "idx"]
        + [f for f in ("custom_dye_chart", "custom_dye_chart_item_name") if meta.has_field(f)],
    )
    by_line = {e.custom_dye_chart_item_name: e for e in existing if e.get("custom_dye_chart_item_name")}
    keep = set()
    idx = max([cint(e.idx) for e in existing] or [0])
    for r in dc.dye_chart_item:
        if not r.item:
            continue
        keep.add(r.name)
        if r.name in by_line:
            vals = _jci_fields({
                "item_code": r.item, "required_qty": flt(r.total), "custom_mlr": r.mlr,
                "custom_bath": r.bath_no, "custom_dosage": r.dosage, "custom_uoms": r.uom,
                "custom_functions": r.chemicals,
            })
            frappe.db.set_value("Job Card Item", by_line[r.name].name, vals, update_modified=False)
            continue
        idx += 1
        row = frappe.get_doc(_jci_fields({
            "doctype": "Job Card Item", "parent": job_card, "parenttype": "Job Card",
            "parentfield": "items", "idx": idx, "item_code": r.item,
            "item_name": frappe.db.get_value("Item", r.item, "item_name"),
            "uom": r.stock_uom or frappe.db.get_value("Item", r.item, "stock_uom"),
            "stock_uom": r.stock_uom or frappe.db.get_value("Item", r.item, "stock_uom"),
            "source_warehouse": store, "required_qty": flt(r.total),
            "custom_dye_chart": dc.name, "custom_dye_chart_item_name": r.name,
            "custom_mlr": r.mlr, "custom_bath": r.bath_no, "custom_dosage": r.dosage,
            "custom_uoms": r.uom, "custom_functions": r.chemicals,
        }))
        row.db_insert()
    for e in existing:
        if (e.get("custom_dye_chart") == dc.name and e.get("custom_dye_chart_item_name")
                and e.custom_dye_chart_item_name not in keep and not flt(e.transferred_qty)):
            frappe.db.delete("Job Card Item", {"name": e.name})


@frappe.whitelist()
def save_dye_chart(job_card, lot_weight, lines, dye_receipe=None, submit=0):
    """Create or update (while draft) the Job Card's Dye Chart."""
    assert_role(*ROLES)
    lines = frappe.parse_json(lines) if isinstance(lines, str) else (lines or [])
    lines = [l for l in lines if l.get("item")]
    if not lines:
        frappe.throw(_("Add at least one chemical line"))
    if flt(lot_weight) <= 0:
        frappe.throw(_("Lot weight must be more than 0"))
    jc = _jc(job_card)
    if jc.docstatus != 0:
        frappe.throw(_("Job Card {0} is already {1}").format(job_card, jc.status))

    name = _dye_chart_for(job_card, jc.custom_dye_chart)
    dc = frappe.get_doc("Dye Chart", name) if name else frappe.new_doc("Dye Chart")
    if dc.docstatus == 1:
        frappe.throw(_("Dye Chart {0} is submitted — use Add chemical for anything extra").format(dc.name))
    dc.jobcard = job_card
    dc.item = jc.production_item
    dc.lot_weight = flt(lot_weight, 3)
    dc.dye_receipe = dye_receipe or dc.get("dye_receipe")
    dc.set("dye_chart_item", [])
    for l in lines:
        uom = l.get("uom") if l.get("uom") in UOMS else "Percentage"
        dc.append("dye_chart_item", {
            "bath_no": str(l.get("bath_no") or "") or None, "mlr": l.get("mlr"),
            "chemicals": l.get("chemicals") or None, "item": l.get("item"),
            "dosage": flt(l.get("dosage")), "uom": uom,
            "total": line_total(lot_weight, l.get("dosage"), uom, l.get("mlr")),
        })
    dc.flags.ignore_permissions = True
    dc.save()
    if frappe.get_meta("Job Card").has_field("custom_dye_chart"):
        frappe.db.set_value("Job Card", job_card, "custom_dye_chart", dc.name, update_modified=False)
    _sync_job_card_items(dc, job_card)
    if cint(submit):
        dc.submit()
    frappe.db.commit()
    return {"dye_chart": dc.name, "docstatus": dc.docstatus}


# ── Batches ────────────────────────────────────────────────────────────────

@frappe.whitelist()
def get_batches(item_code, warehouse=None):
    """Batches with stock in the chemical store, oldest first (FIFO order)."""
    warehouse = warehouse or settings().get("chemical_store_warehouse")
    if not warehouse:
        frappe.throw(_("Set the Chemical Store in Production App Settings"))
    has_batch = cint(frappe.db.get_value("Item", item_code, "has_batch_no"))
    return {
        "warehouse": warehouse,
        "has_batch_no": has_batch,
        "stock_uom": frappe.db.get_value("Item", item_code, "stock_uom"),
        "batches": [{"batch_no": b, "qty": flt(q, 3)} for b, q in _batch_stock(item_code, warehouse)],
    }


def fifo_allocation(item_code, warehouse, qty):
    out, remaining = [], floor3(qty)
    for b, avail in _batch_stock(item_code, warehouse):
        if remaining <= 0:
            break
        take = floor3(min(avail, remaining))
        if take > 0:
            out.append({"batch_no": b, "qty": take})
            remaining = flt(remaining - take, 3)
    return out, remaining


def check_allocations(item_code, warehouse, qty, allocations):
    """Validate user-chosen batches: they must add up to qty and each batch
    must have that much stock. Returns clean [{batch_no, qty}]."""
    qty = floor3(qty)
    allocations = [a for a in (allocations or []) if flt(a.get("qty")) > 0]
    if not allocations:
        alloc, short = fifo_allocation(item_code, warehouse, qty)
        if short > 0.0005:
            frappe.throw(_("Not enough stock of {0} in {1}: short by {2}").format(item_code, warehouse, short))
        return alloc
    total = flt(sum(flt(a.get("qty")) for a in allocations), 3)
    if abs(total - qty) > 0.0015:
        frappe.throw(_("{0}: the batches add up to {1}, but the quantity is {2}").format(item_code, total, qty))
    stock = dict(_batch_stock(item_code, warehouse))
    has_batch = cint(frappe.db.get_value("Item", item_code, "has_batch_no"))
    seen, out = {}, []
    for a in allocations:
        b = a.get("batch_no") or None
        if has_batch and not b:
            frappe.throw(_("{0}: pick a batch for every row").format(item_code))
        seen[b] = flt(flt(seen.get(b)) + flt(a.get("qty")), 3)
        if seen[b] > flt(stock.get(b)) + 0.0005:
            frappe.throw(_("{0}: batch {1} has only {2} in {3}").format(
                item_code, b or "-", flt(stock.get(b), 3), warehouse))
        out.append({"batch_no": b, "qty": floor3(a.get("qty"))})
    return out


# ── Additions ──────────────────────────────────────────────────────────────

@frappe.whitelist()
def add_chemical(job_card, item_code, qty, allocations=None, bath_no=None, chemicals=None,
                 remarks=None, source_warehouse=None, client_id=None, added_at=None, offline=0):
    """Add a chemical while the Job Card is running: issue it at once (MTM
    against the Job Card, chosen batches) and record it on the Dye Chart.

    Offline (sent later from the device's queue): client_id makes a re-sent
    addition return the first one instead of issuing twice; added_at is when
    it was really added; batches picked from a stale stock list fall back to
    FIFO if they no longer have the stock."""
    assert_role(*ROLES)
    if client_id:
        done = frappe.db.get_value("Dye Chart Addition", {"client_id": client_id},
                                   ["stock_entry", "addition_no"], as_dict=True)
        if done:
            return {"stock_entry": done.stock_entry, "addition_no": done.addition_no, "batches": [], "duplicate": True}
    allocations = frappe.parse_json(allocations) if isinstance(allocations, str) else allocations
    qty = floor3(qty)
    if qty <= 0:
        frappe.throw(_("Enter a quantity"))
    jc = _jc(job_card)
    if jc.docstatus != 0:
        frappe.throw(_("Job Card {0} is already {1}").format(job_card, jc.status))
    if not jc.running:
        frappe.throw(_("Start Job Card {0} before adding chemicals").format(job_card))
    dc_name = _dye_chart_for(job_card, jc.custom_dye_chart)
    if not dc_name:
        frappe.throw(_("Job Card {0} has no Dye Chart").format(job_card))
    store = source_warehouse or default_chemical_store(job_card)
    if not store:
        frappe.throw(_("Select the Chemical Store"))
    wip = frappe.db.get_value("Work Order", jc.work_order, "wip_warehouse") or jc.wip_warehouse
    try:
        alloc = check_allocations(item_code, store, qty, allocations)
    except frappe.ValidationError:
        if not cint(offline) or not allocations:
            raise
        frappe.clear_messages()
        alloc = check_allocations(item_code, store, qty, None)  # FIFO from current stock
    uom = frappe.db.get_value("Item", item_code, "stock_uom")

    # make sure the Job Card has an item row for it (a chemical not on the chart)
    jci = job_card_item_map(job_card)
    if item_code not in jci:
        idx = cint(frappe.db.sql("select max(idx) from `tabJob Card Item` where parent=%s", job_card)[0][0]) + 1
        row = frappe.get_doc(_jci_fields({
            "doctype": "Job Card Item", "parent": job_card, "parenttype": "Job Card",
            "parentfield": "items", "idx": idx, "item_code": item_code,
            "item_name": frappe.db.get_value("Item", item_code, "item_name"),
            "uom": uom, "stock_uom": uom, "source_warehouse": store, "required_qty": qty,
            "custom_dye_chart": dc_name, "custom_functions": chemicals, "custom_bath": bath_no,
        }))
        row.db_insert()
        jci = job_card_item_map(job_card)
    else:
        frappe.db.sql("update `tabJob Card Item` set required_qty = required_qty + %s where name=%s",
                      (qty, jci[item_code]))

    se = stock_entry_base("Material Transfer for Manufacture", settings().mtm_naming_series,
                          jc.company or frappe.db.get_value("Warehouse", store, "company"), today())
    se.work_order = jc.work_order
    se.job_card = job_card
    se.custom_job_card = job_card
    se.project = frappe.db.get_value("Work Order", jc.work_order, "project")
    se.from_warehouse = store
    se.to_warehouse = wip
    se.fg_completed_qty = 0
    se.custom_production_entry_type = ENTRY_CHEMICAL
    se.custom_dye_chart = dc_name
    se.remarks = _("Chemical addition during {0}").format(jc.operation or "dyeing") + (f": {remarks}" if remarks else "")
    for a in alloc:
        row = {
            "s_warehouse": store, "t_warehouse": wip, "item_code": item_code,
            "qty": a["qty"], "transfer_qty": a["qty"], "uom": uom, "stock_uom": uom,
            "conversion_factor": 1, "job_card_item": jci.get(item_code),
        }
        if a.get("batch_no"):
            row.update({"batch_no": a["batch_no"], "use_serial_batch_fields": 1})
        se.append("items", row)
    se.flags.ignore_permissions = True
    se.insert()
    se.submit()

    # record on the Dye Chart (row level: the chart may be submitted)
    n = cint(frappe.db.sql(
        "select count(*) from `tabDye Chart Addition` where parent=%s and parenttype='Dye Chart'", dc_name)[0][0])
    add = frappe.get_doc({
        "doctype": "Dye Chart Addition", "parent": dc_name, "parenttype": "Dye Chart",
        "parentfield": "custom_additions", "idx": n + 1, "addition_no": n + 1,
        "posting_datetime": added_at or now_datetime(), "bath_no": bath_no, "chemicals": chemicals,
        "item": item_code, "item_name": frappe.db.get_value("Item", item_code, "item_name"),
        "qty": qty, "stock_uom": uom,
        "batches": ", ".join(f"{a['batch_no'] or '-'}: {a['qty']}" for a in alloc),
        "stock_entry": se.name, "added_by": frappe.session.user, "remarks": remarks,
        "client_id": client_id,
    })
    add.db_insert()
    frappe.db.commit()
    return {"stock_entry": se.name, "addition_no": n + 1, "batches": alloc}


def remove_additions_for(stock_entry):
    """Stock Entry cancelled → drop its addition row and give back the
    required qty it added on the Job Card item."""
    rows = frappe.get_all("Dye Chart Addition", filters={"stock_entry": stock_entry},
                          fields=["name", "parent", "item", "qty"])
    for r in rows:
        jc = frappe.db.get_value("Dye Chart", r.parent, "jobcard")
        if jc:
            frappe.db.sql(
                """update `tabJob Card Item` set required_qty = greatest(required_qty - %s, 0)
                   where parent=%s and item_code=%s order by idx limit 1""",
                (flt(r.qty), jc, r.item))
        frappe.db.delete("Dye Chart Addition", {"name": r.name})
