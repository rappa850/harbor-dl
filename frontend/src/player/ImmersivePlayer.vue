<script setup>
import {ref,computed,watch,onMounted,onBeforeUnmount,nextTick} from 'vue'
import GalleryPlayer from '../components/GalleryPlayer.vue'
import Icon from '../components/Icon.vue'
import {clampIndex,mountedIndexes,nextIndex,keyAction,cycleSpeed,clock} from './feed.js'
// Full-screen vertical feed. Scroll-snap does the swiping (wheel, touch, trackpad); an IntersectionObserver tells which
// slide is on screen. Only the active slide plays, its neighbours are preloaded, everything else is an empty placeholder.
// Playback records stay in App.vue: this component reports the active work through `change` and forwards the media events
// of the active element (carrying data-asset-id / data-subscription-id like the dialog player does).
const props=defineProps({items:{type:Array,required:true},start:{type:Number,default:0},scope:String,mode:{type:String,default:'order'},autoNext:{type:Boolean,default:true},api:Function})
const emit=defineEmits(['change','close','loadedmetadata','timeupdate','pause','ended'])
const scroller=ref(null),active=ref(clampIndex(props.start,props.items.length))
const loopOne=ref(props.mode==='single'),auto=ref(props.autoNext),idle=ref(false)
const muted=ref(false),speed=ref(1),time=ref(0),duration=ref(0),paused=ref(false),flash=ref(''),soundHint=ref(false),seeking=ref(false)
const players={}
let observer=null,flashTimer=null,idleTimer=null,overRail=false
const current=computed(()=>props.items[active.value])
const mounted=computed(()=>mountedIndexes(props.items,active.value))
const timed=computed(()=>current.value&&current.value.kind!=='image')
const src=item=>`/api/files/${item.id}/stream`
const setPlayer=(i,el)=>{if(el)players[i]=el;else delete players[i]}
const activeEl=()=>players[active.value]

function poke(kind){flash.value=kind;clearTimeout(flashTimer);flashTimer=setTimeout(()=>flash.value='',650)}
async function play(el){
  if(!el)return
  el.muted=muted.value;el.playbackRate=speed.value
  try{await el.play();paused.value=false}
  catch(e){
    if(muted.value||e?.name==='AbortError'){return}
    muted.value=true;el.muted=true;soundHint.value=true            // the browser refused sound without a recent gesture
    try{await el.play();paused.value=false}catch(err){paused.value=true}
  }
}
function activate(){
  const item=current.value;if(!item)return
  for(const [i,el] of Object.entries(players))if(Number(i)!==active.value)el.pause?.()
  time.value=0;duration.value=0;paused.value=false
  emit('change',item,active.value)
  const el=activeEl()
  if(el&&item.kind!=='image'){
    if(el.readyState>=1){duration.value=el.duration||0;emit('loadedmetadata',{target:el})}   // preloaded neighbour: its metadata event already fired
    play(el)
  }
}
function onMeta(e,i){if(i!==active.value)return;duration.value=e.target.duration||0;e.target.playbackRate=speed.value;emit('loadedmetadata',e)}
function onTime(e,i){if(i!==active.value)return;if(!seeking.value)time.value=e.target.currentTime;emit('timeupdate',e)}
function onPause(e,i){if(i===active.value&&!e.target.ended)emit('pause',e)}
function onEnded(e,i){
  if(i!==active.value)return
  emit('ended',e)
  if(!auto.value)return
  const to=nextIndex(active.value,props.items.length,loopOne.value?'single':props.mode==='random'?'random':'order')
  if(to!==null&&to!==active.value)goto(to)
}
function onData(e,i){if(i===active.value&&!paused.value&&e.target.paused)play(e.target)}

