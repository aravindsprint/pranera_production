// src/composables/useOffline.js
// Offline helpers for the floor pages (Job Card, Dye Chart, Verify Rolls):
//   * cached(key, fetcher) — fetch and keep a copy; offline, return the copy
//   * Job Card Start / End that work offline (queued with the device time)
//   * an overlay so a Job Card shows "running" / "ended" while its queued
//     actions haven't reached ERPNext yet
import { callOrQueue, groupHasPending, localNow, isOnline } from '@/composables/useSync'

const CACHE = 'PROD_CACHE_'
const OVL = 'PROD_JC_OVL_'
const NETWORK_ERR = /Failed to fetch|NetworkError|Load failed|network|BackendUnreachable|timed? ?out|502|503|504/i

const read = (k) => { try { return JSON.parse(localStorage.getItem(k) || 'null') } catch { return null } }
const write = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)) } catch { /* storage full */ } }

export function cacheGet(key) { return read(CACHE + key) }
export function cachePut(key, data) { write(CACHE + key, { at: new Date().toISOString(), data }) }

// { data, offline, at } — offline: true when the copy came from the device
export async function cached(key, fetcher) {
  try {
    if (!isOnline.value) throw new Error('network: offline')
    const data = await fetcher()
    cachePut(key, data)
    return { data, offline: false, at: null }
  } catch (err) {
    const c = cacheGet(key)
    if (c && NETWORK_ERR.test(err.message || '')) return { data: c.data, offline: true, at: c.at }
    throw err
  }
}

export const jcGroup = (jobCard) => 'jc:' + jobCard
const M = 'pranera_production.api.process.'

export async function startJobCard(jobCard) {
  const from_time = localNow()
  const r = await callOrQueue(M + 'start_job_card', { job_card: jobCard, from_time },
    `Start ${jobCard}`, { group: jcGroup(jobCard), clientId: true })
  if (r?.queued) write(OVL + jobCard, { ...(read(OVL + jobCard) || {}), running_since: from_time })
  return r
}

export async function completeJobCard(jobCard, completedQty) {
  const to_time = localNow()
  const r = await callOrQueue(M + 'complete_job_card',
    { job_card: jobCard, completed_qty: completedQty, submit: 1, to_time },
    `End ${jobCard} (${completedQty})`, { group: jcGroup(jobCard), clientId: true })
  if (r?.queued) write(OVL + jobCard, { ...(read(OVL + jobCard) || {}), ended_at: to_time, completed_qty: completedQty })
  return r
}

// Apply queued (not yet synced) Start/End to a job_card object from the
// server or the cache. Returns the pending state, or null once synced.
export async function applyJobCardOverlay(jobCard, jc) {
  const ovl = read(OVL + jobCard)
  if (!ovl) return null
  if (!(await groupHasPending(jcGroup(jobCard)))) {
    localStorage.removeItem(OVL + jobCard)
    return null
  }
  if (jc) {
    if (ovl.running_since && !jc.running_since && jc.docstatus === 0) {
      jc.running_since = ovl.running_since
      jc.running = true
      jc.status = 'Work In Progress'
    }
    if (ovl.ended_at) {
      jc.running_since = null
      jc.running = false
      jc.status = 'Completed'
      jc.pending_end = true
    }
  }
  return ovl
}
