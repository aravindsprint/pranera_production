"""Offline support.

Verify Rolls (the put-away page) is served by textiles_and_garments. These
wrappers let the app take that page offline:

* offline_pack()   — while online, the device downloads every transfer still
                     waiting to be put away, their rolls and the bins next to
                     them, so the page can be used without a network.
* verify_transfer() — the put-away the device queued. If the device sends it
                     twice (the reply to the first try was lost), the second
                     call returns the first put-away instead of failing with
                     "already put away".
"""
import frappe
from frappe import _


def _vr():
    try:
        from textiles_and_garments.api import verify_rolls
    except ImportError:
        frappe.throw(_("Verify Rolls needs the textiles_and_garments app on this site"))
    return verify_rolls


@frappe.whitelist()
def offline_pack(limit=50):
    vr = _vr()
    transfers, bins, seen_bins = [], [], set()
    for row in vr.search_material_transfers(None, limit):
        try:
            t = vr.get_transfer_for_verification(row["name"])
        except Exception:
            frappe.clear_messages()
            continue  # e.g. a batch transfer with no rolls
        transfers.append(t)
        near = (t.get("source_warehouses") or [None])[0] or row.get("to_warehouse")
        for b in vr.search_bins(None, near_warehouse=near, company=t.get("company"), limit=100):
            if b["name"] not in seen_bins:
                seen_bins.add(b["name"])
                bins.append({**b, "company": t.get("company"), "near": near})
    return {"transfers": transfers, "bins": bins, "at": str(frappe.utils.now_datetime())}


@frappe.whitelist(methods=["POST"])
def verify_transfer(stock_entry, rolls, posting_date=None, submit=1, client_id=None):
    vr = _vr()
    name = vr._resolve_stock_entry_name(stock_entry)
    if client_id:
        existing = vr._existing_put_away(name)
        # same user re-sending → that was this device's own put-away;
        # someone else's → a real conflict, let it fail below
        if existing and frappe.db.get_value("Stock Entry", existing.name, "owner") == frappe.session.user:
            return {"stock_entry": existing.name, "submitted": existing.docstatus == 1,
                    "rolls": len(frappe.parse_json(rolls) if isinstance(rolls, str) else rolls or []),
                    "duplicate": True}
    return vr.create_verified_transfer(stock_entry, rolls, posting_date, submit)