// Controls fade out while a work plays untouched; any pointer, touch or key brings them back.
function wake(){idle.value=false;clearTimeout(idleTimer);idleTimer=setTimeout(()=>{if(!paused.value&&!overRail&&!seeking.value)idle.value=true},2600)}
function rail(over){overRail=over;if(over)wake()}
watch(paused,p=>{if(p)wake()})
function toggleLoop(){loopOne.value=!loopOne.value;wake()}
function toggleAuto(){auto.value=!auto.value;wake()}
function goto(index){
  const to=clampIndex(index,props.items.length)
  if(!scroller.value||to===active.value&&Math.abs(scroller.value.scrollTop-to*scroller.value.clientHeight)<4)return
  scroller.value.scrollTo({top:to*scroller.value.clientHeight,behavior:'smooth'})
}
function move(by){goto(active.value+by)}
function toggle(){
  const el=activeEl();if(!el)return
  if(el.paused){play(el);poke('play')}else{el.pause();paused.value=true;poke('pause')}
}
function seek(by){const el=activeEl();if(el&&Number.isFinite(el.duration))el.currentTime=Math.min(el.duration,Math.max(0,el.currentTime+by))}
function toggleMute(){muted.value=!muted.value;soundHint.value=false;for(const el of Object.values(players))el.muted=muted.value;try{localStorage.setItem('harbor-immersive-muted',muted.value?'1':'0')}catch(e){}}
function bump(){speed.value=cycleSpeed(speed.value);for(const el of Object.values(players))if(el.playbackRate!==undefined)el.playbackRate=speed.value}
function scrub(e){const el=activeEl();if(el&&Number.isFinite(el.duration)){el.currentTime=Number(e.target.value)/1000*el.duration}}
function onKey(e){
  wake()
  if(e.target.closest?.('input,select,textarea'))return
  const action=keyAction(e.key,current.value?.kind)
  if(!action)return
  e.preventDefault()
  if(action.type==='move')move(action.by)
  else if(action.type==='toggle')toggle()
  else if(action.type==='seek')seek(action.by)
  else if(action.type==='mute')toggleMute()
  else if(action.type==='close')emit('close')
}
function stageClick(i){if(i===active.value&&current.value?.kind!=='image')toggle()}

