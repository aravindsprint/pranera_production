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
    # Fields this app reads that a local bench (older backup) may not have.
    from pranera_production.schema import ensure_fields
    ensure_fields()
    _repair_pick_transferred_qty()
    _seed_chemical_stores()
    _repair_mf_roll_batches()
    _seed_inspection_mistakes()

    # Seed defaults on the Single the first time (fixture defaults only apply
    # to new docs created through the form).
    settings = frappe.get_single("Production App Settings")
    changed = False
    defaults = {
        "mtm_naming_series": "MTM/26/",
        "transit_naming_series": "MT/26/",
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
    # Never save a link to a record this site doesn't have (e.g. no Operation
    # called INSPECTION on a local bench): blank it, the Settings form shows it.
    for df in settings.meta.get_link_fields():
        value = settings.get(df.fieldname)
        if value and not frappe.db.exists(df.options, value):
            print(f"pranera_production: Production App Settings.{df.fieldname} cleared "
                  f"({df.options} {value!r} does not exist on this site)")
            settings.set(df.fieldname, None)
            changed = True
    if changed:
        settings.flags.ignore_permissions = True
        try:
            settings.save()
            frappe.db.commit()
        except Exception as e:  # settings must never break migrate
            frappe.db.rollback()
            print(f"pranera_production: could not save Production App Settings ({e}); "
                  "open it in the desk and save it once.")


def _repair_pick_transferred_qty():
    """Roll-pick MTMs submitted before From BOM was ticked have For Quantity 0,
    so their Work Order shows nothing transferred. Fix those, once."""
    from pranera_production.api.pick import set_transferred_lot_qty
    names = frappe.get_all("Stock Entry", pluck="name", filters={
        "docstatus": 1, "purpose": "Material Transfer for Manufacture",
        "custom_production_entry_type": "Roll Pick", "fg_completed_qty": 0,
        "work_order": ["is", "set"]})
    for name in names:
        try:
            set_transferred_lot_qty(frappe.get_doc("Stock Entry", name))
            frappe.db.commit()
            print(f"pranera_production: set For Quantity on {name}")
        except Exception as e:
            frappe.db.rollback()
            print(f"pranera_production: could not fix {name}: {e}")


# Pranera's two in-house dyeing units (erp.pranera.in, Oct 2026)
_UNIT_STORES = [
    ("OMS - PSS", "DYE/CHEMICAL STORES - PSS"),
    ("SATHIYA - PSS", "DYE/CHEMICAL STORES (SATHIYA) - PSS"),
]


def _seed_chemical_stores():
    """Fill Chemical Store by Unit once, if empty and the warehouses exist."""
    try:
        s = frappe.get_single("Production App Settings")
        if s.get("chemical_stores"):
            return
        rows = [(u, c) for u, c in _UNIT_STORES
                if frappe.db.exists("Warehouse", u) and frappe.db.exists("Warehouse", c)]
        if not rows:
            return
        for u, c in rows:
            s.append("chemical_stores", {"unit_warehouse": u, "chemical_store": c})
        s.flags.ignore_permissions = True
        s.save()
        frappe.db.commit()
        print("pranera_production: Chemical Store by Unit filled for " + ", ".join(u for u, _ in rows))
    except Exception as e:
        frappe.db.rollback()
        print(f"pranera_production: could not fill Chemical Store by Unit: {e}")


def _repair_mf_roll_batches():
    """Rolls manufactured before the finished batch was read from its Serial
    and Batch Bundle have no target batch on their MF history row, so they
    still show the greige batch. Fill it in from the MF's finished row."""
    from pranera_production.api.common import get_row_batch
    from pranera_production.roll_tracking import recompute_current, save_roll, _create_roll_packing_list
    rows = frappe.db.sql("""select distinct parent, document_name from `tabRoll Tracking Entries`
        where parenttype = 'Roll' and document_type = 'Stock Entry'
          and custom_event = 'Manufactured' and ifnull(target_batch, '') = ''""", as_dict=True)
    batches = {}
    for r in rows:
        try:
            if r.document_name not in batches:
                se = frappe.get_doc("Stock Entry", r.document_name)
                fg = next((it for it in se.items if it.is_finished_item), None)
                batches[r.document_name] = get_row_batch(fg) if fg and se.docstatus == 1 else None
            batch = batches[r.document_name]
            if not batch:
                continue
            roll = frappe.get_doc("Roll", r.parent)
            for e in roll.roll_tracking_entries:
                if e.document_name == r.document_name and e.custom_event == "Manufactured" and not e.target_batch:
                    e.target_batch = batch
            recompute_current(roll)
            save_roll(roll)
            frappe.db.commit()
            print(f"pranera_production: roll {r.parent} batch set to {batch} ({r.document_name})")
        except Exception as e:
            frappe.db.rollback()
            print(f"pranera_production: could not fix roll {r.parent}: {e}")
    # and the Roll Packing List those MFs skipped for want of a batch
    for name, batch in batches.items():
        if not batch or frappe.db.exists("Roll Packing List", {"stock_entry": name, "docstatus": 1}):
            continue
        try:
            se = frappe.get_doc("Stock Entry", name)
            fg = next(it for it in se.items if it.is_finished_item)
            _create_roll_packing_list(se, fg, batch, se.get("custom_job_card") or se.get("job_card"))
            frappe.db.commit()
            print(f"pranera_production: Roll Packing List created for {name}")
        except Exception as e:
            frappe.db.rollback()
            print(f"pranera_production: could not create Roll Packing List for {name}: {e}")


# The Ionic inspection app's tile board: board -> columns of
# (mistake, tap adds, colour, height as % of board width).
_IONIC_BOARD = {
    "Main": [
        [("Colour fly/Foreign", "2", "#ff6666", 11), ("Yarn Stain (Knitting)", "4", "#1B4F72", 24)],
        [("Cut Holes", "4", "#159274", 11), ("Dye Dots", "4", "#784213", 11), ("Joint", "4", "#000000", 13)],
        [("Holes", "4", "#d279a6", 11), ("Lycra cut", "4", "#88cc00", 24)],
        [("Nice Yarn", "Metre", "#E92929", 11), ("Set Off", "4", "#e65c00", 11), ("Softner patches", "2", "#F1C40E", 13)],
        [("Stain_1", "1", "#70dbdb", 9), ("Stain_2", "2", "#2eb8b8", 8), ("Stain_4", "4", "#145252", 8),
         ("Yarn pulling (Snagging)", "4", "#512E5F", 10)],
        [("Yarn Cut", "4", "#707D7E", 12), ("Yarn Joint", "4", "#00bfff", 11), ("Stain line", "Metre", "#aaaa55", 12)],
    ],
    "Other": [
        [("Crease Marks", "Metre", "#9900ff", 11), ("Crush Mark", "Metre", "#009999", 24)],
        [("Dye Patches", "4", "#159274", 11), ("LycraJump", "4", "#784213", 11), ("Moire Effect (Knitting)", "Metre", "#000000", 13)],
        [("Mild Snagging", "4", "#2D58B4", 11), ("Needle Drop", "Metre", "#00802b", 11), ("Needle Line", "4", "#ff5500", 13)],
        [("Poovari/Navhole", "4", "#800001", 24), ("Thick & Thin Yarn", "Metre", "#F1C40E", 11)],
        [("Uneven Finishing", "Metre", "#707D7E", 12), ("Vertical(Dust)line", "Metre", "#00bfff", 11), ("Yarn Knots", "4", "#ff6666", 12)],
        [("Oil Stain", "2", "#808000", 11), ("Pilling", "2", "#D2691E", 6.65), ("Nurling", "4", "#2F4F4F", 6.65),
         ("Weave Distortion", "4", "#008000", 11)],
    ],
}
# recorded under Roll checks in the Ionic app, so not on the board
_IONIC_HIDDEN = {"Crow feet", "Patta Problem", "Rope Mark"}
_EXTRA_COLOURS = ["#6d28d9", "#0f766e", "#b45309", "#be123c", "#1d4ed8", "#4d7c0f"]


def _seed_inspection_mistakes():
    """Inspection Mistakes are maintained in the desk. Create the shipped list
    only where a mistake doesn't exist, and lay out the board (Ionic layout)
    the first time only — after that board, column, order, colour and
    show/hide are whatever the desk says."""
    import json
    try:
        path = frappe.get_app_path("pranera_production", "setup_data", "inspection_mistakes.json")
        for row in json.load(open(path)):
            if not frappe.db.exists("Inspection Mistake", row["name"]):
                doc = frappe.get_doc({k: v for k, v in row.items()
                                      if k not in ("creation", "modified", "modified_by", "owner")})
                doc.flags.ignore_permissions = True
                doc.insert()
        layout = {}
        for board, cols in _IONIC_BOARD.items():
            for ci, col in enumerate(cols, 1):
                for seq, (name, pt, colour, h) in enumerate(col, 1):
                    layout[name] = {"board": board, "column_no": ci, "sequence": seq,
                                    "tile_point": pt, "tile_color": colour, "tile_height": h, "show_on_board": 1}
        # lay the board out once: after that the desk owns it
        if frappe.db.exists("Inspection Mistake", {"tile_color": ["is", "set"]}):
            frappe.db.commit()
            return
        extra = 0
        for m in frappe.get_all("Inspection Mistake", fields=["name"], order_by="sequence asc"):
            if m.name in layout:
                vals = layout[m.name]
            else:
                vals = {"board": "Other", "column_no": 7, "sequence": extra + 1, "tile_point": "4",
                        "tile_color": _EXTRA_COLOURS[extra % len(_EXTRA_COLOURS)], "tile_height": 11,
                        "show_on_board": 0 if m.name in _IONIC_HIDDEN else 1}
                if m.name not in _IONIC_HIDDEN:
                    extra += 1
            frappe.db.set_value("Inspection Mistake", m.name, vals, update_modified=False)
        frappe.db.commit()
    except Exception as e:
        frappe.db.rollback()
        print(f"pranera_production: could not set up Inspection Mistakes: {e}")
