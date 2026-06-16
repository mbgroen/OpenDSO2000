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

  const trigExtra = el("div",{id:"trig-extra"});
  root.append(section("Trigger",[
    selectField("Type",[["Edge","EDGE"],["Pulse","PULSe"],["Slope","SLOPe"],["Video","TV"],
      ["Timeout","TIMeout"],["Window","WINdow"],["Interval","INTerval"],["Runt","UNDerthrow"],
      ["Pattern","PATTern"],["UART","UART"],["CAN","CAN"],["LIN","LIN"],["I2C","IIC"],["SPI","SPI"]],
      state.trig.mode, v=>{state.trig.mode=v; send({cmd:"trigger",mode:v}); renderTrigExtra(v, trigExtra);}),
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
    trigExtra,
  ]));
  renderTrigExtra(state.trig.mode, trigExtra);

  buildExtraSections(root);

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

// ---------- advanced trigger parameters ----------
// Per-type fields. f=field: {l:label, p:SCPI path, k:kind, o:options|range}
const POL = [["Positive","POSItive"],["Negative","NEGAtive"]];
const WHEN = [["=","EQUAl"],["≠","NEQUal"],[">","GREAt"],["<","LESS"]];
const SRC4 = [["CH1","CHANnel1"],["CH2","CHANnel2"]];
const TRIG_PARAMS = {
  PULSe:[{l:"Polarity",p:"PULSe:POLarity",k:"sel",o:POL},{l:"When",p:"PULSe:WHEN",k:"sel",o:WHEN},
    {l:"Width",p:"PULSe:WIDth",k:"time"},{l:"Level (V)",p:"PULSe:LEVel",k:"num"}],
  SLOPe:[{l:"Polarity",p:"SLOPe:POLarity",k:"sel",o:POL},{l:"When",p:"SLOPe:WHEN",k:"sel",o:WHEN},
    {l:"Width",p:"SLOPe:WIDth",k:"time"},{l:"Level A (V)",p:"SLOPe:ALEVel",k:"num"},{l:"Level B (V)",p:"SLOPe:BLEVel",k:"num"}],
  TV:[{l:"Standard",p:"TV:STANdard",k:"sel",o:[["NTSC","NTSC"],["PAL","PAL"]]},
    {l:"Sync",p:"TV:MODE",k:"sel",o:[["All lines","ALINes"],["Line","LINEs"],["Field 1","FIEld1"],["Field 2","FIEld2"],["All fields","AFIelds"]]},
    {l:"Line",p:"TV:LINE",k:"int",o:[1,625]},{l:"Polarity",p:"TV:POLarity",k:"sel",o:POL},{l:"Level (V)",p:"VIDeo:LEVel",k:"num"}],
  TIMeout:[{l:"Polarity",p:"TIMeout:POLarity",k:"sel",o:POL},{l:"Time",p:"TIMeout:WIDth",k:"time"},{l:"Level (V)",p:"TIMeout:LEVel",k:"num"}],
  WINdow:[{l:"Level A (V)",p:"WINDOw:ALEVel",k:"num"},{l:"Level B (V)",p:"WINDOw:BLEVel",k:"num"}],
  INTerval:[{l:"Slope",p:"INTERVAl:SLOp",k:"sel",o:[["Rising","RISIng"],["Falling","FALLing"],["Double","DOUBle"]]},
    {l:"When",p:"INTERVAl:WHEN",k:"sel",o:WHEN},{l:"Time",p:"INTERVAl:TIME",k:"time"},{l:"Level (V)",p:"INTERVAl:ALEVel",k:"num"}],
  UNDerthrow:[{l:"Polarity",p:"UNDER_Am:POLarity",k:"sel",o:POL},{l:"When",p:"UNDER_Am:WHEN",k:"sel",o:WHEN},
    {l:"Time",p:"UNDER_Am:TIME",k:"time"},{l:"Level A (V)",p:"UNDER_Am:ALEVel",k:"num"},{l:"Level B (V)",p:"UNDER_Am:BLEVel",k:"num"}],
  UART:[{l:"Baud",p:"UART:BAUd",k:"sel",o:[["9600","9600"],["19200","19200"],["38400","38400"],["57600","57600"],["115200","115200"],["4800","4800"]]},
    {l:"Condition",p:"UART:CONdition",k:"sel",o:[["Start","START"],["Stop","STOP"],["Data","READ_DATA"],["Parity err","PARITY_ERR"]]},
    {l:"Parity",p:"UART:PARIty",k:"sel",o:[["None","NONE"],["Odd","ODD"],["Even","EVEN"]]},
    {l:"Data bits",p:"UART:WIDTh",k:"sel",o:[["8","8"],["7","7"],["6","6"],["5","5"]]},
    {l:"Data",p:"UART:DATA",k:"int",o:[0,255]},{l:"Level (V)",p:"UART:ALEVel",k:"num"}],
  CAN:[{l:"Baud",p:"CAN:BAUd",k:"sel",o:[["125k","125000"],["250k","250000"],["500k","500000"],["1M","1000000"]]},
    {l:"Idle",p:"CAN:IDLe",k:"sel",o:[["Low","LOW"],["High","HIGH"]]},
    {l:"Condition",p:"CAN:CONdition",k:"sel",o:[["Frame start","FRAM_STARE"],["Error","ERR_ALL"],["ACK error","ACK_ERR"]]},
    {l:"ID",p:"CAN:ID",k:"int",o:[0,28]},{l:"DLC",p:"CAN:DLC",k:"int",o:[0,8]},{l:"Level (V)",p:"CAN:ALEVel",k:"num"}],
  LIN:[{l:"Baud",p:"LIN:BAUd",k:"sel",o:[["9600","9600"],["19200","19200"],["115200","115200"]]},
    {l:"Idle",p:"LIN:IDLe",k:"sel",o:[["Low","LOW"],["High","HIGH"]]},
    {l:"Condition",p:"LIN:CONdition",k:"sel",o:[["Sync","SYNC_FIELD"],["ID","ID_FIELD"],["Data","DATA"]]},
    {l:"ID",p:"LIN:ID",k:"int",o:[0,63]},{l:"Level (V)",p:"LIN:ALEVel",k:"num"}],
  IIC:[{l:"Condition",p:"IIC:CONdition",k:"sel",o:[["Start","START"],["Stop","STOP"],["Restart","RESTART"],["No-ACK","ADDR_NO_ACK"],["Read data","READ_DATA"]]},
    {l:"Address",p:"IIC:ADDer",k:"int",o:[0,1023]},{l:"SCL level (V)",p:"IIC:ALEVel",k:"num"},{l:"SDA level (V)",p:"IIC:BLEVel",k:"num"}],
  SPI:[{l:"Clock edge",p:"SPI:SCK",k:"sel",o:[["Rising","Rising"],["Falling","Falling"]]},
    {l:"Data width",p:"SPI:WIDth",k:"int",o:[4,32]},{l:"Data",p:"SPI:DATA",k:"int",o:[0,2147483647]},
    {l:"SCL level (V)",p:"SPI:ALEVel",k:"num"},{l:"SDA level (V)",p:"SPI:BLEVel",k:"num"}],
  PATTern:[{l:"Pattern (CH1,CH2)",p:"PATTern:PATTern",k:"text",ph:"H,L,X,X"}],
};
function timeField(label, onSeconds){
  let val=el("input",{type:"number",value:1,style:"flex:1",onchange:fire});
  let unit=el("select",{onchange:fire});
  [["ns",1e-9],["µs",1e-6],["ms",1e-3],["s",1]].forEach(([t,f])=>{const o=el("option",{value:f},t);if(f===1e-6)o.selected=true;unit.append(o);});
  function fire(){ onSeconds(parseFloat(val.value)*parseFloat(unit.value)); }
  return el("div",{class:"field"},[el("label",{},label), el("div",{class:"stepper"},[val,unit])]);
}
function renderTrigExtra(type, container){
  container.innerHTML="";
  const fields = TRIG_PARAMS[type]; if(!fields) return;
  fields.forEach(f=>{
    const sendP=v=>send({cmd:"trigger",param:f.p,value:v});
    if(f.k==="sel") container.append(selectField(f.l,f.o,f.o[0][1],sendP));
    else if(f.k==="time") container.append(timeField(f.l,sendP));
    else if(f.k==="num") container.append(numField(f.l,0,v=>sendP(String(v))));
    else if(f.k==="int") container.append(el("div",{class:"field"},[el("label",{},f.l),
      el("input",{type:"number",min:f.o?f.o[0]:0,max:f.o?f.o[1]:0,value:0,onchange:e=>sendP(e.target.value)})]));
    else if(f.k==="text") container.append(el("div",{class:"field"},[el("label",{},f.l),
      el("input",{type:"text",placeholder:f.ph||"",onchange:e=>sendP(e.target.value)})]));
  });
}

