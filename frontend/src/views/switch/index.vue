<template>
  <section class="page" data-module="switch">
    <header class="page-head">
      <div>
        <h2>转辙机管理</h2>
        <p class="page-desc">维护转辙机，围绕设备编号、设备型号、安装道岔、动作电流做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记转辙机</button>
        <button class="btn" type="button" @click="exportRows">导出转辙机清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :disabled="!isActionAllowed(action, row)"
              :title="actionHint(action, row)"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无转辙机数据，可先登记转辙机</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条转辙机记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type Stat = { label: string; value: number }
type ActionResult = { ok: boolean; message: string; entry?: Row | null }

const ENDPOINT = '/api/switch'
const columns = ["设备编号", "设备型号", "安装道岔", "动作电流", "转换时间", "所属区段", "上次检修日", "设备状态"]
const actions = ["确认检修", "登记动作异常", "更换设备"]
const statuses = ["待检修", "运用正常", "动作异常", "已更换"]
// 与后端状态机保持一致：每行只放开当前状态允许的那个动作。
const allowedActions: Record<string, string[]> = {
  "待检修": ["确认检修"],
  "运用正常": ["登记动作异常"],
  "动作异常": ["更换设备"],
  "已更换": [],
}

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<Stat[]>([
  { "label": "在运转辙机", "value": 0 },
  { "label": "动作异常台数", "value": 0 },
  { "label": "待检修台数", "value": 0 },
])
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function isActionAllowed(action: string, row: Row) {
  return allowedActions[String(row.status ?? '')]?.includes(action) ?? false
}

function actionHint(action: string, row: Row) {
  if (isActionAllowed(action, row)) {
    return `执行${action}`
  }
  const status = String(row.status ?? '')
  if (status === '已更换') {
    return '该转辙机已更换，动作已全部关闭'
  }
  if (action === '登记动作异常' && status === '动作异常') {
    return '已处于动作异常状态，无需重复登记'
  }
  const open = allowedActions[status] ?? []
  return open.length
    ? `当前为「${status}」状态，只能执行${open.join('、')}`
    : `当前为「${status}」状态，不允许执行${action}`
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '转辙机登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  if (!isActionAllowed(action, row)) {
    errorMessage.value = actionHint(action, row)
    return
  }
  errorMessage.value = ''
  try {
    // 后端约定动作要放在 values 里；只看 HTTP 状态码会把业务拒绝误判成成功。
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = (await response.json().catch(() => null)) as ActionResult | null
    if (!response.ok || !payload) {
      throw new Error('转辙机动作未生效，请稍后重试')
    }
    if (!payload.ok) {
      // 被状态机/幂等拦下：展示后端给出的具体原因，列表与统计保持原样。
      errorMessage.value = payload.message
      return
    }
    if (payload.entry) {
      Object.assign(row, payload.entry)
    }
    // 状态变更后列表、统计卡片同时刷新，保证三者口径一致。
    await Promise.all([reload(), reloadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '转辙机操作失败'
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      return
    }
    const payload = await response.json()
    if (Array.isArray(payload.items)) {
      stats.value = payload.items
    }
  } catch {
    // 统计刷新失败不打断列表操作，下次动作或进页面时会再取。
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('转辙机列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '转辙机列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void reloadStats()
})
</script>
