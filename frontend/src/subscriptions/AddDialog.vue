<script setup>
import {ref,computed,onMounted} from 'vue'
import Icon from '../components/Icon.vue'
import {INTERVALS} from './meta.js'
const props=defineProps({api:Function,cookieSaved:Boolean})
const emit=defineEmits(['close','created','login'])
const KINDS=[
  {id:'douyin',label:'抖音博主',hint:'博主主页链接或分享短链接',placeholder:'https://www.douyin.com/user/… 或 https://v.douyin.com/…',platform:'douyin'},
  {id:'youtube_videos',label:'YouTube 频道',hint:'频道主页链接',placeholder:'https://www.youtube.com/@频道名',platform:'youtube'},
  {id:'youtube_shorts',label:'YouTube Shorts',hint:'频道主页链接（只订阅 Shorts）',placeholder:'https://www.youtube.com/@频道名',platform:'youtube'},
  {id:'youtube_playlist',label:'YouTube 歌单',hint:'歌单链接或 PL 开头的歌单标识',placeholder:'https://www.youtube.com/playlist?list=PL…',platform:'youtube_playlist'},
  {id:'bilibili',label:'B 站作者',hint:'作者空间链接',placeholder:'https://space.bilibili.com/用户标识',platform:'bilibili'}
]
const kind=ref('douyin'),link=ref(''),nickname=ref(''),interval=ref(28800),autoDownload=ref(false)
const busy=ref(false),error=ref(''),input=ref(null)
const current=computed(()=>KINDS.find(k=>k.id===kind.value))
const needsLogin=computed(()=>kind.value==='douyin')
async function paste(){try{link.value=(await navigator.clipboard.readText()).trim()}catch(e){error.value='浏览器没有允许读取剪贴板，请手动粘贴'}}
async function submit(){
  if(!link.value.trim()){error.value='请先填写链接';input.value?.focus();return}
  busy.value=true;error.value=''
  try{
    const created=await props.api('/subscriptions','POST',{platform:current.value.platform,profile_url:link.value.trim(),nickname:nickname.value.trim(),
      update_interval:interval.value,auto_download:autoDownload.value,youtube_tab_type:kind.value==='youtube_shorts'?'shorts':'videos'})
    emit('created',created)
  }catch(e){error.value=e.message}finally{busy.value=false}
}
onMounted(()=>input.value?.focus())
</script>
<template>
  <div class="dialog-backdrop" @click.self="!busy&&emit('close')" @keydown.esc="!busy&&emit('close')">
    <section class="dialog wide" role="dialog" aria-modal="true" aria-labelledby="add-sub-title">
      <header class="dialog-head"><div><h2 id="add-sub-title">添加订阅</h2><p>订阅后会按设定的间隔自动检查新作品，并按需自动下载。</p></div><button class="icon-btn" aria-label="关闭" :disabled="busy" @click="emit('close')"><Icon name="close"/></button></header>
      <form class="add-form" @submit.prevent="submit">
        <div class="field"><span class="field-label">订阅类型</span>
          <div class="kind-grid" role="radiogroup"><button v-for="k in KINDS" :key="k.id" type="button" role="radio" :aria-checked="kind===k.id" class="kind" :class="{on:kind===k.id}" :disabled="busy" @click="kind=k.id;error=''">{{k.label}}</button></div>
        </div>
        <div v-if="needsLogin" class="login-card" :class="{ok:cookieSaved}">
          <Icon :name="cookieSaved?'check':'key'" :size="18"/>
          <div><strong>{{cookieSaved?'已保存抖音登录状态':'读取抖音博主作品需要先登录'}}</strong><p>{{cookieSaved?'可以直接添加订阅。登录过期时在这里重新登录即可。':'点击右侧按钮，在弹出的浏览器里登录抖音并保存。下载作品本身不需要登录。'}}</p></div>
          <button type="button" class="btn small" :disabled="busy" @click="emit('login')">{{cookieSaved?'重新登录':'登录抖音'}}</button>
        </div>
        <label class="field"><span class="field-label">{{current.hint}}</span>
          <span class="input-row"><input ref="input" v-model="link" :disabled="busy" maxlength="8192" :placeholder="current.placeholder" spellcheck="false" autocomplete="off"><button type="button" class="btn small" :disabled="busy" @click="paste">粘贴</button></span>
        </label>
        <div class="field-grid">
          <label class="field"><span class="field-label">自定义昵称 <em>可选</em></span><input v-model="nickname" :disabled="busy" maxlength="256" placeholder="留空使用平台名称"></label>
          <label class="field"><span class="field-label">检查频率</span><select v-model.number="interval" :disabled="busy"><option v-for="i in INTERVALS" :key="i.value" :value="i.value">{{i.label}}</option></select></label>
        </div>
        <label class="switch-row"><input v-model="autoDownload" type="checkbox" :disabled="busy"><span class="switch" aria-hidden="true"></span><span><strong>发现新作品时自动下载</strong><small>默认关闭：只记录作品，需要时在作品列表里手动下载。开启后，首次扫描到的作品也会立即加入下载队列。</small></span></label>
        <p v-if="error" class="inline-error" role="alert">{{error}}</p>
        <footer class="dialog-actions"><button type="button" class="btn" :disabled="busy" @click="emit('close')">取消</button><button class="btn primary" :disabled="busy">{{busy?'正在解析…':'解析并添加'}}</button></footer>
      </form>
    </section>
  </div>
</template>
