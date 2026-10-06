<script setup>
import {ref,computed,onMounted,onUnmounted} from 'vue'
const props=defineProps({api:Function,notify:Function,platform:{type:String,required:true},label:{type:String,default:''}})
const emit=defineEmits(['close','saved'])
const status=ref(null),error=ref(''),starting=ref(true),saving=ref(false),closing=ref(false)
let poll=null,beat=null
const embedded=computed(()=>status.value?.mode==='docker'&&status.value?.running)
const frame=computed(()=>embedded.value?'/novnc/vnc_lite.html?path=websockify&autoconnect=true&resize=remote&scale=true&reconnect=true':'')
async function refresh(){try{status.value=await props.api('/browser');if(!status.value.running&&!starting.value&&!closing.value)error.value='浏览器已关闭，需要重新打开才能登录'}catch(e){error.value=e.message}}
async function open(){
  starting.value=true;error.value=''
  try{
    const current=await props.api('/browser')
    if(current.active_tasks>0&&!window.confirm(`当前有 ${current.active_tasks} 个订阅同步 / 检查任务在运行，打开登录浏览器可能影响它们。是否继续？`)){emit('close');return}
    status.value=await props.api(`/browser/${props.platform}/login`,'POST')
    poll=setInterval(refresh,3000)
    beat=setInterval(()=>props.api('/browser/heartbeat','POST').catch(()=>{}),10000)
  }catch(e){error.value=e.message}finally{starting.value=false}
}
async function save(){
  saving.value=true;error.value=''
  try{await props.api(`/browser/${props.platform}/save`,'POST');props.notify(`${props.label}登录状态已保存`);emit('saved');await shut()}
  catch(e){error.value=e.message}finally{saving.value=false}
}
async function shut(){
  closing.value=true;clearInterval(poll);clearInterval(beat)
  try{await props.api('/browser/close','POST')}catch(e){/* already closed */}
  emit('close')
}
onMounted(open)
onUnmounted(()=>{clearInterval(poll);clearInterval(beat)})
</script>
<template>
  <div class="overlay"><section class="modal browser-login" role="dialog" aria-modal="true" aria-labelledby="browser-login-title">
    <h2 id="browser-login-title">{{label}}登录</h2>
    <p v-if="starting">正在启动浏览器…</p>
    <template v-else-if="status?.running">
      <p v-if="embedded">下方是服务器上的内嵌浏览器，请在其中完成{{label}}登录。无操作超过 {{Math.round(status.idle_timeout/60)}} 分钟或关闭本窗口时会自动关闭。</p>
      <p v-else>已在独立的 Chrome 窗口中打开{{label}}（使用 Harbor-DL 专用用户目录，不影响你日常使用的 Chrome）。请在该窗口完成登录，然后回到这里保存。</p>
      <iframe v-if="embedded" class="browser-frame" :src="frame" title="内嵌浏览器"></iframe>
      <p class="hint" role="status">登录状态：{{status.logged_in?'已检测到登录':'尚未检测到登录'}}</p>
    </template>
    <p v-if="error" class="error" role="alert">{{error}}</p>
    <div class="modal-actions"><button :disabled="saving||closing" @click="shut">关闭浏览器</button><button class="primary" :disabled="saving||closing||!status?.running||!status?.logged_in" @click="save">{{saving?'正在保存…':'保存登录状态'}}</button></div>
  </section></div>
</template>
