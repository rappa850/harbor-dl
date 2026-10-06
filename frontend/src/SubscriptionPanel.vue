<script setup>
import {ref,computed,watch,onMounted,onUnmounted,nextTick} from 'vue'
import Icon from './components/Icon.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
import BrowserLogin from './BrowserLogin.vue'
import AddDialog from './subscriptions/AddDialog.vue'
import WorksView from './subscriptions/WorksView.vue'
import SettingsView from './subscriptions/SettingsView.vue'
import {FILTERS,platformLabel,platformTone,intervalLabel,relative,count} from './subscriptions/meta.js'
import './subscriptions/subscriptions.css'
const props=defineProps({api:Function,notify:Function})
const emit=defineEmits(['play'])
const items=ref(null),loadError=ref(''),selectedId=ref(null),tab=ref('works'),search=ref(''),filter=ref('')
const addOpen=ref(false),loginOpen=ref(false),importOpen=ref(false),removing=ref(null),removeBusy=ref(false),removeError=ref('')
const checking=ref({}),syncing=ref({}),errors=ref({}),cookieSaved=ref(false),works=ref(null),moreOpen=ref(false)
const progress=ref({}),importText=ref(''),importResult=ref(null),importBusy=ref(false)
let timer=null,progressTimer=null

function remember(id){try{id?localStorage.setItem('harbor.sub.selected',id):localStorage.removeItem('harbor.sub.selected')}catch(e){/* private mode */}}
function recall(){try{return localStorage.getItem('harbor.sub.selected')}catch(e){return null}}
async function load(){
  try{
    const list=(await props.api('/subscriptions')).items;items.value=list;loadError.value=''
    if(!list.some(i=>i.id===selectedId.value))select(list.find(i=>i.id===recall())?.id||list[0]?.id||null)
  }catch(e){loadError.value=e.message;if(items.value===null)items.value=[]}
}
async function loadCookie(){try{cookieSaved.value=!!(await props.api('/network')).cookies?.douyin?.exists}catch(e){cookieSaved.value=false}}
const busyIds=computed(()=>(items.value||[]).filter(i=>i.runtime.is_syncing||syncing.value[i.id]||checking.value[i.id]).map(i=>i.id))
async function pollProgress(){
  const ids=busyIds.value
  if(!ids.length){progress.value={};return}
  const next={}
  await Promise.all(ids.map(async id=>{try{next[id]=(await props.api(`/subscriptions/${id}/sync-progress`)).progress}catch(e){next[id]=null}}))
  progress.value=next
}
function progressView(i){
  const p=progress.value[i.id]
  const verb=p?.mode==='check'?'检查更新':'同步完整历史'
  if(!p)return {text:syncing.value[i.id]||checking.value[i.id]?'正在准备…':'',pct:null}
  if(p.state==='queued')return {text:`排队中：同一时间最多处理 ${p.limit} 个订阅，轮到后自动开始`,pct:null,queued:true}
  const pct=p.total&&p.mode==='sync'?Math.min(99,Math.round(p.fetched/p.total*100)):null
  const count=p.total&&p.mode==='sync'?`已读取 ${p.fetched} / 约 ${p.total} 项`:`已读取 ${p.fetched} 项`
  return {text:`正在${verb} · ${count}${p.pages?`（第 ${p.pages} 页）`:''}`,pct}
}
function select(id){selectedId.value=id;remember(id);tab.value='works';moreOpen.value=false}
const selected=computed(()=>items.value?.find(i=>i.id===selectedId.value)||null)
const visible=computed(()=>{
  const q=search.value.trim().toLowerCase(),f=FILTERS.find(x=>x.id===filter.value)
  return (items.value||[]).filter(i=>(!f||f.match(i.platform))&&(!q||`${i.nickname} ${i.user_id} ${i.storage_name}`.toLowerCase().includes(q)))
})
const totals=computed(()=>{const l=items.value||[];return {subs:l.length,works:l.reduce((n,i)=>n+(i.runtime.stored_videos||0),0),
  auto:l.filter(i=>i.runtime.next_check_at).length,failing:l.filter(i=>i.runtime.last_error).length}})
