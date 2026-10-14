# Pranera Production

Process-floor PWA for ERPNext (dyeing, stenter, finishing, inspection), served at
`/production-app`. Same architecture as `pranera_knit`: a Vue 3 + Vite PWA built into
`pranera_production/public/production_app`, served by a server-rendered www page
(which injects the csrf token), with whitelisted Python APIs and doc_events.

## Flow

```
Lot section ──(Roll Pick Assignment → scan rolls → Roll Wise Pick List)──► MTM against Job Card ──► WIP (workstation)
Chemical Stores ──(Dye Chart on the Job Card, FIFO batches)────────────► MTM against Job Card ──► WIP
Job Card(s) ── start / complete (multi-operation: rolls move to the next operation, process only)
INSPECTION Job Card ── lot checks on the Job Card + one Roll Inspection per roll (4-point, grade)
MF (partial allowed) ── rolls → finished item / batch / weight, chemicals consumed pro rata,
                        Roll Packing List created, rolls keep their GREIGE roll no to billing
```

## Roll state

`Roll.item_code / batch / roll_weight / warehouse` keep their original (greige / inward)
values so knitting reports don't change. The live state is in the new fields:

| Field | Meaning |
|---|---|
| `current_status` | `In Process` (in a WIP against a Work Order) / `In Stock` |
| `current_process`, `current_work_order`, `current_job_card` | where it is in production |
| `current_item`, `current_batch`, `current_weight`, `current_warehouse` | live stock identity |
| `current_process_loss` | cumulative loss since greige |
| `current_grade`, `current_total_points`, `last_roll_inspection` | latest inspection |
| `roll_tracking_entries` | process history (child table *Roll Tracking Entries*) |

`current_*` is never written directly. It is always recomputed from the last row of the
process history (`roll_tracking.recompute_current`). Cancelling a Stock Entry or a Job Card
just removes the rows that document added and recomputes.

## New doctypes (module "Production Module")

* **Production App Settings** (single): naming series, pick tolerance, chemical store,
  operations that keep weight at MF, inspection operation, grade thresholds.
* **Roll Inspection** + **Roll Inspection Mistake**: replaces QI Report Details /
  QI CC Report Details rows.
* **Inspection Mistake**: master list of mistakes, seeded from the old Mistake Details options.
* **Inspection Grade Summary**: grade-wise summary on the Inspection Job Card.
* **Production Stock Entry Roll**: rolls moved / manufactured by a Stock Entry.

## Roles

`Production Supervisor` (everything), `Roll Picker` (from pranera_knit), `Chemical Issuer`,
`Process Operator`, `Inspection Checker`. The app's menu is filtered by these roles.

See `DEPLOY.md` for installation and the go-live checklist.
