"""Dashboard + pivot data (inspection and process production)."""
import frappe
from frappe.utils import getdate, add_days, today

from pranera_production.roll_tracking import ENTRY_MF, ST_IN_PROCESS


def _range(from_date, to_date):
    to_date = getdate(to_date or today())
    from_date = getdate(from_date or add_days(to_date, -6))
    return from_date, to_date


@frappe.whitelist()
def get_dashboard(from_date=None, to_date=None):
    f, t = _range(from_date, to_date)
    p = {"f": f, "t": t}
    insp_where = "date(ri.inspected_on) between %(f)s and %(t)s"
    totals = frappe.db.sql(f"""
        select count(*) rolls, ifnull(sum(ri.roll_weight),0) weight, ifnull(sum(ri.total_qty),0) pcs,
               ifnull(avg(ri.point_percentage),0) avg_pct
        from `tabRoll Inspection` ri where {insp_where}""", p, as_dict=True)[0]
    by_type = frappe.db.sql(f"""
        select ri.inspection_type label, count(*) rolls, sum(ri.roll_weight) weight, sum(ri.total_qty) pcs
        from `tabRoll Inspection` ri where {insp_where} group by 1""", p, as_dict=True)
    by_grade = frappe.db.sql(f"""
        select ri.grade label, count(*) rolls, sum(ri.roll_weight) weight
        from `tabRoll Inspection` ri where {insp_where} group by 1 order by 1""", p, as_dict=True)
    by_checker = frappe.db.sql(f"""
        select ifnull(ri.checker_name, ri.checker) label, count(*) rolls, sum(ri.roll_weight) weight,
               avg(ri.point_percentage) avg_pct
        from `tabRoll Inspection` ri where {insp_where} group by 1 order by weight desc limit 15""", p, as_dict=True)
    by_mistake = frappe.db.sql(f"""
        select m.mistake label, count(distinct ri.name) rolls, sum(m.total_points) points
        from `tabRoll Inspection Mistake` m join `tabRoll Inspection` ri on ri.name = m.parent
        where {insp_where} group by 1 order by points desc limit 15""", p, as_dict=True)
    by_day = frappe.db.sql(f"""
        select date(ri.inspected_on) label, count(*) rolls, sum(ri.roll_weight) weight
        from `tabRoll Inspection` ri where {insp_where} group by 1 order by 1""", p, as_dict=True)

    production = frappe.db.sql("""
        select ifnull(jc.operation, '-') label, count(*) rolls, sum(r.weight_before) weight_in,
               sum(r.weight_after) weight_out, sum(r.process_loss) loss
        from `tabProduction Stock Entry Roll` r
        join `tabStock Entry` se on se.name = r.parent
        left join `tabJob Card` jc on jc.name = se.custom_job_card
        where se.docstatus = 1 and se.custom_production_entry_type = %(mf)s
          and se.posting_date between %(f)s and %(t)s
        group by 1 order by weight_out desc""", {**p, "mf": ENTRY_MF}, as_dict=True)
    in_process = frappe.db.sql("""
        select ifnull(current_process, '-') label, count(*) rolls, sum(current_weight) weight
        from `tabRoll` where current_status = %(st)s group by 1 order by rolls desc""",
        {"st": ST_IN_PROCESS}, as_dict=True)
    return {
        "from_date": f, "to_date": t,
        "inspection": {"totals": totals, "by_type": by_type, "by_grade": by_grade,
                       "by_checker": by_checker, "by_mistake": by_mistake, "by_day": by_day},
        "production": {"by_operation": production, "in_process": in_process},
    }


@frappe.whitelist()
def get_pivot_data(dataset="inspection", from_date=None, to_date=None):
    """Flat rows for the client-side pivot."""
    f, t = _range(from_date, to_date)
    p = {"f": f, "t": t, "mf": ENTRY_MF}
    if dataset == "production":
        return frappe.db.sql("""
            select se.posting_date as `Date`, ifnull(jc.operation,'-') as `Operation`,
                   ifnull(jc.workstation,'-') as `Workstation`, se.work_order as `Work Order`,
                   wo.production_item as `Item`, ifnull(wo.color,'-') as `Color`,
                   ifnull(wo.project,'-') as `Project`, r.roll_no as `Roll`,
                   r.weight_before as `Weight In`, r.weight_after as `Weight Out`,
                   r.process_loss as `Process Loss`
            from `tabProduction Stock Entry Roll` r
            join `tabStock Entry` se on se.name = r.parent
            left join `tabJob Card` jc on jc.name = se.custom_job_card
            left join `tabWork Order` wo on wo.name = se.work_order
            where se.docstatus=1 and se.custom_production_entry_type=%(mf)s
              and se.posting_date between %(f)s and %(t)s
            limit 20000""", p, as_dict=True)
    return frappe.db.sql("""
        select date(ri.inspected_on) as `Date`, ri.inspection_type as `Type`,
               ifnull(ri.checker_name, ri.checker) as `Checker`, ri.grade as `Grade`,
               ri.work_order as `Work Order`, ri.item_code as `Item`, ifnull(wo.color,'-') as `Color`,
               ifnull(ri.project,'-') as `Project`, ri.roll as `Roll`,
               ri.roll_weight as `Weight`, ri.total_qty as `Pcs`, ri.total_points as `Points`,
               ri.point_percentage as `Points %%`
        from `tabRoll Inspection` ri
        left join `tabWork Order` wo on wo.name = ri.work_order
        where date(ri.inspected_on) between %(f)s and %(t)s
        limit 20000""", p, as_dict=True)
