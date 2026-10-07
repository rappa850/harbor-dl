<script setup>
// 有头像显示图片（版本号用来绕过浏览器缓存），否则显示用户名首字母。
defineProps({name: {type: String, default: ''}, version: {type: Number, default: null}, size: {type: Number, default: 32}})
</script>

<template>
  <span class="avatar" :style="{width: size + 'px', height: size + 'px', fontSize: size * .42 + 'px'}">
    <img v-if="version" :src="`/api/auth/avatar?v=${version}`" alt="" draggable="false">
    <template v-else>{{name.slice(0, 1).toUpperCase()}}</template>
  </span>
</template>

<style>
.avatar{overflow:hidden;flex-shrink:0}
.avatar img{width:100%;height:100%;object-fit:cover;display:block}
</style>
