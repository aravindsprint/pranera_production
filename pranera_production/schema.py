"""Fields this app reads that it does not own.

The app's own Custom Fields ship as fixtures (module "Production Module").
These others were made on erp.pranera.in by hand or by other apps
(textiles_and_garments, pranera_knit). A local bench restored from an older
backup may not have them, and every query that selects one then fails with
"Unknown column ...".

ensure_fields() runs on every migrate. It only CREATES a field that is
missing, using the definition copied from erp.pranera.in (Oct 2026). A
field that exists is never touched, so this is a no-op on the live site.
The fields are created without a module, so they never end up in this
app's fixtures.
"""
import json
import os

import frappe

_D = "Data"

UPSTREAM_FIELDS = [
    # Item (Work Order / Job Card fetch from these)
    {"dt": "Item", "fieldname": "commercial_name", "label": "Commercial Name", "fieldtype": _D, "insert_after": "gst_hsn_code"},
    {"dt": "Item", "fieldname": "color", "label": "Color", "fieldtype": _D, "insert_after": "commercial_name"},
    {"dt": "Item", "fieldname": "width", "label": "Width/Size", "fieldtype": _D, "insert_after": "color"},
    # Work Order
    {"dt": "Work Order", "fieldname": "width", "label": "Width", "fieldtype": _D, "insert_after": "item_name", "fetch_from": "production_item.width"},
    {"dt": "Work Order", "fieldname": "commercial_name", "label": "Commercial Name", "fieldtype": _D, "insert_after": "width", "fetch_from": "production_item.commercial_name"},
    {"dt": "Work Order", "fieldname": "color", "label": "Color", "fieldtype": _D, "insert_after": "commercial_name", "fetch_from": "production_item.color"},
    {"dt": "Work Order", "fieldname": "required_gsm", "label": "Required GSM", "fieldtype": "Int", "insert_after": "color"},
    {"dt": "Work Order", "fieldname": "required_dia", "label": "Required Dia", "fieldtype": "Int", "insert_after": "required_gsm"},
    # Job Card
    {"dt": "Job Card", "fieldname": "commercial_name", "label": "Commercial Name", "fieldtype": _D, "insert_after": "item_name", "fetch_from": "production_item.commercial_name"},
    {"dt": "Job Card", "fieldname": "color", "label": "Color", "fieldtype": _D, "insert_after": "commercial_name", "fetch_from": "production_item.color"},
    {"dt": "Job Card", "fieldname": "width", "label": "Width", "fieldtype": _D, "insert_after": "color", "fetch_from": "production_item.width"},
    {"dt": "Job Card", "fieldname": "stock_uom", "label": "Stock UOM", "fieldtype": _D, "insert_after": "width", "fetch_from": "production_item.stock_uom"},
    {"dt": "Job Card", "fieldname": "custom_dye_chart", "label": "Dye Chart", "fieldtype": "Link", "options": "Dye Chart", "insert_after": "stock_uom"},
    # Stock Entry
    {"dt": "Stock Entry", "fieldname": "custom_roll_wise_pick_list", "label": "Roll Wise Pick List", "fieldtype": "Link", "options": "Roll Wise Pick List", "insert_after": "posting_time"},
    {"dt": "Stock Entry", "fieldname": "custom_job_card", "label": "Job Card", "fieldtype": "Link", "options": "Job Card", "insert_after": "work_order"},
    {"dt": "Stock Entry", "fieldname": "custom_batch_wise_packing_summary", "label": "Batch Wise Packing Summary", "fieldtype": "Table", "options": "Batch Wise Packing Summary", "insert_after": "custom_roll_wise_pick_list"},
    {"dt": "Stock Entry", "fieldname": "colour", "label": "Colour", "fieldtype": _D, "insert_after": "custom_job_card", "no_copy": 1},
    # Roll Pick Assignment (textiles_and_garments / pranera_knit)
    {"dt": "Roll Pick Assignment", "fieldname": "roll_source", "label": "Roll Source", "fieldtype": "Select", "options": "Roll\nQI Report Details", "default": "Roll", "insert_after": "pick_type", "in_standard_filter": 1, "allow_on_submit": 1},
    {"dt": "Roll Pick Assignment", "fieldname": "purchase_order", "label": "Purchase Order", "fieldtype": "Link", "options": "Purchase Order", "insert_after": "sales_order", "depends_on": "eval:doc.pick_type=='To Subcontracting Order'"},
    {"dt": "Roll Pick Assignment", "fieldname": "subcontracting_order", "label": "Subcontracting Order", "fieldtype": "Link", "options": "Subcontracting Order", "insert_after": "purchase_order", "depends_on": "eval:doc.pick_type=='To Subcontracting Order'"},
    {"dt": "Roll Pick Assignment", "fieldname": "pick_qty_summary", "label": "Pick Qty (by UOM)", "fieldtype": "Table", "options": "Roll Pick Qty Summary", "insert_after": "pick_qty", "read_only": 1},
    {"dt": "Roll Pick Assignment", "fieldname": "scanned_rolls", "label": "Scanned Rolls (In Progress)", "fieldtype": "Table", "options": "Roll Pick Assignment Scan", "insert_after": "pick_qty_summary", "allow_on_submit": 1},
    {"dt": "Roll Pick Assignment", "fieldname": "source_warehouse_address", "label": "Source Warehouse Address", "fieldtype": "Link", "options": "Address", "insert_after": "source_warehouse", "read_only": 1},
    {"dt": "Roll Pick Assignment", "fieldname": "target_warehouse_address", "label": "Target Warehouse Address", "fieldtype": "Link", "options": "Address", "insert_after": "target_warehouse", "read_only": 1},
    {"dt": "Roll Pick Assignment", "fieldname": "execution_source_warehouse", "label": "Execution Source Warehouse", "fieldtype": "Link", "options": "Warehouse", "insert_after": "scanned_rolls", "allow_on_submit": 1},
    {"dt": "Roll Pick Assignment", "fieldname": "execution_target_warehouse", "label": "Execution Target Warehouse", "fieldtype": "Link", "options": "Warehouse", "insert_after": "execution_source_warehouse", "allow_on_submit": 1},
]

