"use strict";
// OpenDSO2000 web client: device picker, control panel, WebSocket streaming,
// and a Canvas oscilloscope screen drawn in division coordinates.

const COLORS = {1:"#f2d011", 2:"#13c4f0", math:"#c060f0", trig:"#ff6a00",
  grid:"#2a3340", axis:"#465a6e", screen:"#0a0f14"};
const HDIV = 14, VDIV = 8;
const MATH_SCALE_STEPS = [0.01,0.02,0.05,0.1,0.2,0.5,1,2,5,10];
const TOKEN = new URLSearchParams(location.search).get("token") || "";

let spec = null;            // capabilities from /api/connect
let ws = null;
let frame = null;           // latest decoded frame
const state = {};

// ---------- helpers ----------
function el(tag, props={}, kids=[]) {
  const e = document.createElement(tag);
  for (const k in props) {
    if (k === "class") e.className = props[k];
    else if (k === "html") e.innerHTML = props[k];
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), props[k]);
    else e.setAttribute(k, props[k]);
  }
  (Array.isArray(kids)?kids:[kids]).forEach(c => c!=null && e.append(c.nodeType?c:document.createTextNode(c)));
  return e;
}
function eng(v, unit="") {
  if (v == null || isNaN(v)) return "—";
  if (v === 0) return "0 " + unit;
  const a = Math.abs(v), p = [[1e9,"G"],[1e6,"M"],[1e3,"k"],[1,""],[1e-3,"m"],[1e-6,"µ"],[1e-9,"n"],[1e-12,"p"]];
  for (const [f,s] of p) if (a >= f) {
    let t = (v/f).toPrecision(3);
    if (t.indexOf(".") >= 0) t = t.replace(/\.?0+$/, "");   // trim only fractional zeros
    return t + " " + s + unit;
  }
  return v + " " + unit;
}
function send(obj){ if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }

// ---------- device picker ----------
let pickerSel = null;
async function loadDevices() {
  const list = document.getElementById("device-list");
  const status = document.getElementById("picker-status");
  list.innerHTML = "";
  let devices = [];
  try { devices = (await (await fetch("/api/devices")).json()).devices; } catch(e){}
  const usb = devices.filter(d => d.kind === "usb");
  status.textContent = usb.length ? `${usb.length} USB device(s) found` : "No USB scope found — pick a simulator";
  devices.forEach((d, i) => {
    const li = el("li", {onclick: () => { pickerSel = d;
      [...list.children].forEach(c => c.classList.remove("sel")); li.classList.add("sel"); }},
      (d.kind === "usb" ? "🔌  " : "🖥  ") + d.label);
    if ((usb.length && d === usb[0]) || (!usb.length && d.kind === "sim" && d.model === "DSO2D15")) {
      pickerSel = d; li.classList.add("sel");
    }
    list.append(li);
  });
}
async function connectSelected() {
  if (!pickerSel) return;
  const status = document.getElementById("picker-status");
  status.textContent = "Connecting…";
  const body = Object.assign({token: TOKEN}, pickerSel);
  let res;
  try { res = await (await fetch("/api/connect", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify(body)})).json(); }
  catch(e){ status.textContent = "Connection failed."; return; }
  if (res.error) { status.textContent = "Failed: " + res.error; return; }
  spec = res.info;
  initState();
  buildControls();
  openWS();
  document.getElementById("picker").classList.add("hidden");
  document.getElementById("app").classList.remove("hidden");
  resizeCanvas();
}

