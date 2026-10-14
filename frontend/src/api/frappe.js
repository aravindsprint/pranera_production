// ── Connectivity signal ───────────────────────────────────────────────────
// Any HTTP answer from the server (other than a gateway error) proves the
// network path works. useSync listens for this and flips the app back online
// even if its own probe failed/timed out — so a real request can never be
// blocked by a stale "offline" flag.
function signalServerReachable(res) {
  const s = res && res.status
  if (s && s !== 502 && s !== 503 && s !== 504) {
    try { window.dispatchEvent(new Event('prod:api-ok')) } catch { /* ignore */ }
  }
}

// ── CSRF ──────────────────────────────────────────────────────────────────
let _csrf = ''

function getCookieValue(name) {
  return document.cookie
    .split('; ')
    .find(r => r.startsWith(name + '='))
    ?.split('=')[1] || ''
}

export async function ensureCSRF() {
  // 1. Already cached
  if (_csrf) return _csrf
  // 2. Injected by Jinja (production)
  if (window.csrf_token) { _csrf = window.csrf_token; return _csrf }
  // 3. Cookie fallback
  const cookie = getCookieValue('csrftoken') || getCookieValue('X-Frappe-CSRF-Token')
  if (cookie) { _csrf = cookie; return _csrf }
  // 4. Fetch from Server Script (dev proxy)
  try {
    const r = await fetch('/api/method/pranera_production.api.common.get_csrf_token', { credentials: 'include' })
    if (r.ok) {
      const d = await r.json()
      if (d?.message) { _csrf = d.message; window.csrf_token = d.message }
      else console.warn('ensureCSRF: get_csrf_token returned no token (no session/sid cookie?)')
    } else {
      console.warn('ensureCSRF: get_csrf_token HTTP', r.status)
    }
  } catch(e) {
    console.warn('ensureCSRF: get_csrf_token failed', e)
  }
  return _csrf
}

// Forget the cached CSRF token so the next ensureCSRF() call re-fetches it.
// Required after login/logout, since both actions issue a brand new session
// (and therefore a brand new token) — reusing the old one causes silent
// CSRFTokenError 403s on the very next authenticated request.
export function resetCSRF() {
  _csrf = ''
  window.csrf_token = ''
}

export async function initCSRF() {
  window.__FRAPPE_SESSION__ = {
    user: decodeURIComponent(getCookieValue('user_id') || '') || 'Guest',
    base_url: ''
  }
  // Pre-warm the token so first API call doesn't need to fetch it
  await ensureCSRF()
  // Keep csrf_token on the session object too — logout()/other callers read
  // it from here, and previously this field was silently dropped because
  // this function replaces window.__FRAPPE_SESSION__ wholesale.
  window.__FRAPPE_SESSION__.csrf_token = _csrf
  console.log('Session user:', window.__FRAPPE_SESSION__.user, '| CSRF:', _csrf ? '✓' : '✗')
}

// True once we've established the browser holds a real (non-Guest) Frappe
// session. Call initCSRF() first so window.__FRAPPE_SESSION__ is current.
export function isLoggedIn() {
  const user = window.__FRAPPE_SESSION__?.user
  return !!user && user !== 'Guest'
}