onMounted(async()=>{
  try{muted.value=localStorage.getItem('harbor-immersive-muted')==='1'}catch(e){}
  await nextTick()
  const box=scroller.value
  box.scrollTop=active.value*box.clientHeight
  observer=new IntersectionObserver(entries=>{
    for(const entry of entries){
      if(!entry.isIntersecting||entry.intersectionRatio<0.6)continue
      const index=Number(entry.target.dataset.index)
      if(index!==active.value){active.value=index}
    }
  },{root:box,threshold:[0.6]})
  box.querySelectorAll('.slide').forEach(el=>observer.observe(el))
  window.addEventListener('keydown',onKey)
  wake()
  document.documentElement.style.overflow='hidden'
  activate()
})
watch(active,async()=>{await nextTick();activate()})
onBeforeUnmount(()=>{observer?.disconnect();window.removeEventListener('keydown',onKey);clearTimeout(flashTimer);clearTimeout(idleTimer);document.documentElement.style.overflow='';for(const el of Object.values(players))el.pause?.()})
</script>
<template>
  <Teleport to="body">
    <div class="immersive" :class="{idle}" role="dialog" aria-modal="true" aria-label="沉浸式播放" @pointermove="wake" @pointerdown="wake" @wheel.passive="wake" @touchstart.passive="wake">
      <div ref="scroller" class="feed">
        <section v-for="(item,i) in items" :key="item.id+':'+i" class="slide" :data-index="i" :data-kind="item.kind" @click="stageClick(i)">
          <template v-if="mounted.has(i)">
            <img v-if="item.cover&&item.kind!=='image'" class="backdrop" :src="item.cover" alt="" aria-hidden="true">
            <component :is="item.kind==='audio'?'audio':'video'" v-if="item.kind!=='image'" :ref="el=>setPlayer(i,el)" :class="item.kind==='audio'?'sound':'film'"
              :data-asset-id="item.id" :data-subscription-id="scope||''" :src="src(item)" :poster="item.kind==='video'?item.cover||undefined:undefined" :loop="loopOne" :muted="muted"
              playsinline preload="auto" @loadedmetadata="onMeta($event,i)" @loadeddata="onData($event,i)" @timeupdate="onTime($event,i)" @pause="onPause($event,i)" @ended="onEnded($event,i)"/>
            <div v-if="item.kind==='audio'" class="record" aria-hidden="true"><img v-if="item.cover" :src="item.cover" alt=""><Icon v-else name="music" :size="56"/></div>
            <GalleryPlayer v-if="item.kind==='image'" immersive :asset-id="item.id" :title="item.title" :api="api" :muted="muted" :chain="auto&&!loopOne" @finished="move(1)"/>
          </template>
          <span v-if="i===active&&flash" class="flash" aria-hidden="true"><Icon :name="flash==='play'?'play':'pause'" :size="40"/></span>
        </section>
      </div>
      <header class="top"><span class="pos">{{active+1}} / {{items.length}}</span><button class="round" aria-label="退出沉浸模式" @click="emit('close')"><Icon name="close" :size="20"/></button></header>
      <aside class="rail" aria-label="播放操作" @pointerenter="rail(true)" @pointerleave="rail(false)" @focusin="wake">
        <button class="round" :aria-label="muted?'开启声音':'静音'" :aria-pressed="muted" @click.stop="toggleMute"><Icon :name="muted?'mute':'volume'" :size="22"/></button>
        <button v-if="timed" class="round text" :aria-label="`倍速 ${speed}x`" @click.stop="bump">{{speed}}x</button>
        <a v-if="current" class="round" :href="`/api/files/${current.id}/${current.kind==='image'?'archive':'download'}`" aria-label="保存" @click.stop><Icon name="download" :size="22"/></a>
        <button class="round" :class="{on:loopOne}" :aria-pressed="loopOne" :aria-label="loopOne?'取消单集循环':'单集循环'" :title="loopOne?'单集循环：开':'单集循环'" @click.stop="toggleLoop"><Icon name="loop" :size="22"/><b v-if="loopOne" class="one">1</b></button>
        <button class="round" :class="{on:auto}" :aria-pressed="auto" :aria-label="auto?'关闭自动连播':'开启自动连播'" :title="auto?'自动连播：开':'自动连播：关'" @click.stop="toggleAuto"><Icon name="next" :size="22"/></button>
        <button class="round" aria-label="上一条" :disabled="active<=0" @click.stop="move(-1)"><Icon name="chevron" :size="22" class="up"/></button>
        <button class="round" aria-label="下一条" :disabled="active>=items.length-1" @click.stop="move(1)"><Icon name="chevron" :size="22" class="down"/></button>
      </aside>
      <footer class="caption" v-if="current"><h2>{{current.title}}</h2><button v-if="soundHint" class="hint" @click="toggleMute">已静音播放，点击开启声音</button></footer>
      <div v-if="timed" class="line" aria-hidden="true"><i :style="{width:(duration?time/duration*100:0)+'%'}"></i></div>
      <div v-if="timed" class="scrub"><span>{{clock(time)}}</span>
        <input type="range" min="0" max="1000" step="1" :value="duration?Math.round(time/duration*1000):0" aria-label="播放进度" @pointerdown="seeking=true" @pointerup="seeking=false" @input="scrub($event);time=Number($event.target.value)/1000*duration"><span>{{clock(duration)}}</span></div>
    </div>
  </Teleport>
