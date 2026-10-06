// Resume only when more than 5 s in and more than 10 s before the end.
export function resumeTime(progress,duration){
  return Number.isFinite(progress)&&Number.isFinite(duration)&&progress>5&&progress<duration-10?progress:0
}

// An explicit work selection takes precedence over resetMode.
export function playbackIndex(items,record,{workId,resetMode=false}={}){
  if(workId)return items.findIndex(item=>item.work_id===workId)
  if(resetMode){
    const index=items.findIndex(item=>{
      const progress=record?.video_progress?.[item.work_id]
      return Number.isFinite(progress)&&progress>5&&(!item.duration||progress<item.duration-10)
    })
    return Math.max(0,index)
  }
  return Math.min(record?.current_index||0,Math.max(0,items.length-1))
}
