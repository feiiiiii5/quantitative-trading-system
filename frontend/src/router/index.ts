import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import Market from '../views/Market.vue'
import StrategyIntro from '../views/StrategyIntro.vue'
import Strategy from '../views/Strategy.vue'
import Portfolio from '../views/Portfolio.vue'
import Watchlist from '../views/Watchlist.vue'
import StockDetail from '../views/StockDetail.vue'

const routes = [
  { path: '/', name: 'Dashboard', component: Dashboard },
  { path: '/market', name: 'Market', component: Market },
  { path: '/strategy-intro', name: 'StrategyIntro', component: StrategyIntro },
  { path: '/strategy', name: 'Strategy', component: Strategy },
  { path: '/portfolio', name: 'Portfolio', component: Portfolio },
  { path: '/watchlist', name: 'Watchlist', component: Watchlist },
  { path: '/stock/:code', name: 'StockDetail', component: StockDetail },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router