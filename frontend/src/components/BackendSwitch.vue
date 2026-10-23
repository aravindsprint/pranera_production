<template>
  <div class="bswitch" :class="{ 'bswitch--compact': compact }">
    <button
      v-for="b in options" :key="b.key" type="button"
      class="opt" :class="[`opt--${b.key}`, { 'opt--on': b.key === current }]"
      :disabled="busy" :aria-pressed="b.key === current" @click="pick(b.key)"
    >
      <span class="opt__top">
        <span class="opt__dot"></span>
        <span class="opt__name">{{ compact ? b.short : b.label }}</span>
        <span v-if="b.key === current" class="opt__tag">in use</span>
      </span>
      <span v-if="!compact" class="opt__sub">{{ b.target }}</span>
      <span v-if="!compact" class="opt__note">{{ b.key === 'live' ? 'Real data — anything you submit is real.' : 'Your test data. Needs the bench running on port 8001.' }}</span>
    </button>
  </div>
</template>

<script setup>
// Dev server only (rendered behind `isDev`). Same switch and cookie (pp_backend)
// as pranera_planning: the login cookie (sid) is shared by every app on
// localhost, so switching here switches the other dev apps too — on purpose.
import { ref } from 'vue'
import { BACKENDS, currentBackend, setBackend } from '@/config/backend'
import { isLoggedIn } from '@/api/frappe'
import { useAuthStore } from '@/stores/auth'
import { db } from '@/db'

defineProps({ compact: { type: Boolean, default: false } })

const auth = useAuthStore()
const options = Object.values(BACKENDS)
const current = ref(currentBackend())
const busy = ref(false)

// Data cached from one site must not show up on the other.
async function clearSiteCaches() {
  try {
    Object.keys(localStorage)
      .filter(k => k.startsWith('PROD_') && k !== 'PROD_THEME')
      .forEach(k => localStorage.removeItem(k))
  } catch { /* storage blocked */ }
  try { await db.delete() } catch { /* not open / blocked */ }
}

async function pick(mode) {
  if (mode === current.value || busy.value) return
  busy.value = true
  // Sign out of the backend we're leaving while requests still reach it.
  // A dead backend must not block the switch.
  try { if (isLoggedIn()) await auth.logout() } catch { /* switching anyway */ }
  await clearSiteCaches()
  setBackend(mode)
  // Full page load: re-runs main.js against the new backend.
  window.location.href = '/production-app/login'
}
</script>

<style scoped>
.bswitch { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.opt {
  text-align: left; background: #fff; border: 1.5px solid var(--slate-200); border-radius: var(--radius-md);
  padding: 12px 14px; display: flex; flex-direction: column; gap: 4px; color: var(--slate-700); font-family: inherit; cursor: pointer;
}
.opt:hover:not(:disabled) { border-color: var(--slate-400); }
.opt:disabled { opacity: 0.6; cursor: wait; }
.opt__top { display: flex; align-items: center; gap: 8px; }
.opt__dot { width: 9px; height: 9px; border-radius: 50%; background: var(--slate-400); flex-shrink: 0; }
.opt--live .opt__dot { background: #dc2626; }
.opt--local .opt__dot { background: #047857; }
.opt__name { font-size: 14px; font-weight: 650; color: var(--slate-900); }
.opt__tag { margin-left: auto; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--slate-500); }
.opt__sub { font-size: 12px; font-family: ui-monospace, Menlo, monospace; color: var(--slate-500); word-break: break-all; }
.opt__note { font-size: 12px; color: var(--slate-500); }
.opt--on.opt--live { border-color: #dc2626; background: #fff7f7; }
.opt--on.opt--local { border-color: #047857; background: #f3fbf7; }
.opt--on .opt__tag { color: var(--slate-900); }

.bswitch--compact { gap: 6px; }
.bswitch--compact .opt { padding: 8px 10px; }
.bswitch--compact .opt__name { font-size: 13px; }
@media (max-width: 520px) { .bswitch:not(.bswitch--compact) { grid-template-columns: 1fr; } }
</style>
