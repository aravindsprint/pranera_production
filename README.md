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

## Dye Chart and chemical additions

* **Dye Chart** (`/production-app/dye-chart/<job card>`, from Job Cards → "Create Dye Chart"): pick a
  Dye Receipe, lot weight = Job Card qty + add-on qty, edit the lines, Save / Submit. Uses the existing
  textiles_and_garments Dye Chart, and writes its lines into the Job Card's items (like "Update JobCard").
* **Additions**: once the Job Card is started, "Add chemical" issues the qty at once (its own MTM
  against the Job Card, FIFO batch suggested, changeable) and records it on the Dye Chart's
  *Chemical Additions* table. Repeat as often as needed, then **End Job Card**. Cancelling an
  addition's Stock Entry removes its row. The MF consumes additions with the other chemicals in WIP.
* **Chemical Issue** lists every open Job Card (those without a Dye Chart greyed out) and lets the
  store change the FIFO batches too.

## Reports and go-live tools

* **Lot Inspection Report** (`/production-app/lot-report`): port of the Ionic pivot
  page and its External / Internal PDFs. It shows the lot header, a mistake × roll point
  matrix (8 rolls per table) with weight, GSM, width, length, point / 100 sqm, grade and
  defect flags, and a grade summary. It prints to A4 (Save as PDF).
* **Pivot Analysis** (`/production-app/pivot`): free rows × columns pivot over roll
  inspections or MF rolls, with CSV export.
* **Adopt Rolls** (`/production-app/adopt-rolls`): attach rolls that moved before go-live
  to their Work Order's WIP, or to a batch already in stock.

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
