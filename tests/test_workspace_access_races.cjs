const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'), vm=require('node:vm'), path=require('node:path');
function fixture(){
 const nodes=new Map(),pending=[];
 function element(){return {hidden:false,disabled:false,value:'',textContent:'',children:[],addEventListener(){},appendChild(n){this.children.push(n)},set innerHTML(v){this.children=[]},get innerHTML(){return ''}}}
 function node(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)}
 /* The page bootstraps a session on load (GET /api/me).  These tests drive the
  * page in a logged-out fixture, so that one call is answered immediately with
  * 401 and never enters the pending queue; the race scenarios below are
  * unchanged. */
 const env={document:{getElementById:node,createElement:element},fetch:(url,opts)=>{
   if(url==='/api/me')return Promise.resolve({ok:false,status:401,json:async()=>({error:'unauthenticated'})});
   return new Promise((resolve,reject)=>pending.push({url,opts,resolve,reject}));
 }};
 vm.createContext(env);vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/env_rag_final/access/static/app.js'),'utf8'),env);
 const run=code=>vm.runInContext(code,env);
 run('state.csrf="fixture";state.user={user_id:"dual"};state.selection="air";state.recordId="air-record";state.lastResult={};');
 return {run,node,pending,env};
}
function respond(req,body){req.resolve({ok:true,json:async()=>body})}
test('old air generation success cannot overwrite newer water generation',async()=>{
 const f=fixture();f.run('var oldAnswer=doGenerate();selectWorkspace("water");state.recordId="water-record";state.lastResult={};var newAnswer=doGenerate();');
 respond(f.pending[0],{generation:{status:'success',answer:'OLD_AIR'}});await f.env.oldAnswer;
 assert.equal(f.node('generation').textContent,'生成中…');assert.equal(f.node('generate').disabled,true);
 respond(f.pending[1],{generation:{status:'success',answer:'NEW_WATER'}});await f.env.newAnswer;
 assert.match(f.node('generation').textContent,/NEW_WATER/);assert.equal(f.node('generate').disabled,false);
});
test('late generation failure after logout cannot restore private UI',async()=>{
 const f=fixture();f.run('var oldAnswer=doGenerate();var logout=doLogout();');
 f.pending[0].reject(new Error('old-private-error'));await f.env.oldAnswer;
 assert.equal(f.node('generation').hidden,true);assert.equal(f.node('generation').textContent,'');assert.equal(f.node('app-panel').hidden,true);
 respond(f.pending[1],{});await f.env.logout;
});
test('history response from a previous selection or user is ignored',async()=>{
 const f=fixture();f.run('var oldHistory=loadRecords();selectWorkspace("water");state.user={user_id:"new-user"};var newHistory=loadRecords();');
 respond(f.pending[0],{records:[{record_id:'private-air',question:'OLD_HISTORY',status:'complete'}]});await f.env.oldHistory;
 assert.equal(f.node('records').children.length,0);
 respond(f.pending[1],{records:[{record_id:'water',question:'NEW_HISTORY',status:'retrieved'}]});await f.env.newHistory;
 assert.match(f.node('records').children[0].children[0].textContent,/NEW_HISTORY/);
});
test('new query hides previous answer and obsolete query errors',async()=>{
 const f=fixture();f.node('generation').textContent='old answer';f.node('generation').hidden=false;
 f.run('var oldQuery=doQuery({preventDefault(){}});selectWorkspace("water");');
 f.pending[0].reject(new Error('obsolete query'));await f.env.oldQuery;
 assert.equal(f.node('generation').textContent,'');assert.equal(f.node('generation').hidden,true);
 assert.match(f.node('ask-status').textContent,/water/);
});
