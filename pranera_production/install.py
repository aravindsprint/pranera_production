import frappe

APP_ROLES = [
    "Production Supervisor",
    "Process Operator",
    "Chemical Issuer",
    "Inspection Checker",
    # Owned by pranera_knit's fixtures; created here too so this app installs
    # cleanly on a site where pranera_knit isn't installed yet.
    "Roll Picker",
]


def ensure_roles():
    for role in APP_ROLES:
        if not frappe.db.exists("Role", role):
            frappe.get_doc({
                "doctype": "Role",
                "role_name": role,
                "desk_access": 1,
            }).insert(ignore_permissions=True)
    frappe.db.commit()


def after_migrate():
    # Seed defaults on the Single the first time (fixture defaults only apply
    # to new docs created through the form).
    settings = frappe.get_single("Production App Settings")
    changed = False
    defaults = {
        "mtm_naming_series": "MTM/26/",
        "mf_naming_series": "MF/26/",
        "pick_tolerance_pct": 3,
        "inspection_operation": "INSPECTION" if frappe.db.exists("Operation", "INSPECTION") else None,
        "keep_weight_operations": "DYEING\nRE DYEING\nDOUBLE DYEING\nDYEING + BIO WASH\nBIO WASH + DOUBLE DYEING\nDYEING + WICKING",
        "grade_2_min_points": 40,
        "grade_3_min_points": 100,
    }
    for field, value in defaults.items():
        if value is not None and not settings.get(field):
            settings.set(field, value)
            changed = True
    if not frappe.db.get_singles_dict("Production App Settings"):
        # nothing stored yet: persist the JSON defaults (incl. the Check
        # require_inspection_before_mf = 1) so they show in the form
        changed = True
    if changed:
        settings.flags.ignore_permissions = True
        settings.save()
        frappe.db.commit()
