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

# 确保能 import adapter（从 starter_kit/ 运行）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adapter  # noqa: E402


# ── HTML 模板 ───────────────────────────────────────────────────────────────

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>LoomQ // 量子科普</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --page:#e7e1d2;--panel:#111213;--ink:#2b2822;--paper:#f4efe4;
  --muted:#8b8676;--muted-dark:#9a988c;
  --blue:#3d6ea5;--tan:#d1a34a;--gray:#9aa0a6;--red:#c8493c;--purple:#7a5aa8;
  --danger:#c8493c;--code-bg:#1b1c1e;
  --mono:ui-monospace,"SF Mono",Consolas,"Courier New",monospace
}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
background:var(--page);color:var(--ink);line-height:1.6;min-height:100vh;display:flex;flex-direction:column}
.container{max-width:760px;margin:0 auto;width:100%;padding:0 1rem;flex:1;display:flex;flex-direction:column}

/* Header */
.header{text-align:center;padding:2rem 0 1rem}
.tag{display:inline-block;font-family:var(--mono);font-size:.62rem;letter-spacing:.1em;
background:var(--tan);color:#2a2210;padding:3px 12px;border-radius:999px;margin-bottom:.7rem;
text-transform:uppercase;font-weight:700}
.header h1{font-size:1.45rem;font-weight:700;letter-spacing:-.01em;color:var(--ink)}
.header h1 span{color:var(--blue)}
.header p{color:var(--muted);font-size:.85rem;margin-top:.35rem}

/* generic instrument panel */
.panel{background:var(--panel);color:var(--paper);border-radius:16px;
padding:1.1rem 1.25rem;box-shadow:0 6px 16px rgba(43,40,34,.12)}

