<script setup>
import {ref,computed,watch,onMounted,onUnmounted} from 'vue'
import HoverPreview from '../components/HoverPreview.vue'
import Icon from '../components/Icon.vue'
import ConfirmDialog from '../components/ConfirmDialog.vue'
import {STATUS,statusLabel,duration,dateText} from './meta.js'
const props=defineProps({item:Object,api:Function,notify:Function})
const emit=defineEmits(['play','changed'])
const PAGE=24
const videos=ref(null),stats=ref(null),status=ref('all'),query=ref(''),page=ref(1),loading=ref(false),error=ref('')
const selecting=ref(false),selected=ref(new Set()),menu=ref(null),busyIds=ref({}),batching=ref(false)
const redownload=ref(null),removing=ref(null),working=ref(false),dialogError=ref('')
async function exportLibrary(v){
  try{
    const r=await props.api(`${base.value}/videos/${v.id}/library`,'POST')
    const poster={cache:'封面已缓存',thumbnail:'使用下载时的缩略图',remote:'已拉取封面',frame:'无封面，已用视频截帧代替'}[r.cover_source]||'没有封面'
    props.notify(r.nfo_kept?'已导出（NFO 被手动修改过，保持原样）':`已导出到媒体库：${poster}`)
  }catch(e){props.notify(e.message)}
}
const nfo=ref(null),cleanup=ref(null),residual=ref(true)
let request=0,poll=null,typing=null
const base=computed(()=>`/subscriptions/${props.item.id}`)
const pages=computed(()=>videos.value?Math.max(1,Math.ceil(videos.value.total/PAGE)):1)
const tabs=computed(()=>[{id:'all',label:'全部',count:stats.value?.total},...Object.entries(STATUS).map(([id,s])=>({id,label:s.label,count:stats.value?.[id+'_count']}))])
const pending=computed(()=>(stats.value?.not_downloaded_count||0)+(stats.value?.failed_count||0)+(stats.value?.cancelled_count||0)+(stats.value?.orphaned_count||0))
const pageNumbers=computed(()=>{const n=pages.value,c=page.value,out=[];for(let i=1;i<=n;i++)if(i===1||i===n||Math.abs(i-c)<=1)out.push(i);else if(out[out.length-1]!=='…')out.push('…');return out})
async function load(silent=false){
  const mine=++request;if(!silent)loading.value=true;error.value=''
  try{
    const q=new URLSearchParams({page:page.value,page_size:PAGE,status:status.value});if(query.value.trim())q.set('q',query.value.trim())
    let [list,summary]=await Promise.all([props.api(`${base.value}/videos?${q}`),props.api(`${base.value}/videos/stats`)])
    if(mine!==request)return
    const last=Math.max(1,Math.ceil(list.total/PAGE))
    if(page.value>last){page.value=last;return load(silent)}
    videos.value=list;stats.value=summary
  }catch(e){if(mine===request)error.value=e.message}finally{if(mine===request)loading.value=false}
}
function setStatus(id){status.value=id;page.value=1;selected.value=new Set()}
function go(n){if(typeof n==='number'&&n!==page.value){page.value=n;window.scrollTo({top:0,behavior:'smooth'})}}
watch([status,page],()=>load())
watch(query,()=>{clearTimeout(typing);typing=setTimeout(()=>{page.value=1;load()},300)})
watch(()=>props.item.id,()=>{status.value='all';query.value='';page.value=1;selected.value=new Set();selecting.value=false;videos.value=null;stats.value=null;load()})
onMounted(()=>{load();poll=setInterval(()=>{if(stats.value?.downloading_count>0&&!loading.value)load(true)},3000);document.addEventListener('click',closeMenu)})
onUnmounted(()=>{clearInterval(poll);clearTimeout(typing);++request;document.removeEventListener('click',closeMenu)})
function closeMenu(){menu.value=null}
defineExpose({reload:()=>load(true)})

