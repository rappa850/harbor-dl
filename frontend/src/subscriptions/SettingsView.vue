<script setup>
import {ref,computed,watch} from 'vue'
import {INTERVALS} from './meta.js'
const props=defineProps({item:Object,api:Function,notify:Function})
const emit=defineEmits(['saved','remove'])
const draft=ref({}),busy=ref(false),error=ref(''),custom=ref(false)
function reset(){
  const i=props.item
  draft.value={nickname:i.nickname||'',update_interval:Number(i.update_interval),auto_download:!!i.auto_download,generate_nfo:!!i.generate_nfo,
    skip_bilibili_upower:!!i.skip_bilibili_upower,quality:i.quality||'best'}
  custom.value=!INTERVALS.some(o=>o.value===draft.value.update_interval);error.value=''
}
watch(()=>[props.item.id,props.item.updated_at],reset,{immediate:true})
const dirty=computed(()=>{const i=props.item,d=draft.value
  return d.nickname!==(i.nickname||'')||d.update_interval!==Number(i.update_interval)||d.auto_download!==!!i.auto_download||d.generate_nfo!==!!i.generate_nfo||
    d.skip_bilibili_upower!==!!i.skip_bilibili_upower||d.quality!==(i.quality||'best')})
const preset=computed({get:()=>custom.value?'custom':String(draft.value.update_interval),
  set:v=>{if(v==='custom'){custom.value=true}else{custom.value=false;draft.value.update_interval=Number(v)}}})
async function save(){
  busy.value=true;error.value=''
  try{
    const body={nickname:draft.value.nickname,update_interval:Number(draft.value.update_interval),auto_download:draft.value.auto_download,
      generate_nfo:draft.value.generate_nfo,quality:draft.value.quality}
    if(props.item.platform.startsWith('bilibili'))body.skip_bilibili_upower=draft.value.skip_bilibili_upower
    await props.api(`/subscriptions/${props.item.id}`,'PATCH',body)
    props.notify('订阅设置已保存');emit('saved')
  }catch(e){error.value=e.message}finally{busy.value=false}
}
</script>
<template>
  <form class="settings-view" @submit.prevent="save">
    <section class="card">
      <h3>基本信息</h3>
      <label class="field"><span class="field-label">显示昵称</span><input v-model="draft.nickname" maxlength="256" :disabled="busy"><small>修改后昵称会固定，不再随平台自动更新；存储名称保持“{{item.storage_name}}”。</small></label>
      <div class="kv"><span>平台标识</span><code>{{item.user_id}}</code></div>
      <div class="kv"><span>主页</span><a v-if="item.profile_url" :href="item.profile_url" target="_blank" rel="noopener noreferrer">{{item.profile_url}}</a><em v-else>—</em></div>
    </section>
    <section class="card">
      <h3>自动检查</h3>
      <label class="field"><span class="field-label">检查频率</span>
        <select v-model="preset" :disabled="busy"><option v-for="o in INTERVALS" :key="o.value" :value="String(o.value)">{{o.label}}</option><option value="custom">自定义…</option></select></label>
      <label v-if="custom" class="field"><span class="field-label">间隔（秒）</span><input v-model.number="draft.update_interval" type="number" min="0" step="60" :disabled="busy"><small>0 表示暂停；大于 0 且不足 3600 秒时按 3600 秒执行。</small></label>
      <label class="switch-row"><input v-model="draft.auto_download" type="checkbox" :disabled="busy"><span class="switch" aria-hidden="true"></span><span><strong>发现新作品时自动下载</strong><small>检查到新作品后立即加入下载队列。</small></span></label>
    </section>
    <section class="card">
      <h3>下载选项</h3>
      <label class="field"><span class="field-label">下载画质</span><input v-model="draft.quality" maxlength="200" required :disabled="busy"><small>默认 best；也可以填 1080、720 等分辨率上限。抖音按平台提供的最高画质下载，不受此项影响。</small></label>
      <label class="switch-row"><input v-model="draft.generate_nfo" type="checkbox" :disabled="busy"><span class="switch" aria-hidden="true"></span><span><strong>生成 NFO</strong><small>目前只保存此设置，自动生成 NFO 暂未支持。</small></span></label>
      <label v-if="item.platform.startsWith('bilibili')" class="switch-row"><input v-model="draft.skip_bilibili_upower" type="checkbox" :disabled="busy"><span class="switch" aria-hidden="true"></span><span><strong>跳过充电专属内容</strong></span></label>
    </section>
    <p v-if="error" class="inline-error" role="alert">{{error}}</p>
    <div class="settings-bar"><span v-if="dirty" class="dirty">有未保存的修改</span><button type="button" class="btn" :disabled="busy||!dirty" @click="reset">还原</button><button class="btn primary" :disabled="busy||!dirty">{{busy?'正在保存…':'保存设置'}}</button></div>
    <section class="card danger-zone"><div><h3>删除订阅</h3><p>只删除订阅配置和作品列表，已下载的文件与任务保留在媒体库。</p></div><button type="button" class="btn danger-outline" :disabled="busy" @click="emit('remove')">删除订阅…</button></section>
  </form>
</template>
