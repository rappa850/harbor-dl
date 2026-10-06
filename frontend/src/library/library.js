// Media library model: files of one post are merged into one entry, covers snap to a few common shapes.
export const SHAPES = [
  {id:'9:16',ratio:9/16},{id:'3:4',ratio:3/4},{id:'1:1',ratio:1},{id:'4:3',ratio:4/3},{id:'16:9',ratio:16/9}
]
export const TYPES = [
  {id:'',name:'全部'},{id:'video',name:'视频'},{id:'gallery',name:'图集'},{id:'image',name:'图片'},{id:'audio',name:'音频'}
]
export const LAYOUTS = [
  {id:'irregular',name:'不规则',hint:'按封面比例，取最近的常用档位'},
  {id:'phone',name:'手机比例',hint:'统一 9:16',shape:'9:16'},
  {id:'tablet',name:'平板比例',hint:'统一 3:4',shape:'3:4'}
]
export const SORTS = [
  {id:'new',name:'最新收藏'},{id:'old',name:'最早收藏'},{id:'big',name:'体积最大'},{id:'name',name:'名称'}
]

/** Nearest common shape, measured on a log scale so 2:1 is as far from 1:1 as 1:2 is. */
export function snapShape(ratio,fallback='16:9'){
  if(!(ratio>0))return SHAPES.find(s=>s.id===fallback)
  return SHAPES.reduce((best,s)=>Math.abs(Math.log(ratio/s.ratio))<Math.abs(Math.log(ratio/best.ratio))?s:best)
}

const stem=name=>name.replace(/\.[^.]+$/,'')

/** One entry per post (task) that has pictures; every other file stands alone. Order follows the first file of each. */
export function groupFiles(files){
  const posts=new Set(files.filter(f=>f.task_id&&f.kind==='image').map(f=>f.task_id))
  const entries=[],emitted=new Set()
  for(const f of files){
    if(f.kind==='attachment')continue
    if(!(f.task_id&&posts.has(f.task_id))){entries.push(single(f));continue}
    if(emitted.has(f.task_id))continue
    emitted.add(f.task_id)
    entries.push(post(files.filter(m=>m.task_id===f.task_id&&m.kind!=='attachment')))
  }
  return entries
}

function single(f){
  return {key:f.id,type:f.kind==='image'?'image':f.kind,primary:f,files:[f],title:f.title,size:f.size,created_at:f.created_at,
    cover:f.cover||(f.kind==='image'?`/api/files/${f.id}/stream`:null),ratio:f.ratio,
    counts:{images:f.kind==='image'?1:0,motion:0,audio:f.kind==='audio'?1:0},label:f.extension.replace('.','').toUpperCase()}
}

function post(members){
  const images=members.filter(m=>m.kind==='image').sort((a,b)=>a.path<b.path?-1:1)
  const primary=members.find(m=>m.is_primary&&m.kind==='image')||images[0]
  const counts={images:images.length,motion:members.filter(m=>m.kind==='video').length,audio:members.filter(m=>m.kind==='audio').length}
  const type=images.length+counts.motion>1||counts.audio?'gallery':'image'
  return {key:'post:'+primary.task_id,type,primary,files:members,title:primary.title||stem(primary.name),
    size:members.reduce((a,m)=>a+m.size,0),created_at:members.reduce((a,m)=>m.created_at>a?m.created_at:a,''),
    cover:primary.cover||`/api/files/${images[0].id}/stream`,ratio:primary.ratio||images[0].ratio,counts,
    label:type==='gallery'?'图集':stem(primary.extension||'').toUpperCase()||'IMG'}
}

export function filterEntries(entries,{type='',query='',sort='new'}={}){
  const words=query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const found=entries.filter(e=>(!type||e.type===type)&&words.every(w=>e.title.toLowerCase().includes(w)||e.files.some(f=>f.name.toLowerCase().includes(w))))
  const order={new:(a,b)=>a.created_at<b.created_at?1:a.created_at>b.created_at?-1:0,old:(a,b)=>a.created_at<b.created_at?-1:a.created_at>b.created_at?1:0,
    big:(a,b)=>b.size-a.size,name:(a,b)=>a.title.localeCompare(b.title,'zh-CN')}[sort]||(()=>0)
  return found.slice().sort(order)
}

export function typeCounts(entries){
  const counts={'':entries.length}
  for(const e of entries)counts[e.type]=(counts[e.type]||0)+1
  return counts
}

/** How many columns fit: cards are at least `min` wide. */
export function columnCount(width,{min=240,gap=20,max=5}={}){
  return Math.max(1,Math.min(max,Math.floor((width+gap)/(min+gap))))
}

export function shapeOf(entry,layout='irregular'){
  const fixed=LAYOUTS.find(l=>l.id===layout)?.shape
  if(fixed)return SHAPES.find(s=>s.id===fixed)
  return snapShape(entry.ratio,entry.type==='video'?'16:9':'1:1')
}

/** Masonry: each entry goes to the currently shortest column, so reading order stays roughly left to right. */
export function distribute(entries,columns,{info=0.55,layout='irregular'}={}){
  const lanes=Array.from({length:columns},()=>({height:0,items:[]}))
  for(const e of entries){
    const lane=lanes.reduce((a,b)=>b.height<a.height-1e-6?b:a)
    lane.items.push(e)
    lane.height+=1/shapeOf(e,layout).ratio+info
  }
  return lanes.map(l=>l.items)
}
