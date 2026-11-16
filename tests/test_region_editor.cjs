/* 运行 node tests/test_region_editor.cjs，用模拟页面验证区域编辑、坐标换算和保存校验。 */
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const assert = require('node:assert/strict');
const initial = {session:[.05,.12,.3,.95],message:[.31,.15,.99,.8],title:[.32,.04,.85,.12]};
const ctx = new Proxy({}, {get:()=>()=>{}, set:()=>true});
const nodes = new Map();
for (const id of ['regionEditCanvas','regionEditTarget','regionEditStatus','btnRegionSave','btnRegionLoad','btnRegionReset']) nodes.set(id,{});
const cv=nodes.get('regionEditCanvas'), target=nodes.get('regionEditTarget');
let pointer=null, calls=[], notices=[];
Object.assign(cv,{style:{},getContext:()=>ctx,
  getBoundingClientRect:()=>({left:20,top:10,width:600,height:400}),
  setPointerCapture:id=>pointer=id,hasPointerCapture:id=>pointer===id,
  releasePointerCapture:()=>pointer=null});
target.value='session';
class FakeImage { set src(v) { queueMicrotask(()=>this.onload()); } }
const sandbox = {structuredClone, document:{getElementById:id=>nodes.get(id),createElement:()=>({getContext:()=>ctx})},Image:FakeImage,
  confirm:()=>true,toast:s=>notices.push(s),
  callApi:async(name,args)=>{
    calls.push({name,args:structuredClone(args)});
    return {ok:true,regions:structuredClone(args[0]==='save'?args[1]:initial),
      window_size:[1500,1000],display:[1500,1000],image:'data:image/mock',manual:args[0]==='save',
      visual:args[0]==='save'?structuredClone(args[3]||{}):{},
      defaults:{input:[.4,.75,.95,.95],send_button:[.95,.96]},
      auto_regions:structuredClone(initial),
      schema:[{key:'input',label:'输入框区域',type:'rect'}, {key:'send_button',label:'发送按钮',type:'point'}]};
  }};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../webui/region-editor.js'),'utf8'),sandbox);
sandbox.bootRegionEditor();
const event=(x,y)=>({clientX:20+x*600,clientY:10+y*400,pointerId:1,pointerType:'mouse',button:0,preventDefault(){}});
function drag(x,y,nx,ny,cancel=false) {
  cv.onpointerdown(event(x,y)); cv.onpointermove(event(nx,ny));
  (cancel?cv.onpointercancel:cv.onpointerup)(event(nx,ny));
}
(async()=>{
  await nodes.get('btnRegionLoad').onclick();
  assert.equal(cv.width,1500);
  assert.equal(nodes.get('btnRegionSave').disabled,true);
  // 显示宽度为 600 像素、画布宽度为 1500 像素，拖动仍移动整窗宽度的 0.1。
  drag(.17,.5,.27,.5);
  assert.equal(nodes.get('btnRegionSave').disabled,false);
  await nodes.get('btnRegionSave').onclick();
  let box=calls.at(-1).args[1].session;
  assert.ok(Math.abs(box[0]-.15)<1e-9);
  assert.ok(Math.abs(box[2]-.4)<1e-9);
  assert.deepEqual(calls.at(-1).args[2],[1500,1000]);
  // 右下角控制柄缩放。
  drag(.4,.95,.5,.9);
  await nodes.get('btnRegionSave').onclick();
  box=calls.at(-1).args[1].session;
  assert.ok(Math.abs(box[2]-.5)<1e-9 && Math.abs(box[3]-.9)<1e-9);
  // 取消拖拽恢复原框，不产生未保存状态。
  drag(.25,.5,.35,.5,true);
  assert.equal(nodes.get('btnRegionSave').disabled,true);
  // 扩展输入区域也能缩放并作为独立覆盖项保存。
  target.value='input'; target.onchange();
  drag(.95,.95,.9,.9);
  await nodes.get('btnRegionSave').onclick();
  assert.ok(Math.abs(calls.at(-1).args[3].input[2]-.9)<1e-9);
  // 发送点单击定位，CSS 缩放后仍保存整窗比例，预览不会实际点击微信。
  target.value='send_button'; target.onchange();
  cv.onpointerdown(event(.92,.97));cv.onpointerup(event(.92,.97));
  await nodes.get('btnRegionSave').onclick();
  assert.deepEqual(calls.at(-1).args[3].send_button,[.92,.97]);
  // 消息框移到标题上方时阻止保存，不调用后端。
  target.value='message'; target.onchange();
  drag(.6,.4,.6,.25);
  const count=calls.length;
  await nodes.get('btnRegionSave').onclick();
  assert.equal(calls.length,count);
  assert.ok(notices.at(-1).includes('标题'));
  await nodes.get('btnRegionReset').onclick();
  assert.equal(calls.at(-1).args[0],'reset');
  assert.equal(nodes.get('btnRegionSave').disabled,true);
  console.log('区域编辑器交互测试通过：移动、缩放、取消、CSS 坐标、保存、重叠校验与恢复自动');
})().catch(e=>{console.error(e);process.exitCode=1;});
