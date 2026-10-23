<template>
  <div class="page">
    <AppHeader title="Settings" subtitle="Backend & site check" active="settings" />
    <main class="page-content">
      <div v-if="isDev" class="card">
        <div class="section-title">Backend</div>
        <p class="lead">
          Where this dev server sends its requests. Pick <b>Local bench</b> to test code that isn't
          deployed to erp.pranera.in yet, without touching live data.
        </p>
        <BackendSwitch />
        <p class="note">
          Switching signs you out of the current backend, clears this app's cached data and takes you
          to the login page, because the two sites have separate users and sessions. It takes effect
          immediately, with no restart of <code>yarn dev</code>. The other dev apps on localhost
          (Planning, Knit) switch with it, since they share the login cookie.
        </p>
      </div>

      <div class="card">
        <div class="section-title">Connection</div>
        <dl class="facts">
          <dt>Backend</dt>
          <dd>
            {{ backendLabel() }}
            <span v-if="isDev" class="badge" :class="mode === 'live' ? 'badge-danger' : 'badge-success'">{{ mode === 'live' ? 'LIVE DATA' : 'LOCAL' }}</span>
          </dd>

          <dt>Reachable</dt>
          <dd>
            <span v-if="busy" class="muted">Checking…</span>
            <span v-else-if="reach.ok" class="badge badge-success">Yes · {{ reach.ms }} ms</span>
            <span v-else class="badge badge-danger">{{ reach.error }}</span>
          </dd>

          <template v-if="!busy && reach.ok">
            <dt>Signed in as</dt>
            <dd>{{ info?.user || auth.frappeUser || 'Guest' }}</dd>
          </template>

          <template v-if="!busy && info">
            <dt>Site</dt><dd>{{ info.site }}</dd>
            <dt>pranera_production</dt>
            <dd>
              v{{ info.app_version }}
              <span class="badge" :class="info.installed ? 'badge-success' : 'badge-danger'">{{ info.installed ? 'Installed on this site' : 'Not installed on this site' }}</span>
            </dd>
            <dt>Your app roles</dt>
            <dd>
              <span v-if="!info.app_roles.length" class="badge badge-warning">None — menu items will be hidden</span>
              <span v-for="r in info.app_roles" :key="r" class="badge badge-secondary role">{{ r }}</span>
            </dd>
            <dt>Production App Settings</dt>
            <dd><span class="badge" :class="info.settings_ok ? 'badge-success' : 'badge-warning'">{{ info.settings_ok ? 'Saved' : 'Not saved yet — run bench migrate' }}</span></dd>
            <dt>Database fields</dt>
            <dd>
              <span v-if="!info.schema.missing.length" class="badge badge-success">All {{ info.schema.checked }} present</span>
              <span v-else class="badge badge-danger">{{ info.schema.missing.length }} missing</span>
            </dd>
          </template>
        </dl>

        <div v-if="!busy && info && !info.installed" class="alert alert-error"><div>
          The app's code is on this bench, but it is not installed on <b>{{ info.site }}</b>, so
          <code>bench migrate</code> skips it (no fields, no settings). Run
          <code>bench --site {{ info.site }} install-app pranera_production</code>, then
          <code>bench --site {{ info.site }} migrate</code>.
        </div></div>

        <div v-if="!busy && info && info.schema.missing.length" class="missing">
          <div v-if="info.is_system_manager" class="fixrow">
            <button class="btn btn-primary" :disabled="fixing" @click="fix">{{ fixing ? 'Creating…' : 'Create missing fields now' }}</button>
            <span class="muted small">Same as what migrate does. Existing fields are never changed.</span>
          </div>
          <div v-if="fixMsg" class="alert" :class="fixOk ? 'alert-success' : 'alert-warning'">{{ fixMsg }}</div>
          <div class="alert alert-warning"><div>
            This site is missing fields or doctypes the app reads, so some pages will fail with
            "Unknown column …". Run <code>bench --site {{ info.site }} migrate</code> — it creates any missing
            field (and never changes existing ones). Anything still listed after that needs the fix shown.
          </div></div>
          <table class="mtable">
            <thead><tr><th>Missing</th><th>From</th><th>Fix</th></tr></thead>
            <tbody>
              <tr v-for="m in info.schema.missing" :key="m.what">
                <td class="mono">{{ m.what }}</td><td>{{ m.source }}</td><td>{{ m.fix }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="!busy && reach.ok && !info" class="alert alert-warning">
          <template v-if="notLoggedIn">Sign in to check this site.</template>
          <template v-else>
            pranera_production is not installed or not up to date on this backend, so its pages will not work here.
            <template v-if="isDev && mode === 'live'"> Switch to <b>Local bench</b> to test them.</template>
          </template>
          <div v-if="infoError && !notLoggedIn" class="detail">{{ infoError }}</div>
        </div>

        <button class="btn btn-outline" :disabled="busy" @click="check">Check again</button>
      </div>

      <div class="card" v-if="!busy && info">
        <div class="section-title">Page check</div>
        <p class="lead">Runs the query behind every page on this site, the same way the page does, and lists any that fail. Nothing is written.</p>
        <button class="btn btn-primary" :disabled="checking" @click="runPages">{{ checking ? 'Checking pages…' : (pages ? 'Run again' : 'Check all pages') }}</button>
        <div v-if="pagesError" class="alert alert-error" style="margin-top:12px">{{ pagesError }}</div>
        <template v-if="pages">
          <div class="summary">
            <span class="badge badge-success">{{ pages.passed }} OK</span>
            <span class="badge" :class="pages.failed ? 'badge-danger' : 'badge-success'">{{ pages.failed }} failed</span>
            <span class="badge badge-secondary">{{ pages.results.length - pages.passed - pages.failed }} skipped</span>
          </div>
          <table class="mtable">
            <thead><tr><th>Page</th><th>Check</th><th>Result</th></tr></thead>
            <tbody>
              <tr v-for="(r, i) in sortedPages" :key="i" :class="'r-' + r.status">
                <td>{{ r.page }}</td>
                <td class="mono">{{ r.check }}</td>
                <td>
                  <span v-if="r.status === 'ok'" class="ok">✓ {{ r.ms }} ms</span>
                  <span v-else-if="r.status === 'skipped'" class="muted">skipped — {{ r.error }}</span>
                  <span v-else class="err">{{ r.error }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </template>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import AppHeader from '@/components/AppHeader.vue'
import BackendSwitch from '@/components/BackendSwitch.vue'
import { useAuthStore } from '@/stores/auth'
import { call, isLoggedIn } from '@/api/frappe'
import { isDev, currentBackend, backendLabel } from '@/config/backend'

const auth = useAuthStore()
const mode = currentBackend()

const busy = ref(true)
const reach = reactive({ ok: false, ms: 0, error: '' })
const info = ref(null)
const infoError = ref('')
const notLoggedIn = computed(() => !isLoggedIn())
const fixing = ref(false)
const fixMsg = ref('')
const fixOk = ref(false)
const checking = ref(false)
const pages = ref(null)
const pagesError = ref('')
const ORDER = { error: 0, skipped: 1, ok: 2 }
const sortedPages = computed(() => [...(pages.value?.results || [])].sort((a, b) => ORDER[a.status] - ORDER[b.status]))

async function fix() {
  fixing.value = true
  fixMsg.value = ''
  try {
    const r = (await call('pranera_production.api.health.fix_schema')).message
    fixOk.value = !r.skipped.length
    fixMsg.value = `Created ${r.created.length} field(s).` + (r.skipped.length ? ` Could not create: ${r.skipped.join('; ')}` : '')
    await check()
    if (pages.value) await runPages()
  } catch (e) {
    fixOk.value = false
    fixMsg.value = e.message
  } finally {
    fixing.value = false
  }
}

async function runPages() {
  checking.value = true
  pagesError.value = ''
  try {
    pages.value = (await call('pranera_production.api.health.check_pages')).message
  } catch (e) {
    pagesError.value = e.message
  } finally {
    checking.value = false
  }
}

async function check() {
  busy.value = true
  info.value = null
  infoError.value = ''
  reach.ok = false

  // 1. Is the backend there at all? `ping` needs no login.
  const t0 = performance.now()
  try {
    const r = await fetch('/api/method/ping', { credentials: 'include' })
    const data = await r.json().catch(() => null)
    if (!r.ok) {
      reach.error = data?.exception?.split(': ').slice(1).join(': ') || `HTTP ${r.status}`
    } else if (data?.message !== 'pong') {
      reach.error = 'Answered, but not like a Frappe site — check the proxy target'
    } else {
      reach.ok = true
      reach.ms = Math.round(performance.now() - t0)
    }
  } catch (e) {
    reach.error = e.message || 'Network error'
  }

  // 2. Is this app deployed there, and does the site have every field it reads?
  if (reach.ok && isLoggedIn()) {
    try {
      info.value = (await call('pranera_production.api.common.get_app_info')).message
    } catch (e) {
      infoError.value = e.message
    }
  }
  busy.value = false
}

onMounted(check)
</script>

<style scoped>
.lead { font-size: 14px; color: var(--slate-700); margin-bottom: 14px; line-height: 1.5; }
.note { font-size: 12px; color: var(--slate-500); margin-top: 12px; line-height: 1.5; }
.facts { display: grid; grid-template-columns: max-content 1fr; gap: 8px 20px; margin-bottom: 16px; font-size: 14px; align-items: center; }
dt { color: var(--slate-500); }
dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
.muted { color: var(--slate-500); }
.role { margin: 0 4px 4px 0; }
.detail { font-weight: 400; font-size: 12px; margin-top: 6px; opacity: 0.85; }
code { background: var(--slate-100); padding: 1px 6px; border-radius: 4px; font-size: 12px; }
.missing { margin-bottom: 16px; }
.fixrow { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
.summary { display: flex; gap: 8px; margin: 14px 0 4px; }
.small { font-size: 12px; }
.ok { color: #047857; font-weight: 600; }
.err { color: #dc2626; font-size: 12px; overflow-wrap: anywhere; }
.r-error td { background: #fff7f7; }
.mtable { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 10px; }
.mtable th { text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--slate-500); padding: 6px 8px; border-bottom: 1px solid var(--slate-200); }
.mtable td { padding: 6px 8px; border-bottom: 1px solid var(--slate-100); vertical-align: top; }
.mono { font-family: ui-monospace, Menlo, monospace; font-size: 12px; overflow-wrap: anywhere; }
@media (max-width: 520px) { .facts { grid-template-columns: 1fr; gap: 2px; } dd { margin-bottom: 8px; } }
</style>
