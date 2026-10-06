<script setup>
defineProps({title:String,confirm:{type:String,default:'确认'},cancel:{type:String,default:'取消'},danger:Boolean,busy:Boolean,error:String})
const emit=defineEmits(['confirm','cancel'])
</script>
<template>
  <div class="dialog-backdrop" @click.self="!busy&&emit('cancel')" @keydown.esc="!busy&&emit('cancel')">
    <section class="dialog" role="dialog" aria-modal="true" :aria-label="title">
      <h2>{{title}}</h2>
      <div class="dialog-body"><slot/></div>
      <p v-if="error" class="inline-error" role="alert">{{error}}</p>
      <footer class="dialog-actions"><button class="btn" :disabled="busy" @click="emit('cancel')">{{cancel}}</button><button class="btn" :class="danger?'danger':'primary'" :disabled="busy" @click="emit('confirm')">{{busy?'请稍候…':confirm}}</button></footer>
    </section>
  </div>
</template>