function state(i){
  if(i.runtime.is_syncing||checking.value[i.id]||syncing.value[i.id])return {tone:'info',text:'检查中'}
  if(i.status==='paused'||!Number(i.update_interval))return {tone:'idle',text:'已暂停'}
  if(i.runtime.last_error)return {tone:'bad',text:'检查失败'}
  if(!i.runtime.check_available)return {tone:'idle',text:'手动同步'}
  return {tone:'ok',text:'自动检查'}
}
async function runCheck(i){
  checking.value={...checking.value,[i.id]:true};errors.value={...errors.value,[i.id]:''}
  try{const r=await props.api(`/subscriptions/${i.id}/check`,'POST')
    props.notify(r.new_videos_count?`发现 ${r.new_videos_count} 个新作品${r.queued_count?`，已加入下载 ${r.queued_count} 项`:''}`:'没有新作品')
    await load();works.value?.reload()}
  catch(e){errors.value={...errors.value,[i.id]:e.message};await load().catch(()=>{})}
  finally{checking.value={...checking.value,[i.id]:false}}
}
async function runSync(i){
  syncing.value={...syncing.value,[i.id]:true};errors.value={...errors.value,[i.id]:''};moreOpen.value=false
  try{const r=await props.api(`/subscriptions/${i.id}/sync`,'POST');props.notify(`同步完成：读取 ${r.fetched} 项，新增 ${r.new_videos_count} 项`);await load();works.value?.reload()}
  catch(e){errors.value={...errors.value,[i.id]:e.message}}
  finally{syncing.value={...syncing.value,[i.id]:false}}
}
async function created(item){
  addOpen.value=false;await load();select(item.id)
  props.notify(`已添加「${item.nickname||item.user_id}」，稍后会自动做第一次检查`)
  await nextTick();document.getElementById('sub-'+item.id)?.scrollIntoView({block:'nearest'})
}
async function confirmRemove(){
  removeBusy.value=true;removeError.value=''
  try{await props.api(`/subscriptions/${removing.value.id}`,'DELETE');const name=removing.value.nickname;removing.value=null;selectedId.value=null;await load();props.notify(`已删除订阅「${name}」`)}
  catch(e){removeError.value=e.message}finally{removeBusy.value=false}
}
async function loggedIn(){await loadCookie();props.notify('抖音登录状态已保存，现在可以检查作品了')}
async function exportConfig(){
  moreOpen.value=false
  try{const data=await props.api('/backup/subscriptions');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}))
    const a=document.createElement('a');a.href=url;a.download='harbor-dl-subscriptions.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
  catch(e){props.notify(e.message)}
}
async function readFile(event){const file=event.target.files?.[0];if(file)importText.value=await file.text();event.target.value=''}
async function runImport(){
  importBusy.value=true;importResult.value=null
  try{importResult.value=await props.api('/backup/subscriptions/import','POST',JSON.parse(importText.value));await load()}
  catch(e){importResult.value={total:0,success:0,failed:0,errors:[e instanceof SyntaxError?'文件不是有效的 JSON':e.message]}}
  finally{importBusy.value=false}
}
const closeMore=()=>{moreOpen.value=false}
onMounted(()=>{load();loadCookie();progressTimer=setInterval(()=>{if(!document.hidden)pollProgress()},1000);timer=setInterval(()=>{if(!document.hidden)load()},20000);document.addEventListener('click',closeMore)})
onUnmounted(()=>{clearInterval(timer);clearInterval(progressTimer);document.removeEventListener('click',closeMore)})
watch(addOpen,v=>{if(v)loadCookie()})
</script>

