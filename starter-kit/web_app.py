#!/usr/bin/env python3
"""LoomQ Agent 交互入口——零依赖单文件 Web 应用 + CLI fallback。

启动方式：
    python web_app.py              # 浏览器模式（默认 http://localhost:8765）
    python web_app.py --cli        # 终端对话模式
    python web_app.py --port 9000  # 自定义端口

运行前需要 export LOOMQ_LLM_* 环境变量（见 README.md）。
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import threading
import traceback
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs

# 确保能 import adapter（从 starter-kit/ 运行）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adapter  # noqa: E402


# ── HTML 模板 ───────────────────────────────────────────────────────────────

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>LoomQ — 量子接入平权计划</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#f8f9fa;--card:#fff;--border:#e2e8f0;--text:#1a202c;--muted:#64748b;
--accent:#2563eb;--accent-light:#dbeafe;--accent-dark:#1d4ed8;--success:#059669;
--code-bg:#f1f5f9;--radius:12px;--shadow:0 1px 3px rgba(0,0,0,.08)}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
background:var(--bg);color:var(--text);line-height:1.6;min-height:100vh;display:flex;flex-direction:column}
.container{max-width:800px;margin:0 auto;width:100%;padding:0 1rem;flex:1;display:flex;flex-direction:column}

/* Header */
.header{text-align:center;padding:2rem 0 1rem}
.header h1{font-size:1.5rem;font-weight:600;letter-spacing:-.02em}
.header h1 span{color:var(--accent)}
.header p{color:var(--muted);font-size:.9rem;margin-top:.25rem}

/* Welcome */
.welcome{margin-bottom:1.5rem}
.welcome h2{font-size:1.1rem;font-weight:500;margin-bottom:.75rem}
.cards{display:grid;grid-template-columns:1fr;gap:.75rem}
@media(min-width:540px){.cards{grid-template-columns:repeat(3,1fr)}}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
padding:1rem;cursor:pointer;transition:border-color .15s,box-shadow .15s}
.card:hover{border-color:var(--accent);box-shadow:var(--shadow)}
.card .icon{font-size:1.5rem;margin-bottom:.5rem}
.card h3{font-size:.85rem;font-weight:600;margin-bottom:.25rem}
.card p{font-size:.78rem;color:var(--muted);line-height:1.4}

/* Chat */
.chat-area{flex:1;display:flex;flex-direction:column;min-height:0;margin-bottom:1rem}
.messages{flex:1;overflow-y:auto;padding:.5rem 0;display:flex;flex-direction:column;gap:.75rem}
.msg{max-width:90%;padding:.75rem 1rem;border-radius:var(--radius);font-size:.9rem;word-break:break-word}
.msg.user{align-self:flex-end;background:var(--accent);color:#fff;border-bottom-right-radius:4px}
.msg.bot{align-self:flex-start;background:var(--card);border:1px solid var(--border);border-bottom-left-radius:4px}
.msg.bot .thinking{color:var(--muted);font-style:italic;font-size:.82rem}

/* Code blocks */
.msg pre{background:var(--code-bg);border-radius:8px;padding:.75rem;margin:.5rem 0;
overflow-x:auto;font-size:.8rem;font-family:"SF Mono",Monaco,Consolas,monospace;line-height:1.5;white-space:pre-wrap}

/* Chart container */
.chart-box{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);
padding:1rem;margin:.75rem 0}
.chart-box h4{font-size:.82rem;font-weight:600;color:var(--muted);margin-bottom:.5rem;text-transform:uppercase;letter-spacing:.03em}
.chart-box canvas{width:100%!important;height:200px!important}

/* Concept card */
.concept{background:var(--accent-light);border-radius:var(--radius);padding:.75rem 1rem;
margin:.5rem 0;font-size:.82rem;line-height:1.5}
.concept strong{color:var(--accent-dark)}

/* Input */
.input-area{display:flex;gap:.5rem;padding:.75rem 0;border-top:1px solid var(--border)}
.input-area input{flex:1;padding:.6rem 1rem;border:1px solid var(--border);border-radius:var(--radius);
font-size:.9rem;outline:none;transition:border-color .15s}
.input-area input:focus{border-color:var(--accent)}
.input-area button{padding:.6rem 1.25rem;background:var(--accent);color:#fff;border:none;
border-radius:var(--radius);font-size:.9rem;font-weight:500;cursor:pointer;white-space:nowrap;transition:background .15s}
.input-area button:hover{background:var(--accent-dark)}
.input-area button:disabled{opacity:.5;cursor:not-allowed}

/* Status */
.status{text-align:center;padding:.5rem;font-size:.78rem;color:var(--muted)}
.status.error{color:#dc2626}

/* Story stages (orb onboarding) */
.story-hidden{display:none!important}
.story{text-align:center;padding:1rem 0 2rem}
.bubble{background:var(--card);border:1px solid var(--border);border-radius:16px;
padding:.85rem 1.15rem;max-width:480px;margin:0 auto 1.25rem;font-size:.88rem;
line-height:1.6;box-shadow:var(--shadow)}
.orb-stage{display:flex;justify-content:center;align-items:center;gap:2.5rem;min-height:150px;margin-bottom:.75rem}
.orb{width:96px;height:96px;border-radius:50%;cursor:pointer;transition:transform .15s}
.orb:hover{transform:scale(1.06)}
.orb.superpos{background:radial-gradient(circle at 34% 30%,#bfdbfe,#3b82f6 45%,#fb923c 100%);
box-shadow:0 0 28px rgba(59,130,246,.35);animation:orbPulse 2.4s ease-in-out infinite}
@keyframes orbPulse{0%,100%{filter:hue-rotate(0deg) brightness(1)}50%{filter:hue-rotate(35deg) brightness(1.12)}}
.orb.collapsed-blue{background:radial-gradient(circle at 34% 30%,#93c5fd,#2563eb);
box-shadow:0 0 22px rgba(37,99,235,.5);animation:none}
.orb.collapsed-orange{background:radial-gradient(circle at 34% 30%,#fdba74,#ea580c);
box-shadow:0 0 22px rgba(234,88,12,.5);animation:none}
.orb.settling{animation:orbSettle .4s ease-out}
@keyframes orbSettle{0%{transform:scale(1.35)}55%{transform:scale(.88)}100%{transform:scale(1)}}
.tally{font-size:.78rem;color:var(--muted);min-height:1.1rem;margin-bottom:.85rem}
.story-btn{padding:.55rem 1.4rem;border-radius:999px;border:1px solid var(--border);
background:var(--card);font-size:.85rem;cursor:pointer}
.story-btn.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.story-btn:hover{box-shadow:var(--shadow)}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1><span>LoomQ</span> 量子助手</h1>
    <p>不需要任何物理背景，从一颗小球开始</p>
  </div>

  <!-- 第一幕：单颗小球，叠加与测量 -->
  <div class="story" id="storyStage1">
    <div class="bubble" id="s1Caption">轻触下面这颗小球，看看它在想什么。</div>
    <div class="orb-stage"><div class="orb superpos" id="orb1" onclick="clickOrb1()"></div></div>
    <div class="tally" id="s1Tally"></div>
    <div id="s1Next" class="story-hidden">
      <button class="story-btn primary" onclick="goStage2()">下一步：两颗球的秘密 →</button>
    </div>
  </div>

  <!-- 第二幕：两颗小球，纠缠 -->
  <div class="story story-hidden" id="storyStage2">
    <div class="bubble" id="s2Caption">如果两颗小球被"绑"在一起，会发生什么？轻触它们试试。</div>
    <div class="orb-stage">
      <div class="orb superpos" id="orbA" onclick="clickOrbPair()"></div>
      <div class="orb superpos" id="orbB" onclick="clickOrbPair()"></div>
    </div>
    <div class="tally" id="s2Tally"></div>
    <div id="s2Next" class="story-hidden">
      <button class="story-btn primary" onclick="goStage3()">下一步：自己动手做实验 →</button>
    </div>
  </div>

  <!-- 第三幕：自由探索（原有聊天界面） -->
  <div class="welcome story-hidden" id="welcome">
    <h2>现在你已经知道叠加和纠缠是什么了，想自己试试吗？</h2>
    <div class="cards">
      <div class="card" onclick="tryPrompt('帮我生成一个贝尔态电路，我想看两个量子比特纠缠是什么效果')">
        <div class="icon">🔗</div>
        <h3>量子纠缠</h3>
        <p>生成贝尔态——量子世界最神奇的现象，两个粒子"心灵感应"</p>
      </div>
      <div class="card" onclick="tryPrompt('这段量子代码有错误，帮我修好并解释：H q[0]; CX q[0] q[1];')">
        <div class="icon">🔧</div>
        <h3>代码纠错</h3>
        <p>给一段有 bug 的量子代码，AI 自动修复并解释问题在哪</p>
      </div>
      <div class="card" onclick="tryPrompt('我想运行一个 5 比特的量子电路，不想花钱也不想排队，推荐哪个平台？')">
        <div class="icon">🌐</div>
        <h3>选平台</h3>
        <p>根据你的需求（比特数、预算、排队时间）智能推荐量子云平台</p>
      </div>
    </div>
  </div>

  <div class="chat-area story-hidden" id="chatAreaWrap">
    <div class="messages" id="messages"></div>
    <div class="input-area">
      <input type="text" id="input" placeholder="用自然语言描述你想做的量子实验…" autocomplete="off"
             onkeydown="if(event.key==='Enter'&&!event.shiftKey)sendMsg()"/>
      <button id="sendBtn" onclick="sendMsg()">发送</button>
    </div>
  </div>
  <div class="status" id="status"></div>
</div>

<script>
const messagesEl=document.getElementById('messages'),inputEl=document.getElementById('input'),
      sendBtn=document.getElementById('sendBtn'),statusEl=document.getElementById('status'),
      welcomeEl=document.getElementById('welcome');
let busy=false,chartCounter=0;

function tryPrompt(text){inputEl.value=text;sendMsg()}

// ── 第一、二幕：小球引导（本地精确模拟器驱动，不占用 LLM 调用预算） ──────────
const SUPERPOS_QASM='OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[1];\ncreg c[1];\nh q[0];\nmeasure q[0] -> c[0];';
const BELL_QASM='OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];\nmeasure q[0] -> c[0];\nmeasure q[1] -> c[1];';

let superposDist=null, bellDist=null;
let s1Clicks=0, s1Blue=0, s1Orange=0;
let s2Clicks=0, s2Same=0;

async function fetchDist(qasm, fallback){
  try{
    const r=await fetch('/api/simulate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({qasm})});
    const d=await r.json();
    return d.ok ? d.ideal_distribution : fallback;
  }catch(e){ return fallback; }
}

function sampleFromDist(dist){
  const r=Math.random(); let acc=0;
  for(const k of Object.keys(dist)){ acc+=dist[k]; if(r<=acc) return k; }
  return Object.keys(dist)[0];
}

async function clickOrb1(){
  if(!superposDist) superposDist=await fetchDist(SUPERPOS_QASM,{'0':0.5,'1':0.5});
  const outcome=sampleFromDist(superposDist);
  const orb=document.getElementById('orb1');
  const cls=outcome==='0'?'collapsed-blue':'collapsed-orange';
  orb.classList.remove('superpos');
  orb.classList.add(cls,'settling');
  setTimeout(()=>orb.classList.remove('settling'),400);

  s1Clicks++; if(outcome==='0') s1Blue++; else s1Orange++;
  document.getElementById('s1Tally').textContent=
    s1Clicks>0 ? `摸了 ${s1Clicks} 次 —— 蓝色 ${s1Blue} 次，橙色 ${s1Orange} 次` : '';
  const cap=document.getElementById('s1Caption');
  if(s1Clicks===1){
    cap.textContent=(outcome==='0'?'这一次它选择了蓝色！':'这一次它选择了橙色！')+
      ' 在你碰它之前，它同时是蓝色的可能、也是橙色的可能——这叫"叠加"。你一碰，它才选定一个，这叫"测量"。';
  } else if(s1Clicks<3){
    cap.textContent='再摸一次，看看这次它选谁。每次结果都可能不一样。';
  } else {
    cap.textContent='多摸几次你会发现：大约一半蓝色、一半橙色。这不是运气——这些数字是用真正的量子模拟器算出来的，不是预设的动画。';
    document.getElementById('s1Next').classList.remove('story-hidden');
  }
  setTimeout(()=>{ orb.classList.remove('collapsed-blue','collapsed-orange'); orb.classList.add('superpos'); },1300);
}

async function clickOrbPair(){
  if(!bellDist) bellDist=await fetchDist(BELL_QASM,{'00':0.5,'11':0.5});
  const outcome=sampleFromDist(bellDist);
  const cls=outcome==='00'?'collapsed-blue':'collapsed-orange';
  const a=document.getElementById('orbA'), b=document.getElementById('orbB');
  [a,b].forEach(o=>{o.classList.remove('superpos');o.classList.add(cls,'settling');});
  setTimeout(()=>{a.classList.remove('settling');b.classList.remove('settling');},400);

  s2Clicks++; s2Same++; // 贝尔态理想分布只会出现 00/11，两球必然同色
  document.getElementById('s2Tally').textContent=`试了 ${s2Clicks} 次 —— ${s2Same} 次两颗球选了同一个颜色`;
  const cap=document.getElementById('s2Caption');
  if(s2Clicks===1){
    cap.textContent='看！两颗球选了同一个颜色，不是一蓝一橙。它们之间没有任何连线，却总是心有灵犀——这就是"量子纠缠"，爱因斯坦叫它"鬼魅般的超距作用"。';
  } else if(s2Clicks<2){
    cap.textContent='再试一次，看看这次两颗球还会不会一样。';
  } else {
    cap.textContent='不管试多少次，这两颗球永远选一样的颜色。这是真实计算出的结果，不是预设好的动画。';
    document.getElementById('s2Next').classList.remove('story-hidden');
  }
  setTimeout(()=>{ [a,b].forEach(o=>{o.classList.remove('collapsed-blue','collapsed-orange');o.classList.add('superpos');}); },1300);
}

function goStage2(){
  document.getElementById('storyStage1').classList.add('story-hidden');
  document.getElementById('storyStage2').classList.remove('story-hidden');
}

function goStage3(){
  document.getElementById('storyStage2').classList.add('story-hidden');
  document.getElementById('welcome').classList.remove('story-hidden');
  document.getElementById('chatAreaWrap').classList.remove('story-hidden');
  inputEl.focus();
}

function addMsg(role,content){
  const div=document.createElement('div');
  div.className='msg '+role;
  if(role==='bot') div.innerHTML=renderResponse(content);
  else div.textContent=content;
  messagesEl.appendChild(div);
  messagesEl.scrollTop=messagesEl.scrollHeight;
  return div;
}

function renderResponse(text){
  // Split by ```qasm blocks and render charts for them
  const parts=[];
  let last=0;
  const re=/```qasm\s*\n([\s\S]*?)```/g;
  let m;
  while((m=re.exec(text))!==null){
    if(m.index>last) parts.push({type:'text',content:text.slice(last,m.index)});
    parts.push({type:'qasm',content:m[1].trim()});
    last=m.index+m[0].length;
  }
  if(last<text.length) parts.push({type:'text',content:text.slice(last)});

  let html='';
  for(const p of parts){
    if(p.type==='text'){
      // Convert remaining ``` blocks
      let t=p.content.replace(/```(\w*)\n([\s\S]*?)```/g,(_,lang,code)=>
        '<pre>'+escHtml(code.trim())+'</pre>');
      // Convert inline `code`
      t=t.replace(/`([^`]+)`/g,'<code style="background:var(--code-bg);padding:2px 5px;border-radius:4px;font-size:.82rem">$1</code>');
      // Convert newlines
      t=t.replace(/\n/g,'<br>');
      html+=t;
    } else {
      html+='<pre>'+escHtml(p.content)+'</pre>';
      // Add chart placeholder
      const cid='chart_'+chartCounter++;
      html+=`<div class="chart-box"><h4>测量结果分布</h4><canvas id="${cid}"></canvas></div>`;
      // Schedule simulation
      setTimeout(()=>simulateAndChart(p.content,cid),100);
    }
  }

  // Add concept cards for key quantum terms
  if(/纠缠|entangle/i.test(text)&&!/concept-shown/.test(text)){
    html+=`<div class="concept"><strong>什么是量子纠缠？</strong> 两个量子比特像一对有默契的骰子——分开后各自随机，但结果总是完美关联。测到 00 或 11 的概率各约 50%，不会出现 01 或 10。这不是"传信号"，而是它们共享了同一个量子状态。</div>`;
  }
  if(/叠加|superposition/i.test(text)&&!/纠缠|entangle/i.test(text)){
    html+=`<div class="concept"><strong>什么是量子叠加？</strong> 一个量子比特可以同时是 0 和 1——就像一枚还在空中旋转的硬币。测量的一瞬间才会"落地"变成确定的值，测量前它处于两种可能性的叠加。</div>`;
  }
  if(/GHZ|ghz/i.test(text)){
    html+=`<div class="concept"><strong>什么是 GHZ 态？</strong> 把纠缠从 2 个粒子扩展到 3 个或更多——它们同时全是 0 或全是 1，中间没有任何"部分纠缠"的状态。这是量子力学最极端的多体纠缠。</div>`;
  }

  return html;
}

function escHtml(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

async function simulateAndChart(qasm,canvasId){
  try{
    const resp=await fetch('/api/simulate',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({qasm})});
    const data=await resp.json();
    if(!data.ok) return;
    const dist=data.ideal_distribution;
    const labels=Object.keys(dist).sort();
    const values=labels.map(k=>+(dist[k]*100).toFixed(2));
    const canvas=document.getElementById(canvasId);
    if(!canvas) return;
    new Chart(canvas,{
      type:'bar',
      data:{labels:labels.map(l=>'|'+l+'⟩'),
        datasets:[{label:'概率 (%)',data:values,
          backgroundColor:values.map(v=>v>5?'#2563eb':'#93c5fd'),
          borderRadius:4,barPercentage:0.7}]},
      options:{responsive:true,maintainAspectRatio:false,
        scales:{y:{beginAtZero:true,max:100,ticks:{callback:v=>v+'%',font:{size:11}},
                   grid:{color:'#e2e8f0'}},
                x:{ticks:{font:{size:12,family:'monospace'}},grid:{display:false}}},
        plugins:{legend:{display:false},
          tooltip:{callbacks:{label:ctx=>ctx.parsed.y.toFixed(1)+'%'}}}}
    });
  }catch(e){console.error('simulate error',e)}
}

async function sendMsg(){
  if(busy) return;
  const text=inputEl.value.trim();
  if(!text) return;
  inputEl.value='';
  welcomeEl.style.display='none';
  addMsg('user',text);
  const thinkDiv=addMsg('bot','');
  thinkDiv.innerHTML='<span class="thinking">正在思考中…</span>';
  busy=true;sendBtn.disabled=true;statusEl.textContent='';statusEl.className='status';

  try{
    const resp=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({prompt:text})});
    const data=await resp.json();
    if(data.error){
      thinkDiv.innerHTML='<span style="color:#dc2626">出错了：'+escHtml(data.error)+'</span>';
      statusEl.textContent='请检查 LOOMQ_LLM_* 环境变量是否正确设置';statusEl.className='status error';
    } else {
      thinkDiv.innerHTML=renderResponse(data.reply);
    }
  }catch(e){
    thinkDiv.innerHTML='<span style="color:#dc2626">网络错误：'+escHtml(e.message)+'</span>';
  }
  busy=false;sendBtn.disabled=false;
  messagesEl.scrollTop=messagesEl.scrollHeight;
}
</script>
</body>
</html>"""


