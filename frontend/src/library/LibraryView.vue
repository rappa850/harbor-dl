<script setup>
import {ref,computed,watch,onMounted,onUnmounted,nextTick} from 'vue'
import {route,setQuery} from '../router.js'
import HoverPreview from '../components/HoverPreview.vue'
import {TYPES,SORTS,LAYOUTS,groupFiles,filterEntries,typeCounts,columnCount,distribute,shapeOf} from './library.js'
// Media library: posts with pictures are merged into one card, covers keep one of a few common shapes
// (so the grid is irregular but never arbitrary), and columns are balanced by those shapes.
const props=defineProps({files:{type:Array,required:true},size:Function,date:Function})
const emit=defineEmits(['play','immersive','refresh','create'])
const KEY='harbor-library'
function saved(){try{return JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){return {}}}
const start=saved()
// URL parameters (type, sort, layout, q) win over what the browser remembered, so a link shows the same view
const from=route.query
const pick1=(list,value,fallback)=>list.some(x=>x.id===value)?value:fallback
const layout=ref(pick1(LAYOUTS,from.layout??start.layout,'irregular'))
const type=ref(pick1(TYPES,from.type??start.type,'')),sort=ref(pick1(SORTS,from.sort??start.sort,'new')),query=ref(from.q||'')
function remember(){
  setQuery({type:type.value,sort:sort.value==='new'?'':sort.value,layout:layout.value==='irregular'?'':layout.value,q:query.value.trim()})
  try{localStorage.setItem(KEY,JSON.stringify({type:type.value,sort:sort.value,layout:layout.value}))}catch(e){}
}
const entries=computed(()=>groupFiles(props.files))
const counts=computed(()=>typeCounts(entries.value))
const visible=computed(()=>filterEntries(entries.value,{type:type.value,query:query.value,sort:sort.value}))
const total=computed(()=>props.files.filter(f=>f.kind!=='attachment').reduce((a,f)=>a+f.size,0))
const grid=ref(null),columns=ref(3)
const lanes=computed(()=>distribute(visible.value,columns.value,{layout:layout.value}))
let observer=null
function measure(){if(grid.value)columns.value=columnCount(grid.value.clientWidth)}
onMounted(async()=>{await nextTick();measure();if(window.ResizeObserver){observer=new ResizeObserver(measure);observer.observe(grid.value)}})
onUnmounted(()=>observer?.disconnect())
function immerse(){
  const items=visible.value.filter(e=>['video','audio','image'].includes(e.primary.kind)).map(e=>({...e.primary,cover:e.cover}))
  if(items.length)emit('immersive',{items,start:0})
}
function pick(id){type.value=id;remember()}
function shape(e){return shapeOf(e,layout.value).id}
function setLayout(id){layout.value=id;remember()}
function meta(e){
  if(e.type!=='gallery')return `${props.size(e.size)} · ${props.date(e.created_at)}`
  const parts=[`${e.counts.images} 张`]
  if(e.counts.motion)parts.push(`${e.counts.motion} 个实况`)
  if(e.counts.audio)parts.push('含音乐')
  return `${parts.join(' · ')} · ${props.size(e.size)} · ${props.date(e.created_at)}`
}
function saveHref(e){return e.type==='gallery'?`/api/files/${e.primary.id}/archive`:`/api/files/${e.primary.id}/download`}
</script>
<template>
  <div class="library">
    <div class="library-heading"><p>已收藏 {{entries.length}} 个作品 · {{props.files.filter(f=>f.kind!=='attachment').length}} 个文件 · {{size(total)}}</p><button class="text-button" @click="emit('refresh')">↻ 刷新</button></div>
    <section v-if="!entries.length" class="panel empty"><span>▦</span><h3>媒体库还在等你的第一份收藏</h3><p>下载完成后，文件会自动出现在这里。</p><button class="primary" @click="emit('create')">新建下载</button></section>
    <template v-else>
      <div class="library-filters">
        <div class="tabs" role="tablist" aria-label="按类型筛选"><button v-for="t in TYPES" :key="t.id" role="tab" :aria-selected="type===t.id" :class="{active:type===t.id}" :disabled="Boolean(t.id)&&!counts[t.id]" @click="pick(t.id)">{{t.name}}<small>{{counts[t.id]||0}}</small></button></div>
        <input v-model="query" class="search" @input="remember" type="search" placeholder="搜索标题或文件名…" aria-label="搜索媒体库">
        <button class="btn immersive-btn" :disabled="!visible.length" title="全屏竖滑连续播放当前筛选结果" @click="immerse">▶ 沉浸播放</button>
        <div class="layout-switch" role="group" aria-label="卡片布局"><button v-for="l in LAYOUTS" :key="l.id" :class="{active:layout===l.id}" :aria-pressed="layout===l.id" :title="l.hint" @click="setLayout(l.id)">{{l.name}}</button></div>
        <select v-model="sort" aria-label="排序" @change="remember"><option v-for="s in SORTS" :key="s.id" :value="s.id">{{s.name}}</option></select>
      </div>
      <div v-if="!visible.length" class="panel empty"><span>▦</span><h3>没有符合条件的媒体</h3><p>试试其他类型或关键词。</p><button class="text-button" @click="query='';pick('')">清除筛选</button></div>
      <section ref="grid" class="library-grid" :style="{'--cols':columns}">
        <div v-for="(lane,n) in lanes" :key="n" class="library-lane">
          <article v-for="e in lane" :key="e.key" class="media-card" :data-type="e.type">
            <div class="cover-wrap">
              <button class="media-cover" :data-shape="shape(e)" :style="{aspectRatio:shape(e).replace(':',' / ')}" :aria-label="`播放 ${e.title}`" @click="emit('play',e.primary)">
              <img v-if="e.cover" :src="e.cover" alt="" loading="lazy" @error="$event.target.remove()">
              <span class="extension">{{e.label}}</span>
              <span v-if="e.counts.images>1" class="stack" aria-hidden="true">{{e.counts.images}}</span>
              <span class="play-button">▶</span>
              <span v-if="!e.cover" class="media-wave"></span>
            </button>
              <HoverPreview v-if="e.type==='video'" :src="`/api/files/${e.primary.id}/stream`"/>
            </div>
            <div class="media-info"><h3 :title="e.title">{{e.title}}</h3><p>{{meta(e)}}</p><div><button class="text-button" @click="emit('play',e.primary)">{{e.type==='gallery'?'查看':'播放'}}</button><a :href="saveHref(e)">{{e.type==='gallery'?'打包保存 ↓':'保存文件 ↓'}}</a></div></div>
          </article>
        </div>
      </section>
    </template>
  </div>
