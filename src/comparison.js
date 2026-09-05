import {TwistyPlayer} from 'cubing/twisty';
import './comparison.css';
let meta,players=[];
const settle=async()=>{for(let i=0;i<3;i++)await new Promise(requestAnimationFrame);};
window.comparison={
 async init(data){
  meta=data;
  document.querySelector('#grid').innerHTML=data.runs.map((r,i)=>`<section class="cube" id="panel${i}" style="--accent:${r.color}"><div class="label"><h2>${r.label}</h2><small>${r.effort}</small></div><div class="mount"></div><div class="status"></div></section>`).join('')+`<section class="chart"><h2>Usage vs. solve length</h2><p>Verified completions · lower is better</p><svg viewBox="0 0 480 290" id="chart"></svg><div class="legend">${data.runs.map(r=>`<span style="color:${r.color}">● ${r.label.replace('GPT-','')}</span>`).join('')}</div><div class="note">Usage = cube-tool calls<br>5.5: no full solve · Cost unavailable</div></section>`;
  for(let i=0;i<3;i++){
   const p=new TwistyPlayer({puzzle:'3x3x3',experimentalSetupAlg:data.scramble,alg:'',background:'none',hintFacelets:'floating',controlPanel:'none',experimentalDragInput:'none',experimentalMovePressInput:'none'});
   p.experimentalSetFlashLevel('none');document.querySelector(`#panel${i} .mount`).append(p);players.push(p);
  }
  await new Promise(r=>setTimeout(r,1200));await settle();
 },
 async render({index,fraction,phase}){
  for(let i=0;i<3;i++){
   const r=meta.runs[i],step=r.steps[Math.min(index,r.steps.length-1)],p=players[i];
   const done=index>=r.steps.length,solved=step?.solved && (fraction===1||done);
   const setup=step?.setup||meta.scramble,move=step?.move||'';
   if(p._setup!==setup||p._move!==move){p.experimentalSetupAlg=setup;p.alg=move;p._setup=setup;p._move=move;await settle();}
   if(fraction===1||done)p.jumpToEnd({flash:false});else p.timestamp=fraction*(move.includes('2')?1500:1000);
   const panel=document.querySelector(`#panel${i}`);panel.classList.toggle('solved',!!solved);
   panel.querySelector('.status').innerHTML=r.pending?'Run finishing…': index<0?'Ready to solve':solved?`<strong>${done||phase==='final'?'Last solve':'Solved'} · ${step.count} moves</strong>`:done?`No full solve · ${step?.count||0} moves`:'Solving…';
  }
  const maxCalls=Math.max(10,...meta.runs.flatMap(r=>r.solves.map(s=>s.calls)));
  const maxMoves=Math.max(22,...meta.runs.flatMap(r=>r.solves.map(s=>s.moves)))+1;
  const minMoves=Math.max(0,Math.min(18,...meta.runs.flatMap(r=>r.solves.map(s=>s.moves)))-1);
  const x=v=>65+v/maxCalls*380,y=v=>215-(v-minMoves)/(maxMoves-minMoves)*165;
  let svg='';
  for(let v=minMoves;v<=maxMoves;v++){svg+=`<path d="M65 ${y(v)}H445" stroke="#2a374b"/><text x="49" y="${y(v)+7}" text-anchor="end">${v}</text>`;}
  for(let v=0;v<=maxCalls;v+=2)svg+=`<text x="${x(v)}" y="248" text-anchor="middle">${v}</text>`;
  svg+='<text x="65" y="29">Moves</text><text x="255" y="283" text-anchor="middle">Cumulative tool calls</text>';
  for(let i=0;i<3;i++){
   const r=meta.runs[i],visible=r.solves.filter(s=>s.step<index||s.step===index&&fraction===1);
   svg+=`<polyline points="${visible.map(s=>`${x(s.calls)},${y(s.moves)}`).join(' ')}" fill="none" stroke="${r.color}" stroke-width="3" opacity="0.75"/>`;
   for(const s of visible)svg+=`<circle cx="${x(s.calls)}" cy="${y(s.moves)}" r="${9-i*2}" fill="${r.color}" stroke="#101b2c" stroke-width="1.5"/>`;
  }
  document.querySelector('#chart').innerHTML=svg;
  document.querySelector('#foot').textContent=phase==='final'?'Final states · All verified solves shown':'Synchronized replay · Thinking time compressed';
  await settle();
 }
};
