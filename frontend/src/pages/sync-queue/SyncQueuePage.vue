<template>
  <div class="page">
    <AppHeader title="Offline Queue" subtitle="Actions saved on this device" active="sync-queue" />
    <main class="page-content">
      <div class="card">
        <div class="qhead">
          <div>
            <span class="badge" :class="isOnline ? 'badge-success' : 'badge-danger'">{{ isOnline ? 'Online' : 'Offline' }}</span>
            <span class="muted small" v-if="lastSyncAt"> · last sync {{ when(lastSyncAt) }}</span>
          </div>
          <button class="btn btn-primary" :disabled="!isOnline || isSyncing || !pending.length" @click="syncNow">
            {{ isSyncing ? 'Syncing…' : 'Sync now' }}
          </button>
        </div>
        <p class="lead">
          Actions done without a network are kept here and sent to ERPNext in order when the
          connection is back. Actions on the same Job Card or transfer always go one after the other.
        </p>
      </div>

      <div class="card" v-if="failed.length">
        <div class="section-title">Need attention ({{ failed.length }})</div>
        <p class="lead">ERPNext refused these. Fix the cause (e.g. stock, a finished Job Card) and Retry, or Discard.
          Later actions on the same Job Card / transfer wait until this is resolved.</p>
        <div class="item item--failed" v-for="x in failed" :key="x.id">
          <div class="item__main">
            <b>{{ x.label || x.method }}</b>
            <div class="muted small">{{ when(x._createdAt) }} · {{ x.group || 'no group' }}</div>
            <div class="err">{{ x._error }}</div>
          </div>
          <div class="item__btns">
            <button class="btn btn-outline" :disabled="!isOnline" @click="retry(x)">Retry</button>
            <button class="btn btn-ghost danger" @click="discard(x)">Discard</button>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="section-title">Waiting to send ({{ pending.length }})</div>
        <div v-if="!pending.length" class="muted">Nothing waiting.</div>
        <div class="item" v-for="x in pending" :key="x.id">
          <div class="item__main">
            <b>{{ x.label || x.method }}</b>
            <div class="muted small">{{ when(x._createdAt) }} · {{ x.group || '' }}
              <span v-if="x._retries"> · tried {{ x._retries }}×: {{ x._error }}</span></div>
          </div>
          <span class="badge badge-warning">{{ x._status === 'syncing' ? 'sending' : 'waiting' }}</span>
        </div>
      </div>

      <div class="card" v-if="synced.length">
        <div class="section-title">Sent recently</div>
        <div class="item" v-for="x in synced" :key="x.id">
          <div class="item__main">
            <b>{{ x.label || x.method }}</b>
            <div class="muted small">done {{ when(x._createdAt) }} · sent {{ when(x._syncedAt) }}<span v-if="resultName(x)"> · {{ resultName(x) }}</span></div>
          </div>
          <span class="badge badge-success">sent</span>
        </div>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import AppHeader from '@/components/AppHeader.vue'
import { db } from '@/db'
import { isOnline, isSyncing, lastSyncAt, flushQueue, retryItem, discardItem } from '@/composables/useSync'

const pending = ref([])
const failed = ref([])
const synced = ref([])

async function refresh() {
  const all = await db.syncQueue.orderBy('_createdAt').toArray()
  pending.value = all.filter(x => x._status === 'pending' || x._status === 'syncing')
  failed.value = all.filter(x => x._status === 'failed')
  synced.value = all.filter(x => x._status === 'synced').reverse().slice(0, 30)
}
function when(t) { return t ? new Date(t).toLocaleString() : '' }
function resultName(x) {
  const r = x._result
  return r && (r.stock_entry || r.name || r.status) || ''
}
async function syncNow() { await flushQueue(); refresh() }
async function retry(x) { await retryItem(x.id); refresh() }
async function discard(x) {
  if (!confirm('Discard this action? It will not be sent to ERPNext.')) return
  await discardItem(x.id); refresh()
}

let t = null
watch(isSyncing, refresh)
onMounted(() => { refresh(); t = setInterval(refresh, 3000) })
onUnmounted(() => clearInterval(t))
</script>

<style scoped>
.qhead { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 8px; }
.lead { font-size: 13px; color: var(--slate-700); line-height: 1.5; margin: 6px 0 0; }
.item { display: flex; gap: 10px; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--slate-100); }
.item__main { flex: 1; min-width: 0; font-size: 14px; }
.item__btns { display: flex; gap: 6px; }
.item--failed { align-items: flex-start; }
.err { color: #b91c1c; font-size: 12px; margin-top: 4px; overflow-wrap: anywhere; }
.muted { color: var(--slate-500); }
.small { font-size: 12px; }
.danger { color: #b91c1c; }
</style>
