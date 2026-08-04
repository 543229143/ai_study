<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <span class="brand-mark"></span>
        <span class="brand-name">问题排查台</span>
        <span class="brand-sub mono">ISSUE INVESTIGATION CONSOLE</span>
      </div>
      <nav class="nav">
        <router-link to="/" class="nav-link" active-class="active">排查会话</router-link>
        <router-link to="/history" class="nav-link" active-class="active">历史记录</router-link>
      </nav>
    </header>
    <main class="content">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts"></script>

<style scoped>
.shell {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.topbar {
  height: 52px;
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  border-bottom: 1px solid var(--line);
  background: rgba(11, 15, 20, 0.85);
  backdrop-filter: blur(8px);
  z-index: 10;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-mark {
  width: 10px;
  height: 10px;
  border-radius: 3px;
  background: var(--accent);
  box-shadow: 0 0 12px var(--accent);
}

.brand-name {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.brand-sub {
  font-size: 10px;
  color: var(--ink-faint);
  letter-spacing: 2px;
}

.nav {
  display: flex;
  gap: 6px;
}

.nav-link {
  color: var(--ink-dim);
  text-decoration: none;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 13px;
  transition: all 0.15s;
}

.nav-link:hover {
  color: var(--ink);
  background: var(--bg-2);
}

.nav-link.active {
  color: var(--accent);
  background: rgba(45, 212, 191, 0.1);
}

.content {
  flex: 1;
  min-height: 0;
  display: flex;
}
</style>
