// src/stores/auth.js — Frappe session + the app roles that decide which
// screens a user sees (Production Supervisor, Roll Picker, Chemical Issuer,
// Process Operator, Inspection Checker).
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api, ensureCSRF, resetCSRF } from '@/api/frappe'

const CACHE_KEY = 'PROD_SESSION'

export const useAuthStore = defineStore('auth', () => {
  const cached = JSON.parse(localStorage.getItem(CACHE_KEY) || 'null')
  const frappeUser = ref(window.__FRAPPE_SESSION__?.user || '')
  const isLoggedIn = ref(!!frappeUser.value && frappeUser.value !== 'Guest')
  const info = ref(cached && cached.user === frappeUser.value ? cached : null)
  const loading = ref(false)
  const error = ref('')

  const username = computed(() => info.value?.full_name || frappeUser.value)
  const designation = computed(() => info.value?.designation || (info.value?.roles || [])[0] || '')
  const roles = computed(() => new Set(info.value?.roles || []))
  const settings = computed(() => info.value?.settings || {})
  const hasAccess = computed(() => !!info.value?.has_access)

  const isAdmin = computed(() => roles.value.has('System Manager') || roles.value.has('Manufacturing Manager') || frappeUser.value === 'Administrator')
  function can(...need) {
    if (isAdmin.value || roles.value.has('Production Supervisor')) return true
    return need.some(r => roles.value.has(r))
  }

  function refreshSession() {
    const u = window.__FRAPPE_SESSION__?.user || ''
    frappeUser.value = u
    isLoggedIn.value = !!u && u !== 'Guest'
  }

  async function loadSession() {
    if (!isLoggedIn.value) return false
    loading.value = true
    error.value = ''
    try {
      const s = await api.session()
      info.value = s
      localStorage.setItem(CACHE_KEY, JSON.stringify(s))
      return s.has_access
    } catch (err) {
      error.value = err.message
      return hasAccess.value // keep working offline on the cached session
    } finally {
      loading.value = false
    }
  }

  async function login(email, password) {
    loading.value = true
    error.value = ''
    try {
      const res = await fetch('/api/method/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ usr: email, pwd: password }).toString(),
        credentials: 'include',
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok || data.message !== 'Logged In') {
        let m = 'Incorrect email or password'
        try {
          const msgs = JSON.parse(data._server_messages || '[]')
          if (msgs.length) m = JSON.parse(msgs[msgs.length - 1]).message || m
        } catch { /* keep default */ }
        throw new Error(m)
      }
      return true
    } catch (err) {
      error.value = err.message || 'Login failed'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function logout() {
    try {
      const token = await ensureCSRF()
      await fetch('/api/method/frappe.auth.logout', { method: 'POST', headers: { 'X-Frappe-CSRF-Token': token }, credentials: 'include' })
    } catch { /* still clear local state */ }
    localStorage.removeItem(CACHE_KEY)
    info.value = null
    resetCSRF()
    if (window.__FRAPPE_SESSION__) window.__FRAPPE_SESSION__.user = 'Guest'
    frappeUser.value = 'Guest'
    isLoggedIn.value = false
  }

  return {
    frappeUser, isLoggedIn, info, loading, error,
    username, designation, roles, settings, hasAccess, isAdmin,
    can, refreshSession, loadSession, login, logout,
  }
})