</template>
<style scoped>
.immersive{position:fixed;inset:0;z-index:40;background:#050c09;color:#fff;font-family:var(--font-sans)}
.feed{position:absolute;inset:0;overflow-y:auto;scroll-snap-type:y mandatory;overscroll-behavior:contain;scrollbar-width:none}
.feed::-webkit-scrollbar{display:none}
.slide{position:relative;height:100%;scroll-snap-align:start;scroll-snap-stop:always;display:grid;place-items:center;overflow:hidden;cursor:pointer}
.backdrop{position:absolute;inset:-8%;width:116%;height:116%;object-fit:cover;filter:blur(40px) brightness(.45);transform:scale(1.05)}
.film{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:transparent}
.sound{position:absolute;width:1px;height:1px;opacity:0;pointer-events:none}
.record{position:relative;width:min(56vmin,320px);aspect-ratio:1;border-radius:50%;overflow:hidden;display:grid;place-items:center;background:var(--surface-3);color:var(--text-3);box-shadow:0 0 0 14px rgba(255,255,255,.06),var(--shadow-lg)}
.record img{width:100%;height:100%;object-fit:cover}
.slide>:deep(.gallery){position:absolute;inset:0;cursor:default}
.flash{position:absolute;z-index:3;display:grid;place-items:center;width:84px;height:84px;border-radius:50%;background:rgba(5,12,9,.55);animation:pop .65s var(--ease) both;pointer-events:none}
@keyframes pop{from{transform:scale(.7);opacity:0}30%{opacity:1}to{transform:scale(1.15);opacity:0}}
.top{position:absolute;top:0;left:0;right:0;z-index:5;display:flex;justify-content:space-between;align-items:center;padding:var(--sp-16) var(--sp-20);background:linear-gradient(rgba(5,12,9,.6),transparent);pointer-events:none}
.top>*{pointer-events:auto}
.pos{font-size:var(--fs-12);background:rgba(5,12,9,.55);border-radius:var(--r-pill);padding:var(--sp-4) var(--sp-12)}
.round{width:44px;height:44px;border-radius:50%;border:0;background:rgba(5,12,9,.55);color:#fff;display:grid;place-items:center;cursor:pointer;backdrop-filter:blur(6px);font-size:var(--fs-12);font-weight:600;text-decoration:none;transition:background var(--dur-fast)}
.round:hover:not(:disabled){background:var(--brand)}
.round:disabled{opacity:.35;cursor:not-allowed}
.round :deep(.up){transform:rotate(-90deg)}.round :deep(.down){transform:rotate(90deg)}
.rail{position:absolute;right:var(--sp-16);bottom:96px;z-index:5;display:flex;flex-direction:column;gap:var(--sp-12)}
.caption{position:absolute;left:var(--sp-20);right:92px;bottom:56px;z-index:5;pointer-events:none;text-shadow:0 1px 6px rgba(0,0,0,.7)}
.caption h2{margin:0;font-size:var(--fs-16);font-weight:600;line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.hint{pointer-events:auto;margin-top:var(--sp-8);border:0;border-radius:var(--r-pill);background:var(--warning-soft);color:var(--warning-text);padding:var(--sp-4) var(--sp-12);font-size:var(--fs-12);cursor:pointer}
.top,.rail,.caption,.scrub{transition:opacity .3s var(--ease)}
.idle .top,.idle .rail,.idle .scrub{opacity:0;pointer-events:none}
.caption{transition:opacity .3s var(--ease),bottom .3s var(--ease)}
.idle .caption{bottom:20px;right:var(--sp-20)}
.idle .slide{cursor:none}
.line{position:absolute;left:0;right:0;bottom:0;height:3px;z-index:4;background:rgba(255,255,255,.18);opacity:0;transition:opacity .3s var(--ease);pointer-events:none}
.line i{display:block;height:100%;background:var(--brand-text)}
.idle .line{opacity:1}
.round.on{background:var(--brand)}
.one{position:absolute;margin:-18px -20px 0 0;width:15px;height:15px;border-radius:50%;background:#fff;color:#050c09;font-size:10px;line-height:15px;text-align:center}
.round{position:relative}
.scrub{position:absolute;left:0;right:0;bottom:0;z-index:5;display:flex;align-items:center;gap:var(--sp-12);padding:var(--sp-8) var(--sp-20) var(--sp-12);background:linear-gradient(transparent,rgba(5,12,9,.7));font-size:var(--fs-11);font-variant-numeric:tabular-nums}
.scrub input{flex:1;accent-color:var(--brand);height:16px;margin:0;padding:0;border:0;background:transparent;cursor:pointer}
@media (max-width:640px){.rail{bottom:84px;right:var(--sp-12)}.round{width:40px;height:40px}.caption{right:72px;left:var(--sp-16)}}
@media (prefers-reduced-motion:reduce){.flash{animation:none}}
</style>
