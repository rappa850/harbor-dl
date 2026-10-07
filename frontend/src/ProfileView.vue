<script setup>
import {ref,onMounted} from 'vue'
import Avatar from './components/Avatar.vue'
const props=defineProps({api:Function,notify:Function})
const emit=defineEmits(['renamed','avatar'])
const profile=ref(null),busy=ref(false),loadError=ref('')
const picker=ref(null),avatarError=ref('')
const name=ref(''),nameError=ref('')
const form=ref({current:'',next:'',again:''}),passwordError=ref('')
function created(value){return value?new Date(value).toLocaleDateString('zh-CN',{year:'numeric',month:'long',day:'numeric'}):'—'}
async function load(){
  try{profile.value=await props.api('/auth/profile');name.value=profile.value.username;loadError.value=''}
  catch(e){loadError.value=e.message}
}
async function rename(){
  busy.value=true;nameError.value=''
  try{const result=await props.api('/auth/profile','PATCH',{username:name.value});emit('renamed',result.username);await load();props.notify('用户名已更新')}
  catch(e){nameError.value=e.message}finally{busy.value=false}
}
async function changePassword(){
  passwordError.value=''
  if(form.value.next!==form.value.again){passwordError.value='两次输入的新密码不一致';return}
  busy.value=true
  try{
    await props.api('/auth/password','POST',{current_password:form.value.current,new_password:form.value.next})
    form.value={current:'',next:'',again:''};await load();props.notify('密码已更新，其他设备已退出登录')
  }catch(e){passwordError.value=e.message}finally{busy.value=false}
}
const SIZE=256
// 居中裁成正方形并缩到 256 px，上传体积小，也不会把原图的 EXIF 位置信息带上去。
async function squareJpeg(file){
  const bitmap=await createImageBitmap(file,{imageOrientation:'from-image'})
  const side=Math.min(bitmap.width,bitmap.height),canvas=document.createElement('canvas')
  canvas.width=canvas.height=SIZE
  const ctx=canvas.getContext('2d');ctx.fillStyle='#fff';ctx.fillRect(0,0,SIZE,SIZE)
  ctx.drawImage(bitmap,(bitmap.width-side)/2,(bitmap.height-side)/2,side,side,0,0,SIZE,SIZE);bitmap.close?.()
  return new Promise((resolve,reject)=>canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('图片处理失败')),'image/jpeg',.9))
}
async function chooseAvatar(event){
  const file=event.target.files?.[0];event.target.value=''
  if(!file)return
  avatarError.value='';busy.value=true
  try{
    if(!file.type.startsWith('image/'))throw new Error('请选择图片文件')
    const result=await props.api('/auth/avatar','PUT',await squareJpeg(file))
    profile.value.avatar=result.avatar;emit('avatar',result.avatar);props.notify('头像已更新')
  }catch(e){avatarError.value=e.message||'头像上传失败'}finally{busy.value=false}
}
async function removeAvatar(){
  busy.value=true;avatarError.value=''
  try{await props.api('/auth/avatar','DELETE');profile.value.avatar=null;emit('avatar',null);props.notify('头像已移除')}
  catch(e){avatarError.value=e.message}finally{busy.value=false}
}
async function revokeOthers(){
  busy.value=true
  try{const result=await props.api('/auth/sessions/revoke-others','POST');await load();props.notify(result.revoked?`已退出其他 ${result.revoked} 台设备`:'没有其他已登录的设备')}
  catch(e){props.notify(e.message)}finally{busy.value=false}
}
onMounted(load)
</script>

<template>
  <div class="settings-grid profile">
    <p v-if="loadError" class="error" role="alert">{{loadError}} <button @click="load">重试</button></p>
    <template v-if="profile">
      <section class="panel settings">
        <h2>账号概览</h2>
        <div class="profile-head"><Avatar :name="profile.username" :version="profile.avatar" :size="72"/><div><strong>{{profile.username}}</strong><small>管理员</small><div class="avatar-actions"><input ref="picker" type="file" accept="image/png,image/jpeg,image/webp,image/gif" hidden @change="chooseAvatar"><button :disabled="busy" @click="picker.click()">{{profile.avatar?'更换头像':'上传头像'}}</button><button v-if="profile.avatar" :disabled="busy" class="danger-text" @click="removeAvatar">移除</button></div></div></div>
        <p v-if="avatarError" class="error" role="alert">{{avatarError}}</p>
        <div class="setting-row"><span>创建时间</span><strong>{{created(profile.created_at)}}</strong></div>
        <div class="setting-row"><span>已登录的设备</span><strong>{{profile.active_sessions}} 台（含当前）</strong></div>
        <div class="setting-row"><span>API Token</span><strong>{{profile.api_tokens}} 个 · 在“设置”中管理</strong></div>
        <div class="download-buttons"><button :disabled="busy||profile.active_sessions<2" @click="revokeOthers">退出其他设备</button></div>
      </section>
      <section class="panel settings">
        <h2>修改用户名</h2>
        <form @submit.prevent="rename">
          <label>用户名<input v-model="name" required minlength="3" maxlength="64" autocomplete="username"><small>3–64 个字符，登录时使用。</small></label>
          <p v-if="nameError" class="error" role="alert">{{nameError}}</p>
          <button class="primary" :disabled="busy||name.trim()===profile.username">保存用户名</button>
        </form>
      </section>
      <section class="panel settings">
        <h2>修改密码</h2>
        <p>修改后，除当前设备外的登录会话都会失效。</p>
        <form @submit.prevent="changePassword">
          <label>当前密码<input type="password" v-model="form.current" required autocomplete="current-password"></label>
          <label>新密码<input type="password" v-model="form.next" required minlength="10" maxlength="256" autocomplete="new-password"><small>至少 10 个字符。</small></label>
          <label>确认新密码<input type="password" v-model="form.again" required minlength="10" maxlength="256" autocomplete="new-password"></label>
          <p v-if="passwordError" class="error" role="alert">{{passwordError}}</p>
          <button class="primary" :disabled="busy">更新密码</button>
        </form>
      </section>
    </template>
  </div>
</template>

<style>
.profile-head{display:flex;align-items:center;gap:var(--sp-16);padding:var(--sp-8) 0 var(--sp-16)}
.profile-head strong{display:block;font-size:var(--fs-18)}
.profile-head small{color:var(--text-3)}
.avatar-actions{display:flex;gap:var(--sp-16);margin-top:var(--sp-8);font-size:var(--fs-12)}
.avatar-actions button{padding:0;color:var(--success-text)}
.avatar-actions .danger-text{color:var(--danger-text)}
.profile .error button{margin-left:var(--sp-8);text-decoration:underline}
.profile .download-buttons{margin-top:var(--sp-16)}
</style>
