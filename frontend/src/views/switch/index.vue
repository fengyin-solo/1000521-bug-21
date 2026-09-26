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
      <label class="filter-item">
        <span>设备状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
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
          <td v-for="column in columns" :key="column">
            <button
              v-if="column === '设备编号'"
              class="link"
              type="button"
              @click="openDetail(row)"
            >{{ row[column] ?? '—' }}</button>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <template v-for="action in actions" :key="action">
              <button
                class="link"
                type="button"
                :disabled="!isActionAllowed(row, action) || busyKey === actionKey(action, row)"
                :title="actionTitle(row, action)"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
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

    <div v-if="detail" class="modal-mask" role="dialog" aria-modal="true" @click.self="closeDetail">
      <div class="modal-card">
        <header class="modal-head">
          <h3>转辙机明细 · {{ detail['设备编号'] }}</h3>
          <button class="btn ghost" type="button" @click="closeDetail">关闭</button>
        </header>
        <dl class="detail-grid">
          <div v-for="column in columns" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ detail[column] ?? '—' }}</dd>
          </div>
        </dl>
        <div class="detail-actions">
          <button
            v-for="action in actions"
            :key="action"
            class="btn"
            type="button"
            :disabled="!isActionAllowed(detail, action)"
            :title="actionTitle(detail, action)"
            @click="runAction(action, detail)"
          >
            {{ action }}
          </button>
        </div>
        <p v-if="detailMessage" class="detail-message" :class="{ 'error-text': !detailOk }">{{ detailMessage }}</p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type ActionResult = { ok: boolean; message: string; entry: Row | null }

const ENDPOINT = '/api/switch'
const columns = ["设备编号", "设备型号", "安装道岔", "动作电流", "转换时间", "所属区段", "上次检修日", "设备状态"]
const actions = ["确认检修", "登记动作异常", "更换设备"]
const statuses = ["待检修", "运用正常", "动作异常", "已更换"]

// 与后端状态机保持一致：每个状态下允许执行的动作。
const ALLOWED_BY_STATUS: Record<string, string[]> = {
  "待检修": ["确认检修"],
  "运用正常": ["登记动作异常"],
  "动作异常": ["确认检修", "更换设备"],
  "已更换": [],
}

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const statusFilter = ref('')
const filterFields = columns.slice(0, 3)
const busyKey = ref('')

const stats = ref([
  { label: "在运转辙机", value: 0 },
  { label: "动作异常台数", value: 0 },
  { label: "待检修台数", value: 0 },
])

const detail = ref<Row | null>(null)
const detailMessage = ref('')
const detailOk = ref(true)

const detailId = computed(() => (detail.value ? Number(detail.value.id) : null))

function statusOf(row: Row): string {
  return String(row.status ?? row['设备状态'] ?? '')
}

function isActionAllowed(row: Row, action: string): boolean {
  return (ALLOWED_BY_STATUS[statusOf(row)] ?? []).includes(action)
}

function actionTitle(row: Row, action: string): string {
  if (isActionAllowed(row, action)) {
    return `对 ${row['设备编号']} 执行${action}`
  }
  const status = statusOf(row)
  if (status === '已更换') {
    return '该转辙机已更换归档，终态不再接受动作'
  }
  if (status === '待检修') {
    return action === '登记动作异常'
      ? '尚在待检修、未投入运用，不能登记动作异常，请先确认检修'
      : action === '更换设备'
        ? '尚在待检修、未投入运用，不能直接更换，请先确认检修'
        : ''
  }
  if (status === '运用正常') {
    return action === '确认检修'
      ? '已处于运用正常，无需重复确认检修'
      : '运用正常不允许直接更换，需先登记动作异常并确认无法修复'
  }
  if (status === '动作异常' && action === '登记动作异常') {
    return '已处于动作异常状态，重复登记不会重复记录，请先确认检修或更换设备'
  }
  return `当前状态「${status}」不允许执行${action}`
}

function actionKey(action: string, row: Row): string {
  return `${row.id}:${action}`
}

function resetFilters() {
  filters.value = {}
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '转辙机登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  if (!isActionAllowed(row, action)) {
    errorMessage.value = actionTitle(row, action)
    return
  }
  errorMessage.value = ''
  detailMessage.value = ''
  busyKey.value = actionKey(action, row)
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('转辙机动作未生效，请稍后重试')
    }
    const result = (await response.json()) as ActionResult
    if (!result.ok || !result.entry) {
      // 业务拒绝：把后端给出的原因摆到页面上，列表与统计保持原状。
      errorMessage.value = result.message || '该动作当前状态不允许执行'
      detailMessage.value = errorMessage.value
      detailOk.value = false
      return
    }
    detailOk.value = true
    detailMessage.value = result.message
    await Promise.all([reload(), reloadStats()])
    // 详情弹窗开着时同步最新明细，做到列表、详情、统计卡片同时更新。
    if (detailId.value !== null && Number(result.entry.id) === detailId.value) {
      detail.value = result.entry
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : '转辙机操作失败'
    errorMessage.value = message
    detailMessage.value = message
    detailOk.value = false
  } finally {
    busyKey.value = ''
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      return
    }
    const payload = (await response.json()) as Record<string, number>
    stats.value = [
      { label: "在运转辙机", value: payload.running ?? 0 },
      { label: "动作异常台数", value: payload.abnormal ?? 0 },
      { label: "待检修台数", value: payload.pending_repair ?? 0 },
    ]
  } catch {
    // 统计卡片读不到时保留上一次的值，不影响列表操作。
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams({
    ...(filters.value as Record<string, string>),
    ...(statusFilter.value ? { status: statusFilter.value } : {}),
  }).toString()
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

async function openDetail(row: Row) {
  detailMessage.value = ''
  detailOk.value = true
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('转辙机明细读取失败')
    }
    detail.value = (await response.json()) as Row
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '转辙机明细读取失败'
  }
}

function closeDetail() {
  detail.value = null
  detailMessage.value = ''
}

onMounted(() => {
  void reload()
  void reloadStats()
})
</script>

<style scoped>
.link:disabled {
  color: var(--muted);
  cursor: not-allowed;
  text-decoration: none;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal-card {
  width: 560px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 64px);
  overflow: auto;
  background: #fff;
  border-radius: 10px;
  padding: 16px 20px;
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.modal-head h3 {
  margin: 0;
  font-size: 16px;
}
.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 16px;
  margin: 0 0 12px;
}
.detail-grid dt {
  font-size: 12px;
  color: var(--muted);
}
.detail-grid dd {
  margin: 2px 0 0;
  font-size: 13px;
}
.detail-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.detail-message {
  margin: 10px 0 0;
  font-size: 13px;
}
</style>