// ── Core fetch helpers ────────────────────────────────────────────────────
export async function call(method, args = {}) {
  const token = await ensureCSRF()
  const body = new URLSearchParams()
  for (const [k, v] of Object.entries(args)) {
    // Skip omitted/absent params entirely rather than letting
    // URLSearchParams.append coerce `undefined`/`null` into the literal
    // string "undefined"/"null" — that string then reaches the Python
    // method as a real (invalid) value instead of the missing arg its
    // `=None` default expects, which for a Link field trips validation
    // with a confusing "Could not find <Field>: undefined" error.
    if (v === undefined || v === null) continue
    body.append(k, typeof v === 'object' ? JSON.stringify(v) : v)
  }
  const res = await fetch(`/api/method/${method}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'X-Frappe-CSRF-Token': token
    },
    body: body.toString(),
    credentials: 'include'
  })
  signalServerReachable(res)
  const data = await res.json()
  if (!res.ok || data.exc) throw new Error(extractServerError(data, res.statusText))
  return data
}

// Turn Frappe's error payload into a short human-readable message
// instead of dumping the entire Python traceback into the UI.
function extractServerError(data, fallback = 'Request failed') {
  // 1. _server_messages: JSON array of JSON strings, last one is most relevant
  try {
    const msgs = JSON.parse(data._server_messages || '[]')
    if (msgs.length) {
      const last = JSON.parse(msgs[msgs.length - 1])
      const text = String(last.message || last)
        .replace(/<[^>]+>/g, '')   // strip HTML tags
        .trim()
      if (text) return text
    }
  } catch { /* fall through */ }
  // 2. data.exception: "module.path.ErrorClass: message" — keep the message part
  if (data.exception) {
    const parts = String(data.exception).split(':')
    return (parts.length > 1 ? parts.slice(1).join(':') : parts[0]).trim()
  }
  // 3. Last line of the traceback, if that's all we have
  if (data.exc) {
    try {
      const tb = JSON.parse(data.exc)
      const lines = String(tb[0] || '').trim().split('\n')
      return lines[lines.length - 1].trim()
    } catch { /* fall through */ }
  }
  return fallback
}

export async function getList(doctype, { filters = [], orFilters = [], fields = ['name'], limit = 200, start = 0, orderBy } = {}) {
  const params = new URLSearchParams({
    filters: JSON.stringify(filters),
    fields: JSON.stringify(fields),
    limit_page_length: limit,
    limit_start: start,
    ...(orFilters && orFilters.length ? { or_filters: JSON.stringify(orFilters) } : {}),
    ...(orderBy ? { order_by: orderBy } : {})
  })
  const res = await fetch(`/api/resource/${encodeURIComponent(doctype)}?${params}`, {
    credentials: 'include'
  })
  signalServerReachable(res)
  const data = await res.json()
  if (!res.ok) throw new Error(data.exc || res.statusText)
  return data.data || []
}

// Paginated variant of getList — fetches EVERY matching row, not just the
// first page. Frappe's REST list endpoint silently truncates at whatever
// limit_page_length you pass, and with no explicit order_by it sorts by
// "modified desc" across the WHOLE doctype (not just this app's records) —
// so a plain single-request limit can drop rows in an unpredictable way
// (e.g. an entire warehouse building missing from the dropdown because its
// records happen to be older than 500 other, unrelated warehouses site-wide).
// Pages through with limit_start until a page comes back short.
export async function getAllList(doctype, { filters = [], orFilters = [], fields = ['name'], pageSize = 500, orderBy = 'name asc', maxPages = 40 } = {}) {
  const all = []
  let start = 0
  for (let page = 0; page < maxPages; page++) {
    const params = new URLSearchParams({
      filters: JSON.stringify(filters),
      fields: JSON.stringify(fields),
      limit_page_length: pageSize,
      limit_start: start,
      order_by: orderBy,
      ...(orFilters && orFilters.length ? { or_filters: JSON.stringify(orFilters) } : {})
    })
    const res = await fetch(`/api/resource/${encodeURIComponent(doctype)}?${params}`, {
      credentials: 'include'
    })
    signalServerReachable(res)
    const data = await res.json()
    if (!res.ok) throw new Error(data.exc || res.statusText)
    const rows = data.data || []
    all.push(...rows)
    if (rows.length < pageSize) break // last page reached
    start += pageSize
  }
  return all
}

export async function getDoc(doctype, name) {
  const res = await fetch(
    `/api/resource/${encodeURIComponent(doctype)}/${encodeURIComponent(name)}`,
    { credentials: 'include' }
  )
  const data = await res.json()
  if (!res.ok) throw new Error(data.exc || res.statusText)
  return data.data
}

export async function createDoc(doctype, doc) {
  const token = await ensureCSRF()
  const res = await fetch(`/api/resource/${encodeURIComponent(doctype)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Frappe-CSRF-Token': token },
    body: JSON.stringify(doc),
    credentials: 'include'
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.exc || res.statusText)
  return data.data
}

export async function updateDoc(doctype, name, doc) {
  const token = await ensureCSRF()
  const res = await fetch(
    `/api/resource/${encodeURIComponent(doctype)}/${encodeURIComponent(name)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', 'X-Frappe-CSRF-Token': token },
      body: JSON.stringify(doc),
      credentials: 'include'
    }
  )
  const data = await res.json()
  if (!res.ok) throw new Error(data.exc || res.statusText)
  return data.data
}

// ── Pranera Production API ────────────────────────────────────────────────
const M = 'pranera_production.api.'
const msg = (r) => r?.message

export const api = {
  // common
  session:            ()                 => call(M + 'common.get_session_info').then(msg),
  searchLink:         (doctype, txt, filters = {}, fields = ['name']) =>
                         call(M + 'common.search_link', { doctype, txt, filters, fields }).then(r => r.message || []),

  // picking
  searchWorkOrders:   (txt)              => call(M + 'pick.search_work_orders', { txt }).then(r => r.message || []),
  pickContext:        (work_order)       => call(M + 'pick.get_work_order_pick_context', { work_order }).then(msg),
  createPickOrder:    (payload)          => call(M + 'pick.create_pick_order', payload).then(msg),
  myPickOrders:       (all = 0)          => call(M + 'pick.get_my_pick_orders', { all }).then(r => r.message || []),
  pickOrderDetail:    (name)             => call(M + 'pick.get_pick_order_detail', { name }).then(msg),
  pickScan:           (pick_order, roll_no, source_warehouse) =>
                         call(M + 'pick.scan_roll', { pick_order, roll_no, source_warehouse }).then(msg),
  pickRemove:         (pick_order, roll_no) => call(M + 'pick.remove_scanned_roll', { pick_order, roll_no }).then(msg),
  pickWarehouses:     (pick_order, source_warehouse, target_warehouse) =>
                         call(M + 'pick.update_execution_warehouse', { pick_order, source_warehouse, target_warehouse }).then(msg),
  pickSubmit:         (pick_order, posting_date, submit_stock_entry = 1) =>
                         call(M + 'pick.submit_pick_order', { pick_order, posting_date, submit_stock_entry }).then(msg),

  // chemicals
  chemicalJobCards:   (txt)              => call(M + 'chemical.get_chemical_job_cards', { txt }).then(r => r.message || []),
  chemicalContext:    (job_card, source_warehouse) =>
                         call(M + 'chemical.get_chemical_issue_context', { job_card, source_warehouse }).then(msg),
  issueChemicals:     (job_card, source_warehouse, items, posting_date, submit_stock_entry = 1) =>
                         call(M + 'chemical.issue_chemicals', { job_card, source_warehouse, items, posting_date, submit_stock_entry }).then(msg),

  // job cards
  jobCards:           (params = {})      => call(M + 'process.get_job_cards', params).then(r => r.message || []),
  jobCardDetail:      (job_card)         => call(M + 'process.get_job_card_detail', { job_card }).then(msg),
  startJobCard:       (job_card)         => call(M + 'process.start_job_card', { job_card }).then(msg),
  completeJobCard:    (job_card, completed_qty, submit = 1) =>
                         call(M + 'process.complete_job_card', { job_card, completed_qty, submit }).then(msg),

  // manufacture
  mfWorkOrders:       (txt)              => call(M + 'manufacture.get_mf_work_orders', { txt }).then(r => r.message || []),
  mfContext:          (work_order)       => call(M + 'manufacture.get_mf_context', { work_order }).then(msg),
  createMf:           (payload)          => call(M + 'manufacture.create_mf', payload).then(msg),

  // inspection
  inspectionJobCards: (txt, include_completed = 0) =>
                         call(M + 'inspection.get_inspection_job_cards', { txt, include_completed }).then(r => r.message || []),
  inspectionContext:  (job_card)         => call(M + 'inspection.get_inspection_context', { job_card }).then(msg),
  saveLotChecks:      (job_card, values) => call(M + 'inspection.save_lot_checks', { job_card, values }).then(msg),
  rollForInspection:  (job_card, roll_no) => call(M + 'inspection.get_roll_for_inspection', { job_card, roll_no }).then(msg),
  saveRollInspection: (job_card, roll_no, data) =>
                         call(M + 'inspection.save_roll_inspection', { job_card, roll_no, data }).then(msg),
  deleteRollInspection: (name)           => call(M + 'inspection.delete_roll_inspection', { name }).then(msg),
  markInspectionComplete: (job_card)     => call(M + 'inspection.mark_inspection_complete', { job_card }).then(msg),
  mistakes:           (inspection_type)  => call(M + 'inspection.get_mistakes', { inspection_type }).then(r => r.message || []),

  // rolls
  searchRolls:        (params = {})      => call(M + 'rolls.search_rolls', params).then(r => r.message || []),
  rollTrace:          (roll_no)          => call(M + 'rolls.get_roll_trace', { roll_no }).then(msg),

  // dashboard
  dashboard:          (from_date, to_date) => call(M + 'dashboard.get_dashboard', { from_date, to_date }).then(msg),
  pivotData:          (dataset, from_date, to_date) =>
                         call(M + 'dashboard.get_pivot_data', { dataset, from_date, to_date }).then(r => r.message || []),
}

// Lookup tables cached offline (Dexie) by useSync
export const syncWarehouses = () =>
  getAllList('Warehouse', { filters: [['Warehouse', 'is_group', '=', 0]], fields: ['name', 'warehouse_name', 'modified'], pageSize: 500, orderBy: 'name asc' })

export const syncPurchaseOrders = () =>
  getAllList('Purchase Order', {
    filters: [['Purchase Order', 'docstatus', '!=', 2]],
    fields: ['name', 'supplier', 'status', 'transaction_date', 'modified'],
    pageSize: 500, orderBy: 'modified desc', maxPages: 6
  })

export const syncSubcontractingOrders = () =>
  getAllList('Subcontracting Order', {
    filters: [['Subcontracting Order', 'docstatus', '!=', 2]],
    fields: ['name', 'supplier', 'status', 'transaction_date', 'modified', 'purchase_order'],
    pageSize: 500, orderBy: 'modified desc', maxPages: 6
  })

// ── Create Rolls page (Cut Rolls / Purchase Order / Subcontract Order) ──────
// PO / SO roll creation reuses the Server Scripts already live on
// erp.pranera.in (knit_get_po_items, knit_get_so_items, knit_create_po_so_roll).
// Cutting uses this app's process-aware cut (pranera_production.api.rolls.cut_roll):
// a roll that has been dyed / finished is cut from its CURRENT weight and the
// new piece inherits its process history.
export const getPOItems = (purchaseOrder) =>
  call('knit_get_po_items', { purchase_order: purchaseOrder }).then(r => r.message || [])

export const getSOItems = (subcontractingOrder) =>
  call('knit_get_so_items', { subcontracting_order: subcontractingOrder }).then(r => r.message || [])

export const createPOSORoll = (payload) =>
  call('knit_create_po_so_roll', payload).then(r => r.message)

export const cutRoll = (payload) =>
  call(M + 'rolls.cut_roll', payload).then(r => r.message)

export const searchRollsForCut = (txt) =>
  getList('Roll', {
    orFilters: [
      ['Roll', 'name', 'like', `%${txt}%`],
      ['Roll', 'item_code', 'like', `%${txt}%`],
      ['Roll', 'current_item', 'like', `%${txt}%`],
      ['Roll', 'commercial_name', 'like', `%${txt}%`]
    ],
    fields: [
      'name', 'item_code', 'item_name', 'commercial_name', 'color', 'width',
      'stock_uom', 'batch', 'roll_weight', 'total_qty', 'project',
      'work_order', 'purchase_order', 'subcontracting_order', 'job_card',
      'warehouse', 'knit_operator', 'knit_operator_name',
      'current_item', 'current_batch', 'current_weight', 'current_status', 'current_process', 'current_warehouse'
    ],
    limit: 25,
    orderBy: 'creation desc'
  })

export const getBatchesForItemCode = (itemCode) =>
  getList('Batch', {
    filters: [['Batch', 'item', '=', itemCode]],
    fields: ['name', 'batch_id', 'item'],
    limit: 200,
    orderBy: 'creation desc'
  })