// ---------- state ----------
function nearestIndex(arr, v){ let bi=0,bd=1e99; arr.forEach((x,i)=>{const d=Math.abs(x-v); if(d<bd){bd=d;bi=i;}}); return bi; }
function initState() {
  const vs = spec.volt_div_steps, ts = spec.time_div_steps;
  state.ch = {
    1:{display:true, vIndex:nearestIndex(vs,1.0), coupling:"DC", probe:"1", bw:false, invert:false, pos:0},
    2:{display:true, vIndex:nearestIndex(vs,0.5), coupling:"DC", probe:"1", bw:false, invert:false, pos:0},
  };
  state.tIndex = nearestIndex(ts, 100e-6);
  state.tbmode = "MAIN"; state.depth = "4000"; state.acq = "NORMal";
  state.trig = {mode:"EDGE", sweep:"AUTO", source:"CHANnel1", slope:"RISIng", levelDiv:0};
  state.math = {enabled:false, operator:"ADD", source1:1, source2:2, scaleIndex:6, window:"HANNing", unit:"DB"};
  state.cursor = {mode:"OFF", type:"X", source:1, ax:-3, bx:3, ay:1.5, by:-1.5};
  state.measure = false; state.fps = 30; state.run = true;
}
const vdiv = ch => spec.volt_div_steps[state.ch[ch].vIndex];
const tdiv = () => spec.time_div_steps[state.tIndex];
const srcScale = src => vdiv(src.endsWith("2") ? 2 : 1);

// ---------- controls ----------
function stepper(getText, dec, inc) {
  const val = el("span", {class:"val"});
  const refresh = () => val.textContent = getText();
  const w = el("div", {class:"stepper"}, [
    el("button", {onclick:()=>{dec();refresh();}}, "−"), val, el("button", {onclick:()=>{inc();refresh();}}, "+")]);
  refresh(); return w;
}
function selectField(label, options, current, onchange) {
  const sel = el("select", {onchange:e=>onchange(e.target.value)});
  options.forEach(([t,v]) => { const o=el("option",{value:v},t); if(v===current)o.selected=true; sel.append(o); });
  return el("div",{class:"field"},[el("label",{},label), sel]);
}
function toggleBtn(label, get, set) {
  const b = el("button",{class:"toggle"});
  const r=()=>{b.textContent=label; b.classList.toggle("on",get());};
  b.addEventListener("click",()=>{set(!get()); r();}); r(); return b;
}
function section(title, kids){ return el("div",{class:"section"},[el("h3",{},title),...kids]); }

function channelSection(ch) {
  const c = state.ch[ch];
  const scale = stepper(()=>eng(vdiv(ch),"V"),
    ()=>{c.vIndex=Math.max(0,c.vIndex-1); send({cmd:"channel",ch,scale:vdiv(ch)});},
    ()=>{c.vIndex=Math.min(spec.volt_div_steps.length-1,c.vIndex+1); send({cmd:"channel",ch,scale:vdiv(ch)});});
  const pos = el("input",{type:"range",min:-4,max:4,step:0.1,value:0,
    oninput:e=>{c.pos=parseFloat(e.target.value);}});
  const coupling = selectField("Coupling",[["DC","DC"],["AC","AC"],["GND","GND"]],c.coupling,
    v=>{c.coupling=v; send({cmd:"channel",ch,coupling:v});});
  const probe = selectField("Probe",[["1x","1"],["10x","10"],["100x","100"],["1000x","1000"]],c.probe,
    v=>{c.probe=v; send({cmd:"channel",ch,probe:parseInt(v)});});
  const btns = el("div",{class:"btnrow"},[
    toggleBtn("Display",()=>c.display,v=>{c.display=v; send({cmd:"channel",ch,display:v});}),
    toggleBtn("BW",()=>c.bw,v=>{c.bw=v; send({cmd:"channel",ch,bw:v});}),
    toggleBtn("Inv",()=>c.invert,v=>{c.invert=v; send({cmd:"channel",ch,invert:v});}),
  ]);
  return el("div",{},[
    el("div",{class:"chhdr c"+ch},"CH"+ch),
    el("div",{class:"field"},[el("label",{},"Volts / div"), scale]),
    el("div",{class:"field"},[el("label",{},"Position"), pos]),
    coupling, probe, btns]);
}

