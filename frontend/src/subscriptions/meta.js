export const PLATFORMS={
  douyin:{label:'抖音',tone:'#1c1c2b'},douyin_collection:{label:'抖音合集',tone:'#1c1c2b'},douyin_favorite:{label:'抖音点赞',tone:'#1c1c2b'},
  youtube:{label:'YouTube',tone:'#c4302b'},youtube_playlist:{label:'YouTube 歌单',tone:'#c4302b'},
  bilibili:{label:'哔哩哔哩',tone:'#00a1d6'},bilibili_collection:{label:'B 站合集',tone:'#00a1d6'},
  tiktok:{label:'TikTok',tone:'#25262b'},instagram:{label:'Instagram',tone:'#a43c8a'},x:{label:'X',tone:'#222'},netease:{label:'网易云',tone:'#c20c0c'},
  xiaohongshu:{label:'小红书',tone:'#ff2742'},kuaishou:{label:'快手',tone:'#ff5b00'}
}
export const platformLabel=(item)=>{
  const base=PLATFORMS[item.platform]?.label||item.platform
  if(item.platform==='youtube'&&item.youtube_tab_type==='shorts')return 'YouTube Shorts'
  if(item.subscription_type==='favorite'&&!base.includes('点赞'))return base+'·收藏'
  return base
}
export const platformTone=(item)=>PLATFORMS[item.platform]?.tone||'#4a6556'
export const FILTERS=[{id:'douyin',label:'抖音',match:p=>p.startsWith('douyin')},{id:'youtube',label:'YouTube',match:p=>p.startsWith('youtube')},
  {id:'bilibili',label:'B 站',match:p=>p.startsWith('bilibili')},{id:'other',label:'其他',match:p=>!/^(douyin|youtube|bilibili)/.test(p)}]
export const INTERVALS=[{value:3600,label:'每小时'},{value:7200,label:'每 2 小时'},{value:14400,label:'每 4 小时'},{value:28800,label:'每 8 小时'},
  {value:43200,label:'每 12 小时'},{value:86400,label:'每天'},{value:0,label:'暂停自动检查'}]
export function intervalLabel(seconds){
  const hit=INTERVALS.find(i=>i.value===Number(seconds));if(hit)return hit.label
  const h=Number(seconds)/3600;return Number.isInteger(h)?`每 ${h} 小时`:`每 ${Math.round(Number(seconds)/60)} 分钟`
}
export function duration(seconds){
  if(!Number.isFinite(seconds)||seconds<=0)return ''
  const s=Math.round(seconds),m=Math.floor(s/60),r=s%60,h=Math.floor(m/60)
  return h?`${h}:${String(m%60).padStart(2,'0')}:${String(r).padStart(2,'0')}`:`${m}:${String(r).padStart(2,'0')}`
}
export function relative(value,future=false){
  if(!value||value==='pending')return value==='pending'?'即将进行':'尚未检查'
  const t=new Date(value).getTime();if(Number.isNaN(t))return '—'
  const diff=Math.round((future?t-Date.now():Date.now()-t)/1000)
  if(diff<45)return future?'即将':'刚刚'
  const units=[[86400,'天'],[3600,'小时'],[60,'分钟']]
  for(const [size,name] of units)if(diff>=size)return future?`${Math.round(diff/size)} ${name}后`:`${Math.round(diff/size)} ${name}前`
  return '刚刚'
}
export const dateText=(value)=>{if(!value)return '时间未知';const d=new Date(value);return Number.isNaN(d.getTime())?'时间未知':d.toLocaleDateString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit'})}
export const count=(n)=>{if(n===null||n===undefined)return '—';if(n>=1e8)return (n/1e8).toFixed(1)+' 亿';if(n>=1e4)return (n/1e4).toFixed(1)+' 万';return String(n)}
export const STATUS={downloaded:{label:'已下载',tone:'ok'},downloading:{label:'下载中',tone:'info'},not_downloaded:{label:'未下载',tone:'idle'},
  failed:{label:'下载失败',tone:'bad'},cancelled:{label:'已取消',tone:'idle'},orphaned:{label:'文件缺失',tone:'warn'}}
export const statusLabel=(video)=>video.task_status==='PENDING'?'排队中':video.task_status==='PROCESSING'?'处理中':STATUS[video.status]?.label||video.status
