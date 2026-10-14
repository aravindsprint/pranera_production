import { api } from '@/api/frappe'
import { db } from '@/db'

export const BASE = '/production-app'

export function fmt(n, d = 2) {
  const v = Number(n)
  return Number.isFinite(v) ? v.toFixed(d) : (0).toFixed(d)
}

export function today() {
  const d = new Date()
  const z = (x) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`
}

export function daysAgo(n) {
  const d = new Date(Date.now() - n * 86400000)
  const z = (x) => String(x).padStart(2, '0')
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`
}

export function isPcs(uom) {
  return ['pcs', 'nos', 'pc'].includes(String(uom || '').trim().toLowerCase())
}

// Warehouse search: offline cache first (Dexie), live search as fallback
export async function warehouseFetcher(txt) {
  const q = String(txt || '').toLowerCase()
  try {
    const rows = await db.warehouses.toArray()
    if (rows.length) {
      return rows
        .filter(r => !q || r.id.toLowerCase().includes(q))
        .slice(0, 40)
        .map(r => ({ value: r.id }))
    }
  } catch { /* fall through */ }
  const live = await api.searchLink('Warehouse', txt)
  return live.map(r => ({ value: r.name }))
}

export const userFetcher = async (txt) =>
  (await api.searchLink('User', txt, {}, ['name', 'full_name'])).map(u => ({ value: u.name, label: u.full_name || u.name, description: u.name }))

export function statusClass(s) {
  const v = String(s || '').toLowerCase()
  if (['completed', 'in stock', 'submitted'].includes(v)) return 'badge-success'
  if (['in progress', 'work in progress', 'in process', 'material transferred'].includes(v)) return 'badge-info'
  if (['pending', 'open', 'draft', 'not started'].includes(v)) return 'badge-warning'
  if (['cancelled', 'on hold', 'stopped'].includes(v)) return 'badge-danger'
  return 'badge-secondary'
}

export function gradeClass(g) {
  return { '1': 'badge-success', 'Direct': 'badge-info', '2': 'badge-warning', '3': 'badge-danger' }[String(g)] || 'badge-secondary'
}
