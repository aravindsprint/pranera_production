from . import __version__ as app_version

app_name        = "pranera_production"
app_title       = "Pranera Production"
app_publisher   = "Pranera Services & Solutions"
app_description = "Process production floor app (dyeing, stenter, finishing, inspection) for ERPNext"
app_email       = "admin@pranera.in"
app_license     = "MIT"

# Same /<app>-app SPA pattern as pranera_knit: a server-rendered www page
# (injects csrf_token) serving the Vite build from public/production_app.
add_to_apps_screen = [
    {
        "name": "pranera_production",
        "logo": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect width='100' height='100' rx='22' fill='%231e3a5f'/%3E%3Ccircle cx='50' cy='50' r='26' fill='none' stroke='white' stroke-width='7'/%3E%3Ccircle cx='50' cy='50' r='8' fill='white'/%3E%3C/svg%3E",
        "title": "Production App",
        "route": "/production-app",
    }
]

website_route_rules = [
    {"from_route": "/production-app/<path:app_path>", "to_route": "production-app"},
]

# Roles must exist before the doctype permissions that reference them are
# synced, so create them before install AND before every migrate.
before_install = "pranera_production.install.ensure_roles"
before_migrate = "pranera_production.install.ensure_roles"
after_migrate  = "pranera_production.install.after_migrate"

doc_events = {
    # Every Stock Entry this app creates carries custom_production_entry_type
    # and a custom_production_rolls table. The handlers ignore any Stock
    # Entry without that marker, so ordinary entries are untouched.
    "Stock Entry": {
        "on_submit": "pranera_production.roll_tracking.on_stock_entry_submit",
        "before_cancel": "pranera_production.roll_tracking.on_stock_entry_before_cancel",
        "on_cancel": "pranera_production.roll_tracking.on_stock_entry_cancel",
    },
    # Multi-operation Work Orders: completing an intermediate operation's
    # Job Card moves the rolls on to the next operation (process only —
    # weight is captured at the MF).
    "Job Card": {
        "validate": "pranera_production.roll_tracking.on_job_card_validate",
        "on_submit": "pranera_production.roll_tracking.on_job_card_submit",
        "on_cancel": "pranera_production.roll_tracking.on_job_card_cancel",
    },
    # Roll Wise Pick Item.roll_weight is fetch_from roll_no.roll_weight (the
    # greige weight). For rolls that have been through a process, swap in
    # the roll's current weight. Runs after pranera_knit's own validate hook.
    "Roll Wise Pick List": {
        "validate": "pranera_production.roll_tracking.use_current_roll_weights",
    },
}

fixtures = [
    # Custom Fields are NOT fixtures: a fixture import is all-or-nothing and
    # fails when a site already has a field of the same name (e.g. a local
    # textiles_and_garments branch whose Roll has current_warehouse).
    # schema.ensure_fields() creates them in after_migrate instead, from
    # setup_data/custom_fields.json, skipping any field the doctype already has.
    {"doctype": "Role", "filters": [["name", "in", [
        "Production Supervisor", "Process Operator", "Chemical Issuer", "Inspection Checker",
    ]]]},
    # Updated to compare against Roll.current_batch (falls back to Roll.batch)
    # now that a roll's batch changes as it moves through processes.
    {"doctype": "Server Script", "filters": [["name", "in", ["roll_packing_list_single_batch"]]]},
]
