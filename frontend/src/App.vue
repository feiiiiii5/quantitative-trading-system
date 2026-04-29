<template>
  <div class="app">
    <aside class="sidebar">
      <div class="sidebar-brand">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none">
          <path d="M3 18L9 9L15 15L21 3" stroke="url(#brand-grad)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
          <defs><linearGradient id="brand-grad" x1="3" y1="18" x2="21" y2="3"><stop stop-color="#2997ff"/><stop offset="1" stop-color="#5ac8fa"/></linearGradient></defs>
        </svg>
        <span class="brand-name">QuantCore</span>
      </div>
      <nav class="sidebar-nav">
        <router-link v-for="(item, idx) in navItems" :key="item.path" :to="item.path" class="nav-item" :class="{ active: isActive(item.path) }" :style="{ animationDelay: idx * 0.05 + 's' }">
          <span class="nav-icon" v-html="item.icon"></span>
          <span class="nav-label">{{ item.label }}</span>
          <span class="nav-indicator"></span>
        </router-link>
      </nav>
      <div class="sidebar-footer">
        <div class="market-status" :class="{ open: isMarketOpen }">
          <span class="status-dot"></span>
          <span>{{ marketSessionName }}</span>
        </div>
      </div>
    </aside>
    <div class="main-wrapper">
      <div class="top-bar">
        <div class="search-box">
          <svg class="search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
          <input
            v-model="searchQuery"
            @input="onSearchInput"
            @keydown.up.prevent="selectPrev"
            @keydown.down.prevent="selectNext"
            @keydown.enter="goSelected"
            @keydown.esc="closeSearch"
            @blur="onBlur"
            @focus="onFocus"
            placeholder="搜索股票代码/名称/拼音 (如 gzmt)"
            class="search-input"
          />
          <Transition name="dropdown">
            <div v-if="showDropdown && searchResults.length" class="search-dropdown">
              <div
                v-for="(r, i) in searchResults"
                :key="r.code"
                class="search-item"
                :class="{ selected: i === selectedIndex }"
                @click="goResult(r)"
                @mousedown.prevent="goResult(r)"
                @mouseenter="selectedIndex = i"
                :style="{ animationDelay: i * 0.03 + 's' }"
              >
                <div class="si-left">
                  <span class="si-code">{{ r.code }}</span>
                  <span class="si-name">{{ r.name }}</span>
                </div>
                <div class="si-right">
                  <span class="si-market">{{ r.market }}</span>
                  <span v-if="r._price" class="si-price" :class="r._pct >= 0 ? 'up' : 'down'">{{ r._price?.toFixed(2) }}</span>
                  <span v-if="r._pct !== undefined" class="si-pct" :class="r._pct >= 0 ? 'up' : 'down'">
                    {{ r._pct >= 0 ? '+' : '' }}{{ r._pct?.toFixed(2) }}%
                  </span>
                </div>
              </div>
            </div>
          </Transition>
        </div>
      </div>
      <main class="main-content">
        <router-view v-slot="{ Component, route: currentRoute }">
          <Transition :name="transitionName" mode="out-in">
            <component :is="Component" :key="currentRoute.path" />
          </Transition>
        </router-view>
      </main>
    </div>
    <div class="noise-overlay"></div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { api } from './api'

const router = useRouter()
const route = useRoute()

const transitionName = ref('page-slide')

watch(() => route.path, (to, from) => {
  if (!from) {
    transitionName.value = 'page-fade'
    return
  }
  const toDepth = to.split('/').length
  const fromDepth = from.split('/').length
  if (toDepth > fromDepth) {
    transitionName.value = 'page-slide-left'
  } else if (toDepth < fromDepth) {
    transitionName.value = 'page-slide-right'
  } else {
    transitionName.value = 'page-fade'
  }
})

