import{a as G,b as $}from"./chunk-T7QVTNXF.js";import{a as U,b as I}from"./chunk-RPXHAG6F.js";import{j as _,k as y,l as O,m as B}from"./chunk-VQ5YXO54.js";import{e as H}from"./chunk-76WAVKUG.js";import{b as W,d as M}from"./chunk-VWKSMFWJ.js";import{I as v,S as z,a as R,c as m,d as T,h as A,i as b,w as e,x as k,z as u}from"./chunk-GT4EAKAO.js";import{d as w}from"./chunk-G7NGB5UX.js";w();w();var j=/\b(github_pat_[A-Za-z0-9_]{22,255}|gh[pousr]_[A-Za-z0-9]{30,255})\b/;function S(t){return t.startsWith("github_pat_")?"fine":t.startsWith("ghp_")?"classic":t.startsWith("ghu_")?"app":"oauth"}var P=[{id:"contents",says:"Read the code and add the workflow file"},{id:"workflows",says:"Change files in .github/workflows"},{id:"actions",says:"Start the first run and watch it"},{id:"pull_requests",says:"Open a pull request when the branch is protected"},{id:"variables",says:"Set the every-CI-run switch"},{id:"secrets",says:"Save keys for Connections"},{id:"pages",says:"Turn on the web page"},{id:"administration",says:"Read the repo's Actions settings"}];function E(){let t=new URLSearchParams({name:"StackVitals",description:"Lets the StackVitals app set up and run StackVitals in the repos you pick",expires_in:"90"});for(let i of P)t.set(i.id,"write");return`https://github.com/settings/personal-access-tokens/new?${t}`}var J={contents:t=>`/repos/${t}/contents/`,actions:t=>`/repos/${t}/actions/workflows?per_page=1`,pull_requests:t=>`/repos/${t}/pulls?per_page=1`,variables:t=>`/repos/${t}/actions/variables?per_page=1`,secrets:t=>`/repos/${t}/actions/secrets/public-key`,pages:t=>`/repos/${t}/pages`,administration:t=>`/repos/${t}/actions/permissions`};async function q(t,i){let p=await t.call("GET","/user");if(!p.ok)throw I(p,!0);let g=S(i),f={login:p.data.login,avatar:p.data.avatar_url,name:p.data.name||null,kind:g};if(g==="classic"||g==="oauth"){let n=(p.headers.get("x-oauth-scopes")||"").split(",").map(a=>a.trim()),d=a=>n.includes(a),h=P.map(a=>({id:a.id,says:a.says,ok:a.id==="workflows"?d("workflow"):d("repo")}));return{...f,repos:null,probe:null,checks:h,missing:h.filter(a=>a.ok===!1)}}let l=await t.call("GET","/user/repos?per_page=100&sort=pushed");if(!l.ok)throw I(l,!0);let x=l.data||[],c=(x.find(n=>n.private)||x[0])?.full_name||null,s=await Promise.all(P.map(async n=>{let d=c&&J[n.id]?.(c);if(!d)return{id:n.id,says:n.says,ok:null};let h=await t.call("GET",d);return{id:n.id,says:n.says,ok:h.status===403?!1:h.ok||h.status===404?!0:null}}));return{...f,repos:x.length,probe:c,checks:s,missing:s.filter(n=>n.ok===!1)}}var K=`/* Connect GitHub, the repo picker, the Welcome screen and setup's plan and live steps. Loads with Welcome and Setup only. */
.gh-avatar { border-radius: 50%; flex: none; background: var(--surface-2); display: grid; place-items: center; color: var(--ink-3); object-fit: cover; }
.account-bar { display: flex; align-items: center; gap: 12px; min-width: 0; }
.account-bar.is-compact { gap: 8px; font-size: 13.5px; }
.account-text { display: flex; flex-direction: column; min-width: 0; flex: 1 1 auto; }
.account-text small { color: var(--ink-2); font-size: 12.5px; }
.account-bar.is-compact .account-text small { display: none; }

.connect { display: flex; flex-direction: column; gap: 14px; }
.connect-or { display: flex; align-items: center; gap: 10px; color: var(--ink-3); font-size: 13px; margin: 0; }
.connect-or::before, .connect-or::after { content: ""; flex: 1; height: 1px; background: var(--line); }
.connect-steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 18px; }
.connect-steps > li { display: flex; gap: 12px; align-items: flex-start; }
.connect-steps > li > div { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 8px; align-items: flex-start; }
.connect-steps > li > div > .field { width: 100%; margin: 0; }
.connect-steps p { margin: 0; color: var(--ink-2); font-size: 14px; }
.step-n { width: 26px; height: 26px; border-radius: 50%; background: var(--accent-soft); color: var(--accent); font-weight: 700; font-size: 13px; display: grid; place-items: center; flex: none; margin-top: 1px; }
.connect-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; width: 100%; flex-wrap: wrap; }
.remember { display: inline-flex; align-items: center; gap: 10px; font-size: 14px; cursor: pointer; }
.pick-hint { margin: 2px 0 0; padding: 10px 12px; border: 1px dashed var(--line-strong); border-radius: 12px; font-size: 13px; width: 100%; display: flex; flex-direction: column; gap: 6px; }
.pick-hint-row { display: flex; align-items: center; gap: 8px; color: var(--ink-3); }
.pick-hint-row.is-on { color: var(--ink); font-weight: 600; }
.pick-hint .radio { width: 14px; height: 14px; border-radius: 50%; border: 1.6px solid var(--line-strong); flex: none; }
.pick-hint .radio.is-on { border: 4px solid var(--accent); }
.pick-hint-chip { margin-left: auto; white-space: nowrap; display: inline-flex; align-items: center; gap: 4px; border: 1px solid var(--line-strong); color: var(--ink-2);
  border-radius: 6px; padding: 1px 8px; font: 500 12px var(--mono, monospace); pointer-events: none; }
.pick-hint-chip .ic { width: 12px; height: 12px; color: var(--good); }
.pick-hint-tag { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: var(--ink-3); }
.pick-hint figcaption { color: var(--ink-2); }
.connect-result { display: flex; flex-direction: column; gap: 12px; }
.abilities { display: flex; flex-direction: column; gap: 10px; }
.ability-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; font-size: 14px; }
.ability-list li { display: flex; align-items: center; gap: 8px; }
.ability-list li > span:first-of-type { flex: 1; min-width: 0; }
.ability-list .ic { width: 17px; height: 17px; color: var(--good); flex: none; }
.ability-list .is-missing .ic { color: var(--bad); }
.note-act { display: block; margin-top: 8px; }
.note b { font-weight: 700; }

/* Repo picker */
.picker { display: flex; flex-direction: column; gap: 14px; }
.picker .search-field { flex: none; }
.picker-group { display: flex; flex-direction: column; gap: 6px; }
.picker-owner { font-size: 13px; font-weight: 700; color: var(--ink-2); margin: 0 4px; display: flex; gap: 8px; align-items: baseline; text-transform: none; }
.picker-owner .num { color: var(--ink-3); font-weight: 600; }
.picker .row-title { display: inline-flex; align-items: center; gap: 6px; }
.picker .row-sub { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.repo-lock { width: 14px; height: 14px; color: var(--ink-3); }
.checking { display: inline-flex; color: var(--ink-3); }
.picker-none { color: var(--ink-2); margin: 0 4px; }

/* Setup: plan and live steps */
.plan { list-style: none; margin: 0; padding: 4px 0; }
.plan-row { display: flex; align-items: center; gap: 14px; padding: 12px 16px; }
.plan-row + .plan-row { border-top: 1px solid var(--line); }
.plan-text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.plan-text small { color: var(--ink-2); font-size: 13.5px; }
.wf-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.wf-chip { display: inline-flex; align-items: center; gap: 4px; border-radius: 999px; padding: 4px 11px; font: inherit; font-size: 13px; border: 1px solid var(--line-strong); background: var(--surface); color: var(--ink-2); cursor: pointer; }
.wf-chip[aria-pressed="true"] { background: var(--accent-soft); border-color: transparent; color: var(--accent); font-weight: 600; }
.wf-chip .ic { width: 14px; height: 14px; }
.advanced { display: flex; flex-direction: column; gap: 12px; margin-top: 12px; }
.adv-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; font-size: 14px; }
.adv-row > span:first-child { flex: 1 1 200px; }
.yaml-peek { margin-top: 12px; }
.yaml-peek summary { cursor: pointer; color: var(--accent); font-weight: 600; font-size: 14px; padding: 4px 0; }
.yaml-peek .code { margin-top: 8px; }
.yaml-peek pre { max-height: 360px; }
.go-card { display: flex; flex-direction: column; gap: 14px; }
.go-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; font-size: 14.5px; }
.go-list li { display: flex; gap: 8px; align-items: flex-start; }
.go-list .ic { width: 18px; height: 18px; color: var(--good); flex: none; margin-top: 1px; }
.go-buttons { display: flex; flex-wrap: wrap; gap: 8px; }
.go-or { margin: 0; color: var(--ink-2); font-size: 13.5px; }
.setup-steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.setup-step { display: flex; gap: 12px; align-items: flex-start; padding: 8px 0; }
.setup-mark { width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; flex: none; background: var(--surface-2); color: var(--ink-3); }
.setup-mark .ic { width: 16px; height: 16px; }
.setup-step.is-running .setup-mark { background: var(--accent-soft); color: var(--accent); }
.setup-step.is-done .setup-mark { background: var(--good-soft); color: var(--good); }
.setup-step.is-failed .setup-mark { background: var(--bad-soft); color: var(--bad); }
.setup-step.is-waiting .setup-mark { background: var(--watch-soft); color: var(--watch); }
.setup-step.is-pending b, .setup-step.is-skipped b { color: var(--ink-2); font-weight: 600; }
.setup-body { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; align-items: flex-start; padding-top: 3px; }
.setup-body p { margin: 0; color: var(--ink-2); font-size: 14px; }
.setup-fix { display: flex; gap: 6px; align-items: flex-start; color: var(--ink) !important; }
.setup-fix .ic { width: 16px; height: 16px; color: var(--accent); flex: none; margin-top: 2px; }
.setup-site { font-size: 14px; color: var(--ink-2); }
.jobs { list-style: none; margin: 6px 0 0; padding: 0; display: flex; flex-direction: column; gap: 6px; font-size: 13.5px; width: 100%; }
.jobs > li { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.job-state { color: var(--ink-3); }
.job-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ink-3); }
.job-dot.is-in_progress { background: var(--accent); } .job-dot.is-success { background: var(--good); } .job-dot.is-failure { background: var(--bad); }
.job-steps { list-style: none; margin: 0; padding: 0 0 0 16px; width: 100%; display: flex; flex-direction: column; gap: 3px; color: var(--ink-2); }
.job-steps li { display: flex; align-items: center; gap: 6px; }
.job-steps .ic, .job-steps .spin { width: 13px; height: 13px; }
.job-steps .is-success .ic { color: var(--good); } .job-steps .is-failure .ic { color: var(--bad); }

/* Instrument (sheet design): Connect, the account bar, permissions and the repo picker. Steps numbered in blue rings with bold sans
   figures; the pick sketch a grey panel with a bold label; names 600, headings 700; mono only for the repo id */
[data-design="sheet"] .connect { gap: 20px; }
[data-design="sheet"] .connect-or { font: 600 14px var(--font); color: var(--ink-2); }
[data-design="sheet"] .connect-or::before, [data-design="sheet"] .connect-or::after { background: var(--line-strong); }
[data-design="sheet"] .connect-steps { gap: 0; }
[data-design="sheet"] .connect-steps > li { gap: 14px; }
[data-design="sheet"] .connect-steps > li + li { border-top: 1px solid var(--line); margin-top: 22px; padding-top: 22px; }
[data-design="sheet"] .connect-steps > li > div > b { font-weight: 700; font-size: 18px; line-height: 1.25; }
[data-design="sheet"] .connect-steps p { font-size: 15px; color: var(--ink-2); }
[data-design="sheet"] .step-n { width: 30px; height: 30px; margin-top: -2px; background: var(--accent-soft); border: 1.5px solid var(--sv-blue); color: var(--accent);
  font: 700 15px/1 var(--font); font-variant-numeric: tabular-nums; border-radius: 50% !important; }
[data-design="sheet"] .connect-steps .btn { min-height: 44px; }
[data-design="sheet"] .pick-hint { margin-top: 6px; background: var(--surface-2); border: 1px solid var(--line-strong); padding: 14px 16px; gap: 8px; font-size: 15px; }
[data-design="sheet"] .pick-hint-tag { font: 700 13.5px/1.3 var(--font); letter-spacing: .04em; text-transform: uppercase; color: var(--ink-2); border-bottom: 1px solid var(--line-strong); padding-bottom: 8px; }
[data-design="sheet"] .pick-hint-row { gap: 10px; color: var(--ink-2); flex-wrap: wrap; }
[data-design="sheet"] .pick-hint-row.is-on { color: var(--ink); font-weight: 600; }
[data-design="sheet"] .pick-hint .radio, [data-design="sheet"] .pick-hint .radio.is-on { width: 15px; height: 15px; border: 1.5px solid var(--ink); background: var(--surface); display: inline-grid; place-items: center; }
[data-design="sheet"] .pick-hint .radio.is-on { border-color: var(--sv-blue); }
[data-design="sheet"] .pick-hint .radio.is-on::after { content: ""; width: 7px; height: 7px; background: var(--sv-blue); border-radius: 50% !important; }
/* The picked repo sits under its option, as on the sheet Welcome's sketch */
[data-design="sheet"] .pick-hint-row.is-on { display: grid; grid-template-columns: 15px auto; justify-content: start; row-gap: 6px; }
[data-design="sheet"] .pick-hint-chip { grid-column: 2; justify-self: start; margin: 0; font: 400 13.5px var(--mono); color: var(--ink); background: var(--surface); border-color: var(--line-strong); padding: 2px 8px; }
[data-design="sheet"] .pick-hint figcaption { font-size: 14.5px; }
[data-design="sheet"] .connect-steps .field-label { font-size: 18px; font-weight: 700; line-height: 1.25; }
[data-design="sheet"] .pick-hint-chip .ic { color: var(--good); }
[data-design="sheet"] .remember { font-size: 15px; }
[data-design="sheet"] .connect-result { gap: 14px; }
[data-design="sheet"] .account-bar b { font-weight: 600; }
[data-design="sheet"] .account-text small { font-size: 14px; color: var(--ink-2); }
[data-design="sheet"] .gh-avatar { border: 1.5px solid var(--line-strong); background: var(--surface-2); }
[data-design="sheet"] .ability-list { gap: 8px; font-size: 15px; }
[data-design="sheet"] .ability-list li { align-items: flex-start; flex-wrap: wrap; gap: 4px 10px; }
[data-design="sheet"] .ability-list .ic { margin-top: 3px; color: var(--good); }
[data-design="sheet"] .ability-list .is-missing .ic { color: var(--bad); }
[data-design="sheet"] .picker-owner { font: 700 15px var(--font); color: var(--ink); margin: 0; }
[data-design="sheet"] .picker-owner .num { font: 600 14px var(--font); font-variant-numeric: tabular-nums; color: var(--ink-2); }
[data-design="sheet"] .picker .glist.card { border: 1.5px solid var(--frame); }
[data-design="sheet"] .picker .row-title { font-weight: 600; }
@media (max-width: 640px) {
  [data-design="sheet"] .connect-steps > li { gap: 10px; }
  [data-design="sheet"] .connect-row { flex-direction: column; align-items: stretch; }
  [data-design="sheet"] .pick-hint { padding: 12px; }
  [data-design="sheet"] .account-bar { flex-wrap: wrap; gap: 8px 12px; }
  [data-design="sheet"] .account-text { flex: 1 1 160px; }
  [data-design="sheet"] .account-text small { overflow-wrap: anywhere; }
  [data-design="sheet"] .account-bar.is-compact .account-text { flex: 0 1 auto; }
  [data-design="sheet"] .ability-list li > span:first-of-type { flex: 1 1 180px; }
  [data-design="sheet"] .ability-list li > .pill { margin-left: 27px; }
  [data-design="sheet"] .picker .row { gap: 8px 10px; padding: 10px 12px; }
  [data-design="sheet"] .picker .row-text { flex: 1 1 0; }
  [data-design="sheet"] .picker .row-sub { white-space: normal; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
  [data-design="sheet"] .picker .row-trail { margin-left: 42px; order: 3; flex: 1 1 100%; }
  [data-design="sheet"] .picker .row-chev { margin-left: auto; }
}
`;document.getElementById("sv-connect-css")||document.head.appendChild(Object.assign(document.createElement("style"),{id:"sv-connect-css",textContent:K}));function L({src:t,size:i=36}){return t?e("img",{class:"gh-avatar",src:t.includes("?")?t:`${t}?s=${i*2}`,alt:"",width:i,height:i}):e("span",{class:"gh-avatar",style:{width:`${i}px`,height:`${i}px`},children:e(k,{name:"lock"})})}function F({info:t}){return e("div",{class:"abilities",children:[t.repos===0?e("div",{class:"note note-bad",role:"alert",children:[e(k,{name:"warn"}),e("span",{children:["This token reaches no repos. On GitHub's page, under",e("b",{children:" Repository access"}),", choose ",e("b",{children:"Only select repositories"})," and pick yours."]})]}):null,e("ul",{class:"ability-list","aria-label":"What the token can do",children:t.checks.map(i=>e("li",{class:i.ok===!1?"is-missing":"",children:[e(k,{name:i.ok===!1?"warn":i.ok?"check":"dot"}),e("span",{children:i.says}),i.ok===!1?e(v,{tone:"bad",icon:null,children:"missing"}):i.ok===null?e(v,{tone:"neutral",icon:null,children:"checked at setup"}):null]}))}),t.missing.length?e("div",{class:"note note-watch",children:[e(k,{name:"warn"}),e("span",{children:["Missing: ",t.missing.map(i=>i.says.toLowerCase()).join("; "),". Make a new token with everything ticked and paste it here.",e("span",{class:"note-act",children:e(u,{size:"sm",variant:"tinted",href:E(),external:!0,iconEnd:"external",children:"Make a new token"})})]})]}):null]})}var N=A(null);function D(t,i){let[p,g]=m(""),[f,l]=m(!1),[x,c]=m(null),[s,n]=m(null),d=async a=>{let o=a.match(j)?.[1];if(!o){c("That doesn't look like a GitHub token. It starts with github_pat_ (or ghp_ for a classic one).");return}l(!0),c(null),n(null);try{let r=await q(U(o),o);n(r),N.set(r),O({token:o,kind:S(o),login:r.login,avatar:r.avatar,...r.name?{name:r.name}:{},remember:t}),g(""),z(`Connected as ${r.login}`),!r.missing.length&&r.repos!==0&&i?.()}catch(r){c(r instanceof Error?r.message:"The check failed.")}l(!1)};return{text:p,busy:f,err:x,setErr:c,info:s,setInfo:n,check:d,onInput:a=>{g(a),c(null);let o=a.trim();o&&o.match(j)?.[1]===o&&d(o)}}}function ue(){let t=b(N),i=b(y);return t&&i&&i.login===t.login&&(t.missing.length||t.repos===0)?e(F,{info:t}):null}function fe({compact:t}){let i=b(y);return i?e("div",{class:"account-bar"+(t?" is-compact":""),children:[e(L,{src:i.avatar,size:t?28:36}),e("span",{class:"account-text",children:[e("b",{children:i.login||"Connected"}),e("small",{children:[i.kind==="app"?"Signed in with GitHub":i.kind==="fine"?"Fine-grained token":"Classic token",i.remember?", remembered on this device":", this tab only"]})]}),e(u,{size:"sm",variant:"plain",onClick:()=>{B(),z("Signed out of GitHub","neutral"),location.reload()},children:"Sign out"})]}):null}function me({app:t,onConnected:i}){let p=G(t),[g,f]=m(!1),{text:l,busy:x,err:c,info:s,setInfo:n,check:d,onInput:h}=D(g,i),a=async()=>{p&&location.assign(await $(p,g&&_(),location.hash||"#/"))},o=b(y);return T(()=>{o||n(null)},[o]),e("div",{class:"connect",children:[p?e(R,{children:[e(u,{variant:"filled",size:"lg",wide:!0,icon:"link",onClick:a,children:"Sign in with GitHub"}),e("p",{class:"connect-or",children:e("span",{children:"or use a token"})})]}):null,e("ol",{class:"connect-steps",children:[e("li",{children:[e("span",{class:"step-n","aria-hidden":"true",children:"1"}),e("div",{children:[e("b",{children:"Make a token on GitHub"}),e("p",{children:"The page opens with the name, a 90-day expiry and the permissions filled in."}),e(u,{variant:p?"tinted":"filled",href:E(),external:!0,iconEnd:"external",children:"Open GitHub's token page"}),e("figure",{class:"pick-hint","aria-label":"On GitHub's page: Repository access, Only select repositories, then pick yours",children:[e("span",{class:"pick-hint-tag","aria-hidden":"true",children:"What GitHub's page looks like"}),e("div",{class:"pick-hint-row",children:[e("span",{class:"radio"}),e("span",{children:"All repositories"})]}),e("div",{class:"pick-hint-row is-on",children:[e("span",{class:"radio is-on"}),e("span",{children:"Only select repositories"}),e("span",{class:"pick-hint-chip","aria-hidden":"true",children:[e(k,{name:"check"}),"owner/repo"]})]}),e("figcaption",{children:["On GitHub's page, under ",e("b",{children:"Repository access"}),", pick the repos; GitHub can't fill that in. Then ",e("b",{children:"Generate token"})," and copy it."]})]})]})]}),e("li",{children:[e("span",{class:"step-n","aria-hidden":"true",children:"2"}),e("div",{children:[e(M,{label:"Paste it here",error:c,hint:"Checked as soon as you paste. It goes only to api.github.com and stays in this browser.",children:r=>e("input",{id:r,class:"input mono",type:"password",autoComplete:"off",spellcheck:!1,placeholder:"github_pat_\u2026",value:l,onInput:C=>h(C.currentTarget.value),onKeyDown:C=>{C.key==="Enter"&&d(l)}})}),e("div",{class:"connect-row",children:[_()?e("label",{class:"remember",children:[e(W,{checked:g,onChange:f,labelledBy:"remember-l"}),e("span",{id:"remember-l",children:"Remember on this device"})]}):e("small",{class:"remember",children:["Kept for this tab only: other sites under ",location.hostname," could read a remembered token. Use a custom domain or ",e("code",{children:"stackvitals ui"})," to remember it."]}),e(u,{variant:"tinted",loading:x,disabled:!l.trim(),onClick:()=>d(l),children:"Check token"})]})]})]})]}),s&&o?e(H,{class:"connect-result",children:[e("div",{class:"account-bar",children:[e(L,{src:s.avatar}),e("span",{class:"account-text",children:[e("b",{children:s.login}),e("small",{children:s.repos===null?"Classic token: every repo you can reach":`${s.repos}${s.repos===100?"+":""} repo${s.repos===1?"":"s"} picked`})]}),s.missing.length?e(v,{tone:"watch",children:"Needs more"}):e(v,{tone:"good",children:"Ready"})]}),e(F,{info:s}),i?e(u,{variant:"filled",wide:!0,onClick:i,children:"Continue"}):null]}):null]})}export{E as a,L as b,F as c,N as d,D as e,ue as f,fe as g,me as h};
