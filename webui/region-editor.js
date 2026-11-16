/* 编辑区域、点位、颜色和视觉参数；区域与点位以整窗归一化坐标保存。 */
"use strict";
function bootRegionEditor() {
  const el = id => document.getElementById(id);
  const cv=el("regionEditCanvas"),target=el("regionEditTarget"),status=el("regionEditStatus");
  const save=el("btnRegionSave"),load=el("btnRegionLoad"),reset=el("btnRegionReset"),itemReset=el("btnRegionItemReset");
  const fields=el("regionEditFields"),settings=el("regionEditSettings");
  const primary=["session","message","title"];
  const baseNames={session:"会话区",message:"消息区",title:"标题区"};
  const colors={session:"#22c55e",message:"#38bdf8",title:"#f59e0b",input:"#a78bfa",unread:"#f87171",voice_pill:"#2dd4bf",recall_menu:"#f472b6",recall_confirm:"#fb923c"};
  let image=null,boxes=null,size=null,schema=[],visual={},effective={},manual=false;
  let busy=false,dirty=false,drag=null,pick=null,raw=null,primaryDirty=false,autoBoxes=null;
  const spec=k=>schema.find(s=>s.key===k);
  const val=k=>{
    if(Object.hasOwn(visual,k))return visual[k];
    if(k==="unread"&&boxes)return boxes.session;
    if(k==="selected_sample"&&boxes&&size)return [Math.min(1,boxes.session[0]+(visual.selected_sample_x??effective.selected_sample_x??5)/size[0]),.5];
    if(k==="input_focus"&&visual.input){const b=visual.input;return [(b[0]+b[2])/2,(b[1]+b[3])/2];}
    return effective[k];
  };
  const kind=k=>primary.includes(k)?"rect":spec(k)?.type;
  const label=k=>baseNames[k]||spec(k)?.label||k;
  const geo=k=>primary.includes(k)?boxes[k]:val(k);
  const clamp=(v,a,b)=>Math.min(b,Math.max(a,v));
  const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function controls() {
    save.disabled=busy||!boxes||!dirty||!!drag;
    load.disabled=reset.disabled=target.disabled=busy||!!drag;
    if(itemReset){itemReset.disabled=busy||!boxes||!!drag;itemReset.textContent=primary.includes(target.value)?"三区域恢复自动":"所选项恢复自动";}
    settings?.querySelectorAll("input,select,button").forEach(n=>n.disabled=busy||!!drag);
    fields?.querySelectorAll("input").forEach(n=>n.disabled=busy||!!drag);
  }
  function setGeo(k,b) {
    if(primary.includes(k)){ boxes[k]=b; primaryDirty=true; }
    else visual[k]=b;
    dirty=true;
  }
  function handles(b) {
    const [l,t,r,btm]=b,x=(l+r)/2,y=(t+btm)/2;
    return [[l,t,"nw"],[x,t,"n"],[r,t,"ne"],[r,y,"e"],[r,btm,"se"],[x,btm,"s"],[l,btm,"sw"],[l,y,"w"]];
  }
  function renderFields() {
    if(!fields||!boxes)return;
    const k=target.value,b=geo(k),names=kind(k)==="point"?["X","Y"]:["左","上","右","下"];
    fields.innerHTML=names.map((n,i)=>`<label>${n}（原图像素）<input type="number" min="0" max="${size[i%2]}" step="1" data-index="${i}" value="${Math.round(b[i]*size[i%2])}"></label>`).join("");
    const info=document.createElement("p");info.className="hint";
    info.textContent=primary.includes(k)?"截图与 OCR 共用区域。消息区上界须在标题下界之后。":spec(k).hint+" 调用："+spec(k).source;
    fields.appendChild(info);
    fields.querySelectorAll("input").forEach(input=>input.onchange=()=>{
      const next=geo(k).slice(),i=Number(input.dataset.index),n=Number(input.value);
      if(!Number.isFinite(n))return;
      next[i]=clamp(n/size[i%2],0,1);
      if(kind(k)==="rect"&&(next[2]-next[0]<8/size[0]||next[3]-next[1]<8/size[1])){
        toast("区域宽高至少 8 像素");renderFields();return;
      }
      setGeo(k,next);draw();
    });
  }
  function draw() {
    if(!image||!boxes)return;
    const ctx=cv.getContext("2d");ctx.clearRect(0,0,cv.width,cv.height);ctx.drawImage(image,0,0,cv.width,cv.height);
    const keys=primary.concat(schema.filter(s=>s.type==="rect"||s.type==="point").map(s=>s.key));
    const order=keys.filter(k=>k!==target.value).concat(target.value);
    for(const k of order) {
      const b=geo(k);if(!b)continue;
      const selected=k===target.value;
      // 非选中扩展区域仅显示已覆盖项，避免默认整窗框遮挡截图。
      if(!selected&&!primary.includes(k)&&!Object.hasOwn(visual,k))continue;
      const c=colors[k]||"#e879f9";ctx.strokeStyle=c;ctx.fillStyle=c;ctx.lineWidth=selected?3:1;
      if(kind(k)==="point") {
        const x=b[0]*cv.width,y=b[1]*cv.height;
        ctx.beginPath();ctx.moveTo(x-12,y);ctx.lineTo(x+12,y);ctx.moveTo(x,y-12);ctx.lineTo(x,y+12);ctx.stroke();
        ctx.beginPath();ctx.arc(x,y,6,0,Math.PI*2);ctx.stroke();
        ctx.font="14px sans-serif";ctx.fillText(label(k),x+10,Math.max(16,y-8));
      } else {
        const [l,t,r,btm]=b;ctx.strokeRect(l*cv.width,t*cv.height,(r-l)*cv.width,(btm-t)*cv.height);
        ctx.globalAlpha=selected?.1:.025;ctx.fillRect(l*cv.width,t*cv.height,(r-l)*cv.width,(btm-t)*cv.height);ctx.globalAlpha=1;
        ctx.font="14px sans-serif";ctx.fillText(label(k),l*cv.width+8,Math.max(16,t*cv.height+18));
        if(selected)for(const [x,y] of handles(b)) {
          ctx.fillStyle="#fff";ctx.fillRect(x*cv.width-5,y*cv.height-5,10,10);ctx.strokeRect(x*cv.width-5,y*cv.height-5,10,10);
        }
      }
    }
    const k=target.value,b=geo(k).map((v,i)=>Math.round(v*size[i%2]));
    status.textContent=pick?`取色中：请点击截图中的「${label(pick)}」像素（不会点击真实微信）`:
      `${dirty?"有未保存修改":manual||Object.keys(visual).length?"已加载保存配置":"自动识别 / 默认值"} · ${label(k)} [${b.join(", ")}]${b.length===4?` · ${b[2]-b[0]}×${b[3]-b[1]} 像素`:""}`;
    renderFields();controls();
  }
  function setColor(k,rgb) {
    visual[k]=rgb;
    if(k!=="badge_color")visual[k+"_manual"]=true;
    dirty=true;
  }
  function buildSettings() {
    if(!settings)return;
    const openGroups=new Set(Array.from(settings.querySelectorAll("details[open] summary")).map(n=>n.textContent));
    const groups=[...new Set(schema.filter(s=>!["rect","point"].includes(s.type)).map(s=>s.group))];
    settings.innerHTML=groups.map(group=>`<details class="region-setting-group"><summary>${escape(group)}</summary><div class="region-setting-grid">${schema.filter(s=>s.group===group&&!["rect","point"].includes(s.type)).map(s=>{
      const v=val(s.key);let input;
      if(s.type==="bool")input=`<input type="checkbox" ${v?"checked":""}>`;
      else if(s.type==="select")input=`<select>${Object.entries(s.choices).map(([k,n])=>`<option value="${escape(k)}" ${k===v?"selected":""}>${escape(n)}</option>`).join("")}</select>`;
      else if(s.type==="color")input=`<input type="color" value="#${v.map(c=>c.toString(16).padStart(2,"0")).join("")}"><button type="button" data-pick="${s.key}">从截图取色</button><span class="hint">RGB ${v.join(",")}</span>`;
      else input=`<input type="number" min="${s.min}" max="${s.max}" step="any" value="${v}">`;
      return `<div class="region-setting" data-setting="${s.key}"><label>${escape(s.label)} ${input}</label><small>${escape(s.hint||"")}<br>调用：${escape(s.source)}</small><button type="button" data-default="${s.key}">恢复此项默认</button></div>`;
    }).join("")}</div></details>`).join("");
    settings.querySelectorAll("[data-setting]").forEach(row=>{
      const k=row.dataset.setting,s=spec(k),input=row.querySelector("input,select");
      input.onchange=()=>{
        let v=s.type==="bool"?input.checked:s.type==="number"?Number(input.value):s.type==="color"?[1,3,5].map(i=>parseInt(input.value.slice(i,i+2),16)):input.value;
        if(s.type==="number"&&(!Number.isFinite(v)||v<s.min||v>s.max)){toast("参数超出允许范围");input.value=val(k);return;}
        if(s.type==="color"){setColor(k,v);buildSettings();}else{visual[k]=v;dirty=true;}draw();
      };
    });
    settings.querySelectorAll("[data-pick]").forEach(btn=>btn.onclick=()=>{pick=pick===btn.dataset.pick?null:btn.dataset.pick;draw();cv.scrollIntoView?.({block:"center",behavior:"smooth"});});
    settings.querySelectorAll("[data-default]").forEach(btn=>btn.onclick=()=>{delete visual[btn.dataset.default];dirty=true;buildSettings();draw();});
    settings.querySelectorAll("details").forEach(n=>n.open=openGroups.has(n.querySelector("summary").textContent));
    controls();
  }
  function point(e) {const r=cv.getBoundingClientRect();return [clamp((e.clientX-r.left)/r.width,0,1),clamp((e.clientY-r.top)/r.height,0,1)];}
  function hit(p) {
    if(!boxes)return "";
    if(kind(target.value)==="point")return "point";
    const r=cv.getBoundingClientRect(),b=geo(target.value);
    for(const [x,y,h] of handles(b))if(Math.abs(p[0]-x)*r.width<=10&&Math.abs(p[1]-y)*r.height<=10)return h;
    if(p[0]>=b[0]&&p[0]<=b[2]){if(Math.abs(p[1]-b[1])*r.height<=8)return "n";if(Math.abs(p[1]-b[3])*r.height<=8)return "s";}
    if(p[1]>=b[1]&&p[1]<=b[3]){if(Math.abs(p[0]-b[0])*r.width<=8)return "w";if(Math.abs(p[0]-b[2])*r.width<=8)return "e";}
    return p[0]>=b[0]&&p[0]<=b[2]&&p[1]>=b[1]&&p[1]<=b[3]?"move":"";
  }
  cv.onpointerdown=e=>{
    if(busy||!boxes||(e.pointerType==="mouse"&&e.button!==0))return;
    const p=point(e);
    if(pick){
      const rgb=Array.from(raw.getContext("2d").getImageData(Math.min(size[0]-1,Math.floor(p[0]*size[0])),Math.min(size[1]-1,Math.floor(p[1]*size[1])),1,1).data).slice(0,3);
      setColor(pick,rgb);pick=null;buildSettings();draw();return;
    }
    const mode=hit(p);if(!mode)return;e.preventDefault();
    const k=target.value;drag={id:e.pointerId,p,mode,box:geo(k).slice(),wasDirty:dirty,wasPrimary:primaryDirty,had:Object.hasOwn(visual,k)};
    cv.setPointerCapture(e.pointerId);
    if(mode==="point")setGeo(k,p);draw();
  };
  cv.onpointermove=e=>{
    if(!boxes||busy)return;const p=point(e);
    if(!drag){const cursors={n:"ns-resize",s:"ns-resize",w:"ew-resize",e:"ew-resize",nw:"nwse-resize",se:"nwse-resize",ne:"nesw-resize",sw:"nesw-resize",move:"move",point:"crosshair"};cv.style.cursor=pick?"crosshair":cursors[hit(p)]||"default";return;}
    if(drag.id!==e.pointerId)return;
    const b=drag.box.slice(),dx=p[0]-drag.p[0],dy=p[1]-drag.p[1];
    if(drag.mode==="point") {setGeo(target.value,p);draw();return;}
    if(drag.mode==="move") {const x=clamp(dx,-b[0],1-b[2]),y=clamp(dy,-b[1],1-b[3]);b[0]+=x;b[2]+=x;b[1]+=y;b[3]+=y;}
    else {const mw=8/size[0],mh=8/size[1];if(drag.mode.includes("w"))b[0]=clamp(b[0]+dx,0,b[2]-mw);if(drag.mode.includes("e"))b[2]=clamp(b[2]+dx,b[0]+mw,1);if(drag.mode.includes("n"))b[1]=clamp(b[1]+dy,0,b[3]-mh);if(drag.mode.includes("s"))b[3]=clamp(b[3]+dy,b[1]+mh,1);}
    setGeo(target.value,b);draw();
  };
  function finish(e,cancel){if(!drag||drag.id!==e.pointerId)return;
    if(cancel){if(primary.includes(target.value))boxes[target.value]=drag.box;else if(drag.had)visual[target.value]=drag.box;else delete visual[target.value];dirty=drag.wasDirty;primaryDirty=drag.wasPrimary;}
    drag=null;if(cv.hasPointerCapture(e.pointerId))cv.releasePointerCapture(e.pointerId);draw();}
  cv.onpointerup=e=>finish(e,false);cv.onpointercancel=e=>finish(e,true);cv.onlostpointercapture=e=>finish(e,true);
  target.onchange=()=>{pick=null;draw();};
  async function request(action,keep=false){
    if(busy||drag)return;
    if(action!=="save"&&dirty&&!keep&&!confirm("当前修改尚未保存，确认放弃？"))return;
    if(action==="reset"&&!confirm("确认清除所有手动区域、点位、颜色及视觉参数，恢复默认？"))return;
    if(action==="save"&&boxes.message[1]<boxes.title[3]){toast("消息区上边界应低于标题区下边界，请先调整避免重叠");return;}
    busy=true;controls();status.textContent="正在加载…";
    try{
      const args=[action,action==="save"?boxes:null,size];
      if(action==="save")args.push(visual,manual||primaryDirty);
      const r=await callApi("debug_regions",args);if(!r||!r.ok)throw new Error(r?.error||"请求失败");
      const next=new Image();await new Promise((resolve,reject)=>{next.onload=resolve;next.onerror=()=>reject(new Error("预览图加载失败"));next.src=r.image;});
      image=next;boxes=r.regions;autoBoxes=r.auto_regions;size=r.window_size;manual=r.manual;visual=r.visual||{};schema=r.schema||[];effective=r.defaults||r.effective||{};
      cv.width=r.display[0];cv.height=r.display[1];dirty=false;primaryDirty=false;pick=null;
      raw=document.createElement("canvas");raw.width=size[0];raw.height=size[1];raw.getContext("2d").drawImage(next,0,0,size[0],size[1]);
      const old=target.value;
      target.innerHTML=primary.map(k=>`<option value="${k}">${label(k)}</option>`).concat(schema.filter(s=>["rect","point"].includes(s.type)).map(s=>`<option value="${s.key}">${escape(s.label)}</option>`)).join("");
      target.value=primary.includes(old)||schema.some(s=>s.key===old)?old:"session";
      buildSettings();draw();toast(action==="save"?"全部标定已保存，后续识别与发送立即使用新设置":action==="reset"?"已恢复全部默认":"截图已加载，可调整区域、点击位置或取色");
    }catch(e){status.textContent="失败："+e.message;toast(status.textContent);}finally{busy=false;controls();}
  }
  load.onclick=()=>request("preview");save.onclick=()=>request("save");reset.onclick=()=>request("reset");
  if(itemReset)itemReset.onclick=async()=>{
    const k=target.value;
    if(primary.includes(k)){
      if(autoBoxes){boxes=structuredClone(autoBoxes);manual=false;primaryDirty=false;dirty=true;draw();toast("三区域已恢复自动计算值，保存后生效");}
      return;
    }
    delete visual[k];dirty=true;draw();
  };
}