// ---------- extra sections: zoom, pass/fail, decode, save/recall ----------
function buildExtraSections(root){
  // Zoom / dual window
  state.zoom = state.zoom || {on:false, tIndex:Math.max(0,state.tIndex-4)};
  const zscale = stepper(()=>eng(spec.time_div_steps[state.zoom.tIndex],"s"),
    ()=>{state.zoom.tIndex=Math.max(0,state.zoom.tIndex-1); send({cmd:"zoom",scale:spec.time_div_steps[state.zoom.tIndex]});},
    ()=>{state.zoom.tIndex=Math.min(state.tIndex,state.zoom.tIndex+1); send({cmd:"zoom",scale:spec.time_div_steps[state.zoom.tIndex]});});
  root.append(section("Zoom (dual window)",[
    el("div",{class:"btnrow"},[toggleBtn("Enable",()=>state.zoom.on,v=>{state.zoom.on=v; send({cmd:"zoom",enabled:v});})]),
    el("div",{class:"field"},[el("label",{},"Window time/div"), zscale]),
    el("div",{class:"field"},[el("label",{},"Window position"),
      el("input",{type:"range",min:-7,max:7,step:0.1,value:0,
        oninput:e=>{state.zoom.pos=parseFloat(e.target.value); send({cmd:"zoom",position:state.zoom.pos*tdiv()});}})]),
  ]));

  // Pass / Fail mask
  state.mask = state.mask || {on:false, source:"CHANnel1", x:0.4, y:0.4, output:false};
  root.append(section("Pass / Fail",[
    el("div",{class:"btnrow"},[toggleBtn("Enable",()=>state.mask.on,v=>{state.mask.on=v; send({cmd:"mask",enabled:v});})]),
    selectField("Source",[["CH1","CHANnel1"],["CH2","CHANnel2"],["Math","MATH"]],state.mask.source,
      v=>{state.mask.source=v; send({cmd:"mask",source:v});}),
    numField("X tolerance (div)",0.4,v=>{state.mask.x=v; send({cmd:"mask",x:v});}),
    numField("Y tolerance (div)",0.4,v=>{state.mask.y=v; send({cmd:"mask",y:v});}),
    el("div",{class:"btnrow"},[
      el("button",{onclick:()=>send({cmd:"mask",create:true})},"Create mask"),
      toggleBtn("Output",()=>state.mask.output,v=>{state.mask.output=v; send({cmd:"mask",output:v});})]),
  ]));

  // Protocol decode (host-side)
  state.dec = state.dec || {protocol:"uart", source:1, sda:1, scl:2, baud:9600,
    canBaud:500000, bits:8, parity:"none", edge:"rising", width:8, invert:false};
  const decOut = el("div",{id:"decode-out",class:"mono",style:"max-height:140px;overflow:auto;margin-top:6px;white-space:pre-wrap"});
  const decFields = el("div",{id:"decode-fields"});
  root.append(section("Protocol decode",[
    selectField("Protocol",[["UART","uart"],["I2C","iic"],["SPI","spi"],["CAN","can"],["LIN","lin"]],
      state.dec.protocol, v=>{state.dec.protocol=v; renderDecodeFields(decFields);}),
    decFields,
    el("div",{class:"btnrow"},[el("button",{class:"primary",onclick:()=>runDecode(decOut)},"Decode")]),
    decOut,
  ]));
  renderDecodeFields(decFields);

  // Save / Recall
  root.append(section("Save / Recall",[
    el("div",{class:"btnrow"},[
      el("button",{onclick:savePNG},"Save PNG"),
      el("button",{onclick:()=>window.open("/api/waveform.csv"+(TOKEN?`?token=${TOKEN}`:""),"_blank")},"Export CSV")]),
    el("div",{class:"btnrow"},[
      el("button",{onclick:saveSetup},"Save setup"),
      el("button",{onclick:loadSetup},"Load setup")]),
  ]));
}

