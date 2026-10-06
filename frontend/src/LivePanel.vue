<script setup>
import {ref,onMounted,onUnmounted} from 'vue'
const props=defineProps({api:Function,notify:Function})
const items=ref([]),backupText=ref(''),result=ref(null),busy=ref(false)
const checking=ref({}),roomStates=ref({}),roomErrors=ref({})
const streamChecks=ref({}),streams=ref({})
const histories=ref({}),recordActions=ref({})
async function history(item){
  histories.value[item.id]=(await props.api(`/live/subscriptions/${item.id}/records`)).items
}
async function record(item,action){
  recordActions.value[item.id]=true;roomErrors.value[item.id]=''
  try{await props.api(`/live/subscriptions/${item.id}/record/${action}`,'POST');await history(item);props.notify(action==='start'?'手动录制已启动':'录制已收尾')}
  catch(e){roomErrors.value[item.id]=e.message}finally{recordActions.value[item.id]=false}
}
async function checkStream(item){
  streamChecks.value[item.id]=true;roomErrors.value[item.id]=''
  try{streams.value[item.id]=await props.api(`/live/subscriptions/${item.id}/stream`,'POST')}
  catch(e){streams.value[item.id]=null;roomErrors.value[item.id]=e.message}finally{streamChecks.value[item.id]=false}
}
let poll,refreshing=false
async function refreshRuntime(){
  if(refreshing||busy.value)return
  refreshing=true
  try{
    const snapshots=(await props.api('/live/subscriptions')).items
    for(const item of items.value){
      const snapshot=snapshots.find(value=>value.id===item.id)
      if(!snapshot)continue
      item.runtime=snapshot.runtime
      if(snapshot.last_detection)roomStates.value[item.id]=snapshot.last_detection
      if(histories.value[item.id])await history(item)
    }
  }catch(e){props.notify(e.message)}finally{refreshing=false}
}
async function check(item){
  checking.value[item.id]=true;roomErrors.value[item.id]=''
  try{roomStates.value[item.id]=await props.api(`/live/subscriptions/${item.id}/check`,'POST')}
  catch(e){roomErrors.value[item.id]=e.message}finally{checking.value[item.id]=false}
}
async function load(){
  items.value=(await props.api('/live/subscriptions')).items
  for(const item of items.value)if(item.last_detection)roomStates.value[item.id]=item.last_detection
}
async function importBackup(){
  busy.value=true;result.value=null
  try{result.value=await props.api('/backup/live_subscriptions/import','POST',JSON.parse(backupText.value));await load();props.notify('直播订阅配置已导入')}
  catch(e){props.notify(e.message)}finally{busy.value=false}
}
async function exportBackup(){
  busy.value=true
  try{
    const value=await props.api('/backup/live_subscriptions')
    const link=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}))
    link.href=url;link.download='harbor-dl-live-subscriptions.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
  }catch(e){props.notify(e.message)}finally{busy.value=false}
}
async function save(item){
  busy.value=true
  const fields=['quality','auto_record','monitor_enabled','check_interval','output_format','split_enabled','split_duration','notification_enabled','notification_end_enabled','remark']
  try{await props.api(`/live/subscriptions/${item.id}`,'PATCH',Object.fromEntries(fields.map(key=>[key,item[key]??''])));await load();props.notify('直播配置已保存')}
  catch(e){props.notify(e.message)}finally{busy.value=false}
}
onMounted(()=>{load().catch(e=>props.notify(e.message));poll=setInterval(()=>{if(items.value.some(item=>item.runtime.monitor_available))refreshRuntime()},5000)})
onUnmounted(()=>clearInterval(poll))
</script>
<template>
  <section class="panel settings"><h2>直播订阅配置</h2><p>可导入直播订阅备份，保留直播间、录制选项和扩展配置。B 站已支持周期检测和手动 TS 录制；分段与后处理暂未支持。</p>
    <form @submit.prevent="importBackup"><label>直播订阅备份 JSON<textarea v-model="backupText" rows="6" required spellcheck="false" placeholder='{"subscriptions":[{"platform":"douyin","room_url":"https://live.douyin.com/直播间"}]}'></textarea></label>
      <div class="download-buttons"><button class="primary" :disabled="busy">导入直播备份</button><button type="button" :disabled="busy" @click="exportBackup">导出直播配置</button></div>
    </form>
    <div v-if="result" role="status"><p>共 {{result.total}} 项 · 成功 {{result.success}} · 失败 {{result.failed}}</p><p v-for="message in result.errors" :key="message" class="error">{{message}}</p><p v-if="result.monitor_warnings.length">{{result.monitor_warnings.length}} 项已保存配置，监控未注册。</p></div>
  </section>
  <section v-if="!items.length" class="panel empty"><h3>暂无直播配置</h3><p>导入直播订阅备份后可编辑配置。</p></section>
  <section v-for="item in items" :key="item.id" class="panel settings"><h2>{{item.anchor_name||item.room_id||item.room_url}}</h2><p>{{item.platform}} · {{item.room_url}}</p><p class="hint">{{item.runtime.reason}}</p>
    <p v-if="item.runtime.monitor_available">周期检测：{{item.runtime.monitor_running?'运行中':'未运行'}} · 实际间隔 {{item.runtime.effective_check_interval}} 秒（每轮随机等待）</p>
    <p v-if="item.runtime.error" class="error">{{item.runtime.error}}</p>
    <p v-if="item.runtime.recording">当前正在录制。</p>
    <p v-if="item.runtime.manual_stopped" role="status">本场已手动停止，将跳过自动开录；手动开始可恢复录制。</p>
    <p v-if="item.runtime.recording_error" class="error">{{item.runtime.recording_error}}</p>
    <button v-if="item.platform==='bilibili'" :disabled="checking[item.id]" @click="check(item)">{{checking[item.id]?'正在检测…':'检测直播间'}}</button>
    <button v-if="item.platform==='bilibili'" :disabled="streamChecks[item.id]" @click="checkStream(item)">{{streamChecks[item.id]?'正在解析…':'检查录制流'}}</button>
    <p v-if="streams[item.id]">{{streams[item.id].is_live?'录制流可用':'当前未开播'}}{{streams[item.id].format?' · '+streams[item.id].format:''}}{{streams[item.id].guest_fallback?' · 使用游客模式':''}}</p>
    <p v-if="roomStates[item.id]">上次检测：{{roomStates[item.id].anchor_name}} · 房间 {{roomStates[item.id].room_id}} · {{roomStates[item.id].is_live?'正在直播':'未开播'}} · 检测时间 {{roomStates[item.id].checked_at}}</p>
    <p v-if="roomErrors[item.id]" class="error" role="alert">{{roomErrors[item.id]}}</p>
    <div class="download-buttons"><button v-if="item.platform==='bilibili'" :disabled="recordActions[item.id]" @click="record(item,'start')">开始手动录制</button><button v-if="item.platform==='bilibili'" :disabled="recordActions[item.id]" @click="record(item,'stop')">停止录制</button><button @click="history(item).catch(e=>notify(e.message))">查看录制历史</button></div>
    <div v-if="histories[item.id]"><p v-if="!histories[item.id].length">暂无录制历史。</p><ol><li v-for="entry in histories[item.id]" :key="entry.id"><p>{{entry.anchor_name}} · {{entry.start_time}} · {{({recording:'录制中',completed:'已完成',stopped:'已停止',failed:'失败'})[entry.status]}} · {{entry.file_size}} B</p><p v-if="entry.error" class="error">{{entry.error}}</p><a v-if="entry.file_size" :href="`/api/live/records/${entry.id}/download`">保存录制文件</a></li></ol></div>
    <form @submit.prevent="save(item)">
      <label class="download-option"><input v-model="item.monitor_enabled" type="checkbox">周期监控配置</label>
      <label class="download-option"><input v-model="item.auto_record" type="checkbox">自动录制配置</label>
      <label>检查间隔（秒）<input v-model.number="item.check_interval" type="number" min="1" step="1" required></label>
      <label>录制画质<input v-model="item.quality" required maxlength="200"></label>
      <label>输出格式<input v-model="item.output_format" required maxlength="50"></label>
      <label class="download-option"><input v-model="item.split_enabled" type="checkbox">分段配置</label>
      <label>分段时长（秒）<input v-model.number="item.split_duration" type="number" min="1" step="1" required></label>
      <label class="download-option"><input v-model="item.notification_enabled" type="checkbox">开播通知配置</label>
      <label class="download-option"><input v-model="item.notification_end_enabled" type="checkbox">结束通知配置</label>
      <label>备注<input v-model="item.remark" maxlength="4096"></label>
      <p v-if="item.has_cookies||item.has_proxy" class="hint">已有凭据：{{item.has_cookies?'Cookie ':''}}{{item.has_proxy?'代理':''}}</p>
      <button class="primary" :disabled="busy">保存直播配置</button>
    </form>
  </section>
</template>
