<script setup>
import {ref,watch,onBeforeUnmount,nextTick} from 'vue'
import Plyr from 'plyr'
import sprite from '../design/plyr.svg?url'
import '../design/plyr-theme.css'
// Plyr on top of the native element. The native <video>/<audio> stays the event source (its dataset and events are what
// the playback record code in App.vue reads), and Plyr is built only once the subtitle list is known, because Plyr reads
// <track> children when it is created and moving a playing element would pause it.
const props=defineProps({src:{type:String,required:true},kind:{type:String,default:'video'},assetId:String,scope:String,tracks:{type:Array,default:null},poster:String})
const emit=defineEmits(['loadedmetadata','timeupdate','pause','play','ended','error'])
const media=ref(null),root=ref(null)
let player=null
const i18n={restart:'重播',rewind:'快退 {seektime} 秒',play:'播放',pause:'暂停',fastForward:'快进 {seektime} 秒',seek:'拖动进度',seekLabel:'{currentTime} / {duration}',
  played:'已播放',buffered:'已缓冲',currentTime:'当前时间',duration:'总时长',volume:'音量',mute:'静音',unmute:'取消静音',enableCaptions:'开启字幕',disableCaptions:'关闭字幕',
  download:'下载',enterFullscreen:'全屏',exitFullscreen:'退出全屏',frameTitle:'播放器：{title}',captions:'字幕',settings:'设置',pip:'画中画',menuBack:'返回上一级',
  speed:'倍速',normal:'正常',quality:'画质',loop:'循环',start:'起点',end:'终点',all:'全部',reset:'重置',disabled:'关闭',enabled:'开启',advertisement:'广告'}
function build(){
  if(player||!media.value||props.tracks===null)return
  const audio=props.kind==='audio'
  player=new Plyr(media.value,{
    iconUrl:sprite,blankVideo:'',i18n,tooltips:{controls:true,seek:true},
    controls:audio?['play','progress','current-time','duration','mute','volume','settings']:
      ['play-large','play','progress','current-time','duration','mute','volume','captions','settings','pip','fullscreen'],
    settings:audio?['speed']:['captions','speed'],
    speed:{selected:1,options:[0.5,0.75,1,1.25,1.5,2]},
    keyboard:{focused:true,global:true},clickToPlay:!audio,hideControls:!audio,
    captions:{active:props.tracks.some(t=>t.is_default),update:true},
    storage:{enabled:true,key:'harbor-plyr'}
  })
  media.value.src=props.src
  player.play()?.catch?.(()=>{})   // the click that opened the player normally allows sound; otherwise the user presses play
}
watch(()=>props.tracks,async()=>{await nextTick();build()},{immediate:true,flush:'post'})
onBeforeUnmount(()=>{try{media.value?.pause()}catch(e){}player?.destroy();player=null})
defineExpose({get element(){return media.value},get player(){return player}})
</script>
<template>
  <div ref="root" class="media-player" :data-kind="kind">
    <component :is="kind==='audio'?'audio':'video'" ref="media" :data-asset-id="assetId" :data-subscription-id="scope||''" :poster="poster||undefined" playsinline preload="metadata"
      @loadedmetadata="emit('loadedmetadata',$event)" @timeupdate="emit('timeupdate',$event)" @pause="emit('pause',$event)" @play="emit('play',$event)"
      @ended="emit('ended',$event)" @error="emit('error',$event)">
      <track v-for="track in tracks||[]" :key="track.id" kind="subtitles" :src="track.path" :label="track.label" :srclang="track.language.split('.')[0]" :default="track.is_default">
    </component>
  </div>
</template>
<style scoped>
.media-player{width:100%;border-radius:var(--r-md);overflow:hidden}
.media-player[data-kind=video] :deep(.plyr){height:min(62vh,720px)}
.media-player[data-kind=video] :deep(.plyr__video-wrapper){height:100%}
.media-player[data-kind=video] :deep(video){width:100%;height:100%;max-height:none;object-fit:contain}
</style>
