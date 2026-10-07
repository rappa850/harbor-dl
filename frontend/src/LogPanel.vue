<script setup>
import {ref,computed,watch,onMounted,onUnmounted} from 'vue'
// 失败日志。source 为空时是完整的“日志”页（可按来源筛选、搜索）；
// 指定 source 并设置 embedded 时，是嵌在对应页面顶部的折叠面板，没有失败记录就不显示。
const props=defineProps({api:Function,notify:Function,source:{type:String,default:''},embedded:Boolean})
const emit=defineEmits(['open'])
const PAGE=50
const names={task:'下载任务',subscription:'作者订阅',live:'直播录制'}
const items=ref([]),total=ref(0),counts=ref({task:0,subscription:0,live:0}),loading=ref(false),failed=ref('')
const filter=ref(props.source),query=ref(''),open=ref(false)
let timer,typing,requests=0
const shown=computed(()=>props.embedded?counts.value[props.source]||0:total.value)
function time(value){return value?new Date(value).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}):'—'}
async function load(more=false){
  const request=++requests
  if(!more)loading.value=true
  try{
    const params=new URLSearchParams({limit:PAGE,offset:more?items.value.length:0})
    if(filter.value)params.set('source',filter.value)
    if(query.value.trim())params.set('query',query.value.trim())
    const data=await props.api(`/logs?${params}`)
    if(request!==requests)return
    items.value=more?[...items.value,...data.items]:data.items;total.value=data.total;counts.value=data.counts;failed.value=''
  }catch(e){if(request===requests)failed.value=e.message}
  finally{if(request===requests)loading.value=false}
}
async function copy(item){
  try{await navigator.clipboard.writeText(`[${names[item.source]}] ${item.title}\n${time(item.time)}\n${item.message}`);props.notify('已复制')}
  catch{props.notify('复制失败，请手动选择文字')}
}
function pick(value){filter.value=value;load()}
watch(query,()=>{clearTimeout(typing);typing=setTimeout(load,300)})
// 定时刷新，新的失败会自己冒出来。
onMounted(()=>{load();timer=setInterval(load,10000)})
onUnmounted(()=>{clearInterval(timer);clearTimeout(typing)})
</script>

<template>
  <details v-if="embedded&&shown" class="panel log-embed" :open="open" @toggle="open=$event.target.open">
    <summary><span>失败日志</span><b>{{shown}}</b><small>{{open?'收起':'点击查看原因'}}</small></summary>
    <p v-if="failed" class="error" role="alert">{{failed}}</p>
    <article v-for="item in items" :key="item.source+item.ref" class="log-item">
      <header><strong>{{item.title}}</strong><time>{{time(item.time)}}</time></header>
      <pre>{{item.message}}</pre>
      <button class="text-button" @click="copy(item)">复制</button>
    </article>
    <button v-if="items.length<total" class="text-button more" :disabled="loading" @click="load(true)">加载更多（{{items.length}} / {{total}}）</button>
  </details>

  <section v-else-if="!embedded" class="panel">
    <div class="toolbar">
      <div class="tabs">
        <button :class="{active:!filter}" @click="pick('')">全部 <small>{{counts.task+counts.subscription+counts.live}}</small></button>
        <button v-for="(label,key) in names" :key="key" :class="{active:filter===key}" @click="pick(key)">{{label}} <small>{{counts[key]}}</small></button>
      </div>
      <input v-model="query" class="search" placeholder="搜索标题或失败原因" aria-label="搜索日志">
    </div>
    <p v-if="failed" class="error log-error" role="alert">{{failed}} <button class="text-button" @click="load()">重试</button></p>
    <div v-if="!items.length&&!loading&&!failed" class="empty"><span>✓</span><h3>{{query?'没有匹配的记录':'没有失败记录'}}</h3><p>下载、订阅同步和直播录制出现失败时，会在这里列出原因。</p></div>
    <article v-for="item in items" :key="item.source+item.ref" class="log-item">
      <header><span :class="['status','failed']">{{names[item.source]}}</span><strong>{{item.title}}</strong><time>{{time(item.time)}}</time></header>
      <pre>{{item.message}}</pre>
      <button class="text-button" @click="copy(item)">复制</button>
    </article>
    <button v-if="items.length<total" class="text-button more" :disabled="loading" @click="load(true)">加载更多（{{items.length}} / {{total}}）</button>
    <p class="hint log-note">订阅同步只保留最近一次的错误，同步成功后会清除；下载与直播的失败记录会一直保留，直到对应任务被删除。</p>
  </section>
</template>

<style>
.log-embed{padding:0}
.log-embed>summary{display:flex;align-items:center;gap:var(--sp-12);padding:var(--sp-16) var(--sp-24);cursor:pointer;list-style:none;font-weight:600;color:var(--danger-text)}
.log-embed>summary::-webkit-details-marker{display:none}
.log-embed>summary b{background:var(--danger-soft);color:var(--danger-text);border-radius:var(--r-sm);padding:var(--sp-2) var(--sp-8);font-size:var(--fs-11)}
.log-embed>summary small{margin-left:auto;color:var(--text-3);font-weight:400}
.log-embed[open]>summary{border-bottom:1px solid var(--border-subtle)}
.log-item{padding:var(--sp-16) var(--sp-24);border-bottom:1px solid var(--border-subtle);position:relative}
.log-item:last-of-type{border-bottom:0}
.log-item header{display:flex;align-items:center;gap:var(--sp-12);margin:0 0 var(--sp-8);min-width:0}
.log-item header strong{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:var(--fs-13)}
.log-item time{color:var(--text-3);font-size:var(--fs-11);white-space:nowrap}
.log-item pre{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;max-height:180px;overflow:auto;font:inherit;font-size:var(--fs-12);color:var(--danger-text);background:var(--danger-soft);border-radius:var(--r-sm);padding:var(--sp-12)}
.log-item .text-button{margin-top:var(--sp-8)}
.more{display:block;margin:var(--sp-12) auto}
.log-error{margin:var(--sp-16) var(--sp-24)}
.log-note{padding:0 var(--sp-24) var(--sp-16)}
</style>
