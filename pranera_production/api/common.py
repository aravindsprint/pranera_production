"""Shared helpers for the Pranera Production app.

Roll "effective" state
──────────────────────
Roll.item_code / batch / roll_weight / warehouse keep their ORIGINAL
(greige / inward) values, so knitting reports keep working. A roll's live
state after it has been through a process lives in the current_* fields,
which are always derived from its Process History (roll_tracking_entries —
see roll_tracking.recompute_current). Everything in this app reads a
roll through effective_roll(), which prefers current_* and falls back to
the original fields for a roll that hasn't been processed yet.
"""
import frappe
from frappe import _
from frappe.utils import flt, cint, nowtime, today

APP_ROLES = {
    "Production Supervisor", "Process Operator", "Chemical Issuer",
    "Inspection Checker", "Roll Picker", "System Manager", "Manufacturing Manager",
}

ROLL_FIELDS = [
    "name", "roll_no", "item_code", "item_name", "batch", "roll_weight", "total_qty",
    "stock_uom", "warehouse", "project", "work_order", "job_card",
    "purchase_order", "subcontracting_order", "knitting_machine_no",
    "current_status", "current_process", "current_work_order", "current_job_card",
    "current_warehouse", "current_item", "current_batch", "current_weight",
    "current_process_loss", "current_grade", "current_total_points", "last_roll_inspection",
]


def settings():
    return frappe.get_cached_doc("Production App Settings")


def floor3(value):
    """Floor (never round up) to 3 decimals so a requested qty never exceeds
    what is actually available in a batch — same rule the knit app uses."""
    return int(flt(value) * 1000) / 1000.0


def is_pcs(uom):
    return (uom or "").strip().lower() in ("pcs", "nos", "pc")


def effective_roll(roll):
    """roll: dict-like Roll row with ROLL_FIELDS. Returns a plain dict with
    the live item / batch / weight / warehouse resolved."""
    r = frappe._dict(roll)
    processed = bool(r.get("current_item") or r.get("current_batch"))
    r.eff_item = r.get("current_item") or r.get("item_code")
    r.eff_batch = r.get("current_batch") or r.get("batch")
    r.eff_weight = flt(r.get("current_weight")) if processed and flt(r.get("current_weight")) else flt(r.get("roll_weight"))
    r.eff_warehouse = r.get("current_warehouse") or r.get("warehouse")
    r.uom = r.get("stock_uom") or "Kgs"
    # Qty that moves in stock: piece count for Pcs items, weight otherwise
    r.eff_qty = cint(r.get("total_qty")) if is_pcs(r.uom) else r.eff_weight
    return r


def get_roll(roll_no, throw=True):
    row = frappe.db.get_value("Roll", roll_no, ROLL_FIELDS, as_dict=True)
    if not row:
        if throw:
            frappe.throw(_("Roll {0} not found").format(roll_no))
        return None
    return effective_roll(row)


def parse_scan(value):
    """Stickers are item_code#batch#roll_no (Roll doctype). A bare value is
    treated as the roll number."""
    value = (value or "").strip()
    parts = [p.strip() for p in value.split("#")]
    if len(parts) >= 3:
        return parts[-1]
    return value


def wo_operations(work_order):
    """Work Order operations in sequence order."""
    return frappe.get_all(
        "Work Order Operation",
        filters={"parent": work_order, "parenttype": "Work Order"},
        fields=["name", "idx", "operation", "sequence_id", "workstation", "status", "completed_qty"],
        order_by="sequence_id asc, idx asc",
    )


def job_card_for_operation(work_order, operation_row):
    names = frappe.get_all(
        "Job Card",
        filters={"work_order": work_order, "operation_id": operation_row, "docstatus": ["<", 2]},
        pluck="name",
        order_by="creation desc",
        limit=1,
    )
    return names[0] if names else None


def first_job_card(work_order):
    ops = wo_operations(work_order)
    for op in ops:
        jc = job_card_for_operation(work_order, op.name)
        if jc:
            return jc
    return None


def last_operation(work_order):
    ops = wo_operations(work_order)
    return ops[-1] if ops else None


def keep_weight_operations():
    raw = settings().keep_weight_operations or ""
    return {l.strip().upper() for l in raw.splitlines() if l.strip()}


def is_inspection_operation(operation):
    insp = (settings().inspection_operation or "INSPECTION").strip().upper()
    return (operation or "").strip().upper() == insp


def get_row_batch(row):
    """Batch of a submitted Stock Entry Detail row — either batch_no (old /
    use_serial_batch_fields) or the first batch in its Serial and Batch
    Bundle."""
    if row.get("batch_no"):
        return row.get("batch_no")
    # ERPNext creates the bundle of an auto-batched finished item during
    # submit, sometimes only in the database — not on the in-memory row.
    bundle = row.get("serial_and_batch_bundle") or (row.name and frappe.db.get_value(
        "Stock Entry Detail", row.name, "serial_and_batch_bundle"))
    if not bundle and row.name:
        bundle = frappe.db.get_value("Serial and Batch Bundle",
                                     {"voucher_detail_no": row.name, "is_cancelled": 0}, "name")
    if bundle:
        b = frappe.db.get_value("Serial and Batch Entry", {"parent": bundle}, "batch_no")
        if b:
            return b
    return None