function buildControls() {
  const root = document.getElementById("sections");
  root.innerHTML = "";

  root.append(section("Vertical",[el("div",{class:"grid2"},[channelSection(1), channelSection(2)])]));

  const tb = stepper(()=>eng(tdiv(),"s"),
    ()=>{state.tIndex=Math.max(0,state.tIndex-1); send({cmd:"timebase",scale:tdiv()});},
    ()=>{state.tIndex=Math.min(spec.time_div_steps.length-1,state.tIndex+1); send({cmd:"timebase",scale:tdiv()});});
  root.append(section("Horizontal",[
    el("div",{class:"field"},[el("label",{},"Time / div"), tb]),
    selectField("Mode",[["Y-T","MAIN"],["X-Y","XY"],["Roll","ROLL"]],state.tbmode,
      v=>{state.tbmode=v; send({cmd:"timebase",mode:v});}),
    selectField("Memory depth", spec.memory_depths.map(d=>[d>=1e6?(d/1e6+" M"):(d/1e3+" K"),String(d)]),
      state.depth, v=>{state.depth=v; send({cmd:"acquire",depth:parseInt(v)});}),
    selectField("Acquisition",[["Normal","NORMal"],["Average","AVERage"],["Peak","PEAK"],["Hi-Res","HRESolution"]],
      state.acq, v=>{state.acq=v; send({cmd:"acquire",type:v});}),
  ]));

  root.append(section("Trigger",[
    selectField("Type",[["Edge","EDGE"],["Pulse","PULSe"],["Slope","SLOPe"],["Video","TV"],
      ["Timeout","TIMeout"],["Window","WINdow"],["Interval","INTerval"],["Runt","UNDerthrow"],
      ["Pattern","PATTern"],["UART","UART"],["CAN","CAN"],["LIN","LIN"],["I2C","IIC"],["SPI","SPI"]],
      state.trig.mode, v=>{state.trig.mode=v; send({cmd:"trigger",mode:v});}),
    selectField("Sweep",[["Auto","AUTO"],["Normal","NORMal"],["Single","SINGle"]],state.trig.sweep,
      v=>{state.trig.sweep=v; send({cmd:"trigger",sweep:v});}),
    selectField("Source",[["CH1","CHANnel1"],["CH2","CHANnel2"],["EXT","EXT/10"]],state.trig.source,
      v=>{state.trig.source=v; send({cmd:"trigger",source:v});}),
    selectField("Slope",[["Rising","RISIng"],["Falling","FALLing"],["Either","EITHer"]],state.trig.slope,
      v=>{state.trig.slope=v; send({cmd:"trigger",slope:v});}),
    el("div",{class:"field"},[el("label",{},"Level"),
      el("input",{type:"range",min:-4,max:4,step:0.05,value:0,
        oninput:e=>{state.trig.levelDiv=parseFloat(e.target.value);
          send({cmd:"trigger",level:state.trig.levelDiv*srcScale(state.trig.source)});}})]),
  ]));

  const mathScale = stepper(()=>eng(MATH_SCALE_STEPS[state.math.scaleIndex],"V"),
    ()=>{state.math.scaleIndex=Math.max(0,state.math.scaleIndex-1); send({cmd:"math",scale:MATH_SCALE_STEPS[state.math.scaleIndex]});},
    ()=>{state.math.scaleIndex=Math.min(MATH_SCALE_STEPS.length-1,state.math.scaleIndex+1); send({cmd:"math",scale:MATH_SCALE_STEPS[state.math.scaleIndex]});});
  root.append(section("Math / FFT",[
    el("div",{class:"btnrow"},[toggleBtn("Display",()=>state.math.enabled,
      v=>{state.math.enabled=v; send({cmd:"math",enabled:v});})]),
    selectField("Operator",[["CH1 + CH2","ADD"],["CH1 − CH2","SUBTract"],["CH1 × CH2","MULTiply"],
      ["CH1 ÷ CH2","DIVision"],["FFT","FFT"]],state.math.operator,
      v=>{state.math.operator=v; send({cmd:"math",operator:v});}),
    selectField("FFT source",[["CH1","1"],["CH2","2"]],String(state.math.source1),
      v=>{state.math.source1=parseInt(v); send({cmd:"math",source1:parseInt(v)});}),
    el("div",{class:"field"},[el("label",{},"Math scale"), mathScale]),
    selectField("FFT window",[["Hanning","HANNing"],["Hamming","HAMMing"],["Blackman","BLACkman"],["Rectangle","RECTangle"]],
      state.math.window, v=>{state.math.window=v; send({cmd:"math",window:v});}),
    selectField("FFT unit",[["dBV","DB"],["Vrms","VRMS"]],state.math.unit,
      v=>{state.math.unit=v; send({cmd:"math",unit:v});}),
  ]));

  root.append(section("Cursor",[
    selectField("Mode",[["Off","OFF"],["Manual","MANual"],["Track","TRACk"]],state.cursor.mode,
      v=>{state.cursor.mode=v;}),
    selectField("Type",[["X (time)","X"],["Y (volts)","Y"],["X & Y","XY"]],state.cursor.type,
      v=>{state.cursor.type=v;}),
    selectField("Source",[["CH1","1"],["CH2","2"]],String(state.cursor.source),
      v=>{state.cursor.source=parseInt(v);}),
  ]));

  if (spec.has_awg) {
    root.append(section("Wave Gen",[
      el("div",{class:"btnrow"},[toggleBtn("Output",()=>state.awgOn,v=>{state.awgOn=v; send({cmd:"awg",on:v});})]),
      selectField("Waveform",[["Sine","SINE"],["Square","SQUAre"],["Ramp","RAMP"],["Exp","EXP"],["Noise","NOISe"],["DC","DC"]],
        "SINE", v=>send({cmd:"awg",type:v})),
      numField("Frequency (Hz)",1000,v=>send({cmd:"awg",freq:v})),
      numField("Amplitude (Vpp)",1,v=>send({cmd:"awg",amp:v})),
      numField("Offset (V)",0,v=>send({cmd:"awg",offset:v})),
      numField("Duty (%)",50,v=>send({cmd:"awg",duty:v})),
    ]));
  }

  root.append(section("Display",[
    el("div",{class:"btnrow"},[toggleBtn("Measure table",()=>state.measure,v=>{
      state.measure=v; send({cmd:"measure",enabled:v});
      document.getElementById("meas-table").classList.toggle("hidden",!v);})]),
    selectField("Max FPS",[["5","5"],["10","10"],["15","15"],["20","20"],["30","30"],["60","60"]],
      String(state.fps), v=>{state.fps=parseInt(v); send({cmd:"fps",value:parseInt(v)});}),
  ]));

  // toolbar
  const run = document.getElementById("run-btn");
  run.onclick = () => { state.run=!state.run; run.textContent=state.run?"Run":"Stop";
    run.classList.toggle("stopped",!state.run); send({cmd:"run",on:state.run}); };
  document.getElementById("single-btn").onclick = ()=>{ send({cmd:"single"});
    state.run=false; run.textContent="Stop"; run.classList.add("stopped"); };
  document.getElementById("auto-btn").onclick = ()=>send({cmd:"autoset"});
  document.getElementById("force-btn").onclick = ()=>send({cmd:"force"});
  document.getElementById("device-btn").onclick = async ()=>{
    await fetch("/api/disconnect",{method:"POST"}); if(ws) ws.close();
    document.getElementById("app").classList.add("hidden");
    document.getElementById("picker").classList.remove("hidden"); loadDevices(); };
}
function numField(label, val, onchange){
  return el("div",{class:"field"},[el("label",{},label),
    el("input",{type:"number",value:val,onchange:e=>onchange(parseFloat(e.target.value))})]);
}

