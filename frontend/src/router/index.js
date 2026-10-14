import { createRouter, createWebHistory } from 'vue-router'
import { isLoggedIn } from '@/api/frappe'

// Eager pages work offline (shell cached by the service worker).
import HomePage            from '@/pages/home/HomePage.vue'
import LoginPage           from '@/pages/login/LoginPage.vue'
import InspectionListPage  from '@/pages/inspection/InspectionListPage.vue'
import InspectionPage      from '@/pages/inspection/InspectionPage.vue'
import RollInspectPage     from '@/pages/inspection/RollInspectPage.vue'
import RollsPage           from '@/pages/rolls/RollsPage.vue'

const B = '/production-app'

const routes = [
  { path: '/', redirect: B + '/home' },
  { path: B, redirect: B + '/home' },
  { path: B + '/login', component: LoginPage },

  { path: B + '/home', component: HomePage },
  { path: B + '/inspection', component: InspectionListPage },
  { path: B + '/inspection/:jobCard', component: InspectionPage, props: true },
  { path: B + '/inspection/:jobCard/roll/:rollNo', component: RollInspectPage, props: true },
  { path: B + '/rolls', component: RollsPage },

  { path: B + '/create-pick-order', component: () => import('@/pages/create-pick-order/CreatePickOrderPage.vue') },
  { path: B + '/my-pick-orders', component: () => import('@/pages/my-pick-orders/MyPickOrdersPage.vue') },
  { path: B + '/pick-execution', component: () => import('@/pages/pick-execution/PickExecutionPage.vue') },
  { path: B + '/chemical-issue', component: () => import('@/pages/chemical-issue/ChemicalIssuePage.vue') },
  { path: B + '/job-cards', component: () => import('@/pages/job-cards/JobCardsPage.vue') },
  { path: B + '/job-cards/:jobCard', component: () => import('@/pages/job-cards/JobCardDetailPage.vue'), props: true },
  { path: B + '/manufacture', component: () => import('@/pages/manufacture/ManufacturePage.vue') },
  { path: B + '/create-rolls', component: () => import('@/pages/create-rolls/CreateRollsPage.vue') },
  { path: B + '/dashboard', component: () => import('@/pages/dashboard/DashboardPage.vue') },
  { path: B + '/lot-report', component: () => import('@/pages/lot-report/LotReportPage.vue') },
  { path: B + '/adopt-rolls', component: () => import('@/pages/adopt-rolls/AdoptRollsPage.vue') },
  { path: B + '/pivot', component: () => import('@/pages/pivot/PivotPage.vue') },
  { path: B + '/no-access', component: () => import('@/pages/NoAccessPage.vue') },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const loggedIn = isLoggedIn()
  if (to.path !== B + '/login' && !loggedIn) return { path: B + '/login', query: { redirect: to.fullPath } }
  if (to.path === B + '/login' && loggedIn) return { path: B + '/home' }
  return true
})

export default router