function isActive(path: string) {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

const navItems = [
  { path: '/', label: '市场总览', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/></svg>' },
  { path: '/market', label: '市场浏览', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 6h18M3 12h18M3 18h18"/><circle cx="8" cy="6" r="2" fill="currentColor"/><circle cx="16" cy="12" r="2" fill="currentColor"/><circle cx="10" cy="18" r="2" fill="currentColor"/></svg>' },
  { path: '/strategy-intro', label: '策略介绍', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/><path d="M8 7h8M8 11h5"/></svg>' },
  { path: '/strategy', label: '策略回测', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>' },
  { path: '/portfolio', label: '组合管理', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/><path d="M9 12l2 2 4-4"/></svg>' },
  { path: '/watchlist', label: '自选股', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>' },
]

const isMarketOpen = computed(() => {
  const now = new Date()
  const day = now.getDay()
  if (day === 0 || day === 6) return false
  const h = now.getHours()
  const m = now.getMinutes()
  const t = h * 60 + m
  return (t >= 570 && t <= 690) || (t >= 780 && t <= 900)
})

const marketSessionName = computed(() => {
  const now = new Date()
  const day = now.getDay()
  if (day === 0 || day === 6) return '休市'
  const h = now.getHours()
  const m = now.getMinutes()
  const t = h * 60 + m
  if (t < 555) return '盘前'
  if (t < 570) return '集合竞价'
  if (t <= 690) return '交易中'
  if (t < 780) return '午休'
  if (t <= 900) return '交易中'
  return '已收盘'
})

const searchQuery = ref('')
const searchResults = ref<any[]>([])
const selectedIndex = ref(0)
const showDropdown = ref(false)
let searchTimer: any = null

async function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  if (!searchQuery.value.trim()) {
    searchResults.value = []
    showDropdown.value = false
    return
  }
  searchTimer = setTimeout(async () => {
    try {
      const results = await api.search(searchQuery.value.trim(), 8)
      searchResults.value = results || []
      selectedIndex.value = 0
      showDropdown.value = true
      fetchPrices(searchResults.value)
    } catch (e) {
      searchResults.value = []
    }
  }, 200)
}

async function fetchPrices(results: any[]) {
  for (const r of results.slice(0, 5)) {
    try {
      const rt = await api.getRealtime(r.code)
      if (rt) {
        r._price = rt.price
        r._pct = rt.pct
      }
    } catch (e) {}
  }
}

function selectPrev() {
  if (selectedIndex.value > 0) selectedIndex.value--
}

function selectNext() {
  if (selectedIndex.value < searchResults.value.length - 1) selectedIndex.value++
}

function goSelected() {
  if (searchResults.value.length > 0 && selectedIndex.value < searchResults.value.length) {
    goResult(searchResults.value[selectedIndex.value])
  }
}

function goResult(r: any) {
  searchQuery.value = ''
  searchResults.value = []
  showDropdown.value = false
  router.push(`/stock/${r.code}`)
}

function closeSearch() {
  showDropdown.value = false
}

function onBlur() {
  setTimeout(() => { showDropdown.value = false }, 300)
}

function onFocus() {
  if (searchResults.value.length > 0) {
    showDropdown.value = true
  }
}
</script>

<style>
:root {
  --bg-primary: #06060a;
  --bg-secondary: #0e0e14;
  --bg-tertiary: #16161f;
  --bg-elevated: #22222e;
  --text-primary: #f0f0f2;
  --text-secondary: #9494a6;
  --text-tertiary: #5a5a6e;
  --border-color: rgba(255,255,255,0.06);
  --border-light: rgba(255,255,255,0.03);
  --accent-blue: #4d9fff;
  --accent-green: #34d399;
  --accent-red: #f43f5e;
  --accent-orange: #fb923c;
  --accent-purple: #a78bfa;
  --accent-cyan: #22d3ee;
  --font-sans: 'DM Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: 'JetBrains Mono', 'SF Mono', 'Fira Code', Menlo, monospace;
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-xl: 24px;
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.5);
  --shadow-md: 0 4px 20px rgba(0,0,0,0.6);
  --shadow-lg: 0 12px 48px rgba(0,0,0,0.7);
  --shadow-glow-blue: 0 0 24px rgba(77,159,255,0.12);
  --shadow-glow-red: 0 0 24px rgba(244,63,94,0.12);
  --shadow-glow-green: 0 0 24px rgba(52,211,153,0.12);
  --transition: 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  --transition-spring: 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
  --transition-slow: 0.5s cubic-bezier(0.4, 0, 0.2, 1);
}

* { margin: 0; padding: 0; box-sizing: border-box; }

html, body { height: 100%; }

body {
  font-family: var(--font-sans);
  background: var(--bg-primary);
  color: var(--text-primary);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

#app { height: 100%; }

.app {
  display: flex;
  height: 100vh;
  overflow: hidden;
  position: relative;
}

.noise-overlay {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 9999;
  opacity: 0.025;
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
  background-repeat: repeat;
  background-size: 256px 256px;
}

.sidebar {
  width: 220px;
  min-width: 220px;
  background: linear-gradient(180deg, rgba(10,10,16,0.97), rgba(6,6,10,0.99));
  backdrop-filter: blur(40px) saturate(200%);
  -webkit-backdrop-filter: blur(40px) saturate(200%);
  border-right: 1px solid rgba(255,255,255,0.04);
  display: flex;
  flex-direction: column;
  padding: 20px 12px;
  position: relative;
  z-index: 10;
}

.sidebar::after {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  width: 1px;
  height: 100%;
  background: linear-gradient(180deg, transparent, rgba(77,159,255,0.12), rgba(167,139,250,0.08), transparent);
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 12px;
  margin-bottom: 28px;
  animation: brandFadeIn 0.6s ease-out;
}

@keyframes brandFadeIn {
  from { opacity: 0; transform: translateX(-12px); }
  to { opacity: 1; transform: translateX(0); }
}

.brand-name {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.5px;
  background: linear-gradient(135deg, #4d9fff, #22d3ee, #a78bfa);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.sidebar-nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  transition: all var(--transition);
  cursor: pointer;
  position: relative;
  overflow: hidden;
  animation: navSlideIn 0.5s ease-out both;
}

@keyframes navSlideIn {
  from { opacity: 0; transform: translateX(-16px); }
  to { opacity: 1; transform: translateX(0); }
}

.nav-item::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, rgba(77,159,255,0.06), rgba(34,211,238,0.03));
  opacity: 0;
  transition: opacity var(--transition);
}

.nav-item:hover {
  color: var(--text-primary);
  transform: translateX(2px);
}

.nav-item:hover::before {
  opacity: 1;
}

.nav-item.active {
  color: var(--accent-blue);
}

.nav-item.active::before {
  opacity: 1;
}

.nav-indicator {
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%) scaleY(0);
  width: 3px;
  height: 20px;
  border-radius: 0 3px 3px 0;
  background: linear-gradient(180deg, var(--accent-blue), var(--accent-cyan), var(--accent-purple));
  transition: transform var(--transition-spring);
}

.nav-item.active .nav-indicator {
  transform: translateY(-50%) scaleY(1);
}

.nav-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  transition: transform var(--transition);
}

.nav-item:hover .nav-icon {
  transform: scale(1.1);
}

.nav-label { white-space: nowrap; position: relative; z-index: 1; }

.sidebar-footer {
  padding: 12px;
  border-top: 1px solid var(--border-color);
  margin-top: 12px;
}

.market-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-tertiary);
}

.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-tertiary);
  transition: all 0.3s;
}

