import {spawn} from 'node:child_process';
import {readFile,writeFile,mkdir,mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import Cube from 'cubejs';
import {Alg,Move} from 'cubing/alg';
import {chromium} from 'playwright';

const sources = [
 ['GPT-5.5','xhigh','#67c5ff','runs/20260905T055253Z_codex_gpt55_full_solve/001_full_solve_gpt_5_5_xhigh'],
 ['GPT-5.6 Sol','max','#ffbd69','runs/20260905T044936Z_codex_f2l_full_cube/003_full_solve_gpt_5_6_sol_max'],
 ['GPT-6 Astra','max','#bd9dff','runs/20260905T044936Z_codex_f2l_full_cube/004_full_solve_gpt_6_astra_max'],
];
const scramble="B U F B D F R L' F D2 F2 L' D2 F2 B2 R U2 L2 D2 L2 F";
const expand=s=>[...new Alg(s).expand().childAlgNodes()].filter(m=>m instanceof Move).map(String);
const output=resolve(process.argv[2] || 'media/full-solve-comparison.mp4');
const preview=process.argv.includes('--preview');
const runs=[];
for(const [label,effort,color,path] of sources){
 let text;
 try{text=await readFile(`${path}/codex-events.jsonl`,'utf8');}catch(e){if(!preview)throw new Error(`Run not ready: ${path}`);}
 let cube=new Cube().move(scramble),moves=[],calls=0,steps=[],solves=[],lastSolved=-1;
 for(const line of (text||'').split('\n').filter(Boolean)){
  const e=JSON.parse(line),i=e.item;
  if(e.type!=='item.completed'||i?.type!=='mcp_tool_call'||i.server!=='cubebench'||i.error||i.status!=='completed'||i.result?.isError)continue;
  calls++;
  if(i.tool==='load_scramble'){
   cube=new Cube().move(scramble);moves=[];
   steps.push({setup:scramble,move:'',count:0,calls,reset:true});
  }
  if(i.tool==='apply_moves'){
   const chunk=expand(i.arguments.moves);const trial=cube.clone();trial.move(chunk.join(' '));
   for(const move of chunk){
    const setup=[scramble,...moves].join(' ');cube.move(move);moves.push(move);
    const solved=cube.isSolved();
    steps.push({setup,move,count:moves.length,calls,solved});
    if(solved){solves.push({calls,moves:moves.length,sequence:moves.join(' '),step:steps.length-1});lastSolved=steps.length-1;}
   }
   const reported=i.result?.structured_content?.state;
   if(reported && ['cp','co','ep','eo'].some(k=>JSON.stringify(cube.toJSON()[k])!==JSON.stringify(reported[k])))throw new Error(`${label}: replay disagrees with tool state`);
  }
 }
 if(lastSolved>=0)steps=steps.slice(0,lastSolved+1);
 runs.push({label,effort,color,path,pending:!text,steps,solves,calls});
}
await mkdir(join(output,'..'),{recursive:true});
await writeFile(output.replace(/\.mp4$/,'.json'),JSON.stringify({scramble,metric:'Cumulative completed cube-tool calls versus verified solution moves (HTM). Token/cost histories unavailable. Synchronized move playback, not wall-clock time. Stops at last verified solve; duplicate final submissions are not replayed.',runs},null,2));
console.log(runs.map(r=>({model:r.label,steps:r.steps.length,solves:r.solves.map(s=>s.moves)})));
const server=spawn('npm',['run','dev','--','--host','127.0.0.1','--port','4175','--strictPort'],{stdio:'ignore'});
let browser;const temp=await mkdtemp(join(tmpdir(),'cube-comparison-'));
function command(cmd,args){return new Promise((res,rej)=>{const p=spawn(cmd,args,{stdio:'inherit'});p.on('error',rej);p.on('exit',c=>c===0?res():rej(Error(`${cmd}: ${c}`)));});}
try{
 for(let i=0;i<80;i++){try{if((await fetch('http://127.0.0.1:4175/comparison.html')).ok)break;}catch{}await new Promise(r=>setTimeout(r,250));}
 browser=await chromium.launch({args:['--no-sandbox']});
 const page=await browser.newPage({viewport:{width:1080,height:1080},deviceScaleFactor:1});
 page.on('pageerror',e=>console.error(e));
 await page.goto('http://127.0.0.1:4175/comparison.html');
 await page.waitForFunction(()=>!!window.comparison);
 await page.evaluate(meta=>window.comparison.init(meta),{runs,scramble});
 const frames=[];let n=0;
 const capture=async(state,duration)=>{
  await page.evaluate(s=>window.comparison.render(s),state);
  const filename=join(temp,`${String(n++).padStart(5,'0')}.png`);
  await page.screenshot({path:filename});frames.push({filename,duration});
 };
 await capture({index:-1,fraction:1,phase:'intro'},2.5);
 if(preview){await page.screenshot({path:output.replace(/\.mp4$/,'.png')});}
 else{
 const max=Math.max(...runs.map(r=>r.steps.length));
 for(let index=0;index<max;index++){
  for(let f=1;f<=6;f++)await capture({index,fraction:f/6,phase:'play'},1/30);
  if(runs.some(r=>r.steps[index]?.solved))await capture({index,fraction:1,phase:'solved'},2.5);
  else if(runs.some(r=>r.steps[index]?.reset))await capture({index,fraction:1,phase:'play'},0.45);
  if(index%10===0)console.log(`Rendered ${index}/${max} move positions`);
 }
 await capture({index:max,fraction:1,phase:'final'},5);
 await page.screenshot({path:output.replace(/\.mp4$/,'.png')});
 const list=frames.map(f=>`file '${f.filename}'\nduration ${f.duration}`).join('\n')+`\nfile '${frames.at(-1).filename}'\n`;
 await writeFile(join(temp,'frames.txt'),list);
 await command('ffmpeg',['-hide_banner','-loglevel','warning','-y','-f','concat','-safe','0','-i',join(temp,'frames.txt'),'-vf','fps=30','-c:v','libx264','-preset','medium','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',output]);
 console.log(`Wrote ${output}`);
 }
}finally{await browser?.close();server.kill();await rm(temp,{recursive:true,force:true});}