# Doctypes (not fields) the app needs from other apps.
REQUIRED_DOCTYPES = [
    "Roll", "Roll Tracking Entries", "Roll Pick Assignment", "Roll Wise Pick List",
    "Roll Packing List", "Dye Chart", "Dye Receipe", "Roll Pick Assignment Scan", "Roll Pick Qty Summary",
]


OWN_MODULE = "Production Module"
_META_KEYS = ("creation", "modified", "modified_by", "owner", "doctype", "name", "idx", "docstatus")


def _own_fields():
    path = frappe.get_app_path("pranera_production", "setup_data", "custom_fields.json")
    with open(path) as f:
        return [{k: v for k, v in x.items() if k not in _META_KEYS} for x in json.load(f)]


def _existing(dt, fieldname):
    """Where an existing field with this name comes from: our Custom Field,
    another Custom Field, or the doctype itself. None if it doesn't exist."""
    cf = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fieldname}, ["name", "module", "fieldtype"], as_dict=True)
    if cf:
        return {"kind": "ours" if cf.module == OWN_MODULE else "custom", "name": cf.name, "fieldtype": cf.fieldtype}
    df = frappe.get_meta(dt).get_field(fieldname)
    if df:
        return {"kind": "standard", "fieldtype": df.fieldtype}
    return None


def _has_column(dt, fieldname, fieldtype):
    if fieldtype in ("Section Break", "Column Break", "Tab Break", "Table", "Table MultiSelect", "HTML", "Button"):
        return frappe.get_meta(dt).has_field(fieldname)
    return frappe.db.has_column(dt, fieldname)


def _target_problem(f):
    """Why a field can't be created here (missing doctype / child table), or None."""
    if not frappe.db.exists("DocType", f["dt"]):
        return f"DocType {f['dt']} is not installed"
    if f.get("fieldtype") in ("Link", "Table", "Table MultiSelect") and f.get("options") \
            and not frappe.db.exists("DocType", f["options"]):
        return f"needs DocType {f['options']}"
    return None