.market-status.open .status-dot {
  background: var(--accent-green);
  box-shadow: 0 0 8px var(--accent-green);
  animation: statusPulse 2s infinite;
}

@keyframes statusPulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(45,212,168,0.5); }
  50% { box-shadow: 0 0 0 6px rgba(45,212,168,0); }
}

.main-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.top-bar {
  height: 52px;
  min-height: 52px;
  background: linear-gradient(90deg, rgba(10,10,16,0.85), rgba(14,14,20,0.9));
  backdrop-filter: blur(40px) saturate(200%);
  -webkit-backdrop-filter: blur(40px) saturate(200%);
  border-bottom: 1px solid rgba(255,255,255,0.04);
  display: flex;
  align-items: center;
  padding: 0 20px;
  position: relative;
  z-index: 100;
}

.top-bar::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(77,159,255,0.08), rgba(167,139,250,0.06), transparent);
}

.search-box {
  position: relative;
  width: 400px;
  max-width: 50%;
}

.search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-tertiary);
  pointer-events: none;
  transition: color var(--transition);
}

.search-input {
  width: 100%;
  height: 34px;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: var(--radius-sm);
  padding: 0 12px 0 36px;
  color: var(--text-primary);
  font-size: 13px;
  font-family: var(--font-sans);
  outline: none;
  transition: all var(--transition);
}

.search-input:focus {
  border-color: rgba(59,139,255,0.4);
  background: rgba(255,255,255,0.06);
  box-shadow: 0 0 0 3px rgba(59,139,255,0.08);
}

.search-input:focus + .search-icon,
.search-input:focus ~ .search-icon {
  color: var(--accent-blue);
}

.search-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  background: rgba(14,14,20,0.95);
  backdrop-filter: blur(32px) saturate(200%);
  -webkit-backdrop-filter: blur(32px) saturate(200%);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: var(--radius-md);
  margin-top: 6px;
  max-height: 320px;
  overflow-y: auto;
  z-index: 1000;
  box-shadow: 0 16px 48px rgba(0,0,0,0.6), 0 0 0 1px rgba(255,255,255,0.05);
}

.search-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  cursor: pointer;
  transition: all 0.15s;
  animation: searchItemIn 0.2s ease-out both;
}

@keyframes searchItemIn {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}

