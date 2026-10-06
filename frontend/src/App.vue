<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import SubscriptionPanel from './SubscriptionPanel.vue'
import LivePanel from './LivePanel.vue'
import GalleryPlayer from './components/GalleryPlayer.vue'
import {resumeTime,playbackIndex} from './playback-policy.js'

const account = ref(null), needsSetup = ref(false), booting = ref(true), busy = ref(false)
const username = ref(''), password = ref(''), error = ref(''), notice = ref('')
const page = ref('dashboard'), url = ref(''), taskTitle = ref(''), filter = ref(''), query = ref('')
const tasks = ref([]), files = ref([]), stats = ref({counts:{},disk:{},recent_tasks:[]})
const settings = ref({concurrency:2}), capabilities = ref([]), selectedTask = ref(null), playing = ref(null)
const deleteMedia = ref(true), deleteRelated = ref(true)
const deleting = ref(null), adding = ref(false), syncing = ref(false), connectionError = ref('')
const parsed = ref(null), selectedFormat = ref(''), subtitles = ref(true), thumbnail = ref(true)
const parseError = ref('')
const network = ref({enabled:false,proxy_display:'',has_proxy:false,no_proxy:'localhost,127.0.0.1,*.local',cookies:{}})
const proxyInput = ref(''), cookiePlatform = ref('youtube'), cookieInput = ref('')
const tokenItems = ref([]), tokenName = ref(''), tokenDays = ref(''), rawToken = ref(''), tokenAction = ref(null)
const subtitleTracks = ref([]), playerMetadata = ref(null), playbackMode = ref('order'), autoNext = ref(true)
let playerLoad = 0
const playerScope=ref(null),playerList=ref([]),videoProgress=ref({}),mediaElement=ref(null),mediaReady=ref(false)
let progressDirty=false,progressPoll,progressWrites=Promise.resolve()
function captureProgress(event){
  const element=event?.target||mediaElement.value
  if(!playerScope.value||!playing.value?.work_id||!mediaReady.value||!element||element.dataset.assetId!==playing.value.id||element.dataset.subscriptionId!==playerScope.value)return
  if(Number.isFinite(element.currentTime)&&element.currentTime>=0){videoProgress.value[playing.value.work_id]=element.currentTime;progressDirty=true}
}
function persistPlayback(){
  if(!playerScope.value||!account.value||!playing.value?.work_id||!progressDirty)return
  const scope=playerScope.value
  const payload={current_index:Math.max(0,playerList.value.findIndex(file=>file.id===playing.value.id)),playback_mode:playbackMode.value,video_progress:{...videoProgress.value}}
  progressDirty=false
  progressWrites=progressWrites.then(()=>api(`/playback/record/${scope}`,'PUT',payload)).catch(e=>toast(`播放记录保存失败：${e.message}`))
}
function saveCurrent(){captureProgress();persistPlayback()}
function closePlayer(){saveCurrent();++playerLoad;playing.value=null;playerScope.value=null;playerList.value=[];videoProgress.value={};mediaReady.value=false;progressDirty=false}
function mediaLoaded(event){
  if(event.target.dataset.assetId!==playing.value?.id||event.target.dataset.subscriptionId!==(playerScope.value||''))return
  if(playerScope.value&&playing.value.work_id){const position=resumeTime(videoProgress.value[playing.value.work_id],event.target.duration);if(position)event.target.currentTime=position}
  mediaReady.value=true
}
function mediaPaused(event){captureProgress(event);persistPlayback()}
watch(playbackMode,()=>{if(playerScope.value&&playing.value?.work_id){progressDirty=true;persistPlayback()}})
async function openSubscriptionPlayer({subscriptionId,videoId,resetMode=false}){
  saveCurrent();const request=++playerLoad
  try{
    await progressWrites
    if(request!==playerLoad||!account.value)return
    const [list,record]=await Promise.all([api(`/subscriptions/${subscriptionId}/playable`),api(`/playback/record/${subscriptionId}`)])
    if(request!==playerLoad||!account.value)return
    if(!list.items.length)throw new Error('此订阅暂无可播放的本地作品')
    const index=playbackIndex(list.items,record,{workId:videoId,resetMode})
    if(index<0)throw new Error('该作品文件当前不可播放，请刷新作品列表')
    saveCurrent()
    const latestProgress=playerScope.value===subscriptionId?{...videoProgress.value}:{}
    playing.value=null;mediaReady.value=false
    playerScope.value=subscriptionId;playerList.value=list.items;videoProgress.value={...record?.video_progress,...latestProgress}
    playbackMode.value=resetMode?'order':record?.playback_mode||'order';progressDirty=true
    openPlayer(list.items[index],true)
  }catch(e){toast(e.message)}
}
const platformNames = {youtube:'YouTube',bilibili:'哔哩哔哩',douyin:'抖音',xiaohongshu:'小红书',kuaishou:'快手',tiktok:'TikTok',instagram:'Instagram',x:'X / Twitter',netease:'网易云音乐',universal:'通用解析',sooplive:'SOOP Live',pandatv:'Panda TV'}
const nav = [{id:'dashboard',icon:'◈',name:'概览'}, {id:'tasks',icon:'↓',name:'下载任务'},
             {id:'subscriptions',icon:'↻',name:'作者订阅'},
             {id:'live',icon:'◉',name:'直播配置'},
             {id:'files',icon:'▦',name:'媒体库'}, {id:'roadmap',icon:'◇',name:'功能进度'}, {id:'settings',icon:'⚙',name:'设置'}]
