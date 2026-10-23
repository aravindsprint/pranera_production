# Deploying pranera_production

> This build has **not** been run on a bench yet. Install it on the local bench
> (`/Users/aravind/webapps/version15/frappe-bench`, site `pranera.com`) with a copy of
> production data, and go through the test checklist below before it goes on erp.pranera.in.

## 1. Install

```bash
cd ~/webapps/version15/frappe-bench
bench get-app /path/to/pranera_production        # or from GitHub once pushed
cd apps/pranera_production/frontend && yarn install && yarn build && cd -
bench --site pranera.com install-app pranera_production
bench --site pranera.com migrate
```

Same rule as pranera_knit: `bench build` does **not** run Vite. Run `yarn build` in
`frontend/` before every commit. `public/production_app` is committed.

### Dev server (`yarn dev`, http://localhost:3002/production-app)

The dev server can talk to **erp.pranera.in** or your **local bench** (`http://127.0.0.1:8001`).
Pick one on **Settings** (menu → App → Settings) or on the login page. Switching takes effect
immediately (no restart): it signs you out, clears the app's cached data and opens the login page.
A **LOCAL** / **LIVE** badge in the header shows which one you're on. It defaults to Local bench.
The choice is the `pp_backend` cookie, shared with the Planning dev app (3001), since both apps
share the same localhost login.

Override the targets in `frontend/.env.local` if needed:
`VITE_LOCAL_TARGET=http://127.0.0.1:8001`, `VITE_LIVE_TARGET=https://erp.pranera.in`,
`VITE_DEFAULT_BACKEND=live`. None of this is in the production build.

Settings also checks the connected site: reachable, app version, your roles, and every
database field the app reads. A local bench restored from an older backup can be missing
fields that exist on erp.pranera.in (e.g. `Job Card.color`), and pages then fail with
"Unknown column …". `bench migrate` creates any missing field (`schema.ensure_fields`, never
changes existing ones).

## 2. What migrate changes on the site

* **Custom Fields** (module *Production Module*, created by `schema.ensure_fields` from `setup_data/custom_fields.json`, not fixtures) on **Roll** (`current_*` + history
  table), **Roll Tracking Entries** (event, WO, JC, weight before/after, loss),
  **Stock Entry** (`custom_production_entry_type`, `custom_dye_chart`,
  `custom_production_rolls`), **Roll Pick Assignment** (`custom_job_card`) and
  **Job Card** (Inspection tab: lot checks + grade summary, allow-on-submit).
* **Roles**: Production Supervisor, Process Operator, Chemical Issuer, Inspection Checker.
* **Inspection Mistake** master records (41).
* **Server Script `roll_packing_list_single_batch` is overwritten** by the fixture
  version. It now compares a row's batch with `Roll.current_batch` and falls back to
  `Roll.batch`. Without this change, the MF's Roll Packing List fails for dyed or
  finished rolls.

## 3. pranera_knit / pranera_roll patch (required)

`pranera_knit_current_roll_state.patch` (shipped alongside this app) changes
`pranera_knit/api/pick_order.py`:

* the pick scan uses `current_item / current_batch / current_weight` when a roll has
  been processed, and refuses rolls that are `In Process`;
* "My Pick Orders" in the Knit App hides production pick orders (`custom_job_card` set).

```bash
cd apps/pranera_knit && git apply /path/to/pranera_knit_current_roll_state.patch
```

**pranera_roll** carries a duplicate of this code, so apply the same two changes there.

## 4. Configure

1. **Production App Settings**: check the MTM / MF naming series (`MTM/26/`,
   `MF/26/`). They must exist in Stock Entry's naming series, so change them at year end.
   Set the default **Chemical Store** (e.g. `DYE/CHEMICAL STORES (SATHIYA) - PSS`).
   Review the "keep weight" operations list and the grade thresholds (40 / 100 points %).
2. Give users their roles (and **Stock User** or the equivalent, so they can read
   warehouses and items).
3. Make sure every operation's Job Card exists when the Work Order is submitted. The
   pick and the MF both look them up by `operation_id`.

## 5. Test checklist (local bench, real data copy)

1. **Pick**: Create Pick Order for a DYEING WO → assign → scan greige rolls → Submit MTM.
   Check that the MTM has `job_card` set, the rows have `job_card_item`, and each Roll is
   now `In Process` with one history row.
2. **Chemicals**: Chemical Issue → Job Card with a Dye Chart → issue the pending qty →
   check the MTM series, the FIFO batches and that `fg_completed_qty` is 0.
3. **Single-op DYEING WO**: complete the Job Card → MF. Rolls keep their weight. Roll →
   dyed item / -D batch / `In Stock`. A Roll Packing List is created.
4. **Next WO (STENTER)**: pick the dyed rolls (they are found by dyed item + batch) →
   MF with new weights → check the process loss on each roll.
5. **Multi-op WO (DYEING > STENTER > INSPECTION)**: complete DYEING → rolls move to
   STENTER. Complete STENTER → INSPECTION. Inspect the rolls (fabric and a collar/cuff
   WO) → complete the INSPECTION Job Card → partial MF (half the rolls), then the rest.
   The second MF should default to the first MF's batch, and chemicals should be
   consumed pro rata, then fully on the last MF.
6. **Cancel** the last MF → the Roll Packing List is cancelled and the rolls go back to
   `In Process` with their previous batch and weight.
7. **Cut** a finished roll on Create / Cut Rolls → the new roll inherits the history and
   current state.
8. **Knit App**: pick finished rolls "To Sales Order" → the finished batch is accepted
   and the qty is the current weight.
9. **Offline inspection**: switch the tablet to airplane mode → save 2 rolls → come back
   online → both sync.
10. **Lot Inspection Report**: open an inspected INSPECTION Job Card → compare the
    External and Internal PDFs with an old QI report PDF for the same kind of lot.
    Check the header, the 8-rolls-per-table defect matrix, the grade 3 highlight and
    the summary.
11. **Adopt Rolls – In WIP**: take a Work Order whose MTM was made from the desk →
    pick the transferred batch → scan its rolls. They become `In Process` at the
    current operation, and adopting more than was transferred (+ tolerance) is refused.
    Then complete the Job Card and MF as normal.
12. **Adopt Rolls – In Stock**: take a dyed `…-D` batch in the lot section → scan rolls
    and enter their weights → they can now be picked for the stenter Work Order.
    Adopting more than the batch stock in that warehouse is refused.

## 6. Go-live notes

* Existing QI Report Details rolls (old finish roll nos) are still pickable through the
  Knit App's "QI Report Details" roll source. New production uses greige roll nos only.
* The ERPNext rule still applies: the MF needs every operation's Job Card completed for
  the quantity (99% over-production allowance on this site). The MF screen says which
  Job Card is pending.
* **Rolls moved before go-live** have no history. Bring them in with **Adopt Rolls**
  (Production Supervisor):
  * **In WIP**: for Work Orders whose MTM was made from the desk.
  * **In Stock**: for batches dyed or finished before go-live.

  This has to be done by scanning, because a greige batch was often split across
  several dyeing Work Orders and dyed batches have no Roll records, so the system can't
  tell which roll went where. Adoption is capped by the ledger quantity and can be undone
  roll by roll.