.search-item:hover,
.search-item.selected {
  background: rgba(59,139,255,0.1);
}

.si-left {
  display: flex;
  gap: 10px;
  align-items: center;
}

.si-code {
  font-family: var(--font-mono);
  font-size: 13px;
  color: var(--accent-cyan);
  min-width: 60px;
}

.si-name {
  font-size: 13px;
  color: var(--text-primary);
}

.si-right {
  display: flex;
  gap: 8px;
  align-items: center;
}

.si-market {
  font-size: 11px;
  color: var(--text-tertiary);
  background: rgba(255,255,255,0.05);
  padding: 2px 8px;
  border-radius: 4px;
}

.si-price {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 600;
}

.si-pct {
  font-family: var(--font-mono);
  font-size: 12px;
}

.up { color: var(--accent-red) !important; }
.down { color: var(--accent-green) !important; }

.main-content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
}

.main-content::-webkit-scrollbar { width: 5px; }
.main-content::-webkit-scrollbar-track { background: transparent; }
.main-content::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 3px; }
.main-content::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.14); }

.font-mono { font-family: var(--font-mono); }
.text-up { color: var(--accent-red) !important; }
.text-down { color: var(--accent-green) !important; }

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.fade-in { animation: fadeIn 0.4s ease-out; }

.page-fade-enter-active { transition: all 0.3s ease-out; }
.page-fade-leave-active { transition: all 0.2s ease-in; }
.page-fade-enter-from { opacity: 0; transform: translateY(8px); }
.page-fade-leave-to { opacity: 0; transform: translateY(-4px); }

.page-slide-left-enter-active { transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1); }
.page-slide-left-leave-active { transition: all 0.2s ease-in; }
.page-slide-left-enter-from { opacity: 0; transform: translateX(30px); }
.page-slide-left-leave-to { opacity: 0; transform: translateX(-20px); }

.page-slide-right-enter-active { transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1); }
.page-slide-right-leave-active { transition: all 0.2s ease-in; }
.page-slide-right-enter-from { opacity: 0; transform: translateX(-30px); }
.page-slide-right-leave-to { opacity: 0; transform: translateX(20px); }

.dropdown-enter-active { transition: all 0.25s cubic-bezier(0.34, 1.56, 0.64, 1); }
.dropdown-leave-active { transition: all 0.15s ease-in; }
.dropdown-enter-from { opacity: 0; transform: translateY(-8px) scale(0.98); }
.dropdown-leave-to { opacity: 0; transform: translateY(-4px) scale(0.99); }

.card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 20px;
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 16px;
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  font-weight: 600;
  border: none;
  cursor: pointer;
  transition: all var(--transition);
  font-family: var(--font-sans);
  position: relative;
  overflow: hidden;
}

.btn::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, rgba(255,255,255,0.1), transparent);
  opacity: 0;
  transition: opacity var(--transition);
}

.btn:hover::after { opacity: 1; }

.btn:active { transform: scale(0.97); }

.btn-primary {
  background: var(--accent-blue);
  color: white;
}
.btn-primary:hover { background: #2a7ae8; box-shadow: var(--shadow-glow-blue); }

.btn-success {
  background: var(--accent-red);
  color: white;
}
.btn-success:hover { box-shadow: var(--shadow-glow-red); }

.btn-danger {
  background: var(--accent-green);
  color: white;
}
.btn-danger:hover { box-shadow: var(--shadow-glow-green); }

.btn-ghost {
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border-color);
}
.btn-ghost:hover { background: rgba(255,255,255,0.05); color: var(--text-primary); border-color: rgba(255,255,255,0.12); }

input, select {
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: var(--radius-sm);
  padding: 8px 12px;
  color: var(--text-primary);
  font-size: 13px;
  font-family: var(--font-sans);
  outline: none;
  transition: all var(--transition);
}

input:focus, select:focus {
  border-color: rgba(59,139,255,0.4);
  box-shadow: 0 0 0 3px rgba(59,139,255,0.08);
}

.skeleton {
  background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--bg-elevated) 50%, var(--bg-tertiary) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
  border-radius: var(--radius-sm);
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

@keyframes glowPulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(59,139,255,0); }
  50% { box-shadow: 0 0 20px rgba(59,139,255,0.1); }
}

@keyframes numberPop {
  0% { transform: scale(1); }
  50% { transform: scale(1.05); }
  100% { transform: scale(1); }
}

@keyframes staggerIn {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}

.stagger-in {
  animation: staggerIn 0.5s cubic-bezier(0.4, 0, 0.2, 1) both;
}
</style>
