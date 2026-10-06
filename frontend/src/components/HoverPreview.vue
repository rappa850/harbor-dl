<script setup>
import {ref,computed,onMounted,onBeforeUnmount} from 'vue'
import Icon from './Icon.vue'
import '../design/preview.css'
// Muted hover preview for a cover. It listens on its parent element (the cover), so the cover keeps its own markup.
// Mouse only: touch has no hover and must not start downloads while scrolling. One preview plays at a time.
const props=defineProps({src:{type:String,required:true},delay:{type:Number,default:280}})
const root=ref(null),video=ref(null),active=ref(false),paused=ref(false),time=ref(0),duration=ref(0),muted=ref(!sound.on)
let host=null,timer=null
function enter(e){
  if(e.pointerType&&e.pointerType!=='mouse')return
  clearTimeout(timer)
  timer=setTimeout(start,props.delay)
}
function start(){
  stopOthers()
  active.value=true;paused.value=false;time.value=0;duration.value=0;muted.value=!sound.on
  host?.classList.add('hp-on')
  mine=stop
}
function stop(){
  clearTimeout(timer)
  if(video.value){video.value.pause();video.value.removeAttribute('src');video.value.load()}
  active.value=false
  host?.classList.remove('hp-on')
  if(mine===stop)mine=null
}
function onPlayable(){const el=video.value;if(!el)return;el.muted=muted.value;el.play().catch(()=>{paused.value=true})}
function toggle(){const el=video.value;if(!el)return;if(el.paused){el.play();paused.value=false}else{el.pause();paused.value=true}}
function toggleSound(){sound.on=!sound.on;muted.value=!sound.on;if(video.value)video.value.muted=muted.value}
const dragging=ref(false)
const pct=computed(()=>duration.value?Math.min(100,time.value/duration.value*100):0)
function seek(e){
  const el=video.value;if(!el||!Number.isFinite(el.duration))return
  const box=e.currentTarget.querySelector('.hp-line').getBoundingClientRect()
  const at=Math.min(1,Math.max(0,(e.clientX-box.left)/box.width))
  el.currentTime=at*el.duration;time.value=el.currentTime
}
function down(e){dragging.value=true;e.currentTarget.setPointerCapture?.(e.pointerId);seek(e)}
function move(e){if(dragging.value)seek(e)}
function up(e){dragging.value=false;e.currentTarget.releasePointerCapture?.(e.pointerId)}
onMounted(()=>{host=root.value?.parentElement;host?.addEventListener('pointerenter',enter);host?.addEventListener('pointerleave',stop)})
onBeforeUnmount(()=>{host?.removeEventListener('pointerenter',enter);host?.removeEventListener('pointerleave',stop);stop()})
</script>
<script>
// Shared by all previews on the page: the sound choice and "the one that is playing".
const sound={on:false}
let mine=null
function stopOthers(){mine?.()}
</script>
<template>
  <div ref="root" class="hp" :class="{on:active}">
    <template v-if="active">
      <video ref="video" class="hp-video" :src="src" :muted="muted" playsinline loop preload="auto" @loadeddata="onPlayable"
        @timeupdate="if(!dragging)time=$event.target.currentTime;duration=$event.target.duration||0" @error="stop"></video>
      <div class="hp-bar" @click.stop>
        <button type="button" class="hp-btn" :aria-label="paused?'播放预览':'暂停预览'" @click.stop.prevent="toggle"><Icon :name="paused?'play':'pause'" :size="15"/></button>
        <button type="button" class="hp-btn" :aria-label="muted?'开启声音':'静音'" :aria-pressed="!muted" @click.stop.prevent="toggleSound"><Icon :name="muted?'mute':'volume'" :size="15"/></button>
      </div>
      <div class="hp-track" :class="{drag:dragging}" role="slider" tabindex="-1" aria-label="预览进度" :aria-valuenow="Math.round(time)" :aria-valuemax="Math.round(duration)"
        @pointerdown.stop.prevent="down" @pointermove="move" @pointerup="up" @pointercancel="up" @click.stop.prevent>
        <span class="hp-line"><i :style="{width:pct+'%'}"></i><b class="hp-dot" :style="{left:pct+'%'}"></b></span>
      </div>
    </template>
  </div>
</template>