const labels = {PENDING:'排队中',DOWNLOADING:'下载中',PROCESSING:'处理中',COMPLETED:'已完成',ERROR:'失败',CANCELLED:'已取消'}
const taskPage = ref(1), taskTotal = ref(0), taskPlatform = ref(''), manualOnly = ref(false), orphanOnly = ref(false)
const visibleTasks = computed(() => tasks.value)
const taskPages = computed(()=>Math.max(1,Math.ceil(taskTotal.value/24)))
let taskRequest=0,filterTimer
const active = computed(() => (stats.value.counts.PENDING || 0) + (stats.value.counts.DOWNLOADING || 0) + (stats.value.counts.PROCESSING || 0))
const diskPercent = computed(() => stats.value.disk.total ? Math.round((1-stats.value.disk.free/stats.value.disk.total)*100) : 0)
let poll, notificationTimer

function size(n) { if (!n) return '0 B'; const i=Math.min(4,Math.floor(Math.log(n)/Math.log(1024)));return `${(n/1024**i).toFixed(i?1:0)} ${['B','KB','MB','GB','TB'][i]}` }
function date(s) { return s ? new Date(s).toLocaleString('zh-CN',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '—' }
function toast(message) { notice.value=message;clearTimeout(notificationTimer);notificationTimer=setTimeout(()=>notice.value='',4000) }
async function api(path, method='GET', body) {
  const response=await fetch(`/api${path}`,{method,credentials:'same-origin',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined})
  const value=await response.json().catch(()=>({detail:'服务响应异常'}))
  if(!response.ok) {
    if(response.status===401 && account.value) { account.value=null;closePlayer();password.value='';cookieInput.value='';proxyInput.value='';rawToken.value='';tokenAction.value=null;tokenItems.value=[];selectedTask.value=null;deleting.value=null;tasks.value=[];files.value=[] }
    throw new Error(typeof value.detail==='string'?value.detail:'输入信息有误，请检查后重试')
  }
  return value
}
async function refresh() {
  if(!account.value || syncing.value) return
  syncing.value=true
  try {
    const [taskOK,f,s]=await Promise.all([loadTasks(),api('/files'),api('/dashboard')])
    if(account.value) { files.value=f.items;stats.value=s;if(taskOK)connectionError.value='' }
  } catch(e) { connectionError.value=e.message } finally { syncing.value=false }
}
async function loadTasks() {
  if(!account.value)return
  const request=++taskRequest
  const params=new URLSearchParams({limit:'24',offset:String((taskPage.value-1)*24),status:filter.value,query:query.value,platform:taskPlatform.value,manual_only:String(manualOnly.value),orphan_only:String(orphanOnly.value)})
  try {const result=await api(`/tasks?${params}`);if(request!==taskRequest || !account.value)return true;tasks.value=result.items;taskTotal.value=result.total;if(taskPage.value>taskPages.value)taskPage.value=taskPages.value;return true}
  catch(e){if(request===taskRequest)connectionError.value=e.message;return false}
}
watch([filter,taskPlatform,manualOnly,orphanOnly,query],()=>{taskPage.value=1;clearTimeout(filterTimer);filterTimer=setTimeout(loadTasks,200)})
watch(taskPage,loadTasks)
async function enter() {
  const [s,c,n,t]=await Promise.all([api('/settings'),api('/capabilities'),api('/network'),api('/auth/tokens')])
  settings.value=s;capabilities.value=c.items;network.value=n;tokenItems.value=t.items.map(tokenForm)
  await refresh()
}
async function authenticate() {
  busy.value=true;error.value=''
  try { account.value=await api(needsSetup.value?'/setup':'/auth/login','POST',{username:username.value,password:password.value});needsSetup.value=false;password.value='';await enter() }
  catch(e) { error.value=e.message; if(needsSetup.value) { try {needsSetup.value=(await api('/setup/status')).needs_setup}catch{} } }
  finally {busy.value=false}
}
async function logout() { try {closePlayer();await progressWrites;await api('/auth/logout','POST');account.value=null;cookieInput.value='';proxyInput.value='';rawToken.value='';tokenAction.value=null;tokenItems.value=[];tasks.value=[];files.value=[];selectedTask.value=null;deleting.value=null;page.value='dashboard'}catch(e){toast(e.message)} }
async function parseMedia() {
  if(busy.value)return
  adding.value=true;busy.value=true;parsed.value=null;parseError.value=''
  try {parsed.value=await api('/media/parse','POST',{text:url.value});selectedFormat.value=parsed.value.formats[0]?.id||'best';taskTitle.value=parsed.value.title}
  catch(e){parseError.value=e.message}finally{busy.value=false}
}
function openDownload() {parsed.value=null;parseError.value='';adding.value=true}
async function createTask(quick=false) {
  if(busy.value)return
  busy.value=true
  try {
    let target=parsed.value
    if(quick)target=await api('/media/parse','POST',{text:url.value})
    if(!target)throw new Error('请先解析媒体链接')
    await api('/tasks','POST',{url:target.url,title:quick?target.title:(taskTitle.value||target.title),author:target.author||'',format_id:quick?'bestvideo+bestaudio/best':selectedFormat.value,subtitles:subtitles.value,thumbnail:thumbnail.value})
    url.value='';taskTitle.value='';parsed.value=null;adding.value=false;page.value='tasks';toast('任务已加入下载队列');await refresh()
  }
  catch(e){toast(e.message)}finally{busy.value=false}
}
async function action(t,kind) {try{await api(`/tasks/${t.id}/${kind}`,'POST');toast(kind==='retry'?'任务已重新排队':'任务已取消');await refresh()}catch(e){toast(e.message)} }
async function detail(t) {try{selectedTask.value=await api(`/tasks/${t.id}`)}catch(e){toast(e.message)} }
async function remove() {busy.value=true;try{await api(`/tasks/${deleting.value.id}?delete_file=${deleteMedia.value}&delete_related=${deleteRelated.value}`,'DELETE');deleting.value=null;toast(deleteMedia.value?'任务及选定文件已删除':'任务已删除，媒体文件已保留');await refresh()}catch(e){toast(e.message)}finally{busy.value=false} }
async function saveSettings() {busy.value=true;try{settings.value=await api('/settings','PUT',{concurrency:Number(settings.value.concurrency)});toast('设置已保存')}catch(e){toast(e.message)}finally{busy.value=false} }
async function saveProxy() {busy.value=true;try{network.value=await api('/network/proxy','PUT',{enabled:network.value.enabled,proxy:proxyInput.value.trim()||null,no_proxy:network.value.no_proxy});proxyInput.value='';toast('代理配置已保存')}catch(e){toast(e.message)}finally{busy.value=false}}
async function saveCookie() {busy.value=true;try{network.value=await api(`/network/cookies/${cookiePlatform.value}`,'PUT',{cookie_content:cookieInput.value});cookieInput.value='';toast('Cookie 已保存')}catch(e){toast(e.message)}finally{busy.value=false}}
async function clearCookie() {busy.value=true;try{network.value=await api(`/network/cookies/${cookiePlatform.value}`,'DELETE');cookieInput.value='';toast('Cookie 已清空')}catch(e){toast(e.message)}finally{busy.value=false}}
function tokenForm(token){const d=token.expires_at?new Date(token.expires_at):null;return {...token,expires_local:d?new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,19):''}}
async function refreshTokens(){tokenItems.value=(await api('/auth/tokens')).items.map(tokenForm)}
async function createToken(){busy.value=true;try{const result=await api('/auth/tokens','POST',{name:tokenName.value,expires_in_days:tokenDays.value?Number(tokenDays.value):null});rawToken.value=result.token;tokenName.value='';await refreshTokens()}catch(e){toast(e.message)}finally{busy.value=false}}
async function editToken(token){busy.value=true;try{await api(`/auth/tokens/${token.id}`,'PATCH',{name:token.name,is_active:token.is_active,expires_at:token.expires_local?new Date(token.expires_local).toISOString():null});await refreshTokens();toast('Token 配置已更新')}catch(e){toast(e.message)}finally{busy.value=false}}
async function confirmTokenAction(){busy.value=true;try{const action=tokenAction.value;const result=await api(`/auth/tokens/${action.token.id}${action.kind==='regenerate'?'/regenerate':''}`,action.kind==='regenerate'?'POST':'DELETE');rawToken.value=action.kind==='regenerate'?result.token:'';tokenAction.value=null;await refreshTokens()}catch(e){toast(e.message)}finally{busy.value=false}}
async function openPlayer(file,scoped=false) {
  saveCurrent()
  if(!scoped){playerScope.value=null;playerList.value=[];videoProgress.value={};progressDirty=false}
  const request=++playerLoad
  playing.value=file;subtitleTracks.value=[];playerMetadata.value=null;mediaReady.value=false
  if(!['video','audio'].includes(file.kind))return
  const current=()=>request===playerLoad && playing.value?.id===file.id
  await Promise.allSettled([
    api(`/files/${file.id}/subtitles`).then(value=>{if(current())subtitleTracks.value=value.subtitles}),
    api(`/files/${file.id}/metadata`).then(value=>{if(current())playerMetadata.value=value})
  ])
}
function nextMedia(direction=1,random=false) {
  const list=playerScope.value?playerList.value:files.value.filter(f=>['video','audio','image'].includes(f.kind))
  const current=list.findIndex(f=>f.id===playing.value?.id)
  if(!list.length)return
  let index=(Math.max(0,current)+direction+list.length)%list.length
  if(random && list.length>1){const others=list.filter(f=>f.id!==playing.value?.id);return openPlayer(others[Math.floor(Math.random()*others.length)],Boolean(playerScope.value))}
  return openPlayer(list[index],Boolean(playerScope.value))
}
function galleryEnded() {
  if(!autoNext.value)return
  nextMedia(1,playbackMode.value==='random')
}
function mediaEnded(event) {
  captureProgress(event);persistPlayback()
  if(!autoNext.value)return
  if(playbackMode.value==='single'){event.target.currentTime=0;event.target.play().catch(()=>toast('点击播放继续'));return}
  nextMedia(1,playbackMode.value==='random')
}
onMounted(async()=>{
  try {needsSetup.value=(await api('/setup/status')).needs_setup;if(!needsSetup.value){try{account.value=await api('/auth/me')}catch{}if(account.value)await enter()}}
  catch(e){error.value=e.message}
  finally{booting.value=false}
  poll=setInterval(refresh,2000)
  progressPoll=setInterval(persistPlayback,5000)
})
onUnmounted(()=>{saveCurrent();clearInterval(progressPoll);clearInterval(poll);clearTimeout(notificationTimer);clearTimeout(filterTimer)})
</script>