// ---------- websocket ----------
function openWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws${TOKEN?`?token=${TOKEN}`:""}`);
  ws.binaryType = "arraybuffer";
  ws.onmessage = ev => {
    if (typeof ev.data === "string") return onJSON(JSON.parse(ev.data));
    parseFrame(ev.data);
  };
  ws.onclose = () => setTimeout(()=>{ if(!document.getElementById("app").classList.contains("hidden")) openWS(); }, 1000);
}
function onJSON(m) {
  if (m.type === "status") {
    const c = document.getElementById("trig-chip");
    const ok = m.trig === "Triggered"; c.textContent = ok?"TD":"AUTO"; c.classList.toggle("ok", true);
    document.getElementById("srate-chip").textContent = eng(m.srate,"Sa/s");
  } else if (m.type === "meas") {
    renderMeas(m.data);
  }
}
function parseFrame(buf) {
  const dv = new DataView(buf);
  const hlen = dv.getUint32(0, true);
  const header = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, hlen)));
  let off = 4 + hlen;
  const channels = [];
  for (const c of header.channels) {
    channels.push({ch:c.ch, scale:c.scale, data:new Float32Array(buf.slice(off, off+c.n*4))});
    off += c.n*4;
  }
  let math = null;
  if (header.math) { math = new Float32Array(buf.slice(off, off+header.math.n*4)); off += header.math.n*4; }
  frame = {channels, math, srate:header.srate};
}

// ---------- measurements ----------
function renderMeas(data) {
  const t = document.getElementById("meas-table");
  if (!spec.measurements) return;
  let html = "<table><tr><th>Measure</th><th style='color:"+COLORS[1]+"'>CH1</th><th style='color:"+COLORS[2]+"'>CH2</th></tr>";
  for (const m of spec.measurements) {
    html += `<tr><td class='name'>${m.label}</td>`;
    for (const ch of [1,2]) {
      const v = data[ch] ? data[ch][m.item] : null;
      html += `<td style='text-align:right;color:${COLORS[ch]}'>${v==null?"—":eng(v,m.unit)}</td>`;
    }
    html += "</tr>";
  }
  t.innerHTML = html + "</table>";
}

// ---------- canvas ----------
const canvas = document.getElementById("scope");
const ctx = canvas.getContext("2d");
let W=0, H=0, dpr=1;
function resizeCanvas() {
  const host = canvas.parentElement;
  dpr = window.devicePixelRatio || 1;
  W = host.clientWidth; H = host.clientHeight;
  canvas.width = W*dpr; canvas.height = H*dpr;
  ctx.setTransform(dpr,0,0,dpr,0,0);
}
window.addEventListener("resize", resizeCanvas);

function x2px(xdiv){ return (xdiv+HDIV/2)/HDIV*W; }
function div2pxY(d){ return H/2 - d*(H/VDIV); }

function drawGrid() {
  ctx.fillStyle = COLORS.screen; ctx.fillRect(0,0,W,H);
  ctx.lineWidth = 1; ctx.strokeStyle = COLORS.grid;
  ctx.beginPath();
  for (let i=0;i<=HDIV;i++){ const x=i/HDIV*W; ctx.moveTo(x,0); ctx.lineTo(x,H); }
  for (let i=0;i<=VDIV;i++){ const y=i/VDIV*H; ctx.moveTo(0,y); ctx.lineTo(W,y); }
  ctx.stroke();
  ctx.strokeStyle = COLORS.axis; ctx.beginPath();
  ctx.moveTo(W/2,0); ctx.lineTo(W/2,H); ctx.moveTo(0,H/2); ctx.lineTo(W,H/2); ctx.stroke();
}
function drawTrace(data, color, scale, posDiv) {
  if (!data || !data.length) return;
  ctx.strokeStyle = color; ctx.lineWidth = 1.3; ctx.beginPath();
  const n = data.length;
  for (let i=0;i<n;i++){
    const xd = -HDIV/2 + i/(n-1)*HDIV;
    const yd = (color===COLORS.math ? data[i] : data[i]/scale + posDiv);
    const y = div2pxY(Math.max(-VDIV/2, Math.min(VDIV/2, yd)));
    const x = x2px(xd);
    if (i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
  }
  ctx.stroke();
}
function drawTrigger() {
  const d = state.trig.levelDiv;
  ctx.strokeStyle = COLORS.trig; ctx.lineWidth=1; ctx.setLineDash([6,4]);
  const y=div2pxY(d); ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(W,y); ctx.stroke(); ctx.setLineDash([]);
}
function drawCursors() {
  const c = state.cursor; if (c.mode==="OFF") return;
  ctx.strokeStyle="#d8dee9"; ctx.lineWidth=1; ctx.setLineDash([4,4]);
  const xOn = c.type==="X"||c.type==="XY"||c.mode==="TRACk";
  const yOn = c.type==="Y"||c.type==="XY";
  ctx.beginPath();
  if (xOn){ [c.ax,c.bx].forEach(d=>{const x=x2px(d); ctx.moveTo(x,0); ctx.lineTo(x,H);}); }
  if (yOn){ [c.ay,c.by].forEach(d=>{const y=div2pxY(d); ctx.moveTo(0,y); ctx.lineTo(W,y);}); }
  ctx.stroke(); ctx.setLineDash([]);
  // readout
  const parts=[]; const t=tdiv(); const vs=vdiv(c.source);
  if (xOn){ const dt=Math.abs(c.bx-c.ax)*t; parts.push("ΔX="+eng(dt,"s")); if(dt>0) parts.push("1/ΔX="+eng(1/dt,"Hz")); }
  if (yOn){ parts.push("ΔY="+eng(Math.abs(c.ay-c.by)*vs,"V")); }
  document.getElementById("cursor-readout").textContent = parts.join("  ");
}
function render() {
  requestAnimationFrame(render);   // keep the loop alive regardless of below
  if (W !== canvas.parentElement.clientWidth || H !== canvas.parentElement.clientHeight) resizeCanvas();
  drawGrid();
  if (!spec) return;               // nothing else to draw until connected
  if (frame) {
    for (const c of frame.channels) {
      if (state.ch[c.ch] && !state.ch[c.ch].display) continue;
      drawTrace(c.data, COLORS[c.ch], c.scale, state.ch[c.ch]?state.ch[c.ch].pos:0);
    }
    if (frame.math) drawTrace(frame.math, COLORS.math, 1, 0);
  }
  drawTrigger();
  drawCursors();
  // chrome
  document.getElementById("tb-chip").textContent = "H " + eng(tdiv(),"s");
  document.getElementById("depth-chip").textContent = eng(parseInt(state.depth),"pts");
  for (const ch of [1,2]) {
    const c=state.ch[ch];
    document.getElementById("ch"+ch+"-info").textContent =
      c.display ? `CH${ch} ${c.coupling} ${eng(vdiv(ch),"V")}` : `CH${ch} off`;
  }
  document.getElementById("math-info").textContent =
    state.math.enabled ? ("Math " + (state.math.operator==="FFT"?"FFT":state.math.operator)) : "Math off";
}

// cursor dragging
let drag = null;
canvas.addEventListener("pointerdown", e=>{
  const r=canvas.getBoundingClientRect(); const px=e.clientX-r.left, py=e.clientY-r.top;
  const c=state.cursor; if (c.mode==="OFF") return;
  const near=(a,b)=>Math.abs(a-b)<10;
  const xOn=c.type==="X"||c.type==="XY"||c.mode==="TRACk", yOn=c.type==="Y"||c.type==="XY";
  if (xOn && near(px,x2px(c.ax))) drag="ax";
  else if (xOn && near(px,x2px(c.bx))) drag="bx";
  else if (yOn && near(py,div2pxY(c.ay))) drag="ay";
  else if (yOn && near(py,div2pxY(c.by))) drag="by";
  if (drag) canvas.setPointerCapture(e.pointerId);
});
canvas.addEventListener("pointermove", e=>{
  if (!drag) return; const r=canvas.getBoundingClientRect();
  if (drag[0]==="a"||drag[0]==="b") {
    if (drag[1]==="x") state.cursor[drag] = (e.clientX-r.left)/W*HDIV - HDIV/2;
    else state.cursor[drag] = -((e.clientY-r.top)/H*VDIV - VDIV/2);
  }
});
canvas.addEventListener("pointerup", ()=>drag=null);

// ---------- boot ----------
document.getElementById("refresh-btn").onclick = loadDevices;
document.getElementById("connect-btn").onclick = connectSelected;
document.getElementById("device-list").addEventListener("dblclick", connectSelected);
loadDevices();
requestAnimationFrame(render);