def stock_entry_base(purpose, naming_series, company, posting_date=None):
    se = frappe.new_doc("Stock Entry")
    if naming_series:
        se.naming_series = naming_series
    se.stock_entry_type = purpose
    se.purpose = purpose
    se.company = company
    # posting_time must be set explicitly: the auto-created Serial and Batch
    # Bundle rows combine posting_date + posting_time before Stock Entry's
    # own validate() would default it (see pranera_knit create_roll_picking_entry).
    se.set_posting_time = 1
    se.posting_date = posting_date or today()
    se.posting_time = nowtime()
    return se


def job_card_item_map(job_card):
    """item_code -> Job Card Item row name, so MTM rows carry their
    job_card_item reference (needed when Manufacturing Settings' 'Allow
    excess material transfer' is ever switched off)."""
    if not job_card:
        return {}
    rows = frappe.get_all(
        "Job Card Item", filters={"parent": job_card, "parenttype": "Job Card"},
        fields=["name", "item_code"],
    )
    return {r.item_code: r.name for r in rows}


@frappe.whitelist()
def get_session_info():
    """Who is using the app and which screens they may open."""
    user = frappe.session.user
    roles = set(frappe.get_roles(user))
    emp = frappe.db.get_value(
        "Employee", {"user_id": user, "status": "Active"},
        ["name", "employee_name", "designation"], as_dict=True,
    ) or {}
    full_name = frappe.db.get_value("User", user, "full_name") or user
    app_roles = sorted(roles & APP_ROLES)
    return {
        "user": user,
        "full_name": emp.get("employee_name") or full_name,
        "employee": emp.get("name"),
        "designation": emp.get("designation"),
        "roles": app_roles,
        "has_access": bool(app_roles) or user == "Administrator",
        "settings": {
            "pick_tolerance_pct": flt(settings().pick_tolerance_pct) or 3,
            "inspection_operation": settings().inspection_operation or "INSPECTION",
            "grade_2_min_points": flt(settings().grade_2_min_points) or 40,
            "grade_3_min_points": flt(settings().grade_3_min_points) or 100,
            "chemical_store_warehouse": settings().chemical_store_warehouse,
        },
    }


def assert_role(*roles):
    user_roles = set(frappe.get_roles())
    if frappe.session.user == "Administrator" or "System Manager" in user_roles:
        return
    if not (user_roles & set(roles) | (user_roles & {"Production Supervisor", "Manufacturing Manager"})):
        frappe.throw(_("You need one of these roles: {0}").format(", ".join(roles)), frappe.PermissionError)


@frappe.whitelist()
def search_link(doctype, txt=None, filters=None, fields=None, limit=30):
    """Small generic search used by the app's AutoComplete fields."""
    allowed = {"Warehouse", "Work Order", "Job Card", "User", "Batch", "Item", "Workstation", "Operation", "Project"}
    if doctype not in allowed:
        frappe.throw(_("Search not allowed for {0}").format(doctype))
    filters = frappe.parse_json(filters) if isinstance(filters, str) else (filters or {})
    fields = frappe.parse_json(fields) if isinstance(fields, str) else (fields or ["name"])
    or_filters = None
    if txt:
        or_filters = {"name": ["like", f"%{txt}%"]}
        if doctype == "User":
            or_filters["full_name"] = ["like", f"%{txt}%"]
        if doctype == "Warehouse":
            filters.setdefault("is_group", 0)
    if doctype == "User":
        filters.setdefault("enabled", 1)
        filters.setdefault("user_type", "System User")
    return frappe.get_all(doctype, filters=filters, or_filters=or_filters, fields=fields,
                          limit=cint(limit) or 30, order_by="modified desc")


@frappe.whitelist()
def get_csrf_token():
    """Used by the PWA when it was loaded from the service-worker cache
    (no server-injected csrf_token)."""
    if frappe.session.user == "Guest":
        return None
    return frappe.sessions.get_csrf_token()


@frappe.whitelist()
def get_app_info():
    """Settings page: which site this is, the app version, the user's roles,
    and any field / doctype the app needs that this site is missing."""
    import pranera_production
    from pranera_production.schema import schema_report

    roles = set(frappe.get_roles())
    return {
        "site": frappe.local.site,
        "app_version": getattr(pranera_production, "__version__", ""),
        "installed": "pranera_production" in frappe.get_installed_apps(),
        "is_system_manager": "System Manager" in roles,
        "user": frappe.session.user,
        "app_roles": sorted(roles & APP_ROLES),
        "settings_ok": bool(frappe.db.get_singles_dict("Production App Settings")),
        "schema": schema_report(),
    }
