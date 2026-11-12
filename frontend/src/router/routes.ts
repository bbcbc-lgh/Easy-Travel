import type { RouteRecordRaw } from 'vue-router'

/**
 * The route table on its own, with no router instance.
 *
 * Split out so it can be read and tested without `createWebHistory`, and so every
 * view stays lazy: importing this module must not pull in a view and its
 * dependencies.
 */
export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'home',
    component: () => import('../views/HomeView.vue')
  },
  {
    path: '/plans',
    name: 'history',
    component: () => import('../views/HistoryView.vue')
  },
  {
    path: '/result',
    name: 'result',
    component: () => import('../views/ResultView.vue')
  },
  {
    // A shared or reloaded plan link. Must not be swallowed by '/result'.
    path: '/result/:id',
    name: 'plan-detail',
    component: () => import('../views/ResultView.vue')
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('../views/NotFoundView.vue')
  }
]