<template>
  <div v-if="booting" class="boot">正在连接媒体工作台…</div>
  <main v-else-if="!account" class="auth-page">
    <div class="auth-story"><div class="brand"><span class="brand-mark">H</span> Harbor-DL <span class="tag">OPEN</span></div><div><p class="eyebrow">YOUR MEDIA, YOUR SPACE</p><h1>把喜欢的内容，<br>留在自己的空间。</h1><p>下载、收藏、播放。<br>一个开放的媒体工作台，重新开始。</p></div><span class="auth-footer">开源 · MIT License · 自主部署</span></div>
    <form class="auth-form" @submit.prevent="authenticate"><p class="eyebrow">{{needsSetup?'WELCOME HOME':'WELCOME BACK'}}</p><h2>{{needsSetup?'创建你的工作台':'登录工作台'}}</h2><p>{{needsSetup?'首次使用，请设置管理员账号。':'继续管理你的媒体收藏。'}}</p><label>用户名<input v-model="username" required minlength="3" maxlength="64" autocomplete="username" placeholder="你的用户名"></label><label>密码<input v-model="password" type="password" required minlength="10" maxlength="256" :autocomplete="needsSetup?'new-password':'current-password'" placeholder="至少 10 个字符"></label><p v-if="error" class="error" role="alert">{{error}}</p><button class="primary" :disabled="busy">{{busy?'请稍候…':needsSetup?'创建并进入':'登录'}}</button><span class="hint">所有功能开放，无需商业授权密钥。</span></form>
  </main>
  <div v-else class="workspace">
    <aside class="sidebar"><div class="brand"><span class="brand-mark">H</span><div>Harbor-DL<small>OPEN EDITION</small></div></div><p class="nav-label">工作台</p><nav><button v-for="item in nav" :key="item.id" :class="{selected:page===item.id}" @click="page=item.id;query=''" :aria-current="page===item.id?'page':undefined"><span>{{item.icon}}</span>{{item.name}}<b v-if="item.id==='tasks' && active">{{active}}</b></button></nav><div class="sidebar-bottom"><div class="license-dot">MIT 开源版</div><span>从收藏，到自己的媒体库。</span><div class="account"><span class="avatar">{{account.username.slice(0,1).toUpperCase()}}</span><span>{{account.username}}<small>管理员</small></span><button @click="logout" aria-label="退出登录" title="退出登录">↗</button></div></div></aside>
    <main class="content">
      <header><div><p class="eyebrow">MEDIA WORKSPACE / {{page.toUpperCase()}}</p><h1>{{nav.find(n=>n.id===page)?.name}}</h1></div><button class="primary" @click="openDownload">＋ 新建下载</button></header>
      <div v-if="connectionError" class="error connection" role="alert">连接异常：{{connectionError}} <button @click="refresh">重试</button></div>
      <SubscriptionPanel v-if="page==='subscriptions'" :api="api" :notify="toast" @play="openSubscriptionPlayer" />
      <LivePanel v-if="page==='live'" :api="api" :notify="toast" />

      <template v-if="page==='dashboard'">
        <section class="welcome"><div><span class="tag">自由收藏 · 自主保存</span><h2>你的媒体，正在这里汇集。</h2><p>粘贴一个链接开始下载，让喜欢的内容随时可用。</p><form class="quick-form" @submit.prevent="parseMedia"><input v-model="url" required placeholder="粘贴链接或分享文本" aria-label="媒体链接"><button class="primary" :disabled="busy">{{busy?'提交中…':'解析链接 →'}}</button></form></div><div class="welcome-art" aria-hidden="true"><div class="art-ring"></div><span class="art-play">▶</span><span class="art-card c1">↓ &nbsp;保存喜欢</span><span class="art-card c2">♫ &nbsp;随时播放</span></div></section>
        <section class="stats"><article><span>全部任务</span><strong>{{stats.total_tasks||0}}<small>项</small></strong><p>工作台中的下载记录</p></article><article><span>进行中</span><strong>{{active}}<small>项</small></strong><p><i class="dot"></i>{{stats.counts.DOWNLOADING||0}} 下载中 · {{stats.counts.PENDING||0}} 排队中</p></article><article><span>媒体文件</span><strong>{{files.length}}<small>个</small></strong><p>已保存 {{size(stats.downloaded_bytes)}}</p></article><article><span>可用空间</span><strong class="disk-value">{{size(stats.disk.free)}}</strong><div class="progress disk"><span :style="{width:diskPercent+'%'}"></span></div><p>磁盘已使用 {{diskPercent}}%</p></article></section>
        <section class="panel"><div class="panel-heading"><h2>最近任务 <span>{{stats.recent_tasks.length}}</span></h2><button class="text-button" @click="page='tasks'">查看全部 →</button></div><div v-if="!stats.recent_tasks.length" class="empty"><span>↓</span><h3>第一份收藏，从一个链接开始</h3><p>提交下载后，你可以在这里查看进度。</p></div><button v-for="t in stats.recent_tasks" :key="t.id" class="recent-row" @click="detail(t)"><span class="file-icon">▶</span><span class="recent-title"><strong>{{t.title}}</strong><small>{{date(t.created_at)}}</small></span><span :class="['status',t.status]">{{labels[t.status]}}</span><span class="row-arrow">↗</span></button></section>
        <div class="open-note"><span>◇</span><p><strong>从现在起，开放每一种可能。</strong><br>订阅、直播与通知功能正在逐步加入。</p><button class="text-button" @click="page='roadmap'">查看功能进度 →</button></div>
      </template>

      <template v-if="page==='tasks'">
        <section class="panel"><div class="toolbar"><div class="tabs"><button @click="filter=''" :class="{active:!filter}">全部</button><button @click="filter='active'" :class="{active:filter==='active'}">进行中</button><button v-for="(label,key) in labels" :key="key" @click="filter=key" :class="{active:filter===key}">{{label}}</button></div><input v-model="query" class="search" placeholder="搜索标题、文件名或作者…" aria-label="搜索任务"></div><div class="task-filters"><label>平台<select v-model="taskPlatform"><option value="">全部平台</option><option v-for="(name,key) in platformNames" :key="key" :value="key">{{name}}</option></select></label><label class="download-option"><input type="checkbox" v-model="manualOnly">仅手动任务</label><label class="download-option"><input type="checkbox" v-model="orphanOnly">仅文件缺失</label><span>共 {{taskTotal}} 项</span></div><div v-if="!visibleTasks.length" class="empty"><span>↓</span><h3>{{tasks.length?'没有符合条件的任务':'还没有下载任务'}}</h3><p>{{tasks.length?'试试其他状态或关键词。':'点击新建下载，保存你的第一份媒体。'}}</p></div><article v-for="t in visibleTasks" :key="t.id" class="task-row"><span class="file-icon">↓</span><div class="task-info"><button class="task-title" @click="detail(t)">{{t.title}}</button><p class="url">{{t.url}}</p><div v-if="t.status==='DOWNLOADING'" class="progress"><span :style="{width:t.progress+'%'}"></span></div><p class="task-meta">{{date(t.created_at)}} <template v-if="t.status==='DOWNLOADING'"> · {{t.total?t.progress.toFixed(1)+'%':'正在获取媒体'}} · {{size(t.downloaded)}}<template v-if="t.total"> / {{size(t.total)}}</template> · {{t.speed||'准备中'}}</template></p><p v-if="t.error" class="task-error">{{t.error}}</p></div><div class="task-actions"><span :class="['status',t.status]">{{labels[t.status]}}</span><div><button v-if="['PENDING','DOWNLOADING','PROCESSING'].includes(t.status)" @click="action(t,'cancel')">取消</button><button v-if="['ERROR','CANCELLED'].includes(t.status)" @click="action(t,'retry')">重试</button><a v-if="t.status==='COMPLETED'" :href="`/api/files/${t.id}/download`">保存</a><button v-if="!['PENDING','DOWNLOADING','PROCESSING'].includes(t.status)" class="danger-text" @click="deleteMedia=true;deleteRelated=true;deleting=t">删除</button></div></div></article><div class="task-pagination"><button :disabled="taskPage<=1" @click="taskPage--">上一页</button><span>第 {{taskPage}} / {{taskPages}} 页</span><button :disabled="taskPage>=taskPages" @click="taskPage++">下一页</button></div></section><p class="hint">每页 24 项，筛选和搜索覆盖全部任务。</p>
      </template>

      <template v-if="page==='files'"><div class="library-heading"><p>已收藏 {{files.length}} 个媒体文件 · {{size(files.reduce((a,f)=>a+f.size,0))}}</p><button class="text-button" @click="refresh">↻ 刷新</button></div><section v-if="!files.length" class="panel empty"><span>▦</span><h3>媒体库还在等你的第一份收藏</h3><p>下载完成后，文件会自动出现在这里。</p><button class="primary" @click="openDownload">新建下载</button></section><section class="file-grid"><article v-for="f in files" :key="f.id" class="media-card"><button class="media-cover" @click="openPlayer(f)" :aria-label="`播放 ${f.title}`"><span class="extension">{{f.extension.replace('.','').toUpperCase()}}</span><span class="play-button">▶</span><span class="media-wave"></span></button><div class="media-info"><h3 :title="f.title">{{f.title}}</h3><p>{{size(f.size)}} · {{date(f.created_at)}}</p><div><button class="text-button" @click="openPlayer(f)">播放</button><a :href="`/api/files/${f.id}/download`">保存文件 ↓</a></div></div></article></section></template>

      <template v-if="page==='settings'"><section class="panel settings"><h2>下载设置</h2><p>调整任务处理方式，设置会在重启后保留。</p><form @submit.prevent="saveSettings"><label>同时下载的任务数<input type="number" v-model.number="settings.concurrency" min="1" max="8" required><small>1–8 项，用于控制带宽与系统负载。</small></label><button class="primary" :disabled="busy">保存设置</button></form></section><section class="panel settings"><h2>运行环境</h2><div class="setting-row"><span>应用版本</span><strong>{{settings.version}}</strong></div><div class="setting-row"><span>FFmpeg</span><strong :class="{warning:!settings.ffmpeg_available}">{{settings.ffmpeg_available?'已安装':'未检测到'}}</strong></div><p v-if="!settings.ffmpeg_available" class="hint">部分媒体需要合并音视频轨道。部署时安装 FFmpeg 可支持这类下载。</p><div class="setting-row"><span>软件许可证</span><strong>MIT · 所有业务功能开放</strong></div></section><section class="panel settings"><h2>网络代理</h2><p>解析与下载共用代理配置。绕过名单支持域名、前导点和 * 通配符，逗号分隔。</p><form @submit.prevent="saveProxy"><label class="download-option"><input type="checkbox" v-model="network.enabled">启用全局代理</label><label>代理地址<input type="password" v-model="proxyInput" autocomplete="off" placeholder="http://host:port 或 socks5://host:port"><small>{{network.has_proxy?'当前 '+network.proxy_display+'；留空保留已保存地址':'尚未配置代理地址'}}</small></label><label>绕过代理<input v-model="network.no_proxy" maxlength="4096"></label><button class="primary" :disabled="busy">保存代理</button></form></section><section class="panel settings"><h2>平台 Cookie</h2><p>导入 Netscape Cookie 文件内容或单行 Cookie 请求头。保存后用于该平台的解析与下载。</p><form @submit.prevent="saveCookie"><label>平台<select v-model="cookiePlatform" @change="cookieInput='' "><option v-for="(name,key) in platformNames" :key="key" :value="key">{{name}}</option></select></label><p>{{network.cookies[cookiePlatform]?.exists?'已配置 · '+date(network.cookies[cookiePlatform].updated_at):'未配置'}} · 保存状态不代表平台登录仍然有效</p><label>Cookie 内容<textarea v-model="cookieInput" rows="6" maxlength="524288" autocomplete="off" spellcheck="false" placeholder="粘贴 Cookie 内容"></textarea></label><div class="download-buttons"><button class="primary" :disabled="busy || !cookieInput.trim()">保存 Cookie</button><button type="button" :disabled="busy || !network.cookies[cookiePlatform]?.exists" @click="clearCookie">清空 Cookie</button></div></form></section><section class="panel settings"><h2>API Token</h2><p>为脚本或外部应用创建独立令牌。调用时使用 X-API-Token 请求头或 Authorization: Bearer。</p><form @submit.prevent="createToken"><label>用途名称<input v-model="tokenName" maxlength="128" required></label><label>有效天数<input type="number" v-model="tokenDays" min="1" step="1" placeholder="留空为不过期"></label><button class="primary" :disabled="busy">创建 Token</button></form><div v-if="rawToken" class="token-reveal"><p>请复制保存：完整 Token 只在这次创建或重置时显示。</p><label>完整 Token<textarea :value="rawToken" readonly rows="3" spellcheck="false" aria-label="完整 API Token"></textarea></label><button @click="rawToken=''">我已保存，关闭显示</button></div><article v-for="token in tokenItems" :key="token.id" class="token-item"><label>名称<input v-model="token.name" maxlength="128" required></label><p>末尾 {{token.token_suffix}} · {{token.expires_at ? '到期 '+date(token.expires_at) : '不过期'}} · 最近使用 {{date(token.last_used_at)}}</p><label>到期时间（清空为不过期）<input type="datetime-local" step="1" v-model="token.expires_local"></label><label class="download-option"><input type="checkbox" v-model="token.is_active">启用</label><div class="download-buttons"><button :disabled="busy" @click="editToken(token)">保存编辑</button><button :disabled="busy" @click="tokenAction={kind:'regenerate',token}">重新生成</button><button :disabled="busy" class="danger-text" @click="tokenAction={kind:'delete',token}">删除</button></div></article><p v-if="!tokenItems.length">尚未创建 Token。</p></section></template>

      <template v-if="page==='roadmap'"><section class="roadmap-intro"><span class="tag">ROADMAP</span><h2>一步一步，把媒体平台做完整。</h2><p>下面显示当前真实的实现状态。待建设模块尚未提供服务。</p></section><section class="panel"><article v-for="c in capabilities" :key="c.id" class="roadmap-row"><span class="phase">0{{c.phase}}</span><div><h3>{{c.name}}</h3><p>{{c.status==='available'?'已实现，可在工作台使用':c.status==='partial'?'配置、手动同步已接入；抖音博主支持定时检查与自动下载，其他平台待适配':'规划中，后续阶段实现'}}</p></div><span :class="['status',c.status==='available'?'COMPLETED':'PENDING']">{{c.status==='available'?'已开放':c.status==='partial'?'部分接入':'待建设'}}</span></article></section></template>
      <footer>Harbor-DL <span>个人媒体，自主掌握。 · MIT License</span></footer>
    </main>
  </div>

  <div v-if="adding && account" class="overlay" @click.self="!busy && (adding=false)"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="add-title">
    <button class="close" :disabled="busy" @click="adding=false" aria-label="关闭">×</button><p class="eyebrow">ADD TO YOUR COLLECTION</p><h2 id="add-title">新建下载</h2>
    <p>解析媒体后选择画质，或直接下载最佳可用格式。</p>
    <form @submit.prevent="parseMedia"><label>链接或分享文本<input v-model="url" required autofocus :disabled="busy" @input="parsed=null;parseError=''" placeholder="粘贴链接或分享文本"></label>
      <div class="download-buttons"><button class="primary" :disabled="busy">{{busy?'处理中…':'解析媒体'}}</button><button type="button" :disabled="busy || !url.trim()" @click="createTask(true)">快速下载</button></div>
    </form>
    <p v-if="parseError" class="error" role="alert">{{parseError}}</p>
    <form v-if="parsed" @submit.prevent="createTask(false)">
      <p>{{parsed.platform}} · {{parsed.author || '未知作者'}}<span v-if="parsed.duration"> · {{Math.round(parsed.duration)}} 秒</span></p>
      <label>媒体标题<input v-model="taskTitle" maxlength="300"></label>
      <label>画质 / 格式<select v-model="selectedFormat"><option v-for="f in parsed.formats" :key="f.id" :value="f.id">{{f.label}} {{f.extension || ''}}{{f.requires_merge?' · 需要合并音视频':''}}</option></select></label>
      <p v-if="parsed.formats.find(f=>f.id===selectedFormat)?.requires_merge && !settings.ffmpeg_available" class="error">此格式需要 FFmpeg，当前未检测到。请选择其他格式或安装 FFmpeg。</p>
      <label class="download-option"><input v-model="subtitles" type="checkbox">保存可用字幕</label><label class="download-option"><input v-model="thumbnail" type="checkbox">保存缩略图</label>
      <button class="primary" :disabled="busy || (parsed.formats.find(f=>f.id===selectedFormat)?.requires_merge && !settings.ffmpeg_available)">加入下载队列</button>
    </form>
  </section></div>
  <div v-if="selectedTask && account" class="overlay" @click.self="selectedTask=null"><section class="modal detail" role="dialog" aria-modal="true" aria-labelledby="detail-title"><button class="close" @click="selectedTask=null" aria-label="关闭">×</button><h2 id="detail-title">任务详情</h2><h3>{{selectedTask.title}}</h3><p class="url">{{selectedTask.url}}</p><span :class="['status',selectedTask.status]">{{labels[selectedTask.status]}}</span><p v-if="selectedTask.error" class="error">{{selectedTask.error}}</p><h3>任务记录</h3><ol class="events"><li v-for="(e,i) in selectedTask.events" :key="i"><small>{{date(e.created_at)}}</small><p>{{e.message}}</p></li></ol></section></div>
  <div v-if="playing && account" class="overlay" @click.self="closePlayer"><section class="modal player" role="dialog" aria-modal="true" aria-labelledby="player-title">
    <button class="close" @click="closePlayer" aria-label="关闭">×</button><h2 id="player-title">{{playing.title}}</h2>
    <audio v-if="playing.kind==='audio'" ref="mediaElement" :key="`${playerScope||'manual'}:${playing.id}`" :data-asset-id="playing.id" :data-subscription-id="playerScope||''" @loadedmetadata="mediaLoaded" @timeupdate="captureProgress" @pause="mediaPaused" @ended="mediaEnded" controls autoplay :src="`/api/files/${playing.id}/stream`"></audio>
    <GalleryPlayer v-else-if="playing.kind==='image'" :key="`${playerScope||'manual'}:${playing.id}`" :asset-id="playing.id" :title="playing.title" :api="api" :chain="autoNext&&Boolean(playerScope)&&playbackMode!=='single'" @finished="galleryEnded"/>
    <video v-else ref="mediaElement" :key="`${playerScope||'manual'}:${playing.id}`" :data-asset-id="playing.id" :data-subscription-id="playerScope||''" @loadedmetadata="mediaLoaded" @timeupdate="captureProgress" @pause="mediaPaused" @ended="mediaEnded" controls autoplay :src="`/api/files/${playing.id}/stream`" @error="toast('浏览器无法播放此格式，可以保存文件后使用本地播放器')"><track v-for="track in subtitleTracks" :key="track.id" kind="subtitles" :src="track.path" :label="track.label" :srclang="track.language.split('.')[0]" :default="track.is_default"></video>
    <div class="player-controls"><button @click="nextMedia(-1)">上一项</button><select v-model="playbackMode" aria-label="播放模式"><option value="order">顺序播放</option><option value="random">随机播放</option><option value="single">单曲循环</option></select><button @click="nextMedia(1)">下一项</button><label class="download-option"><input type="checkbox" v-model="autoNext">播放结束自动继续</label></div>
    <p v-if="playerMetadata?.success" class="hint">{{playerMetadata.width && playerMetadata.height ? playerMetadata.width+' × '+playerMetadata.height+' · ' : ''}}{{playerMetadata.duration ? Math.round(playerMetadata.duration)+' 秒' : ''}}</p><p v-if="playerMetadata && !playerMetadata.success" class="hint">{{playerMetadata.reason}}</p><p class="hint">浏览器支持的格式可直接播放，其他格式可保存到本地。</p><a class="primary download-link" :href="`/api/files/${playing.id}/download`">保存到本地 ↓</a>
  </section></div>
  <div v-if="deleting && account" class="overlay" @click.self="deleting=null"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="delete-title"><h2 id="delete-title">删除这份下载？</h2><p>删除任务记录时，可以选择保留媒体文件。删除文件无法撤销。</p><p class="delete-name">{{deleting.title}}</p><label class="download-option"><input type="checkbox" v-model="deleteMedia">同时删除媒体文件</label><label v-if="deleteMedia" class="download-option"><input type="checkbox" v-model="deleteRelated">删除字幕、缩略图等关联文件</label><div class="modal-actions"><button @click="deleting=null">保留</button><button class="danger" :disabled="busy" @click="remove">确认删除</button></div></section></div>
  <div v-if="tokenAction && account" class="overlay"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="token-action-title"><h2 id="token-action-title">{{tokenAction.kind==='regenerate'?'重新生成 Token？':'删除 Token？'}}</h2><p>{{tokenAction.token.name}} 的现有 Token 将立即失效，请更新使用它的应用。</p><div class="modal-actions"><button :disabled="busy" @click="tokenAction=null">取消</button><button class="danger" :disabled="busy" @click="confirmTokenAction">确认</button></div></section></div>
  <div v-if="notice" class="toast" role="status">{{notice}}</div>
</template>
