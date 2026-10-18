const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'), vm=require('node:vm'), path=require('node:path');
/* Remote-mode page contract (K12/K13):
 * - multi-enterprise humans must choose explicitly; a remote login without a
 *   selected enterprise cannot query,
 * - A→B→A switching invalidates in-flight responses (epoch guard),
 * - logging out and logging in as another account cannot be repainted by a
 *   late reply from the previous account,
 * - the IAM token never enters JS state/localStorage, and the SSO entry point
 *   is a plain navigation to a server route.
 */
function fixture(){
 const nodes=new Map(),pending=[];
 function element(){return {hidden:false,disabled:false,value:'',textContent:'',children:[],addEventListener(){},appendChild(n){this.children.push(n)},set innerHTML(v){this.children=[]},get innerHTML(){return ''}}}
 function node(id){if(!nodes.has(id))nodes.set(id,element());return nodes.get(id)}
 const env={
   document:{getElementById:node,createElement:element},
   fetch:(url,opts)=>new Promise((resolve,reject)=>pending.push({url,opts,resolve,reject})),
   window:{location:{href:''}},
   localStorage:{store:{},getItem(k){return this.store[k]||null},setItem(k,v){this.store[k]=v}},
 };
 vm.createContext(env);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/env_rag_final/access/static/app.js'),'utf8'),env);
 const run=code=>vm.runInContext(code,env);
 return {run,node,pending,env};
}
function respond(req,body){req.resolve({ok:true,json:async()=>body})}
/* Requests interleave (a switch also refreshes the record list), so the tests
 * answer by URL instead of by queue position. */
function answer(f,part,body){
 const i=f.pending.findIndex(r=>r.url.indexOf(part)>=0);
 if(i<0) throw new Error('no pending request matching '+part);
 const [req]=f.pending.splice(i,1);
 respond(req,body);
}

test('remote login without an enterprise cannot query',async()=>{
 const f=fixture();
 f.node('account').value='i3.dual'; f.node('password').value='pw';
 f.run('var login=doLogin({preventDefault(){}});');
 answer(f,'/api/login',{
   csrf:'c1',user_id:'u1',display:'I3 双库读者',
   tenant:null,tenants:[{tenant_id:'t-a',code:'alpha'},{tenant_id:'t-b',code:'beta'}],
   workspaces:[],mode:'remote',
 });
 await f.env.login;
 answer(f,'/api/records',{records:[]});
 assert.equal(f.node('tenant-panel').hidden,false);
 assert.equal(f.node('ask-submit').disabled,true,"query must stay disabled until an enterprise is chosen");
 assert.match(f.node('tenant-hint').textContent,/选择企业/);
 const options=f.node('tenant').children.filter(c=>c.value);
 assert.equal(options.length,2,'both enterprises are offered');
});

test('A to B to A: a late reply from the first enterprise never paints',async()=>{
 const f=fixture();
 f.run('state.csrf="c";state.user={user_id:"u1"};state.mode="remote";state.tenant="t-a";state.tenant_code="alpha";state.contextVersion=2;state.workspaces=[];state.selection="coastal";state.lastResult={};state.recordId=null;');
 f.node('tenant').value='t-b';
 f.run('var switchB=doSwitchTenant();');
 answer(f,'/api/switch-tenant',{csrf:'c',tenant:'t-b',tenant_code:'beta',context_version:3,tenant_epoch:'e2',tenants:[],workspaces:[]});
 await f.env.switchB;
 answer(f,'/api/records',{records:[]});
 assert.match(f.node('tenant-hint').textContent,/beta/,'a successful switch reports the new enterprise');
 assert.equal(f.run('state.tenant'),'t-b','the new enterprise is applied');
 assert.equal(f.run('state.tenant_code'),'beta');
 f.node('tenant').value='t-a';
 f.run('var switchA=doSwitchTenant();');
 answer(f,'/api/switch-tenant',{csrf:'c',tenant:'t-a',tenant_code:'alpha',context_version:4,tenant_epoch:'e3',tenants:[],workspaces:[]});
 await f.env.switchA;
 answer(f,'/api/records',{records:[]});
 // A query issued under B must not paint after switching back to A.
 f.run('state.selection="coastal";var q=doQuery({preventDefault(){}});');
 const epochBefore=f.run('state.tenantEpoch');
 f.node('tenant').value='t-b';
 f.run('var switchB2=doSwitchTenant();');
 answer(f,'/api/switch-tenant',{csrf:'c',tenant:'t-b',tenant_code:'beta',context_version:5,tenant_epoch:'e4',tenants:[],workspaces:[]});
 await f.env.switchB2;
 answer(f,'/api/records',{records:[]});
 answer(f,'/api/query',{record_id:'r-old',workspaces:['coastal'],result:{status:'retrieved',route:'pg',evidence:[]}});
 await f.env.q;
 assert.notEqual(f.run('state.tenantEpoch'),epochBefore,'the epoch advanced on switch');
 assert.equal(f.node('result-panel').hidden,true,'stale reply left the result panel closed');
});