<template>
  <div class="sub-page">
    <header class="sub-top">
      <dl class="sub-stats">
        <div><dt>订阅</dt><dd>{{totals.subs}}</dd></div><div><dt>已读取作品</dt><dd>{{totals.works}}</dd></div>
        <div><dt>自动检查中</dt><dd>{{totals.auto}}</dd></div><div :class="{alert:totals.failing}"><dt>检查失败</dt><dd>{{totals.failing}}</dd></div>
      </dl>
      <div class="sub-top-actions"><button class="btn" @click="importOpen=true;importResult=null"><Icon name="upload" :size="15"/> 导入 / 导出</button><button class="btn primary" @click="addOpen=true"><Icon name="plus" :size="15"/> 添加订阅</button></div>
    </header>

    <p v-if="loadError" class="inline-error" role="alert">订阅列表加载失败：{{loadError}} <button class="link" @click="load">重试</button></p>
    <div v-if="items===null" class="sub-skeleton"><div></div><div></div></div>

    <div v-else-if="!items.length" class="sub-welcome">
      <div class="welcome-art"><Icon name="user" :size="34"/></div><h2>还没有订阅</h2>
      <p>添加喜欢的博主或歌单，Harbor-DL 会定时检查更新，把新作品自动保存到你自己的媒体库。</p>
      <div class="welcome-actions"><button class="btn primary" @click="addOpen=true"><Icon name="plus" :size="15"/> 添加第一个订阅</button><button class="btn" @click="importOpen=true"><Icon name="upload" :size="15"/> 导入备份</button></div>
    </div>

    <div v-else class="sub-layout">
      <aside class="sub-side" aria-label="订阅列表">
        <label class="search"><Icon name="search" :size="15"/><input v-model="search" type="search" placeholder="搜索订阅" aria-label="搜索订阅"></label>
        <div class="chips small"><button class="chip" :class="{on:!filter}" @click="filter=''">全部</button><button v-for="f in FILTERS" :key="f.id" class="chip" :class="{on:filter===f.id}" @click="filter=filter===f.id?'':f.id">{{f.label}}</button></div>
        <ul class="sub-list">
          <li v-for="i in visible" :key="i.id" :id="'sub-'+i.id"><button class="sub-row" :class="{on:i.id===selectedId}" :aria-current="i.id===selectedId" @click="select(i.id)">
            <span class="avatar"><img v-if="i.avatar_url" :src="i.avatar_url" referrerpolicy="no-referrer" loading="lazy" alt="" @error="$event.target.remove()"><b>{{(i.nickname||'?').slice(0,1)}}</b></span>
            <span class="row-text"><strong>{{i.nickname||i.user_id}}</strong><small><i class="dot" :style="{background:platformTone(i)}"></i>{{platformLabel(i)}} · {{i.runtime.stored_videos}} 个作品</small></span>
            <span class="pill" :class="state(i).tone">{{state(i).text}}</span></button></li>
        </ul>
        <p v-if="!visible.length" class="side-empty">没有匹配的订阅</p>
      </aside>

      <section v-if="selected" class="sub-main" :aria-label="selected.nickname">
        <header class="detail-head">
          <span class="avatar big"><img v-if="selected.avatar_url" :src="selected.avatar_url" referrerpolicy="no-referrer" alt="" @error="$event.target.remove()"><b>{{(selected.nickname||'?').slice(0,1)}}</b></span>
          <div class="detail-id"><h2>{{selected.nickname||selected.user_id}}<span class="pill" :class="state(selected).tone">{{state(selected).text}}</span></h2>
            <p class="sig" v-if="selected.signature">{{selected.signature}}</p>
            <p class="facts"><span>{{platformLabel(selected)}}</span><span v-if="selected.follower_count!=null">粉丝 {{count(selected.follower_count)}}</span><span v-if="selected.video_count!=null">平台作品 {{count(selected.video_count)}}</span><span>已读取 {{selected.runtime.stored_videos}}</span><span>{{intervalLabel(selected.update_interval)}}</span></p></div>
          <div class="detail-actions">
            <button v-if="selected.runtime.check_available" class="btn primary" :disabled="checking[selected.id]||syncing[selected.id]||selected.runtime.is_syncing" @click="runCheck(selected)"><Icon name="refresh" :size="15" :class="{spin:checking[selected.id]}"/> {{checking[selected.id]?'正在检查…':'立即检查更新'}}</button>
            <button class="btn" @click="emit('play',{subscriptionId:selected.id})"><Icon name="play" :size="14"/> 播放</button>
            <span class="menu-wrap" @click.stop><button class="icon-btn bordered" aria-label="更多" :aria-expanded="moreOpen" @click="moreOpen=!moreOpen"><Icon name="more" :size="17"/></button>
              <ul v-if="moreOpen" class="menu right" role="menu">
                <li v-if="selected.runtime.manual_sync_available"><button role="menuitem" :disabled="syncing[selected.id]||checking[selected.id]" @click="runSync(selected)"><Icon name="download" :size="14"/> 全量同步历史作品</button></li>
                <li><button role="menuitem" @click="emit('play',{subscriptionId:selected.id,resetMode:true});moreOpen=false"><Icon name="play" :size="14"/> 从未播完的作品继续</button></li>
                <li v-if="selected.profile_url"><a :href="selected.profile_url" target="_blank" rel="noopener noreferrer" role="menuitem"><Icon name="external" :size="14"/> 打开主页</a></li>
                <li><button role="menuitem" class="danger" @click="removing=selected;moreOpen=false;removeError=''"><Icon name="trash" :size="14"/> 删除订阅…</button></li>
              </ul></span>
          </div>
        </header>

        <div v-if="busyIds.includes(selected.id)" class="notice info sync-progress" role="status" aria-live="polite"><Icon :name="progressView(selected).queued?'clock':'refresh'" :size="16" :class="{spin:!progressView(selected).queued}"/>
          <div class="sync-body"><span>{{progressView(selected).text}}</span>
            <div class="sync-bar" :class="{indeterminate:progressView(selected).pct===null&&!progressView(selected).queued,queued:progressView(selected).queued}" role="progressbar" :aria-valuenow="progressView(selected).pct??undefined" aria-valuemin="0" aria-valuemax="100"><i :style="progressView(selected).pct!==null?{width:progressView(selected).pct+'%'}:null"></i></div>
            <small>作品多时需要几分钟，可以离开此页，同步会继续。</small></div></div>
        <div v-if="errors[selected.id]||selected.runtime.last_error" class="notice bad" role="alert"><Icon name="alert" :size="16"/>
          <span><strong>{{errors[selected.id]?'操作失败':'最近一次检查失败'}}：</strong>{{errors[selected.id]||selected.runtime.last_error}}</span>
          <button v-if="selected.platform==='douyin'" class="link" @click="loginOpen=true">{{cookieSaved?'重新登录抖音':'登录抖音'}}</button></div>
        <div v-else-if="selected.platform==='douyin'&&!cookieSaved" class="notice warn"><Icon name="key" :size="16"/><span>还没有保存抖音登录状态，读取博主作品会被平台拒绝。</span><button class="link" @click="loginOpen=true">立即登录</button></div>
        <div v-else-if="!selected.runtime.check_available&&selected.runtime.unavailable_reason" class="notice idle"><Icon name="alert" :size="16"/><span>{{selected.runtime.unavailable_reason}}</span></div>
        <p v-if="selected.runtime.check_available" class="check-line"><Icon name="clock" :size="14"/> 上次检查 {{relative(selected.runtime.last_checked_at)}}<template v-if="selected.runtime.last_mode"> · {{selected.runtime.last_mode==='scheduled'?'自动':'手动'}}，新增 {{selected.runtime.last_new_count}} 项，加入下载 {{selected.runtime.last_queued_count}} 项</template><template v-if="selected.runtime.next_check_at"> · 下次检查 {{relative(selected.runtime.next_check_at,true)}}</template></p>

        <nav class="tabs" role="tablist"><button role="tab" :aria-selected="tab==='works'" :class="{on:tab==='works'}" @click="tab='works'">作品</button><button role="tab" :aria-selected="tab==='settings'" :class="{on:tab==='settings'}" @click="tab='settings'">设置</button></nav>
        <WorksView v-show="tab==='works'" ref="works" :item="selected" :api="api" :notify="notify" @play="emit('play',$event)" @changed="load"/>
        <SettingsView v-if="tab==='settings'" :item="selected" :api="api" :notify="notify" @saved="load" @remove="removing=selected;removeError=''"/>
      </section>
    </div>

    <AddDialog v-if="addOpen" :api="api" :cookie-saved="cookieSaved" @close="addOpen=false" @created="created" @login="loginOpen=true"/>
    <BrowserLogin v-if="loginOpen" platform="douyin" label="抖音" :api="api" :notify="notify" @close="loginOpen=false" @saved="loggedIn"/>
    <ConfirmDialog v-if="removing" title="删除这个订阅？" confirm="删除订阅" danger :busy="removeBusy" :error="removeError" @cancel="removing=null" @confirm="confirmRemove"><p>「{{removing.nickname||removing.user_id}}」的订阅配置和作品列表会被删除，已下载的文件和下载任务保留在媒体库。</p></ConfirmDialog>
    <div v-if="importOpen" class="dialog-backdrop" @click.self="!importBusy&&(importOpen=false)"><section class="dialog wide" role="dialog" aria-modal="true" aria-labelledby="import-title">
      <header class="dialog-head"><div><h2 id="import-title">导入 / 导出订阅</h2><p>导入导出 Harbor-DL 的订阅备份 JSON；重复的订阅会被跳过。</p></div><button class="icon-btn" aria-label="关闭" @click="importOpen=false"><Icon name="close"/></button></header>
      <div class="import-bar"><label class="btn"><Icon name="folder" :size="15"/> 选择备份文件<input type="file" accept="application/json,.json" hidden @change="readFile"></label><button class="btn" @click="exportConfig"><Icon name="download" :size="15"/> 导出当前订阅</button></div>
      <textarea v-model="importText" class="code-area" rows="9" spellcheck="false" placeholder='{"subscriptions": [ … ]}' :disabled="importBusy"></textarea>
      <div v-if="importResult" class="import-result" role="status"><strong>共 {{importResult.total}} 项 · 成功 {{importResult.success}} · 失败 {{importResult.failed}}</strong><p v-for="m in importResult.errors" :key="m" class="inline-error">{{m}}</p></div>
      <footer class="dialog-actions"><button class="btn" @click="importOpen=false">关闭</button><button class="btn primary" :disabled="importBusy||!importText.trim()" @click="runImport">{{importBusy?'正在导入…':'导入'}}</button></footer></section></div>
  </div>
</template>
