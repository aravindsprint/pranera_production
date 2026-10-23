// src/db/index.js — offline cache + sync queue for the Production App
import Dexie from 'dexie'

export const db = new Dexie('PraneraProductionDB')

db.version(1).stores({
  // lookup tables (populated by useSync.syncLookupTables)
  warehouses:            '&id, warehouse_name, modified',
  purchase_orders:       '&id, supplier, modified',
  subcontracting_orders: '&id, supplier, modified',
  mistakes:              '&key, inspection_type',

  // queued API calls made while offline: { method, args }
  syncQueue: '++id, method, _status, _retries, _createdAt',
})

// v2: queue items carry a group (e.g. 'jc:PO-JOB00076') — items of a group
// are sent strictly in order, and a stuck one holds back the rest.
db.version(2).stores({
  syncQueue: '++id, method, group, _status, _retries, _createdAt',
})

// _status values: 'pending' | 'syncing' | 'synced' | 'failed'
export default db