/* Storybook */
.story-hidden{display:none!important}
.storybook{text-align:center;padding:.5rem 0 2rem}
.story-visual{display:flex;align-items:center;justify-content:center;min-height:170px;margin-bottom:.9rem}
.story-panel{max-width:440px;margin:0 auto}
.story-panel .cn{font-size:.95rem;line-height:1.75}
.story-panel .cn b{color:var(--tan)}
.story-nav{display:flex;align-items:center;justify-content:center;gap:1rem;margin-top:1.1rem}
.dots{display:flex;gap:5px}
.dot{width:6px;height:6px;border-radius:50%;background:#c9c2ae}
.dot.active{background:var(--blue);width:16px;border-radius:4px}
.skip-link{display:block;margin:.8rem auto 0;font-size:.75rem;color:var(--muted);
text-decoration:underline;cursor:pointer;background:none;border:none}

/* Welcome (stage 3 cards) */
.welcome{margin-bottom:1.5rem}
.welcome h2{font-size:1rem;font-weight:600;margin-bottom:.75rem;color:var(--ink)}
.cards{display:grid;grid-template-columns:1fr;gap:.75rem}
@media(min-width:540px){.cards{grid-template-columns:repeat(3,1fr)}}
.card{background:var(--panel);color:var(--paper);border-radius:12px;
padding:1rem;cursor:pointer;transition:transform .15s,box-shadow .15s}
.card:hover{transform:translateY(-2px);box-shadow:0 6px 16px rgba(43,40,34,.18)}
.card .icon{width:26px;height:26px;border-radius:7px;margin-bottom:.6rem;
display:flex;align-items:center;justify-content:center;font-size:.9rem;font-weight:700;color:#1a1a1a}
.card:nth-child(1) .icon{background:var(--blue);color:#fff}
.card:nth-child(2) .icon{background:var(--tan)}
.card:nth-child(3) .icon{background:var(--red);color:#fff}
.card h3{font-size:.78rem;font-weight:700;margin-bottom:.3rem;color:var(--paper);
font-family:var(--mono);letter-spacing:.05em}
.card p{font-size:.78rem;color:var(--muted-dark);line-height:1.45}

/* Chat */
.chat-area{flex:1;display:flex;flex-direction:column;min-height:0;margin-bottom:1rem}
.messages{flex:1;overflow-y:auto;padding:.5rem 0;display:flex;flex-direction:column;gap:.75rem}
.msg{max-width:90%;padding:.75rem 1rem;font-size:.9rem;word-break:break-word;border-radius:12px}
.msg.user{align-self:flex-end;background:var(--blue);color:#fff}
.msg.bot{align-self:flex-start;background:var(--panel);color:var(--paper)}
.msg.bot .thinking{color:var(--tan);font-style:normal;font-size:.8rem}

/* Code blocks */
.msg pre{background:var(--code-bg);border-radius:8px;padding:.75rem;margin:.5rem 0;
overflow-x:auto;font-size:.78rem;font-family:var(--mono);line-height:1.5;white-space:pre-wrap;color:#bcd6ee}

/* Chart container */
.chart-box{background:var(--panel);color:var(--paper);border-radius:12px;padding:1rem;margin:.75rem 0}
.chart-box h4{font-size:.7rem;font-weight:600;color:var(--muted-dark);margin-bottom:.5rem;
text-transform:uppercase;letter-spacing:.08em}
.chart-box canvas{width:100%!important;height:200px!important}

/* Concept card */
.concept{background:#ded5bd;border-left:3px solid var(--blue);border-radius:0 8px 8px 0;
padding:.75rem 1rem;margin:.5rem 0;font-size:.82rem;line-height:1.5;color:var(--ink)}
.concept strong{color:var(--blue)}

/* Input */
.input-area{display:flex;gap:.5rem;padding:.75rem 0}
.input-area input{flex:1;padding:.6rem 1rem;background:var(--panel);border:none;border-radius:10px;
color:var(--paper);font-size:.9rem;outline:none;box-shadow:0 0 0 2px transparent;transition:box-shadow .15s}
.input-area input::placeholder{color:var(--muted-dark)}
.input-area input:focus{box-shadow:0 0 0 2px var(--blue)}
.input-area button{padding:.6rem 1.3rem;background:var(--tan);color:#2a2210;border:none;border-radius:10px;
font-size:.85rem;font-weight:700;cursor:pointer;white-space:nowrap;transition:opacity .15s}
.input-area button:hover{opacity:.85}
.input-area button:disabled{opacity:.35;cursor:not-allowed}

/* Status */
.status{text-align:center;padding:.5rem;font-size:.75rem;color:var(--muted)}
.status.error{color:var(--danger)}

/* Story stages (orb onboarding) */
.story{text-align:center;padding:1rem 0 2rem}
.bubble{background:var(--panel);color:var(--paper);border-radius:14px;
padding:.9rem 1.15rem;max-width:520px;margin:0 auto 1.1rem;font-size:.88rem;
line-height:1.7;text-align:left}
.bubble .eq{display:block;margin-top:.6rem;font-family:var(--mono);font-size:.76rem;color:var(--tan)}

.orb-stage{display:flex;justify-content:center;align-items:center;gap:2.5rem;min-height:150px;
margin-bottom:.75rem;position:relative}
.orb{width:92px;height:92px;border-radius:50%;cursor:pointer;transition:transform .15s;position:relative;z-index:2}
.orb:hover{transform:scale(1.06)}
.orb.superpos{background:conic-gradient(from 0deg,#c8493c,#d1a34a,#3d6ea5,#7a5aa8,#c8493c);
box-shadow:0 6px 16px rgba(43,40,34,.25);animation:orbSpin 4s linear infinite}
@keyframes orbSpin{0%{filter:brightness(1)}50%{filter:brightness(1.12)}100%{filter:brightness(1)}}
.orb.collapsed-blue{background:radial-gradient(circle at 34% 30%,#8fb4d9,var(--blue) 60%,#1e3a52 100%);
box-shadow:0 6px 16px rgba(61,110,165,.35);animation:none}
.orb.collapsed-red{background:radial-gradient(circle at 34% 30%,#e6a89f,var(--red) 60%,#5c1c15 100%);
box-shadow:0 6px 16px rgba(200,73,60,.35);animation:none}
.orb.settling{animation:orbSettle .4s ease-out}
@keyframes orbSettle{0%{transform:scale(1.4)}55%{transform:scale(.85)}100%{transform:scale(1)}}

.tether{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:88px;height:2px;z-index:1;
background:linear-gradient(90deg,var(--blue),var(--red));opacity:.3;transition:opacity .3s}
.tether.sync{opacity:1}

.tally{font-size:.75rem;color:var(--muted);min-height:1.1rem;margin-bottom:.85rem}
.story-btn{padding:.55rem 1.4rem;border:none;background:var(--panel);color:var(--paper);
border-radius:999px;font-size:.8rem;cursor:pointer}
.story-btn.primary{background:var(--tan);color:#2a2210;font-weight:700}
.story-btn:hover{opacity:.88}

/* Story icon widgets (bb-quantum-info picture-book beats) */
.ball{width:84px;height:84px;border-radius:50%}
.ball-red{background:var(--red)}
.ball-split{background:linear-gradient(90deg,var(--red) 50%,var(--blue) 50%)}
.ball-row{display:flex;gap:16px}
.ball-row .ball{width:70px;height:70px}
.e-plain{width:88px;height:88px;border-radius:50%;border:3px solid var(--paper);
display:flex;align-items:center;justify-content:center;font-size:1.2rem;font-weight:700;color:var(--paper)}
.e-rainbow{width:88px;height:88px;border-radius:50%;
background:conic-gradient(from 0deg,#c8493c,#d1a34a,#3d6ea5,#7a5aa8,#c8493c);
display:flex;align-items:center;justify-content:center;font-size:1.2rem;font-weight:700;color:#fff;
text-shadow:0 1px 3px rgba(0,0,0,.35)}
.phone{width:62px;height:100px;border:3px solid var(--paper);border-radius:10px;position:relative;
display:flex;align-items:center;justify-content:center;padding:6px}
.phone::after{content:'';position:absolute;bottom:6px;width:8px;height:8px;border-radius:50%;
border:2px solid var(--paper)}
.dotgrid{display:grid;grid-template-columns:repeat(5,1fr);gap:3px;width:100%}
.dotgrid .mini{width:8px;height:8px;border-radius:50%}
.mini.blue{background:var(--blue)}.mini.red{background:var(--red)}
.mini.rainbow{background:conic-gradient(from 0deg,#c8493c,#d1a34a,#3d6ea5,#7a5aa8,#c8493c)}
.scale-col{display:flex;flex-direction:column;gap:.55rem}
.scale-row{display:flex;align-items:center;justify-content:center;gap:8px;font-size:.72rem;color:var(--muted-dark)}
.scale-row .cluster{display:grid;gap:2px}
.scale-row .cluster.n2{grid-template-columns:repeat(2,1fr)}
.scale-row .cluster.n4{grid-template-columns:repeat(2,1fr)}
.scale-row .cluster.n16{grid-template-columns:repeat(4,1fr)}
.scale-row .cluster .mini{width:9px;height:9px}
.scale-row .label{min-width:70px;text-align:left;color:var(--paper);font-weight:600}
.phone-row{display:flex;align-items:flex-end;justify-content:center;gap:1.4rem}
.phone-group{text-align:center}
.phone-cluster{display:flex;flex-wrap:wrap;gap:4px;justify-content:center;max-width:70px;margin-bottom:.4rem}
.phone-cluster .phone{width:26px;height:42px;border-width:2px}
.phone-cluster .phone::after{display:none}
.glabel{font-size:.7rem;color:var(--muted-dark);font-weight:600}
.globe-wrap{position:relative;width:180px;height:180px;margin:0 auto}
.globe{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:76px;height:76px;
border-radius:50%;background:radial-gradient(circle at 35% 30%,#6fa77f,#2f6b8a 65%,#1c4560)}
.globe-phone{position:absolute;top:50%;left:50%;width:13px;height:22px;border:2px solid var(--paper);
border-radius:3px;margin:-11px 0 0 -6.5px}
.bulb{width:56px;height:56px;border-radius:50%;border:3px solid var(--paper);position:relative}
.bulb.on{background:var(--tan);border-color:var(--tan);box-shadow:0 0 22px rgba(209,163,74,.55)}
.bulb::after{content:'';position:absolute;left:50%;bottom:-13px;transform:translateX(-50%);
width:18px;height:9px;border:2px solid var(--paper);border-top:none;border-radius:0 0 4px 4px}
.molecule line{stroke:var(--paper);stroke-width:1.4;opacity:.55}

/* 电路实验室（桥梁2/3：盲盒拼电路 -> 实时 QASM -> 选后端 -> 保真度） */
.lab-row{display:flex;align-items:center;justify-content:center;gap:.4rem;margin-bottom:1rem}
.lab-box{display:flex;flex-direction:column;align-items:center;gap:.4rem;cursor:pointer}
.lab-box .orb{width:64px;height:64px}
.lab-box .orb:not(.superpos){background:#33383e;box-shadow:inset 0 0 0 2px #454b52;animation:none}
.lab-tag{font-family:var(--mono);font-size:.68rem;color:var(--muted)}
.lab-connect{width:34px;height:34px;border-radius:50%;border:2px solid var(--muted-dark);
background:var(--page);color:var(--muted-dark);font-size:1rem;cursor:pointer;flex-shrink:0;
transition:all .15s}
.lab-connect.on{background:var(--tan);border-color:var(--tan);color:#2a2210}
.lab-code-panel{background:var(--code-bg);border-radius:12px;padding:.85rem 1rem;max-width:520px;
margin:0 auto 1rem}
.lab-code-label{font-size:.68rem;color:var(--muted-dark);text-transform:uppercase;letter-spacing:.08em;
margin-bottom:.4rem}
.lab-code-panel pre{font-family:var(--mono);font-size:.8rem;color:#bcd6ee;white-space:pre-wrap;
line-height:1.6}
.lab-actions{display:flex;justify-content:center;gap:.75rem;margin-bottom:1rem}
.lab-backend-picker{max-width:560px;margin:0 auto 1rem}
.lab-backend-title{font-size:.78rem;color:var(--muted);line-height:1.6;margin-bottom:.7rem;text-align:left}
.lab-backend-cards{display:grid;grid-template-columns:1fr;gap:.6rem}
@media(min-width:540px){.lab-backend-cards{grid-template-columns:repeat(3,1fr)}}
.lab-backend-card{background:var(--panel);color:var(--paper);border-radius:12px;padding:.85rem;
text-align:left;cursor:pointer;transition:transform .15s;border:2px solid transparent}
.lab-backend-card:hover{transform:translateY(-2px)}
.lab-backend-card.picked{border-color:var(--tan)}
.lab-backend-card h4{font-size:.8rem;font-weight:700;margin-bottom:.3rem}
.lab-backend-card p{font-size:.72rem;color:var(--muted-dark);line-height:1.5}
.lab-backend-card .tag{display:inline-block;font-family:var(--mono);font-size:.62rem;
background:var(--blue);color:#fff;padding:1px 7px;border-radius:999px;margin-top:.4rem}
.lab-fidelity{max-width:520px;margin:.75rem auto 0;font-size:.85rem;line-height:1.7;text-align:left}
.lab-fidelity .num{font-family:var(--mono);font-weight:700}
.lab-fidelity .num.pass{color:#4a9d6b}
.lab-fidelity .num.fail{color:var(--red)}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <span class="tag">LoomQ · 量子科普</span>
    <h1><span>LoomQ</span> 从一个小球开始</h1>
  </div>

  <!-- 绘本铺垫：改编自 Chris Ferrie《Quantum Information for Babies》的叙事节奏 -->
  <div class="storybook" id="storybook">
    <div class="panel story-panel">
      <div class="story-visual" id="storyVisual"></div>
      <div class="cn" id="storyCn"></div>
    </div>
    <div class="story-nav">
      <button class="story-btn" id="prevBtn" onclick="storyPrev()">‹ 上一页</button>
      <div class="dots" id="storyDots"></div>
      <button class="story-btn primary" id="nextBtn" onclick="storyNext()">下一页 ›</button>
    </div>
    <button class="skip-link" onclick="skipStory()">跳过铺垫，直接开始实验 »</button>
  </div>

  <!-- 第一幕：单个球，叠加与测量 -->
  <div class="story story-hidden" id="storyStage1">
    <div class="bubble">
      <span id="s1Caption">轻触下面这颗球，看看它选了什么颜色。</span>
      <span class="eq" id="s1Eq"></span>
    </div>
    <div class="orb-stage"><div class="orb superpos" id="orb1" onclick="clickOrb1()"></div></div>
    <div class="tally" id="s1Tally"></div>
    <div id="s1Next" class="story-hidden">
      <button class="story-btn primary" onclick="goStage2()">下一步：两颗球的秘密 ›</button>
    </div>
  </div>

  <!-- 第二幕：两个球，纠缠 -->
  <div class="story story-hidden" id="storyStage2">
    <div class="bubble">
      <span id="s2Caption">如果两颗球被"绑"在一起会怎样？触发它们试试。</span>
      <span class="eq" id="s2Eq"></span>
    </div>
    <div class="orb-stage">
      <div class="tether" id="tether"></div>
      <div class="orb superpos" id="orbA" onclick="clickOrbPair()"></div>
      <div class="orb superpos" id="orbB" onclick="clickOrbPair()"></div>
    </div>
    <div class="tally" id="s2Tally"></div>
    <div id="s2Next" class="story-hidden">
      <button class="story-btn primary" onclick="goStage3()">下一步：亲手搭一个电路 ›</button>
    </div>
  </div>

  <!-- 第三幕：电路实验室——点盲盒=H门，接连线=CX门，实时同步 QASM，
       选后端 + 真实计算保真度。装配的正是 GHZ-3（跟官方 L1/L2 测试电路
       同款），呼应后面第四幕 Agent 的 ENTANGLE 建议卡片。 -->
  <div class="story story-hidden" id="circuitLab">
    <div class="bubble">
      <span>现在轮到你亲手搭一个电路了。点一下盲盒＝给它施加"叠加"；点亮两个盒子中间的
      连接钮＝把它们"纠缠"在一起。搭完点"运行"，交给真正的模拟器算出结果——不是预设动画。</span>
    </div>
    <div class="lab-row">
      <div class="lab-box" id="labBox0" onclick="labClickBox(0)">
        <div class="orb" id="labOrb0"></div>
        <div class="lab-tag">q[0]</div>
      </div>
      <button class="lab-connect" id="labConnect01" onclick="labToggleConnect(0)" title="纠缠 q[0]–q[1]">⚭</button>
      <div class="lab-box" id="labBox1" onclick="labClickBox(1)">
        <div class="orb" id="labOrb1"></div>
        <div class="lab-tag">q[1]</div>
      </div>
      <button class="lab-connect" id="labConnect12" onclick="labToggleConnect(1)" title="纠缠 q[1]–q[2]">⚭</button>
      <div class="lab-box" id="labBox2" onclick="labClickBox(2)">
        <div class="orb" id="labOrb2"></div>
        <div class="lab-tag">q[2]</div>
      </div>
    </div>
    <div class="lab-code-panel">
      <div class="lab-code-label">实时生成的 QASM</div>
      <pre id="labQasm">// 点一下盲盒开始搭建…</pre>
    </div>
    <div class="lab-actions">
      <button class="story-btn" onclick="labReset()">重置</button>
      <button class="story-btn primary" onclick="labOpenBackendPicker()">运行 ›</button>
    </div>

    <div class="lab-backend-picker story-hidden" id="labBackendPicker">
      <div class="lab-backend-title">交给哪个后端跑？（文案取自 backend_capabilities.json，
      演示统一用本地精确模拟器执行——真机需要真实排队和账号，不适合现场演示，
      但 adapter.py 的 run()/transpile() 里三个后端都是真实接入的）</div>
      <div class="lab-backend-cards" id="labBackendCards"></div>
    </div>

    <div class="lab-result story-hidden" id="labResult">
      <div class="chart-box"><h4>测量结果分布（有限次抽样，不是理论值）</h4><canvas id="labChart"></canvas></div>
      <div class="lab-fidelity" id="labFidelity"></div>
      <div id="labNext" class="story-hidden">
        <button class="story-btn primary" onclick="goStage4()">下一步：交给 Agent 帮你做 ›</button>
      </div>
    </div>
  </div>

  <!-- 第四幕：自由探索（原有聊天界面） -->
  <div class="welcome story-hidden" id="welcome">
    <h2>刚才是你自己搭的电路，现在把这些体力活交给 Agent 试试？</h2>
    <div class="cards">
      <div class="card" onclick="tryPrompt('帮我生成一个贝尔态电路，我想看两个量子比特纠缠是什么效果')">
        <div class="icon">E</div>
        <h3>ENTANGLE</h3>
        <p>生成贝尔态——量子世界最神奇的现象，两个粒子"心灵感应"</p>
      </div>
      <div class="card" onclick="tryPrompt('这段量子代码有错误，帮我修好并解释：H q[0]; CX q[0] q[1];')">
        <div class="icon">D</div>
        <h3>DEBUG</h3>
        <p>给一段有 bug 的量子代码，AI 自动修复并解释问题在哪</p>
      </div>
      <div class="card" onclick="tryPrompt('我想运行一个 5 比特的量子电路，不想花钱也不想排队，推荐哪个平台？')">
        <div class="icon">R</div>
        <h3>ROUTE</h3>
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

// ── 绘本铺垫：改编自 Chris Ferrie《Quantum Information for Babies》 ─────────
// 只借用其"用小球讲 bit → 用电子讲 qubit → 指数级扩张 → 量子系统模拟量子系统"
// 的叙事节奏，图标是我们自己重新画的，不复制原书画面。
function miniDots(n,cls){let s='';for(let i=0;i<n;i++)s+=`<div class="mini ${cls}"></div>`;return s;}
function ballIcon(cls){return `<div class="ball ${cls}"></div>`}
function ballPair(){return `<div class="ball-row"><div class="ball ball-split"></div><div class="ball ball-split"></div></div>`}
function phoneDots(n,cls){return `<div class="phone"><div class="dotgrid">${miniDots(n,cls)}</div></div>`}
function electronIcon(cls){return `<div class="${cls}">e⁻</div>`}
function cluster(n,cls){return `<div class="cluster n${n}">${miniDots(n,cls)}</div>`}
function scaleRows(){
  return `<div class="scale-col">
    <div class="scale-row">${cluster(2,'blue')}<span>→</span>${cluster(1,'rainbow')}<span class="label">1 个量子位</span></div>
    <div class="scale-row">${cluster(4,'blue')}<span>→</span>${cluster(2,'rainbow')}<span class="label">2 个量子位</span></div>
    <div class="scale-row">${cluster(16,'blue')}<span>→</span>${cluster(4,'rainbow')}<span class="label">4 个量子位</span></div>
  </div>`;
}
function phoneGroup(n,label){
  let s='';for(let i=0;i<n;i++)s+='<div class="phone"></div>';
  return `<div class="phone-group"><div class="phone-cluster">${s}</div><div class="glabel">${label}</div></div>`;
}
function phoneRow3(){return `<div class="phone-row">${phoneGroup(1,'20 个量子位')}${phoneGroup(2,'21 个量子位')}${phoneGroup(4,'22 个量子位')}</div>`}
function moleculeSvg(rainbow){
  const nodes=[[30,88],[54,58],[88,58],[112,88],[88,110],[54,110],[18,52],[146,72],[92,20]];
  const edges=[[0,1],[1,2],[2,3],[3,4],[4,5],[5,0],[1,6],[3,7],[2,8]];
  let s='<svg class="molecule" width="170" height="130" viewBox="0 0 170 130">';
  if(rainbow){
    s+='<defs><radialGradient id="eBallGrad" cx="35%" cy="30%" r="75%">'
      +'<stop offset="0%" stop-color="#f4efe4"/>'
      +'<stop offset="30%" stop-color="#d1a34a"/>'
      +'<stop offset="55%" stop-color="#3d6ea5"/>'
      +'<stop offset="80%" stop-color="#7a5aa8"/>'
      +'<stop offset="100%" stop-color="#c8493c"/></radialGradient></defs>';
  }
  edges.forEach(function(e){s+=`<line x1="${nodes[e[0]][0]}" y1="${nodes[e[0]][1]}" x2="${nodes[e[1]][0]}" y2="${nodes[e[1]][1]}"/>`;});
  // 未量子化：暗淡的实心点（在黑色面板上仍清晰可见，但刻意"平平无奇"）
  // 量子化：每个原子都是一颗彩色的"电子球"（呼应前面 e-rainbow 的视觉语言）
  nodes.forEach(function(p){
    const fill=rainbow?'url(#eBallGrad)':'#f4efe4';
    const op=rainbow?1:.7;
    s+=`<circle cx="${p[0]}" cy="${p[1]}" r="9" fill="${fill}" opacity="${op}"/>`;
  });
  s+='</svg>';
  return s;
}
function globePhones(){
  let s='<div class="globe-wrap"><div class="globe"></div>';
  const n=10,rad=78;
  for(let i=0;i<n;i++){
    const a=(360/n)*i;
    s+=`<div class="globe-phone" style="transform:translate(-50%,-50%) rotate(${a}deg) translate(0,-${rad}px) rotate(${-a}deg)"></div>`;
  }
  s+='</div>';
  return s;
}
function bulbIcon(){return `<div class="bulb on"></div>`}

const SLIDES=[
  {cn:'这是一个球。', visual:function(){return ballIcon('ball-red')}},
  {cn:'这个球可以是<b>红色</b>的，或者<b>蓝色</b>的。', visual:function(){return ballIcon('ball-split')}},
  {cn:'记录一个球的颜色需要 <b>1 bit</b> 信息；记录两个球，需要 <b>2 bit</b>。', visual:function(){return ballPair()}},
  {cn:'电脑和手机能存很多 bit 信息——这部手机能存 <b>100 万 bit</b>。', visual:function(){return phoneDots(20,'blue')}},
  {cn:'但这是一个电子——一个"<b>量子球</b>"。', visual:function(){return electronIcon('e-plain')}},
  {cn:'一个电子能存一个<b>量子位（qubit）</b>。它不是简单的红或蓝，而是像彩虹一样，同时包含所有可能。', visual:function(){return electronIcon('e-rainbow')}},
  {cn:'描述 1 个量子位需要 2 bit；2 个量子位需要 4 bit；4 个量子位，就需要 <b>16 bit</b> 了。', visual:function(){return scaleRows()}},
  {cn:'还记得能存 100 万 bit 的手机吗？它只够装下 <b>20 个量子位</b>的信息。', visual:function(){return phoneDots(20,'rainbow')}},
  {cn:'21 个量子位就要 2 部手机，22 个就要 4 部——每多 1 个量子位，需求就<b>翻一倍</b>。', visual:function(){return phoneRow3()}},
  {cn:'要存下我最喜欢的一个分子的完整量子信息……', visual:function(){return moleculeSvg(false)}},
  {cn:'得用<b>地球上所有的手机</b>才够！<br><br>你有什么办法可以解决这个问题吗？', visual:function(){return globePhones()}},
  {cn:'我们可以用<b>量子系统</b>，来存储量子信息！全世界所有手机才能做到的事，单单<b>一个分子</b>就能做到——这就是量子计算真正的力量。', visual:function(){return moleculeSvg(true)}},
  {cn:'现在，让我们亲手触碰一个量子位，看看"<b>叠加</b>"到底是什么。', visual:function(){return electronIcon('e-rainbow')}, isLast:true}
];
let storyIdx=0;
function renderStory(){
  const s=SLIDES[storyIdx];
  document.getElementById('storyVisual').innerHTML=s.visual();
  document.getElementById('storyCn').innerHTML=s.cn;
  document.getElementById('prevBtn').style.visibility=storyIdx===0?'hidden':'visible';
  document.getElementById('nextBtn').textContent=s.isLast?'开始实验 ›':'下一页 ›';
  document.getElementById('storyDots').innerHTML=SLIDES.map(function(_,i){
    return `<div class="dot${i===storyIdx?' active':''}"></div>`;
  }).join('');
}
function storyPrev(){ if(storyIdx>0){storyIdx--;renderStory();} }
function storyNext(){ if(storyIdx<SLIDES.length-1){storyIdx++;renderStory();} else {skipStory();} }
function skipStory(){
  document.getElementById('storybook').classList.add('story-hidden');
  document.getElementById('storyStage1').classList.remove('story-hidden');
}
renderStory();

// ── 第一、二幕：交互实验（本地精确模拟器驱动，不占用 LLM 调用预算） ──────────
const SUPERPOS_QASM='OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[1];\ncreg c[1];\nh q[0];\nmeasure q[0] -> c[0];';
const BELL_QASM='OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];\nmeasure q[0] -> c[0];\nmeasure q[1] -> c[1];';

let superposDist=null, bellDist=null;
let s1Clicks=0, s1Blue=0, s1Red=0;
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
  const cls=outcome==='0'?'collapsed-blue':'collapsed-red';
  orb.classList.remove('superpos','collapsed-blue','collapsed-red');
  orb.classList.add(cls,'settling');
  setTimeout(()=>orb.classList.remove('settling'),400);

  s1Clicks++; if(outcome==='0') s1Blue++; else s1Red++;
  const pBlue=Math.round(100*s1Blue/s1Clicks), pRed=100-pBlue;
  document.getElementById('s1Tally').textContent=
    `已经触发 ${s1Clicks} 次 — 蓝 ${s1Blue} 次 (${pBlue}%)，红 ${s1Red} 次 (${pRed}%)`;
  const cap=document.getElementById('s1Caption');
  const eq=document.getElementById('s1Eq');
  if(s1Clicks===1){
    cap.textContent=(outcome==='0'?'这一次，它变成了蓝色。':'这一次，它变成了红色。')+
      ' 在你触发它之前，它不是"红"或"蓝"中的一个，而是两者的叠加态——就像刚才绘本里那颗彩虹色的电子。你一测量，它才"坍缩"成一个确定的颜色，这叫"测量"。'+
      ' 物理学家给这两个结果各起了个"official 昵称"：蓝色叫 |0⟩，红色叫 |1⟩——那对尖括号只是"这是一个量子态"的固定写法，不是什么高深符号，你可以直接当成蓝/红的另一个名字来读。';
    eq.textContent='|0⟩ = 蓝    |1⟩ = 红    a|0⟩ + b|1⟩ ,  |a|² = |b|² = 0.5';
  } else if(s1Clicks<4){
    cap.textContent='再触发一次，看这次变成什么颜色。每次结果都可能不一样——这不是 bug，是真随机。';
  } else {
    cap.textContent=`目前蓝 ${pBlue}%、红 ${pRed}%，不一定正好一半一半——次数还不够多。触发的次数越多，比例就会越来越接近 50:50，这是概率统计的规律（"大数定律"），不是巧合。这条日志也不是预设的，是本地精确模拟器实时算出的真实结果。`;
    document.getElementById('s1Next').classList.remove('story-hidden');
  }
}

async function clickOrbPair(){
  if(!bellDist) bellDist=await fetchDist(BELL_QASM,{'00':0.5,'11':0.5});
  const outcome=sampleFromDist(bellDist);
  const cls=outcome==='00'?'collapsed-blue':'collapsed-red';
  const a=document.getElementById('orbA'), b=document.getElementById('orbB');
  const tether=document.getElementById('tether');
  tether.classList.add('sync');
  [a,b].forEach(o=>{o.classList.remove('superpos','collapsed-blue','collapsed-red');o.classList.add(cls,'settling');});
  setTimeout(()=>{a.classList.remove('settling');b.classList.remove('settling');},400);

  s2Clicks++; s2Same++; // 贝尔态理想分布只会出现 00/11，两颗球必然同色
  document.getElementById('s2Tally').textContent=`试了 ${s2Clicks} 次 — 同色 ${s2Same}/${s2Clicks}`;
  const cap=document.getElementById('s2Caption');
  const eq=document.getElementById('s2Eq');
  if(s2Clicks===1){
    cap.textContent='两颗球变成了同一个颜色，不是一红一蓝。它们之间没有任何经典连线，结果却总是相关——这就是"量子纠缠"。用刚才学的昵称写就是：要么两颗都是 |0⟩（记作 |00⟩，两颗都蓝），要么两颗都是 |1⟩（记作 |11⟩，两颗都红），从来不会一红一蓝。注意：这不是"瞬间传信号"，单独看任何一颗球，它的颜色依然完全随机；只有把两边的记录放在一起比对，才会发现这种关联。';
    eq.textContent='|00⟩ = 两颗都蓝    |11⟩ = 两颗都红    (|00⟩ + |11⟩) / √2';
  } else if(s2Clicks<2){
    cap.textContent='再触发一次，看这次两颗球还会不会同色。';
  } else {
    cap.textContent='不管试多少次，两颗球永远同色——只出现过两蓝或两红，从未出现过一红一蓝。这是真实计算出的结果，不是预设动画。';
    document.getElementById('s2Next').classList.remove('story-hidden');
  }
}

function goStage2(){
  document.getElementById('storyStage1').classList.add('story-hidden');
  document.getElementById('storyStage2').classList.remove('story-hidden');
}

function goStage3(){
  document.getElementById('storyStage2').classList.add('story-hidden');
  document.getElementById('circuitLab').classList.remove('story-hidden');
  renderLab();
}

function goStage4(){
  document.getElementById('circuitLab').classList.add('story-hidden');
  document.getElementById('welcome').classList.remove('story-hidden');
  document.getElementById('chatAreaWrap').classList.remove('story-hidden');
  inputEl.focus();
}

// ── 第三幕：电路实验室（桥梁2：盲盒拼电路 -> 实时 QASM；桥梁3：选后端 -> 真实保真度）
// 装配出来的正是官方 L1/L2 测试用的 GHZ-3 电路：h q[0]; cx q[0],q[1]; cx q[1],q[2];
const labState={h:[false,false,false], cx01:false, cx12:false};

// 取自 backend_capabilities.json（L2「智能选后端」判定的唯一基准表），
// 这里只挑 3 条有代表性的做演示卡片，文案跟那份文件保持一致。
const LAB_BACKENDS=[
  {id:'braket_local_simulator', name:'AWS Braket LocalSimulator', tag:'模拟器 · 零排队',
   note:'本地跑，免费，不需要 AWS 账号，最多 25 比特——推荐新手默认选它。'},
  {id:'spinq_cloud_qpu', name:'量旋云真机（超导/核磁）', tag:'真机 · 需排队',
   note:'2–8 比特，需要注册 SpinQ Cloud 账号，排队通常几分钟到几小时。'},
  {id:'originq_wukong', name:'本源悟空超导真机', tag:'真机 · 需排队',
   note:'最多 72 比特，需要本源量子云 API Token，排队通常按小时计。'}
];

function labActivatedSet(){
  // q1 会因为跟 q0 的 cx 而"沾"上叠加；q2 同理沾 q1。用于决定盲盒该不该显示彩虹态。
  const active=[labState.h[0], false, false];
  active[1]=labState.h[1] || (labState.cx01 && active[0]);
  active[2]=labState.h[2] || (labState.cx12 && active[1]);
  return active;
}

function labBuildQasmLines(){
  const lines=[];
  if(labState.h[0]) lines.push('h q[0];');
  if(labState.h[1]) lines.push('h q[1];');
  if(labState.h[2]) lines.push('h q[2];');
  if(labState.cx01) lines.push('cx q[0],q[1];');
  if(labState.cx12) lines.push('cx q[1],q[2];');
  return lines;
}

function renderLab(){
  const active=labActivatedSet();
  for(let i=0;i<3;i++){
    const orb=document.getElementById('labOrb'+i);
    orb.classList.remove('superpos','collapsed-blue','collapsed-red');
    if(active[i]) orb.classList.add('superpos');
  }
  document.getElementById('labConnect01').classList.toggle('on', labState.cx01);
  document.getElementById('labConnect12').classList.toggle('on', labState.cx12);
  const lines=labBuildQasmLines();
  document.getElementById('labQasm').textContent = lines.length
    ? lines.join('\n')
    : '// 点一下盲盒开始搭建…';
  document.getElementById('labBackendPicker').classList.add('story-hidden');
  document.getElementById('labResult').classList.add('story-hidden');
}

function labClickBox(i){
  labState.h[i]=!labState.h[i];
  renderLab();
}
function labToggleConnect(pairStart){
  if(pairStart===0) labState.cx01=!labState.cx01;
  else labState.cx12=!labState.cx12;
  renderLab();
}
function labReset(){
  labState.h=[false,false,false];
  labState.cx01=false; labState.cx12=false;
  renderLab();
}

function labOpenBackendPicker(){
  const lines=labBuildQasmLines();
  if(!lines.length){ alert('先点一下盲盒或连接钮，搭出点什么再运行～'); return; }
  const wrap=document.getElementById('labBackendCards');
  wrap.innerHTML=LAB_BACKENDS.map(function(b){
    return `<div class="lab-backend-card" onclick="labRunOn('${b.id}')">
      <h4>${b.name}</h4><p>${b.note}</p><span class="tag">${b.tag}</span>
    </div>`;
  }).join('');
  document.getElementById('labBackendPicker').classList.remove('story-hidden');
  document.getElementById('labResult').classList.add('story-hidden');
}

function hellingerFidelity(p, q){
  const keys=new Set([...Object.keys(p), ...Object.keys(q)]);
  let sum=0;
  keys.forEach(function(k){
    const a=Math.sqrt(p[k]||0), b=Math.sqrt(q[k]||0);
    sum += (a-b)*(a-b);
  });
  const h = Math.sqrt(sum) / Math.SQRT2;
  return 1 - h;
}

let labChartInstance=null;

async function labRunOn(backendId){
  const picked=LAB_BACKENDS.find(function(b){return b.id===backendId});
  document.querySelectorAll('.lab-backend-card').forEach(function(el,idx){
    el.classList.toggle('picked', LAB_BACKENDS[idx].id===backendId);
  });
  const lines=labBuildQasmLines();
  const measures=[0,1,2].map(function(i){return `measure q[${i}] -> c[${i}];`});
  const qasm='OPENQASM 2.0;\ninclude "qelib1.inc";\nqreg q[3];\ncreg c[3];\n'
    + lines.join('\n') + '\n' + measures.join('\n');

  const resultBox=document.getElementById('labResult');
  const fidelityBox=document.getElementById('labFidelity');
  resultBox.classList.remove('story-hidden');
  fidelityBox.innerHTML='<span style="color:var(--muted)">正在本地精确模拟器上运行…</span>';
  document.getElementById('labNext').classList.add('story-hidden');

  const ideal=await fetchDist(qasm, null);
  if(!ideal){
    fidelityBox.innerHTML='<span style="color:var(--danger)">模拟失败，检查一下是不是搭了个空电路。</span>';
    return;
  }

  // 演示统一走本地精确模拟器执行（真机需要真实账号和排队，不适合现场演示）。
  // 但保真度不是摆设：像官方 L1 评测一样，从理想分布里做有限次抽样，
  // 算出真实的、会因为抽样次数而有涨落的 Hellinger fidelity。
  const SHOTS=8192; // 跟官方 L1 评测同样的 shots 数，抽样噪声才有可比性
  const counts={};
  for(let i=0;i<SHOTS;i++){
    const k=sampleFromDist(ideal);
    counts[k]=(counts[k]||0)+1;
  }
  const sampled={};
  Object.keys(counts).forEach(function(k){ sampled[k]=counts[k]/SHOTS; });
  const fidelity=hellingerFidelity(sampled, ideal);

  const labels=Object.keys(ideal).sort();
  const values=labels.map(function(k){ return +(100*(sampled[k]||0)).toFixed(2); });
  const canvas=document.getElementById('labChart');
  if(labChartInstance) labChartInstance.destroy();
  labChartInstance=new Chart(canvas,{
    type:'bar',
    data:{labels:labels.map(function(l){return '|'+l+'⟩'}),
      datasets:[{label:'抽样占比 (%)',data:values,
        backgroundColor:values.map(function(v){return v>5?'#3d6ea5':'#3a4550'}),
        borderRadius:4,barPercentage:0.7}]},
    options:{responsive:true,maintainAspectRatio:false,
      scales:{y:{beginAtZero:true,max:100,ticks:{callback:function(v){return v+'%'},font:{size:11},color:'#9a988c'},
                 grid:{color:'#2c2d2f'}},
              x:{ticks:{font:{size:12,family:'monospace'},color:'#f4efe4'},grid:{display:false}}},
      plugins:{legend:{display:false}}}
  });

  const pass = fidelity>=0.97;
  fidelityBox.innerHTML =
    `本次在 <b>${picked.name}</b>（演示实际执行在本地精确模拟器上）跑了 <b>${SHOTS}</b> 次采样。`+
    ` Hellinger 保真度：<span class="num ${pass?'pass':'fail'}">${fidelity.toFixed(4)}</span>`+
    ` （官方判定线是 ≥ 0.97，${pass?'这次过线了':'这次没过线——抽样次数越多越接近理论值，这也是真实误差的样子'}）。`+
    ` 分布跟你搭的电路是否符合直觉：${labState.cx01||labState.cx12?'三颗球（或两颗）应该几乎总是同一种结果同时出现——这就是 GHZ 纠缠。':'没有连线的话，每颗球的结果互不影响。'}`;
  document.getElementById('labNext').classList.remove('story-hidden');
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
      t=t.replace(/`([^`]+)`/g,'<code style="background:var(--code-bg);color:#bcd6ee;padding:2px 5px;border-radius:4px;font-family:var(--mono);font-size:.82rem">$1</code>');
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
          backgroundColor:values.map(v=>v>5?'#3d6ea5':'#3a4550'),
          borderRadius:4,barPercentage:0.7}]},
      options:{responsive:true,maintainAspectRatio:false,
        scales:{y:{beginAtZero:true,max:100,ticks:{callback:v=>v+'%',font:{size:11},color:'#9a988c'},
                   grid:{color:'#2c2d2f'}},
                x:{ticks:{font:{size:12,family:'monospace'},color:'#f4efe4'},grid:{display:false}}},
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
      thinkDiv.innerHTML='<span style="color:var(--danger)">出错了：'+escHtml(data.error)+'</span>';
      statusEl.textContent='请检查 LOOMQ_LLM_* 环境变量是否正确设置';statusEl.className='status error';
    } else {
      thinkDiv.innerHTML=renderResponse(data.reply);
    }
  }catch(e){
    thinkDiv.innerHTML='<span style="color:var(--danger)">网络错误：'+escHtml(e.message)+'</span>';
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