const isImage=(v)=>v.extra_data?.media_type==='image'
function toggle(v){const s=new Set(selected.value);s.has(v.id)?s.delete(v.id):s.add(v.id);selected.value=s}
function togglePage(){const ids=videos.value.videos.map(v=>v.id),all=ids.every(id=>selected.value.has(id));const s=new Set(selected.value);ids.forEach(id=>all?s.delete(id):s.add(id));selected.value=s}
function primary(v){return v.status==='downloaded'&&v.asset_id?'play':v.status==='downloading'?'busy':v.status==='downloaded'?'redo':'get'}
async function download(v,again=false){
  busyIds.value={...busyIds.value,[v.id]:true}
  try{await props.api(`${base.value}/videos/${v.id}/download`,'POST',{redownload:again});redownload.value=null;props.notify('已加入下载队列');await load(true);emit('changed')}
  catch(e){props.notify(e.message)}finally{busyIds.value={...busyIds.value,[v.id]:false}}
}
async function batch(ids){
  batching.value=true
  try{
    const r=await props.api(`${base.value}/videos/download`,'POST',ids?{video_ids:ids}:{})
    props.notify(r.requested===0?'没有需要下载的作品':`已加入 ${r.queued} 项${r.skipped?`，跳过 ${r.skipped} 项（已在下载或已完成）`:''}${r.errors.length?`，${r.errors.length} 项失败`:''}`)
    selected.value=new Set();selecting.value=false;await load(true);emit('changed')
  }catch(e){props.notify(e.message)}finally{batching.value=false}
}
async function removeRecord(){
  working.value=true;dialogError.value=''
  try{await props.api(`${base.value}/videos/${removing.value.id}`,'DELETE');removing.value=null;props.notify('已从列表移除，文件保留');await load(true);emit('changed')}
  catch(e){dialogError.value=e.message}finally{working.value=false}
}
async function openNfo(v){
  menu.value=null
  try{const r=await props.api(`${base.value}/videos/${v.id}/nfo`);nfo.value={video:v,content:r.content,etag:r.etag,taskId:r.task_id,error:'',saving:false}}
  catch(e){props.notify(e.message)}
}
async function saveNfo(){
  const n=nfo.value;n.saving=true;n.error=''
  try{await props.api(`${base.value}/videos/${n.video.id}/nfo`,'PUT',{content:n.content,expected_etag:n.etag,expected_task_id:n.taskId});nfo.value=null;props.notify('NFO 已保存')}
  catch(e){n.error=e.message;n.saving=false}
}
async function runCleanup(){
  working.value=true;dialogError.value=''
  try{const r=await props.api(`${base.value}/videos/orphan/cleanup`,'POST',{delete_residual:residual.value});cleanup.value=null
    props.notify(`已重置 ${r.reset_videos} 项，删除任务 ${r.deleted_tasks} 个${r.skipped?`，跳过 ${r.skipped} 项`:''}`);await load(true);emit('changed')}
  catch(e){dialogError.value=e.message}finally{working.value=false}
}
</script>
<template>
  <div class="works" @click="closeMenu">
    <div class="works-toolbar">
      <div class="chips" role="tablist"><button v-for="t in tabs" :key="t.id" role="tab" :aria-selected="status===t.id" class="chip" :class="{on:status===t.id}" @click="setStatus(t.id)">{{t.label}}<b v-if="t.count!==undefined&&t.count!==null">{{t.count}}</b></button></div>
      <div class="works-tools">
        <label class="search"><Icon name="search" :size="15"/><input v-model="query" type="search" placeholder="搜索标题或作品 ID" aria-label="搜索作品"></label>
        <button class="btn" title="全屏竖滑连续播放本地作品" @click="emit('play',{subscriptionId:item.id,immersive:true,resetMode:true})"><Icon name="play" :size="15"/> 沉浸播放</button>
        <button class="btn" :class="{on:selecting}" @click="selecting=!selecting;selected=new Set()">{{selecting?'退出选择':'选择'}}</button>
        <button class="btn primary" :disabled="batching||!pending" :title="pending?'':'没有待下载的作品'" @click="batch(null)"><Icon name="download" :size="15"/> 下载全部待下载<template v-if="pending">（{{pending}}）</template></button>
      </div>
    </div>
    <div v-if="selecting" class="selection-bar"><label class="check"><input type="checkbox" :checked="videos&&videos.videos.length&&videos.videos.every(v=>selected.has(v.id))" @change="togglePage"><span>选择本页</span></label>
      <span>已选 {{selected.size}} 项</span><button class="btn small primary" :disabled="!selected.size||batching" @click="batch([...selected])">下载所选</button></div>
    <div v-if="stats?.orphaned_count&&status!=='orphaned'" class="notice warn"><Icon name="alert" :size="16"/><span>有 {{stats.orphaned_count}} 个作品的本地文件已缺失。</span><button class="link" @click="cleanup={count:stats.orphaned_count};dialogError=''">清理缺失记录</button></div>
    <p v-if="error" class="inline-error" role="alert">{{error}} <button class="link" @click="load()">重试</button></p>

    <div v-if="!videos&&loading" class="grid"><div v-for="n in 8" :key="n" class="work skeleton"><div class="cover"></div><div class="line"></div><div class="line short"></div></div></div>
    <div v-else-if="videos&&!videos.total" class="empty-state"><Icon name="film" :size="28"/><h3>{{query||status!=='all'?'没有符合条件的作品':'还没有作品'}}</h3><p>{{query||status!=='all'?'换个筛选条件试试。':'点击上方“立即检查更新”读取最近的作品，或“全量同步”读取完整历史。'}}</p></div>
    <template v-else-if="videos">
      <div class="grid" :class="{busy:loading}">
        <article v-for="v in videos.videos" :key="v.id" class="work" :class="{picked:selected.has(v.id)}" @click.stop="selecting&&toggle(v)">
          <div class="cover">
            <img v-if="v.cover_local||v.cover_url" :src="v.cover_local||v.cover_url" referrerpolicy="no-referrer" loading="lazy" alt="" @error="$event.target.remove()">
            <Icon class="cover-fallback" :name="isImage(v)?'image':'film'" :size="30"/>
            <span class="badge status" :class="STATUS[v.status]?.tone">{{statusLabel(v)}}</span>
            <span v-if="isImage(v)" class="badge kind"><Icon name="image" :size="12"/> 图集</span>
            <span v-else-if="v.duration" class="badge time">{{duration(v.duration)}}</span>
            <HoverPreview v-if="!selecting&&v.status==='downloaded'&&v.asset_id&&v.media_kind==='video'" :src="`/api/files/${v.asset_id}/stream`"/>
            <span v-if="selecting" class="pick" :class="{on:selected.has(v.id)}"><Icon name="check" :size="14"/></span>
            <div v-if="v.status==='downloading'" class="bar"><i :style="{width:Math.max(4,Math.min(100,v.task_progress||0))+'%'}"></i></div>
          </div>
          <div class="work-body">
            <h4 :title="v.title">{{v.title}}</h4>
            <p class="meta">{{dateText(v.publish_time)}}<template v-if="v.status==='downloading'&&v.task_speed"> · {{v.task_speed}}</template></p>
            <p v-if="v.error_message&&v.status!=='downloaded'" class="work-error" :title="v.error_message">{{v.error_message}}</p>
            <div class="work-actions" @click.stop>
              <button v-if="primary(v)==='play'" class="btn small primary" @click="emit('play',{subscriptionId:item.id,videoId:v.id})"><Icon name="play" :size="13"/> 播放</button>
              <button v-else-if="primary(v)==='busy'" class="btn small" disabled>下载中…</button>
              <button v-else class="btn small" :class="{primary:primary(v)==='get'}" :disabled="busyIds[v.id]" @click="primary(v)==='redo'?redownload=v:download(v)"><Icon name="download" :size="13"/> {{v.status==='failed'?'重试':primary(v)==='redo'?'重新下载':'下载'}}</button>
              <span class="menu-wrap"><button class="icon-btn" aria-label="更多操作" :aria-expanded="menu===v.id" @click.stop="menu=menu===v.id?null:v.id"><Icon name="more" :size="16"/></button>
                <ul v-if="menu===v.id" class="menu" role="menu" @click.stop>
                  <li><a :href="v.url" target="_blank" rel="noopener noreferrer" role="menuitem" @click="menu=null"><Icon name="external" :size="14"/> 打开原作品</a></li>
                  <li v-if="v.status==='downloaded'&&v.asset_id"><button role="menuitem" @click="redownload=v;menu=null"><Icon name="download" :size="14"/> 重新下载</button></li>
                  <li v-if="v.status==='downloaded'&&v.media_kind==='video'"><button role="menuitem" @click="exportLibrary(v)"><Icon name="folder" :size="14"/> 导出到媒体库</button></li>
                  <li v-if="v.status==='downloaded'"><button role="menuitem" @click="openNfo(v)"><Icon name="edit" :size="14"/> 编辑 NFO</button></li>
                  <li><button role="menuitem" class="danger" @click="removing=v;menu=null;dialogError=''"><Icon name="trash" :size="14"/> 从列表移除</button></li>
                </ul></span>
            </div>
          </div>
        </article>
      </div>
      <nav v-if="pages>1" class="pager" aria-label="分页"><button class="btn small" :disabled="page<=1||loading" @click="go(page-1)">上一页</button>
        <template v-for="(n,i) in pageNumbers" :key="i"><span v-if="n==='…'" class="gap">…</span><button v-else class="btn small page" :class="{on:n===page}" :aria-current="n===page?'page':null" @click="go(n)">{{n}}</button></template>
        <button class="btn small" :disabled="page>=pages||loading" @click="go(page+1)">下一页</button><span class="total">共 {{videos.total}} 项</span></nav>
      <p v-else class="pager-total">共 {{videos.total}} 项</p>
    </template>

    <ConfirmDialog v-if="redownload" title="重新下载这个作品？" confirm="重新下载" :busy="busyIds[redownload.id]" @cancel="redownload=null" @confirm="download(redownload,true)"><p>「{{redownload.title}}」会创建新的下载任务，原文件继续保留在媒体库。</p></ConfirmDialog>
    <ConfirmDialog v-if="removing" title="从列表移除作品？" confirm="移除记录" danger :busy="working" :error="dialogError" @cancel="removing=null" @confirm="removeRecord"><p>「{{removing.title}}」只会从订阅作品列表里移除，已下载的文件、下载任务和播放记录都保留。下次同步可能会再次发现它。</p></ConfirmDialog>
    <ConfirmDialog v-if="cleanup" title="清理文件缺失的记录？" confirm="开始清理" danger :busy="working" :error="dialogError" @cancel="cleanup=null" @confirm="runCleanup"><p>共 {{cleanup.count}} 个作品的本地文件已缺失。清理会把它们重置为“未下载”并删除对应任务，之后可以重新下载。</p>
      <label class="check"><input v-model="residual" type="checkbox" :disabled="working"><span>同时删除任务目录里的残留文件</span></label></ConfirmDialog>
    <div v-if="nfo" class="dialog-backdrop" @click.self="!nfo.saving&&(nfo=null)"><section class="dialog wide" role="dialog" aria-modal="true" aria-label="编辑 NFO">
      <header class="dialog-head"><div><h2>编辑 NFO</h2><p>{{nfo.video.title}}</p></div></header>
      <textarea v-model="nfo.content" class="code-area" rows="16" spellcheck="false" maxlength="1048576" :disabled="nfo.saving"></textarea>
      <p v-if="nfo.error" class="inline-error" role="alert">{{nfo.error}}</p>
      <footer class="dialog-actions"><button class="btn" :disabled="nfo.saving" @click="nfo=null">关闭</button><button class="btn primary" :disabled="nfo.saving" @click="saveNfo">{{nfo.saving?'正在保存…':'保存'}}</button></footer></section></div>
  </div>
</template>