</template>
<style scoped>
.library-filters{display:flex;align-items:center;gap:var(--sp-12);flex-wrap:wrap;margin-bottom:var(--sp-20)}
.library-filters .tabs{flex:1 1 auto}
.library-filters .tabs small{margin-left:var(--sp-4);color:var(--text-3);font-size:var(--fs-11)}
.library-filters .tabs button:disabled{opacity:.45;cursor:not-allowed}
.library-filters .search{flex:0 1 240px;min-width:160px}
.layout-switch{display:inline-flex;flex:0 0 auto;padding:var(--sp-2);gap:var(--sp-2);border:1px solid var(--border-strong);border-radius:var(--r-md);background:var(--surface)}
.layout-switch button{height:calc(var(--control) - 6px);padding:0 var(--sp-12);border:0;border-radius:var(--r-sm);background:transparent;color:var(--text-2);font-size:var(--fs-12);cursor:pointer}
.layout-switch button:hover{background:var(--surface-2)}
.layout-switch button.active{background:var(--brand-soft);color:var(--brand-text)}
.library-filters select{flex:0 0 auto;width:auto}
.library-grid{display:grid;grid-template-columns:repeat(var(--cols,3),minmax(0,1fr));gap:var(--sp-20);align-items:start}
.library-lane{display:flex;flex-direction:column;gap:var(--sp-20);min-width:0}
.cover-wrap{position:relative}
.library-grid .media-cover{height:auto;width:100%}
.stack{position:absolute;right:var(--sp-12);top:var(--sp-12);z-index:1;min-width:24px;padding:var(--sp-2) var(--sp-8);border-radius:var(--r-pill);background:var(--overlay);color:var(--on-brand);font-size:var(--fs-11);text-align:center}
.media-cover>.extension{position:absolute;background:var(--overlay);color:var(--on-brand);padding:var(--sp-2) var(--sp-8);border-radius:var(--r-sm);left:var(--sp-12);top:var(--sp-12)}
.media-info p{white-space:normal}
</style>