def _save_field(doc, dt):
    meta = frappe.get_meta(dt)
    if doc.insert_after and not meta.has_field(doc.insert_after):
        doc.insert_after = None  # goes to the end of the form
    doc.flags.ignore_permissions = True
    doc.save()
    frappe.db.commit()  # keep each field even if a later one fails


def ensure_fields(verbose=True):
    """Run on every migrate.

    * Upstream fields (UPSTREAM_FIELDS): created only if missing, never changed.
    * This app's fields (setup_data/custom_fields.json): created if missing,
      updated if they are ours (module Production Module), and left alone if
      the doctype already has a field of that name from somewhere else (a
      standard field, or another app's custom field). Those show up on the
      Settings page so a type clash can't go unnoticed.
    """
    created, updated, skipped, existing = [], [], [], []
    plan = [(f, False) for f in UPSTREAM_FIELDS] + [(f, True) for f in _own_fields()]
    for f, own in plan:
        key = f"{f['dt']}.{f['fieldname']}"
        problem = _target_problem(f)
        if problem:
            skipped.append(f"{key} ({problem})")
            continue
        try:
            ex = _existing(f["dt"], f["fieldname"])
            if ex and ex["kind"] == "ours" and own:
                doc = frappe.get_doc("Custom Field", ex["name"])
                changes = {k: v for k, v in f.items() if k not in ("dt", "fieldname", "insert_after") and doc.get(k) != v}
                if changes or not _has_column(f["dt"], f["fieldname"], f.get("fieldtype")):
                    doc.update(changes)
                    _save_field(doc, f["dt"])
                    updated.append(key)
                continue
            if ex:
                if own and ex["fieldtype"] != f.get("fieldtype"):
                    existing.append(f"{key} (already a {ex['kind']} {ex['fieldtype']} field; app expects {f.get('fieldtype')})")
                continue
            doc = frappe.new_doc("Custom Field")
            doc.update(f)
            doc.module = OWN_MODULE if own else None
            _save_field(doc, f["dt"])
            created.append(key)
        except Exception as e:  # never break migrate over one field
            frappe.db.rollback()
            skipped.append(f"{key} ({e})")
    frappe.db.commit()
    if verbose:
        for label, rows in (("created", created), ("updated", updated),
                            ("left as is (type differs)", existing), ("could not create", skipped)):
            if rows:
                print(f"pranera_production fields {label}: " + "; ".join(rows))
    return {"created": created, "updated": updated, "skipped": skipped + existing}


def schema_report():
    """What the Settings page shows: every field / doctype the app needs and
    whether this site has it."""
    missing = []
    for dt in REQUIRED_DOCTYPES:
        if not frappe.db.exists("DocType", dt):
            missing.append({"what": dt, "kind": "doctype", "source": "other app",
                            "fix": "Install / update textiles_and_garments"})
    for f in UPSTREAM_FIELDS:
        if frappe.db.exists("DocType", f["dt"]) and not _has_column(f["dt"], f["fieldname"], f["fieldtype"]):
            missing.append({"what": f"{f['dt']}.{f['fieldname']}", "kind": "field", "source": "erp.pranera.in",
                            "fix": _target_problem(f) or "bench migrate"})
    for f in _own_fields():
        if not frappe.db.exists("DocType", f["dt"]):
            continue
        ex = _existing(f["dt"], f["fieldname"])
        if not ex or (ex["kind"] == "ours" and not _has_column(f["dt"], f["fieldname"], f["fieldtype"])):
            missing.append({"what": f"{f['dt']}.{f['fieldname']}", "kind": "field", "source": "this app",
                            "fix": _target_problem(f) or "bench migrate"})
        elif ex["kind"] != "ours" and ex["fieldtype"] != f["fieldtype"]:
            missing.append({"what": f"{f['dt']}.{f['fieldname']}", "kind": "clash", "source": f"{ex['kind']} field",
                            "fix": f"is a {ex['fieldtype']} here; the app expects {f['fieldtype']}"})
    checked = len(REQUIRED_DOCTYPES) + len(UPSTREAM_FIELDS) + len(_own_fields())
    return {"checked": checked, "missing": missing}