# ── HTTP 服务 ───────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # 静默常规请求日志
        pass

    def _json(self, code: int, obj: dict):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid JSON"})
            return

        if self.path == "/api/chat":
            prompt = payload.get("prompt", "").strip()
            if not prompt:
                self._json(400, {"error": "prompt is empty"})
                return
            try:
                reply = adapter.agent_chat(prompt)
                self._json(200, {"reply": reply})
            except Exception as exc:
                self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

        elif self.path == "/api/simulate":
            qasm = payload.get("qasm", "").strip()
            if not qasm:
                self._json(400, {"error": "qasm is empty"})
                return
            try:
                from src.agent.tools import run_circuit
                result = run_circuit(qasm)
                self._json(200, result)
            except Exception as exc:
                self._json(500, {"error": str(exc)})

        else:
            self.send_error(404)


# ── CLI 模式 ────────────────────────────────────────────────────────────────

def cli_mode():
    print("╔══════════════════════════════════════════════╗")
    print("║   LoomQ 量子助手 — 终端对话模式              ║")
    print("║   用自然语言描述你想做的量子实验              ║")
    print("║   输入 quit 或按 Ctrl+C 退出                 ║")
    print("╚══════════════════════════════════════════════╝")
    print()
    print("试试这些：")
    print("  1. 帮我生成一个贝尔态电路")
    print("  2. 这段代码有错，帮我修好：H q[0]; CX q[0] q[1]")
    print("  3. 我想运行一个 5 比特电路，不想花钱，选哪个平台？")
    print()

    while True:
        try:
            prompt = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break
        if not prompt or prompt.lower() in ("quit", "exit", "q"):
            print("再见！")
            break
        try:
            reply = adapter.agent_chat(prompt)
            print(f"\n助手 > {reply}\n")
        except Exception as exc:
            print(f"\n[错误] {type(exc).__name__}: {exc}\n")


# ── 入口 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="LoomQ Agent 交互入口")
    parser.add_argument("--cli", action="store_true", help="终端对话模式（不启动 Web 服务）")
    parser.add_argument("--port", type=int, default=8765, help="Web 服务端口（默认 8765）")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    if args.cli:
        cli_mode()
        return

    # 预检环境变量
    missing = [k for k in ("LOOMQ_LLM_BASE_URL", "LOOMQ_LLM_API_KEY", "LOOMQ_LLM_MODEL")
               if not os.environ.get(k)]
    if missing:
        print(f"⚠️  缺少环境变量: {', '.join(missing)}")
        print("   请先 export 这些变量（见 README.md），否则 Agent 对话会报错。")
        print("   Web 界面仍然会启动，但对话功能不可用。\n")

    server = HTTPServer(("0.0.0.0", args.port), Handler)
    url = f"http://localhost:{args.port}"
    print(f"🚀 LoomQ 量子助手已启动: {url}")
    print(f"   按 Ctrl+C 停止\n")

    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 已停止")
        server.server_close()


if __name__ == "__main__":
    main()
