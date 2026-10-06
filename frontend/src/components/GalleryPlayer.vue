<script setup>
import {ref,computed,watch,onMounted,onUnmounted,nextTick} from 'vue'
import Icon from './Icon.vue'
// Picture post viewer: every picture of the post as a slideshow, with the post's music looping underneath.
const props=defineProps({assetId:{type:String,required:true},title:String,api:Function,chain:Boolean,interval:{type:Number,default:4000}})
const emit=defineEmits(['finished'])
const info=ref(null),index=ref(0),error=ref(''),playing=ref(true),musicOn=ref(true),blocked=ref(false),musicPlaying=ref(false),volume=ref(0.7)
const audio=ref(null),stage=ref(null)
let timer=null
const count=computed(()=>info.value?.images.length||0)
const current=computed(()=>info.value?.images[index.value])
const src=(id)=>`/api/files/${id}/stream`
async function load(){
  try{info.value=await props.api(`/files/${props.assetId}/gallery`);index.value=info.value.index||0;error.value=''}
  catch(e){error.value=e.message;return}
  await nextTick();startMusic();schedule();stage.value?.focus()
}
function go(n,fromTimer=false){
  if(!count.value)return
  const next=n<0?count.value-1:n
  if(next>=count.value){
    if(fromTimer&&props.chain){playing.value=false;clearTimeout(timer);emit('finished');return}   // end of post: continue with the next work
    index.value=0
  }else index.value=next
  schedule()
}
function schedule(){clearTimeout(timer);if(playing.value&&count.value>1)timer=setTimeout(()=>go(index.value+1,true),props.interval)}
function toggleSlides(){playing.value=!playing.value;schedule()}
async function startMusic(){
  const el=audio.value;if(!el||!musicOn.value)return
  el.volume=volume.value
  try{await el.play();blocked.value=false}catch(e){blocked.value=true}   // browsers may refuse sound without a recent click
}
function toggleMusic(){
  const el=audio.value;if(!el)return
  if(el.paused){musicOn.value=true;startMusic()}else{musicOn.value=false;el.pause()}
}
watch(volume,v=>{if(audio.value)audio.value.volume=v})
function key(e){
  if(e.key==='ArrowRight'){go(index.value+1);e.preventDefault()}else if(e.key==='ArrowLeft'){go(index.value-1);e.preventDefault()}
  else if(e.key===' '){toggleSlides();e.preventDefault()}
}
watch(()=>props.assetId,()=>{info.value=null;load()})
onMounted(load)
onUnmounted(()=>{clearTimeout(timer);audio.value?.pause()})
</script>
<template>
  <div class="gallery" ref="stage" tabindex="0" @keydown="key" aria-label="图集播放器">
    <p v-if="error" class="inline-error" role="alert">{{error}}</p>
    <template v-else-if="info">
      <div class="gallery-stage">
        <img :key="current.id" class="gallery-image" :src="src(current.id)" :alt="`${title||'图集'} 第 ${index+1} 张`">
        <button v-if="count>1" class="gallery-nav prev" aria-label="上一张" @click="go(index-1)"><Icon name="chevron" :size="22"/></button>
        <button v-if="count>1" class="gallery-nav next" aria-label="下一张" @click="go(index+1)"><Icon name="chevron" :size="22"/></button>
        <span class="gallery-count" aria-live="polite">{{index+1}} / {{count}}</span>
        <div v-if="playing&&count>1" class="gallery-timer" :key="index+'-'+interval" :style="{animationDuration:interval+'ms'}"></div>
      </div>
      <div v-if="count>1" class="gallery-thumbs" role="tablist" aria-label="图片缩略图"><button v-for="(im,i) in info.images" :key="im.id" role="tab" :aria-selected="i===index" :class="{on:i===index}" :aria-label="`第 ${i+1} 张`" @click="go(i)"><img :src="src(im.id)" alt="" loading="lazy"></button></div>
      <div class="gallery-bar">
        <button v-if="count>1" class="gbtn" :aria-pressed="playing" @click="toggleSlides"><Icon :name="playing?'stop':'play'" :size="14"/> {{playing?'暂停轮播':'自动轮播'}}</button>
        <template v-if="info.audio">
          <button class="gbtn" :class="{alert:blocked}" @click="toggleMusic"><Icon name="music" :size="14"/> {{blocked?'点击播放背景音乐':musicPlaying?'暂停音乐':'播放音乐'}}</button>
          <label class="gvol"><Icon name="music" :size="12"/><input type="range" min="0" max="1" step="0.05" v-model.number="volume" aria-label="音乐音量"></label>
          <audio ref="audio" :src="src(info.audio.id)" loop preload="auto" @play="blocked=false;musicPlaying=true" @pause="musicPlaying=false"></audio>
        </template>
        <span v-else class="gmuted">这个图集没有背景音乐</span>
      </div>
    </template>
    <p v-else class="gmuted">正在加载图集…</p>
  </div>
</template>
<style scoped>
.gallery{display:flex;flex-direction:column;gap:12px;outline:none}
.gallery-stage{position:relative;background:#111c17;border-radius:12px;height:min(62vh,640px);display:grid;place-items:center;overflow:hidden}
.gallery-image{max-width:100%;max-height:100%;object-fit:contain;animation:gfade .25s ease}@keyframes gfade{from{opacity:0}to{opacity:1}}
.gallery-nav{position:absolute;top:50%;transform:translateY(-50%);width:42px;height:42px;border-radius:50%;border:0;background:rgba(255,255,255,.88);color:#253c34;display:grid;place-items:center;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.25)}
.gallery-nav:hover{background:#fff}.gallery-nav.prev{left:12px}.gallery-nav.prev svg{transform:rotate(180deg)}.gallery-nav.next{right:12px}
.gallery-count{position:absolute;top:12px;right:12px;background:rgba(17,28,23,.7);color:#fff;font-size:12px;border-radius:999px;padding:4px 11px}
.gallery-timer{position:absolute;left:0;bottom:0;height:3px;background:#59b88a;width:100%;transform-origin:left;animation:gtimer linear forwards}@keyframes gtimer{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.gallery-thumbs{display:flex;gap:8px;overflow-x:auto;padding:2px}
.gallery-thumbs button{flex:0 0 auto;width:62px;height:62px;border-radius:8px;border:2px solid transparent;padding:0;background:#e6ebe2;overflow:hidden;cursor:pointer;opacity:.7}
.gallery-thumbs button.on{border-color:#256349;opacity:1}.gallery-thumbs img{width:100%;height:100%;object-fit:cover;display:block}
.gallery-bar{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.gbtn{display:inline-flex;align-items:center;gap:7px;border:1px solid #d5ddd1;background:#fff;color:#253c34;border-radius:9px;padding:8px 13px;font-size:13px;cursor:pointer}
.gbtn:hover{background:#f4f7f1}.gbtn.alert{background:#fbf3de;border-color:#e5cf93;color:#7d5a14}
.gvol{display:inline-flex!important;flex-direction:row!important;align-items:center;gap:7px;margin:0!important;color:#78877d}.gvol input[type=range]{width:96px;padding:0;border:0;accent-color:#256349}
.gmuted{font-size:12px;color:#78877d}.inline-error{background:#fcefea;color:#9a4630;border-radius:9px;padding:10px 13px;font-size:13px;margin:0}
@media (prefers-reduced-motion:reduce){.gallery-image,.gallery-timer{animation:none}}
</style>