test('late reply after logout and account change cannot restore private UI',async()=>{
 const f=fixture();
 f.run('state.csrf="c";state.user={user_id:"u1"};state.mode="remote";state.tenant="t-a";state.workspaces=[];state.selection="coastal";state.lastResult={};state.recordId="r1";');
 f.run('var q=doQuery({preventDefault(){}});');
 f.run('var lo=doLogout();');
 answer(f,'/api/logout',{});
 await f.env.lo;
 answer(f,'/api/query',{record_id:'r1',workspaces:['coastal'],result:{status:'retrieved',route:'pg',evidence:[{workspace:'coastal'}]}});
 await f.env.q;
 assert.equal(f.node('app-panel').hidden,true,'late reply must not re-open the app');
 assert.equal(f.node('result-panel').hidden,true);
});

test('the IAM token never enters page state or storage',()=>{
 const f=fixture();
 const source=fs.readFileSync(path.join(__dirname,'../src/env_rag_final/access/static/app.js'),'utf8');
 assert.doesNotMatch(source,/localStorage\.setItem\([^)]*token/,'no token writes to localStorage');
 assert.doesNotMatch(source,/subject_token/,'the raw subject token is never referenced by the page');
 assert.doesNotMatch(source,/access_token/,'the raw access token is never referenced by the page');
 assert.match(source,/\/api\/sso\/start/,'SSO entry is a server route');
});

test('error mapping surfaces 401/403/409/503 semantics verbatim',()=>{
 const f=fixture();
 assert.match(f.run('describeError(new Error("upstream_unavailable"))'),/503/);
 assert.match(f.run('describeError(new Error("tenant_selection_required"))'),/选择企业/);
 assert.match(f.run('describeError(new Error("context_changed"))'),/上下文/);
 assert.match(f.run('describeError(new Error("bad_sso_state"))'),/SSO/);
});

test('login and refresh preserve the actual server CAS version',()=>{
 const f=fixture();
 f.run('applySession({csrf:"c",mode:"remote",user_id:"u",display:"u",tenant:"a",tenants:[],workspaces:[],context_version:7,tenant_epoch:"server-e7"});');
 assert.equal(f.run('state.contextVersion'),7);
 assert.equal(f.run('state.serverEpoch'),'server-e7');
 assert.equal(f.node('ask-submit').disabled,true,'no mapped libraries means query unavailable');
});

test('a delayed bootstrap cannot replace a newly logged-in account',async()=>{
 const f=fixture();
 f.run('invalidateResult();applySession({csrf:"new",mode:"remote",user_id:"new-account",display:"new",tenant:"a",tenants:[],workspaces:[],context_version:3,tenant_epoch:"new-e"});');
 answer(f,'/api/me',{csrf:'old',mode:'remote',user_id:'old-account',display:'old',tenant:'b',context_version:1,tenant_epoch:'old-e'});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(f.run('state.user.user_id'),'new-account');
 assert.equal(f.run('state.contextVersion'),3);
});

test('native source links carry a context marker without an IAM credential',()=>{
 const f=fixture();
 f.run('state.mode="remote";state.serverEpoch="epoch-v2";');
 assert.equal(f.run('scopedLink("/api/export/r")'),'/api/export/r?ctx=epoch-v2');
 f.run('state.mode="local";');
 assert.equal(f.run('scopedLink("/api/export/r")'),'/api/export/r');
});
