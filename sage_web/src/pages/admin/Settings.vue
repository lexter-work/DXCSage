<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { get, put } from '../../api'
import DataTable from '../../components/DataTable.vue'
import Drawer from '../../components/Drawer.vue'
import { toast } from '../../toast'

const raw = ref<Record<string, any>>({}), sel = ref<string | null>(null), text = ref('')
const isSecret = (v: any) => v && typeof v === 'object' && 'set' in v && Object.keys(v).length === 1
const rows = computed(() => Object.entries(raw.value).map(([key, v]) => ({ id: key, key, value: isSecret(v) ? (v.set ? 'set' : 'not set') : JSON.stringify(v), secret: isSecret(v) })))
const load = async () => (raw.value = await get('api/settings'))
function open(r: any) { sel.value = r.key; text.value = r.secret ? '' : JSON.stringify(raw.value[r.key], null, 2) }
async function save() {
  const secret = isSecret(raw.value[sel.value!])
  try {
    await put('api/settings', { key: sel.value, value: secret ? text.value : JSON.parse(text.value) })
    toast('Saved'); sel.value = null; await load()
  } catch (e) { toast(e instanceof SyntaxError ? 'The value is not valid JSON.' : e) }
}
onMounted(load)
</script>
<template>
  <section class="page">
    <div class="page-head"><div><h1>Settings</h1><p>All configuration lives here. Secret values are write-only.</p></div></div>
    <DataTable clickable :rows="rows" @select="open" :columns="[{key:'key',label:'Setting',mono:true},{key:'value',label:'Value',mono:true}]">
      <template #value="{ row }"><span v-if="row.secret" class="pill" :class="row.value === 'set' ? 'ok' : 'warn'">{{ row.value }}</span><span v-else class="mono" style="word-break:break-all">{{ row.value.length > 90 ? row.value.slice(0, 90) + '…' : row.value }}</span></template>
    </DataTable>
    <Drawer :open="!!sel" :title="sel ?? ''" @close="sel = null">
      <label class="lbl">{{ isSecret(raw[sel ?? '']) ? 'New secret value (never shown again)' : 'Value (JSON)' }}
        <textarea v-if="!isSecret(raw[sel ?? ''])" class="field mono" rows="14" v-model="text" />
        <input v-else class="field" type="password" v-model="text" autocomplete="new-password"></label>
      <button class="btn primary" @click="save">Save</button>
    </Drawer>
  </section>
</template>