const CHANSEL = [["CH1","1"],["CH2","2"]];
function renderDecodeFields(c){
  c.innerHTML=""; const d=state.dec;
  const baud=[["9600","9600"],["19200","19200"],["38400","38400"],["57600","57600"],["115200","115200"],["4800","4800"]];
  if(d.protocol==="uart"||d.protocol==="lin"){
    c.append(selectField("Source",CHANSEL,String(d.source),v=>d.source=parseInt(v)));
    c.append(selectField("Baud",baud,String(d.baud),v=>d.baud=parseInt(v)));
  }
  if(d.protocol==="uart"){
    c.append(selectField("Data bits",[["8","8"],["7","7"],["6","6"],["5","5"]],String(d.bits),v=>d.bits=parseInt(v)));
    c.append(selectField("Parity",[["None","none"],["Odd","odd"],["Even","even"]],d.parity,v=>d.parity=v));
  }
  if(d.protocol==="can"){
    c.append(selectField("Source",CHANSEL,String(d.source),v=>d.source=parseInt(v)));
    c.append(selectField("Bit rate",[["125k","125000"],["250k","250000"],["500k","500000"],["1M","1000000"]],
      String(d.canBaud),v=>d.canBaud=parseInt(v)));
  }
  if(d.protocol==="iic"){
    c.append(selectField("SDA source",CHANSEL,String(d.sda),v=>d.sda=parseInt(v)));
    c.append(selectField("SCL source",CHANSEL,String(d.scl),v=>d.scl=parseInt(v)));
  }
  if(d.protocol==="spi"){
    c.append(selectField("Clock (SCL)",CHANSEL,String(d.scl),v=>d.scl=parseInt(v)));
    c.append(selectField("Data (SDA)",CHANSEL,String(d.sda),v=>d.sda=parseInt(v)));
    c.append(selectField("Clock edge",[["Rising","rising"],["Falling","falling"]],d.edge,v=>d.edge=v));
    c.append(selectField("Word bits",[["8","8"],["16","16"],["4","4"],["12","12"],["24","24"],["32","32"]],
      String(d.width),v=>d.width=parseInt(v)));
  }
}
async function runDecode(out){
  out.textContent="Decoding…";
  const d=state.dec;
  const body={protocol:d.protocol, token:TOKEN, source:d.source, sda:d.sda, scl:d.scl,
    baud:(d.protocol==="can"?d.canBaud:d.baud), data_bits:d.bits, parity:d.parity,
    edge:d.edge, width:d.width, invert:d.invert};
  try{
    const r=await (await fetch("/api/decode",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(body)})).json();
    if(r.error){ out.textContent="⚠ "+r.error; return; }
    if(!r.frames||!r.frames.length){ out.textContent="No frames decoded (check sources/baud and that a real signal is present)."; return; }
    let head="";
    const chars=r.frames.filter(f=>f.char).map(f=>f.char).join("");
    if(chars) head="ASCII: "+chars+"\n\n";
    out.textContent = head + r.frames.map(f=>
      `${f.t!=null?f.t.toExponential(2)+"s  ":""}${f.text||f.hex||""}${f.ok===false?"  ✗":""}`).join("\n");
  }catch(e){ out.textContent="Decode failed: "+e; }
}
function savePNG(){
  const link=document.createElement("a");
  link.download="opendso2000.png"; link.href=canvas.toDataURL("image/png"); link.click();
}
function saveSetup(){
  const blob=new Blob([JSON.stringify(state,null,2)],{type:"application/json"});
  const link=document.createElement("a"); link.download="opendso2000-setup.json";
  link.href=URL.createObjectURL(blob); link.click();
}
function loadSetup(){
  const inp=el("input",{type:"file",accept:".json",onchange:async e=>{
    const f=e.target.files[0]; if(!f) return;
    try{ const s=JSON.parse(await f.text()); Object.assign(state,s); applyState(); buildControls(); }
    catch(err){ alert("Bad setup file: "+err); }
  }});
  inp.click();
}
function applyState(){
  for(const ch of [1,2]){ const c=state.ch[ch];
    send({cmd:"channel",ch,display:c.display,scale:vdiv(ch),coupling:c.coupling,probe:parseInt(c.probe),bw:c.bw,invert:c.invert}); }
  send({cmd:"timebase",scale:tdiv(),mode:state.tbmode});
  send({cmd:"acquire",type:state.acq,depth:parseInt(state.depth)});
  send({cmd:"trigger",mode:state.trig.mode,sweep:state.trig.sweep,source:state.trig.source,slope:state.trig.slope});
  send({cmd:"math",enabled:state.math.enabled,operator:state.math.operator});
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
function drawZoomBand() {
  if (!state.zoom || !state.zoom.on) return;
  const widthDiv = Math.min(HDIV, HDIV * spec.time_div_steps[state.zoom.tIndex] / tdiv());
  const centerDiv = state.zoom.pos || 0;
  const x0 = x2px(centerDiv - widthDiv/2), x1 = x2px(centerDiv + widthDiv/2);
  ctx.fillStyle = "rgba(58,122,254,0.15)";
  ctx.fillRect(x0, 0, x1-x0, H);
  ctx.strokeStyle = "rgba(58,122,254,0.7)"; ctx.lineWidth=1;
  ctx.strokeRect(x0, 0, x1-x0, H);
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
  drawZoomBand();
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
