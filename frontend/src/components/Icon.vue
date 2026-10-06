<script setup>
defineProps({name:{type:String,required:true},size:{type:Number,default:16}})
const paths={
  plus:'M12 5v14M5 12h14',search:'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4',refresh:'M20 11a8 8 0 0 0-14.9-3M4 5v4h4M4 13a8 8 0 0 0 14.9 3M20 19v-4h-4',
  play:'M8 5v14l11-7z',download:'M12 4v11m0 0l-4-4m4 4l4-4M5 19h14',more:'M5 12h.01M12 12h.01M19 12h.01',check:'M5 12.5l4.5 4.5L19 7.5',
  alert:'M12 8v5m0 3.5h.01M10.3 3.9L2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z',
  image:'M4 5h16v14H4zM8.5 10a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM4 17l5-5 4 4 3-3 4 4',trash:'M5 7h14M10 7V4h4v3m-8 0l1 13h10l1-13M10 11v6m4-6v6',
  edit:'M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4',link:'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3A4 4 0 0 0 11 18.7l1-1',
  settings:'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 13a7.5 7.5 0 0 0 0-2l2-1.5-2-3.4-2.3 1a7.5 7.5 0 0 0-1.7-1L15 3.5h-4l-.4 2.6a7.5 7.5 0 0 0-1.7 1l-2.3-1-2 3.4 2 1.5a7.5 7.5 0 0 0 0 2l-2 1.5 2 3.4 2.3-1a7.5 7.5 0 0 0 1.7 1l.4 2.6h4l.4-2.6a7.5 7.5 0 0 0 1.7-1l2.3 1 2-3.4z',
  user:'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 20a8 8 0 0 1 16 0',close:'M6 6l12 12M18 6L6 18',upload:'M12 15V4m0 0L8 8m4-4l4 4M5 19h14',
  film:'M4 5h16v14H4zM8 5v14M16 5v14M4 9h4M16 9h4M4 15h4M16 15h4',music:'M9 18V6l11-2v12M9 18a3 3 0 1 1-3-3 3 3 0 0 1 3 3zm11-2a3 3 0 1 1-3-3 3 3 0 0 1 3 3z',
  clock:'M12 7v5l3 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z',key:'M14 10a4 4 0 1 0-3.5 4L12 16h2v2h2v2h3v-3l-5-5',folder:'M3 6h6l2 2h10v11H3z',
  chevron:'M9 6l6 6-6 6',stop:'M7 7h10v10H7z',external:'M14 4h6v6M20 4l-9 9M18 14v6H4V6h6'
}
</script>
<template><svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path :d="paths[name]||paths.alert"/></svg></template>
