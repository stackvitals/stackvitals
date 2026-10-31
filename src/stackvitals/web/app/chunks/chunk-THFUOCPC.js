import{b as K,c as q,d as J,e as y,f as Q,g as H}from"./chunk-RQZPSJ2Y.js";import{a as D,c as j,d as N,e as U,g as X}from"./chunk-3IXWEOIJ.js";import{a as W}from"./chunk-Y6LUXDM6.js";import{c as _}from"./chunk-7TJCBOAY.js";import{b as F}from"./chunk-6BDBXA6V.js";import{a as S,b as A,c as G}from"./chunk-T7QVTNXF.js";import{a as Y}from"./chunk-RPXHAG6F.js";import{j as R,k as P,l as L,p as O,r as V}from"./chunk-VQ5YXO54.js";import{I as C,S as B,a as z,c as v,d as g,f as I,i as f,j as T,w as s,z as m}from"./chunk-GT4EAKAO.js";import{d as M}from"./chunk-G7NGB5UX.js";M();M();function Z(){let[e,t]=v(""),[i,a]=v(!1),[c,l]=v(null),[n,p]=v(null);return{text:e,edit:h=>{t(h),l(null),p(null)},busy:i,err:c,found:n,go:async h=>{h?.preventDefault();let d=q(e);if(!d){l("Type it as owner/repo, for example vitejs/vite.");return}a(!0),l(null),p(null);let w=await J(d);if(a(!1),w.kind==="data"){y(O(w.source,w.app.repo)),B(`Opened ${w.app.repo}`);return}p({repo:d,res:w})}}}var ss=(e,t)=>t==="data"?Q(e.full_name,e.private):H(e.full_name,e.private);function rs(){let e=f(P),[t,i]=v(null),a=f(V).filter(l=>l.id!=="here"&&!l.demo),c=new URLSearchParams(location.search).has("welcome");return g(()=>{let l=S();if(!l||!new URLSearchParams(location.search).has("code")){let n=a.find(p=>p.id===T.get("last",""))||a[a.length-1];e&&n&&!c&&y(n);return}i("Finishing sign-in\u2026"),G(l).then(async n=>{if(!n){i(null);return}let p=await Y(n.account.token).get("/user");L({...n.account,login:p?.login,avatar:p?.avatar_url}),B(`Signed in as ${p?.login||"you"}`),i(null)},n=>{i(n instanceof Error?n.message:"Sign-in failed.")})},[]),s(E,{a:e,signing:t,known:a})}var es=`/* The Instrument design's Welcome (loads only in that design): the framed sheet, the self-drawing schematic, framed panels. */
.svw { min-height: 100vh; min-height: 100dvh; background: var(--bg); color: var(--ink); font-size: 17px; line-height: 1.5; overflow-x: hidden; }
.svw p { margin: 0; }
.svw b { font-weight: 600; }
.svw main { padding: 0; outline: none; }

/* The sheet's frame: four hairlines that draw in turn, with centre ticks */
.svw-frame { position: relative; max-width: 1240px; margin: 24px auto; padding: clamp(20px, 4vw, 56px); }
.svw-edge, .svw-tick { position: absolute; background: var(--ink); pointer-events: none; }
.svw-edge.e-t, .svw-edge.e-b { left: 0; right: 0; height: 1px; }
.svw-edge.e-t { top: 0; transform-origin: left; } .svw-edge.e-b { bottom: 0; transform-origin: right; }
.svw-edge.e-l, .svw-edge.e-r { top: 0; bottom: 0; width: 1px; }
.svw-edge.e-r { right: 0; transform-origin: top; } .svw-edge.e-l { left: 0; transform-origin: bottom; }
.svw-tick.k-t, .svw-tick.k-b { left: 50%; width: 1px; height: 10px; } .svw-tick.k-t { top: 0; } .svw-tick.k-b { bottom: 0; }
.svw-tick.k-l, .svw-tick.k-r { top: 50%; height: 1px; width: 10px; } .svw-tick.k-l { left: 0; } .svw-tick.k-r { right: 0; }

/* Headline: the padding keeps descenders (the g in doing) inside the reveal clip; the negative margin keeps the spacing */
.svw-h1 { margin: 0 0 -.18em; padding: 0 0 .18em; font-family: var(--display); font-weight: 700; font-size: clamp(40px, 6vw, 78px); line-height: 1; letter-spacing: -.01em; max-width: 17ch; }

/* Schematic */
.svw-flow { margin: clamp(32px, 5vw, 56px) 0 clamp(28px, 4vw, 44px); }
.svw-schem { display: block; width: 100%; height: auto; overflow: visible; }
.svw-schem.is-tall { display: none; }
.svw-schem text { fill: var(--ink); }
.svw-schem .s-bx { fill: none; stroke: var(--ink); stroke-width: 1.2; }
.svw-schem .s-hl { fill: none; stroke: var(--ink); stroke-width: .8; }
.svw-schem .s-live { fill: none; stroke: var(--sv-blue); stroke-width: 1.6; }
.svw-schem .s-ah { fill: var(--sv-blue); }
.svw-schem .s-dt { fill: var(--ink); }
.svw-schem .s-lbl { font: 600 16.5px var(--font); }
.svw-schem .s-mono { font-family: var(--mono); font-weight: 400; font-size: 13px; }
.svw-schem .s-mono-sm { font-size: 13.5px; }
.svw-schem .s-dim { font: 600 15px var(--font); fill: var(--ink-2); }
.svw-schem .s-cn { font: 700 15px var(--font); }
.svw-schem .s-sl { font: 700 15px var(--font); }
.svw-schem .s-sl.s-bad { fill: var(--bad); } .svw-schem .s-sl.s-warn { fill: var(--watch); } .svw-schem .s-sl.s-ok { fill: var(--good); }
.svw-schem .s-mk { stroke: var(--dot-edge, #000); stroke-width: 1; stroke-linejoin: round; }
.svw-schem .s-mk-bad, .svw-schem .s-bar-bad { fill: var(--sv-coral); }
.svw-schem .s-mk-warn, .svw-schem .s-bar-warn { fill: var(--sv-amber); }
.svw-schem .s-mk-ok, .svw-schem .s-bar-ok { fill: var(--sv-mint); }
.svw-schem .s-mk-g { fill: none; stroke: #000; stroke-width: 1.4; stroke-linecap: round; stroke-linejoin: round; }
.svw-schem .s-rm-only { display: none; }
/* A connected token marks this app healthy: the box fills mint, like the Healthy key */
.svw-schem .s-appfill { fill: var(--sv-mint); transform-box: fill-box; transform-origin: center bottom; transform: scaleY(0); transition: transform .6s .35s var(--sv-ease); }
.svw-schem .s-applbl { transition: fill .2s .5s; }
.svw.is-ok .svw-schem .s-appfill { transform: scaleY(1); }
.svw.is-ok .svw-schem .s-applbl { fill: #000; }

/* Three points, the brand block and the colour key */
.svw-notes-row { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 40px; align-items: end; }
.svw-notes { list-style: none; margin: 0; padding: 0; counter-reset: n; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 28px; }
.svw-notes li { counter-increment: n; display: grid; grid-template-columns: 40px minmax(0, 1fr); padding-top: 14px; border-top: 2px solid var(--ink); font-size: 17px; line-height: 1.45; }
.svw-notes li::before { content: counter(n); width: 28px; height: 28px; border: 1.5px solid var(--ink); border-radius: 50% !important; display: grid; place-items: center; font: 700 15px/1 var(--font); margin-top: -1px; }
.svw-tb { font-size: 15px; background: var(--surface); border: 1.5px solid var(--frame); }
.svw-brand { display: flex; align-items: center; gap: 12px; font-weight: 700; font-size: 24px; letter-spacing: -.01em; background: var(--strip); border-bottom: 1px solid var(--line-strong); padding: 12px 16px; }
.svw-brand .logo-mark { flex: none; display: inline-block; }
.svw-brand .logo-mark svg { width: 100%; height: 100%; display: block; }
.svw-key { display: grid; gap: 8px; padding: 14px 16px 16px; }
.svw-key p { display: flex; align-items: center; gap: 10px; font-size: 15px; color: var(--ink-2); }
.svw-key .sv-mark { width: 14px; height: 14px; vertical-align: 0; }
.svw-key b { color: var(--ink); font-weight: 700; }
.svw-signing { display: flex; align-items: center; gap: 10px; margin-top: 28px; font-weight: 600; }

/* Panels: framed like Instrument's panels; the heading sits on a rule in the colour of the stage it acts on (Actions blue, data mint, app yellow) */
.svw-panels { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; margin-top: clamp(56px, 8vw, 96px); }
.svw-panel { --sec: var(--ink); --sec-t: var(--ink); position: relative; min-width: 0; padding: clamp(20px, 3vw, 36px); background: var(--surface); }
.svw-panel.svw-act { --sec: var(--sv-blue); --sec-t: var(--sv-blue-ink); }
.svw-panel.svw-data { --sec: var(--sv-mint); --sec-t: var(--good); }
.svw-panel.svw-app { --sec: var(--sv-yellow); --sec-t: var(--sv-yellow-ink); }
.svw-panel::before { content: ""; position: absolute; inset: 0; border: 1.5px solid var(--frame); pointer-events: none; transition: clip-path .9s var(--sv-ease); }
.svw-panel.is-wide { grid-column: 1 / -1; }
.svw-dh { display: flex; align-items: center; gap: 12px; margin: 0 0 16px; font-weight: 700; font-size: clamp(24px, 2.4vw, 30px); line-height: 1.15; letter-spacing: -.01em; }
.svw-t { border-bottom: 4px solid var(--sec); padding-bottom: 4px; transition: clip-path .7s .25s var(--sv-ease); }
.svw-lede { color: var(--ink-2); max-width: 46ch; }
.svw h3 { margin: 0 0 6px; font-weight: 700; font-size: 20px; line-height: 1.25; }
.svw-sub { color: var(--ink-2); }
.svw-panel .svw-act { margin-top: 18px; }

/* Steps: numbered in the section's colour, side by side with a rule between */
.svw-steps { list-style: none; margin: 28px 0 0; padding: 0; counter-reset: n; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 40px; }
.svw-steps > li { counter-increment: n; display: grid; grid-template-columns: 42px minmax(0, 1fr); min-width: 0; }
.svw-steps > li > div { min-width: 0; }
.svw-steps > li + li { border-left: 1px solid var(--line-strong); padding-left: 40px; }
.svw-steps > li::before { content: counter(n); width: 30px; height: 30px; border: 1.5px solid var(--sec); color: var(--sec-t); border-radius: 50% !important; display: grid; place-items: center; font: 700 15px/1 var(--font); }
.svw-panel.svw-act .svw-steps > li::before { background: var(--sv-blue); color: #FFF; }
.svw-steps.is-done > li { grid-template-columns: minmax(0, 1fr); }
.svw-steps.is-done > li::before { content: none; }
.svw-signin { display: flex; flex-wrap: wrap; align-items: center; gap: 14px 18px; margin-top: 24px; }
.svw-or { font-size: 15px; font-weight: 600; color: var(--ink-2); }

/* Buttons: plain rectangles at touch size; the demo in yellow, open-by-name outlined in the data branch's mint */
.svw .btn { min-height: 44px; font-size: 16px; }
.svw .btn-sm { min-height: 36px; font-size: 14px; }
.svw .btn.svw-yel { background: var(--sv-yellow); border-color: var(--ink); color: #000; }
.svw .btn.svw-yel:hover { background: transparent; color: var(--ink); }
.svw .btn.svw-mint { border-color: var(--good); color: var(--good); }
.svw .btn.svw-mint:hover { background: var(--sv-mint); border-color: var(--good); color: #000; }

/* GitHub's page, sketched on a grey card with its own header strip */
.svw-mock { margin: 24px 0 0; background: var(--surface-2); border: 1px solid var(--line-strong); }
.svw-mock-title { font-weight: 600; font-size: 15px; color: var(--ink-2); background: var(--strip); border-bottom: 1px solid var(--line-strong); padding: 8px 16px; margin: 0 !important; }
.svw-mock > div { padding: 14px 16px 0; }
.svw-mock-k { font-weight: 600; font-size: 15px; margin-bottom: 6px; }
.svw-radio { display: flex; align-items: center; gap: 10px; font-size: 15px; margin: 5px 0; }
.svw-radio i { width: 14px; height: 14px; border: 1.5px solid var(--ink); background: var(--surface); display: inline-grid; place-items: center; flex: none; }
.svw-radio.is-on i::after { content: ""; width: 6px; height: 6px; border-radius: 50% !important; background: var(--ink); }
.svw-repo { display: inline-block; margin: 8px 0 0 24px; border: 1px solid var(--line-strong); background: var(--surface); padding: 2px 8px; font: 400 14px var(--mono); }
.svw-mock figcaption { padding: 12px 16px 14px; font-size: 15px; color: var(--ink-2); }

/* Fields */
.svw-field { display: block; font-size: 15px; font-weight: 600; margin: 18px 0 6px; }
.svw-row { display: flex; gap: 10px; flex-wrap: wrap; }
.svw-input { flex: 1 1 220px; min-width: 0; height: 44px; border: 1.5px solid var(--ink); background: var(--field); color: var(--ink); font: 400 15px var(--mono); padding: 0 12px; }
.svw-input::placeholder { color: var(--ink-3); }
.svw-input:focus { outline: 2px solid var(--focus); outline-offset: 2px; }
.svw-input[aria-invalid="true"] { border: 2px solid var(--bad); padding: 0 11.5px; }
.svw-help { font-size: 15px; color: var(--ink-2); margin-top: 10px !important; }
.svw-check { display: inline-flex; align-items: center; gap: 10px; margin-top: 14px; font-size: 16px; cursor: pointer; }
.svw-check input { appearance: none; -webkit-appearance: none; width: 18px; height: 18px; border: 1.5px solid var(--ink); margin: 0; display: grid; place-items: center; cursor: pointer; background: var(--surface); }
.svw-check input:checked::after { content: ""; width: 12px; height: 6px; border-left: 2px solid var(--ink); border-bottom: 2px solid var(--ink); transform: translateY(-2px) rotate(-45deg); }

/* The token's route: this browser to api.github.com, dashed while waiting, drawn in blue once it checks out */
.svw-link { display: block; width: 100%; max-width: 420px; height: auto; margin-top: 22px; overflow: visible; }
.svw-link text { font: 600 15px var(--font); fill: var(--ink-2); }
.svw-link .l-end { fill: none; stroke: var(--ink); stroke-width: 1.5; }
.svw-link .l-wait { stroke: var(--line-strong); stroke-width: 1.5; stroke-dasharray: 4 4; }
.svw-link .l-fill { stroke: var(--sv-blue); stroke-width: 5; stroke-dasharray: 1; stroke-dashoffset: 1; }
.svw-link.is-ok .l-fill { animation: svwDraw .7s var(--sv-ease) forwards; }
.svw:not(.is-still) .svw-link.is-busy .l-wait { stroke: var(--sv-blue); animation: svwMarch .6s linear infinite; }
.svw-verdict { display: flex; align-items: center; gap: 14px; min-height: 52px; margin-top: 10px; }
/* Success: a mint block with a black check, the same mark as Healthy in the key and the filled app box */
.svw-okmark { flex: none; display: block; width: 28px; height: 28px; background: var(--sv-mint); outline: 1px solid var(--dot-edge, #000); outline-offset: -1px; animation: svwBlock .35s .55s var(--sv-ease) both; }
.svw-okmark path { fill: none; stroke: #000; stroke-width: 2.6; stroke-linecap: square; stroke-dasharray: 1; stroke-dashoffset: 1; animation: svwDraw .3s .85s var(--sv-ease) forwards; }
.svw-status { min-height: 1.5em; margin-top: 10px !important; font-size: 16px; font-weight: 600; }
.svw-verdict .svw-status { margin-top: 0 !important; }
.svw-verdict .svw-status b { font-weight: 700; }
.svw-verdict .svw-sub { font-weight: 400; }
.svw-status.is-bad { color: var(--bad); display: flex; gap: 8px; align-items: baseline; }
.svw-status .sv-mark { vertical-align: -1px; }
.svw-acct { margin-top: 14px; border-top: 1px solid var(--line-strong); padding-top: 14px; }
.svw-abil { margin-top: 14px; display: flex; flex-direction: column; gap: 10px; }
.svw-picker { margin-top: 16px; }
.svw-note { display: flex; gap: 10px; align-items: flex-start; background: var(--surface-2); border: 1px solid var(--line-strong); padding: 12px 14px; font-size: 15px; margin-top: 4px; }
.svw-note .sv-mark { margin-top: 5px; }
.svw-note-act { display: block; margin-top: 8px; }

/* Recently opened and settings */
.svw-recent { display: flex; flex-wrap: wrap; gap: 10px; }
.svw-recent-btn { display: inline-flex; align-items: center; gap: 10px; min-height: 44px; padding: 0 14px; border: 1.5px solid var(--ink); background: var(--surface); color: var(--ink); font: 400 15px var(--mono); cursor: pointer; }
.svw-recent-btn:hover { border-color: var(--sv-blue); color: var(--sv-blue-ink); }
.svw-settings .appearance { display: flex; flex-wrap: wrap; gap: 28px 56px; padding: 0; margin-top: 6px; }
.svw-settings .pref-row { flex-direction: column; align-items: flex-start; gap: 8px; padding: 0; font-size: 15px; font-weight: 600; }
.svw-settings .seg-opt { min-height: 40px; min-width: 76px; font-size: 15px; justify-content: center; }
.svw-settings .pref-row .switch { margin: 8px 0; }

/* Motion: frame, then schematic, then the three points; the two run states cycle after. Once drawn (.is-drawn) it stays drawn on resize */
@keyframes svwDraw { to { stroke-dashoffset: 0; } }
@keyframes svwMarch { to { stroke-dashoffset: -8; } }
@keyframes svwBlock { from { transform: scale(0); } }
@keyframes svwEdgeX { from { transform: scaleX(0); } }
@keyframes svwEdgeY { from { transform: scaleY(0); } }
@keyframes svwInk { from { opacity: 0; } }
@keyframes svwLetter { from { clip-path: inset(0 100% 0 0); } to { clip-path: inset(0 0 0 0); } }
@keyframes svwGrow { from { transform: scaleX(0); } }
@keyframes svwCycA { 0% { opacity: 0; } 5%, 45% { opacity: 1; } 51%, 100% { opacity: 0; } }
@keyframes svwCycB { 0%, 50% { opacity: 0; } 56%, 95% { opacity: 1; } 100% { opacity: 0; } }
.svw-schem .s-cyc-a, .svw-schem .s-cyc-b { opacity: 0; }
.svw:not(.is-still) .s-cyc-a { animation: svwCycA 8s 3.6s infinite both; }
.svw:not(.is-still) .s-cyc-b { animation: svwCycB 8s 3.6s infinite both; }
.svw:not(.is-still):not(.is-drawn) .s-grow { transform-box: fill-box; transform-origin: left; animation: svwGrow .7s var(--t, 0s) var(--sv-ease) both; }
.svw:not(.is-still):not(.is-drawn) .svw-schem .s-d { stroke-dasharray: 1; stroke-dashoffset: 1; animation: svwDraw .55s var(--t, 0s) var(--sv-ease) forwards; }
.svw:not(.is-still):not(.is-drawn) .svw-schem .s-f { animation: svwInk .35s var(--t, 0s) both; }
.svw:not(.is-still):not(.is-drawn) .e-t, .svw:not(.is-still):not(.is-drawn) .e-b { animation: svwEdgeX .5s var(--sv-ease) both; }
.svw:not(.is-still):not(.is-drawn) .e-r, .svw:not(.is-still):not(.is-drawn) .e-l { animation: svwEdgeY .5s var(--sv-ease) both; }
.svw:not(.is-still):not(.is-drawn) .e-r { animation-delay: .35s; } .svw:not(.is-still):not(.is-drawn) .e-b { animation-delay: .7s; } .svw:not(.is-still):not(.is-drawn) .e-l { animation-delay: 1.05s; }
.svw:not(.is-still):not(.is-drawn) .svw-tick { animation: svwInk .3s 1.3s both; }
.svw:not(.is-still):not(.is-drawn) .svw-h1 { animation: svwLetter .9s .25s var(--sv-ease) both; }
.svw:not(.is-still):not(.is-drawn) .svw-notes li { animation: svwLetter .6s var(--t, 2.6s) var(--sv-ease) both; }
.svw:not(.is-still):not(.is-drawn) .svw-tb { animation: svwInk .5s 2.9s both; }
.svw:not(.is-still):not(.is-drawn) .svw-key { animation: svwInk .5s 3.4s both; }
.svw:not(.is-still) .svw-panel:not(.is-in)::before { clip-path: inset(0 100% 100% 0); }
.svw:not(.is-still) .svw-panel:not(.is-in) .svw-t { clip-path: inset(0 100% 0 0); }
.svw:not(.is-still) .svw-panel .svw-t, .svw:not(.is-still) .svw-panel::before { clip-path: inset(0 0 0 0); }
/* Reduced motion: everything in place at once, both run states side by side */
.svw.is-still *, .svw.is-still *::before, .svw.is-still *::after { animation: none !important; transition: none !important; }
.svw.is-still .s-cyc-a, .svw.is-still .s-cyc-b { opacity: 1; }
.svw.is-still .s-rm-hide { display: none; }
.svw.is-still .s-rm-only { display: inline; }
.svw.is-still .s-sh-a { transform: translateY(-9px); }
.svw.is-still .s-sh-b { transform: translateY(11px); }
.svw.is-still .svw-link .l-fill { stroke-dashoffset: 1; }
.svw.is-still .svw-link.is-ok .l-fill, .svw.is-still .svw-okmark path { stroke-dashoffset: 0; }

/* Between these widths the route sits in a half-width step and scales down, so its labels get bigger units */
@media (min-width: 901px) and (max-width: 1100px) { .svw-link text { font-size: 19px; } }
@media (min-width: 1101px) and (max-width: 1260px) { .svw-link text { font-size: 16.5px; } }
@media (max-width: 900px) {
  .svw-notes-row { grid-template-columns: 1fr; }
  .svw-tb { max-width: 400px; justify-self: end; width: 100%; }
  .svw-notes { grid-template-columns: 1fr; gap: 14px; }
  .svw-panels { grid-template-columns: 1fr; }
  .svw-steps { grid-template-columns: 1fr; gap: 32px; }
  .svw-steps > li + li { border-left: 0; padding-left: 0; border-top: 1px solid var(--line-strong); padding-top: 28px; }
}
/* Below this width the wide schematic would shrink its labels under 14px, so the stacked one takes over */
@media (max-width: 1100px) {
  .svw-schem.is-wide { display: none; }
  .svw-schem.is-tall { display: block; max-width: 380px; margin: 0 auto; }
  .svw-schem.is-tall .s-dim, .svw-schem.is-tall .s-sl { font-size: 16px; }
  .svw-schem.is-tall .s-cn { font-size: 15px; }
  .svw-schem.is-tall .s-lbl { font-size: 16.5px; }
}
@media (max-width: 640px) {
  .svw-frame { margin: 12px; padding: 16px; }
  .svw-panel { padding: 18px 16px 20px; }
  .svw-tb { justify-self: stretch; max-width: none; }
  .svw-steps > li { grid-template-columns: 40px minmax(0, 1fr); }
  .svw-settings .seg-opt { min-width: 64px; }
  /* The route drawing scales down here, so its two end labels get bigger units to stay readable */
  .svw-link text { font-size: 24px; }
}
`;document.getElementById("sv-welcome-sheet-css")||document.head.appendChild(Object.assign(document.createElement("style"),{id:"sv-welcome-sheet-css",textContent:es}));var ts=(e,t)=>`<path class="s-mk s-mk-bad" transform="translate(${e} ${t})" d="M0 -6.5 6.5 5H-6.5z"/>`,is=(e,t)=>`<g transform="translate(${e} ${t})"><circle class="s-mk s-mk-warn" r="6.5"/><path class="s-mk-g" d="M0 -3.8V0H2.8"/></g>`,as=(e,t)=>`<g transform="translate(${e} ${t})"><rect class="s-mk s-mk-ok" x="-5.5" y="-5.5" width="11" height="11"/><path class="s-mk-g" d="M-3 0l2 2.2 4-4.4"/></g>`,o=e=>`style="--t:${e}s" pathLength="1"`,r=e=>`style="--t:${e}s"`,u=(e,t,i,a,c,l,n,p)=>`<circle class="s-dt s-f" ${r(String(a))} cx="${e}" cy="${t}" r="2.4"/><path class="s-hl s-d" ${o(String(a))} d="M${e} ${t} ${c} ${l}"/><circle class="s-hl s-d" ${o((a+.1).toFixed(1))} cx="${n}" cy="${p}" r="12"/><text class="s-cn s-f" ${r((a+.2).toFixed(1))} x="${n}" y="${p+4.5}" text-anchor="middle">${i}</text>`,cs=`
<rect class="s-bx s-d" ${o(".9")} x="1" y="80" width="198" height="56"/>
<text class="s-lbl s-f" ${r("1.3")} x="100" y="113" text-anchor="middle">your repo</text>
<path class="s-live s-d" ${o("1.35")} d="M199 108H264"/><path class="s-ah s-f" ${r("1.6")} d="M258 103.5 267 108l-9 4.5z"/>
<rect class="s-bx s-d" ${o("1.4")} x="267" y="80" width="198" height="56"/>
<text class="s-lbl s-f" ${r("1.75")} x="366" y="113" text-anchor="middle">GitHub Actions run</text>
<path class="s-live s-d" ${o("1.8")} d="M465 108H530"/><path class="s-ah s-f" ${r("2.05")} d="M524 103.5 533 108l-9 4.5z"/>
<rect class="s-bx s-d" ${o("1.85")} x="533" y="80" width="198" height="56"/>
<text class="s-lbl s-f" ${r("2.2")} x="632" y="113" text-anchor="middle"><tspan class="s-mono">stackvitals-data</tspan> branch</text>
<path class="s-live s-d" ${o("2.25")} d="M731 108H798"/><path class="s-ah s-f" ${r("2.5")} d="M792 103.5 801 108l-9 4.5z"/>
<rect class="s-appfill" x="801" y="80" width="198" height="56"/>
<rect class="s-bx s-d" ${o("2.3")} x="801" y="80" width="198" height="56"/>
<text class="s-lbl s-applbl s-f" ${r("2.65")} x="900" y="113" text-anchor="middle">this app</text>
<path class="s-hl s-d" ${o("2.5")} d="M267 74V28M733 74V28"/>
<path class="s-hl s-d" ${o("2.65")} d="M267 36H392M608 36H733"/>
<path class="s-hl s-d" ${o("2.8")} d="M261 42 273 30M727 42 739 30"/>
<text class="s-dim s-f" ${r("2.85")} x="500" y="40" text-anchor="middle">every night, in Actions</text>
<path class="s-hl s-d" ${o("2.6")} d="M1 142V206M999 142V206"/>
<path class="s-hl s-d" ${o("2.75")} d="M1 198H372M628 198H999"/>
<path class="s-hl s-d" ${o("2.9")} d="M-5 204 7 192M993 204 1005 192"/>
<text class="s-dim s-f" ${r("2.95")} x="500" y="202" text-anchor="middle">no server, no account</text>
${u(366,136,1,3,386,158,396,167)}${u(632,136,2,3.1,652,158,662,167)}${u(900,136,3,3.2,920,158,930,167)}
<g class="s-rm-hide"><rect class="s-bar-bad s-cyc-a" x="268" y="131" width="196" height="4"/><rect class="s-bar-warn s-cyc-b" x="268" y="131" width="196" height="4"/></g>
<g class="s-rm-only"><rect class="s-bar-bad" x="268" y="131" width="98" height="4"/><rect class="s-bar-warn" x="366" y="131" width="98" height="4"/></g>
<g class="s-cyc-a"><g class="s-sh-a">${ts(426,167)}<text class="s-sl s-bad" x="440" y="171.5">1 flaky test</text></g></g>
<g class="s-cyc-b"><g class="s-sh-b">${is(426,167)}<text class="s-sl s-warn" x="440" y="171.5">1 slow check</text></g></g>
<rect class="s-bar-ok s-grow" ${r("3.3")} x="534" y="131" width="196" height="4"/>
<g class="s-f" ${r("3.5")}>${as(692,167)}<text class="s-sl s-ok" x="706" y="171.5">182 days kept</text></g>`,ps=`
<rect class="s-bx s-d" ${o(".9")} x="60" y="2" width="200" height="52"/>
<text class="s-lbl s-f" ${r("1.2")} x="160" y="33" text-anchor="middle">your repo</text>
<path class="s-live s-d" ${o("1.25")} d="M160 54V105"/><path class="s-ah s-f" ${r("1.45")} d="M155.5 99 160 108l4.5-9z"/>
<rect class="s-bx s-d" ${o("1.3")} x="60" y="108" width="200" height="52"/>
<text class="s-lbl s-f" ${r("1.6")} x="160" y="139" text-anchor="middle">GitHub Actions run</text>
<path class="s-live s-d" ${o("1.65")} d="M160 160V211"/><path class="s-ah s-f" ${r("1.85")} d="M155.5 205 160 214l4.5-9z"/>
<rect class="s-bx s-d" ${o("1.7")} x="60" y="214" width="200" height="52"/>
<text class="s-lbl s-f" ${r("2")} x="160" y="245" text-anchor="middle"><tspan class="s-mono s-mono-sm">stackvitals-data</tspan> branch</text>
<path class="s-live s-d" ${o("2.05")} d="M160 266V317"/><path class="s-ah s-f" ${r("2.25")} d="M155.5 311 160 320l4.5-9z"/>
<rect class="s-appfill" x="60" y="320" width="200" height="52"/>
<rect class="s-bx s-d" ${o("2.1")} x="60" y="320" width="200" height="52"/>
<text class="s-lbl s-applbl s-f" ${r("2.4")} x="160" y="351" text-anchor="middle">this app</text>
<path class="s-hl s-d" ${o("2.4")} d="M266 108H316M266 266H316"/>
<path class="s-hl s-d" ${o("2.55")} d="M308 108V266"/>
<path class="s-hl s-d" ${o("2.7")} d="M302 114 314 102M302 272 314 260"/>
<text class="s-dim s-f" ${r("2.75")} transform="translate(326 187) rotate(90)" text-anchor="middle">every night</text>
${u(60,134,1,2.8,34,134,22,134)}${u(60,240,2,2.9,34,240,22,240)}${u(60,346,3,3,34,346,22,346)}
<text class="s-dim s-f" ${r("3.2")} x="160" y="398" text-anchor="middle">no server, no account</text>
<g class="s-rm-hide"><rect class="s-bar-bad s-cyc-a" x="61" y="155" width="198" height="4"/><rect class="s-bar-warn s-cyc-b" x="61" y="155" width="198" height="4"/></g>
<g class="s-rm-only"><rect class="s-bar-bad" x="61" y="155" width="99" height="4"/><rect class="s-bar-warn" x="160" y="155" width="99" height="4"/></g>
<g class="s-cyc-a"><g class="s-sh-a">${ts(178,187)}<text class="s-sl s-bad" x="192" y="191.5">1 flaky test</text></g></g>
<g class="s-cyc-b"><g class="s-sh-b">${is(178,187)}<text class="s-sl s-warn" x="192" y="191.5">1 slow check</text></g></g>
<rect class="s-bar-ok s-grow" ${r("3.1")} x="61" y="261" width="198" height="4"/>
<g class="s-f" ${r("3.3")}>${as(178,293)}<text class="s-sl s-ok" x="192" y="297.5">182 days kept</text></g>`,$=typeof matchMedia=="function"?matchMedia("(prefers-reduced-motion: reduce)"):null;function ds(){let e=f(F),[t,i]=v(!!$?.matches);return g(()=>{if(!$)return;let a=()=>i($.matches);return $.addEventListener("change",a),()=>$.removeEventListener("change",a)},[]),e||t}function x({id:e,title:t,tone:i,wide:a,lede:c,children:l}){let n=I(null),[p,b]=v(!1);return g(()=>{let k=n.current;if(!k||typeof IntersectionObserver!="function"){b(!0);return}let h=new IntersectionObserver(d=>{d.some(w=>w.isIntersecting)&&(b(!0),h.disconnect())},{rootMargin:"0px 0px -12% 0px"});return h.observe(k),()=>h.disconnect()},[]),s("section",{ref:n,class:`svw-panel svw-${i}${a?" is-wide":""}${p?" is-in":""}`,"aria-labelledby":e,children:[s("h2",{class:"svw-dh",id:e,children:s("span",{class:"svw-t",children:t})}),c?s("p",{class:"svw-lede",children:c}):null,l]})}function ns({state:e}){return s("svg",{class:`svw-link is-${e}`,viewBox:"0 0 420 44","aria-hidden":"true",children:[s("rect",{class:"l-end",x:"0.5",y:"12.5",width:"10",height:"10"}),s("path",{class:"l-wait",d:"M11 17.5H409"}),s("path",{class:"l-fill",pathLength:1,d:"M11 17.5H409"}),s("rect",{class:"l-end",x:"409.5",y:"12.5",width:"10",height:"10"}),s("text",{x:"0",y:"40",children:"this browser"}),s("text",{x:"420",y:"40","text-anchor":"end",children:"api.github.com"})]})}var vs=()=>s("svg",{class:"svw-okmark",viewBox:"0 0 28 28","aria-hidden":"true",children:s("path",{pathLength:1,d:"M7.5 14.5 12 19l8.5-9"})});function hs(){let e=S(),[t,i]=v(!1),{text:a,busy:c,err:l,setErr:n,check:p,onInput:b}=U(t),k=d=>d.trim()?p(d):n("Paste the token first.");return s(z,{children:[e?s("div",{class:"svw-signin",children:[s(m,{variant:"filled",icon:"link",onClick:async()=>{e&&location.assign(await A(e,t&&R(),location.hash||"#/"))},children:"Sign in with GitHub"}),s("p",{class:"svw-or",children:"or use a token"})]}):null,s("ol",{class:"svw-steps",children:[s("li",{children:s("div",{children:[s("h3",{children:"Make a token on GitHub"}),s("p",{class:"svw-sub",children:"The page opens with the name, a 90-day expiry and the permissions filled in."}),s("div",{class:"svw-act",children:s(m,{variant:e?"tinted":"filled",href:D(),external:!0,iconEnd:"external",children:"Open GitHub's token page"})}),s("figure",{class:"svw-mock","aria-label":"On GitHub's page: Repository access, Only select repositories, then pick yours",children:[s("p",{class:"svw-mock-title",children:"What GitHub's page looks like"}),s("div",{"aria-hidden":"true",children:[s("div",{class:"svw-mock-k",children:"Repository access"}),s("div",{class:"svw-radio",children:[s("i",{class:"sv-round"}),"All repositories"]}),s("div",{class:"svw-radio is-on",children:[s("i",{class:"sv-round"}),"Only select repositories"]}),s("span",{class:"svw-repo",children:"owner/repo"})]}),s("figcaption",{children:["On GitHub's page, under ",s("b",{children:"Repository access"}),", pick the repos; GitHub can't fill that in. Then ",s("b",{children:"Generate token"})," and copy it."]})]})]})}),s("li",{children:s("div",{children:[s("h3",{children:"Paste it here"}),s("form",{noValidate:!0,onSubmit:d=>{d.preventDefault(),k(a)},children:[s("label",{class:"svw-field",for:"svw-tok",children:"GitHub token"}),s("div",{class:"svw-row",children:[s("input",{id:"svw-tok",class:"svw-input",type:"password",placeholder:"github_pat_\u2026",autoComplete:"off",spellcheck:!1,value:a,"aria-invalid":l?"true":void 0,"aria-describedby":"svw-tok-help svw-tok-status",onInput:d=>b(d.currentTarget.value)}),s(m,{type:"submit",variant:"filled",loading:c,children:"Check token"})]}),s("p",{class:"svw-help",id:"svw-tok-help",children:"Checked as soon as you paste. It goes only to api.github.com and stays in this browser."}),R()?s("label",{class:"svw-check",children:[s("input",{type:"checkbox",checked:t,onChange:d=>i(d.currentTarget.checked)})," Remember on this device"]}):s("p",{class:"svw-help",children:["Kept for this tab only: other sites under ",location.hostname," could read a remembered token. Use a custom domain or ",s("code",{children:"stackvitals ui"})," to remember it."]}),s(ns,{state:c?"busy":"wait"}),s("p",{class:"svw-status"+(l?" is-bad":""),id:"svw-tok-status",role:"status","aria-live":"polite",children:l?s(z,{children:[s("span",{class:"sv-mark sv-mark-bad","aria-hidden":"true"}),l]}):c?"Checking with api.github.com\u2026":""})]})]})})]})]})}function ws({a:e}){let t=f(N),i=t&&t.login===e.login?t:null;return s("ol",{class:"svw-steps is-done",children:[s("li",{children:s("div",{children:[s(ns,{state:"ok"}),s("div",{class:"svw-verdict",children:[s(vs,{}),s("p",{class:"svw-status",role:"status",children:["Connected as ",s("b",{children:e.login||"you"}),".",i?s("span",{class:"svw-sub",children:[" ",i.repos===null?"Classic token: every repo you can reach.":`${i.repos}${i.repos===100?"+":""} repo${i.repos===1?"":"s"} picked.`]}):null]})]}),s("div",{class:"svw-acct",children:s(X,{})}),i?s("div",{class:"svw-abil",children:[s("div",{class:"svw-ready",children:i.missing.length||i.repos===0?s(C,{tone:"watch",children:"Needs more"}):s(C,{tone:"good",children:"Ready"})}),s(j,{info:i})]}):null]})}),s("li",{children:s("div",{children:[s("h3",{children:"Pick a repo"}),s("p",{class:"svw-sub",children:"Set up ones open their dashboard; the others go to one-click setup."}),s("div",{class:"svw-picker",children:s(K,{onPick:ss})})]})})]})}function ms(){let{text:e,edit:t,busy:i,err:a,found:c,go:l}=Z();return s("form",{noValidate:!0,onSubmit:l,children:[s("label",{class:"svw-field",for:"svw-repo",children:"Repository"}),s("div",{class:"svw-row",children:[s("input",{id:"svw-repo",class:"svw-input",type:"text",placeholder:"owner/repo",value:e,autoComplete:"off",spellcheck:!1,"aria-invalid":a?"true":void 0,"aria-describedby":"svw-repo-err",onInput:n=>t(n.currentTarget.value)}),s(m,{type:"submit",variant:"tinted",class:"svw-mint",loading:i,children:"Open"})]}),s("p",{class:"svw-status is-bad",id:"svw-repo-err",role:"status","aria-live":"polite",children:a?s(z,{children:[s("span",{class:"sv-mark sv-mark-bad","aria-hidden":"true"}),a]}):null}),c?.res.kind==="none"?s("div",{class:"svw-note",role:"status",children:[s("span",{class:"sv-mark sv-mark-accent","aria-hidden":"true"}),s("span",{children:[s("b",{children:c.repo})," doesn't run StackVitals yet.",s("span",{class:"svw-note-act",children:s(m,{size:"sm",variant:"filled",onClick:()=>H(c.repo,c.res.private),children:"Set it up"})})]})]}):null,c?.res.kind==="missing"?s("div",{class:"svw-note",role:"status",children:[s("span",{class:"sv-mark sv-mark-watch","aria-hidden":"true"}),s("span",{children:["GitHub doesn't show ",s("b",{children:c.repo})," to visitors: the name is off, or it's private. Connect GitHub above to open private repos."]})]}):null]})}function E({a:e,signing:t,known:i}){let a=ds(),[c,l]=v(!1);return g(()=>{let n=setTimeout(()=>l(!0),4300);return()=>clearTimeout(n)},[]),s("div",{class:"svw"+(a?" is-still":"")+(c?" is-drawn":"")+(e?" is-ok":""),children:s("div",{class:"svw-frame",children:[s("span",{class:"svw-edge e-t"}),s("span",{class:"svw-edge e-r"}),s("span",{class:"svw-edge e-b"}),s("span",{class:"svw-edge e-l"}),s("span",{class:"svw-tick k-t"}),s("span",{class:"svw-tick k-r"}),s("span",{class:"svw-tick k-b"}),s("span",{class:"svw-tick k-l"}),s("main",{id:"main",tabIndex:-1,children:[s("section",{"aria-labelledby":"svw-hero",children:[s("h1",{id:"svw-hero",class:"svw-h1",children:"Know how your repo is really doing."}),s("figure",{class:"svw-flow","aria-label":"How it works: your repo runs a GitHub Actions job, which writes to the stackvitals-data branch, which this app reads"+(e?" (healthy: your GitHub token checked out).":" (it turns healthy once a token checks out).")+" Example states: the Actions run found 1 flaky test and 1 slow check; the data branch has 182 days of history kept.",children:[s("svg",{class:"svw-schem is-wide",viewBox:"0 0 1000 214","aria-hidden":"true",dangerouslySetInnerHTML:{__html:cs}}),s("svg",{class:"svw-schem is-tall",viewBox:"0 0 340 404","aria-hidden":"true",dangerouslySetInnerHTML:{__html:ps}})]}),s("div",{class:"svw-notes-row",children:[s("ol",{class:"svw-notes","aria-label":"What it does",children:[s("li",{style:"--t:3.3s",children:s("span",{children:"Finds flaky tests, slow checks and pull requests stuck waiting, with the evidence."})}),s("li",{style:"--t:3.45s",children:s("span",{children:"Keeps the history in your own repo, so trends and fixes are measured over months."})}),s("li",{style:"--t:3.6s",children:s("span",{children:"Runs in your GitHub Actions. Free, open source, no server, no account."})})]}),s("div",{class:"svw-tb",children:[s("div",{class:"svw-brand",children:[s(W,{size:34}),"StackVitals"]}),s("div",{class:"svw-key",children:[s("p",{children:[s("span",{class:"sv-mark sv-mark-good","aria-hidden":"true"}),s("span",{children:[s("b",{children:"Healthy"}),", kept and passing"]})]}),s("p",{children:[s("span",{class:"sv-mark sv-mark-watch","aria-hidden":"true"}),s("span",{children:[s("b",{children:"Slow"})," or waiting"]})]}),s("p",{children:[s("span",{class:"sv-mark sv-mark-bad","aria-hidden":"true"}),s("span",{children:[s("b",{children:"Failing"})," or flaky"]})]})]})]})]}),t?s("p",{class:"svw-signing",role:"status",children:[s("span",{class:"sv-mark sv-mark-watch","aria-hidden":"true"}),t]}):null]}),s("div",{class:"svw-panels",children:[e?s(x,{id:"svw-connect",title:"Your GitHub",tone:"act",wide:!0,lede:"Connected. Open a dashboard, or set StackVitals up in one click.",children:s(ws,{a:e})}):s(x,{id:"svw-connect",title:"Connect GitHub",tone:"act",wide:!0,lede:"See your repos, open private ones, and set StackVitals up in one click.",children:s(hs,{})}),s(x,{id:"svw-demo",title:"Try the demo",tone:"app",lede:"Three example repos with full data. Nothing to connect.",children:s("div",{class:"svw-act",children:s(m,{variant:"filled",class:"svw-yel",href:location.pathname+"?demo=1",children:"Open the demo"})})}),s(x,{id:"svw-open",title:e?"Or open a public repo":"Open a public repo",tone:"data",lede:"Reads its published data from its Pages site or data branch.",children:s(ms,{})}),i.length?s(x,{id:"svw-recent",title:"Recently opened",tone:"set",wide:!0,children:s("div",{class:"svw-recent",children:i.map(n=>s("button",{type:"button",class:"svw-recent-btn press",onClick:()=>y(n),children:[n.label,s("span",{"aria-hidden":"true",children:"\u2192"})]}))})}):null,s(x,{id:"svw-set",title:"Settings",tone:"set",wide:!0,children:s("div",{class:"svw-settings",children:s(_,{})})})]})]})]})})}export{E as a,Z as b,ss as c,rs as d};
