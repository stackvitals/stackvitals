"""One look for every module's static page: the header, the styles, table search and trend charts drawn from tables."""
import html
from pathlib import Path

MODULES = (("ci.html", "CI health"), ("flow.html", "Team Flow"), ("delivery.html", "Delivery"), ("insights.html", "Insights"),
           ("community.html", "Community"), ("portal.html", "Portal"), ("explore.html", "Explore"))
# Each printable page's section in the app (index.html#/<route>).
APP_ROUTES = {"ci.html": "ci", "flow.html": "prs", "delivery.html": "delivery", "insights.html": "insights",
              "community.html": "community", "portal.html": "portal", "explore.html": "explore"}
# Pinned with its integrity hash (from cdnjs), so a changed file never runs; without it the tables still show the numbers.
CHART_JS = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.5.1/chart.umd.min.js"
CHART_SRI = "sha512-WoViKhKD4qI2WruSZqv9+kvM4WfFhUMQCLN4QlDTt5aU56fLQy2gYoxWIqlEnXqJy/+Ac5q/hk1oWfqnMDhwMA=="

CSS = """:root{color-scheme:light dark;--bg:#fff;--fg:#1f2328;--mut:#59636e;--line:#d1d9e0;--bad:#cf222e;--warn:#9a6700;--ok:#1a7f37;--card:#f6f8fa;--link:#0969da;--c1:#0969da;--c2:#bf3989;--c3:#1a7f37}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--mut:#9198a1;--line:#3d444d;--bad:#ff7b72;--warn:#d29922;--ok:#3fb950;--card:#151b23;--link:#4493f8;--c1:#4493f8;--c2:#db61a2;--c3:#3fb950}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}a{color:var(--link)}
.top{border-bottom:1px solid var(--line);background:var(--card)}.top nav{max-width:1100px;margin:0 auto;padding:10px 16px;display:flex;flex-wrap:wrap;gap:4px 18px;align-items:center}
.top a.app{margin-left:auto}.top b{margin-right:6px}.top a{text-decoration:none;padding:2px 0}.top a[aria-current]{color:var(--fg);font-weight:600;border-bottom:2px solid var(--c1)}
main{max-width:1100px;margin:0 auto;padding:20px 16px}h1{font-size:22px;margin:0 0 4px;overflow-wrap:anywhere}h2{font-size:17px;margin:28px 0 8px}
.mut{color:var(--mut)}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}.card b{display:block;font-size:20px}
.tbl{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:600}td{overflow-wrap:break-word}.tag{font-size:12px;padding:1px 7px;border-radius:10px;border:1px solid currentColor;white-space:nowrap}
.nw{white-space:nowrap}.flaky,.broken{color:var(--bad)}.suspect{color:var(--warn)}.fixed,.ok{color:var(--ok)}footer{margin-top:32px;font-size:13px}
.find-bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:4px 0 8px}.find-bar input,.find-bar select{font:inherit;color:var(--fg);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:4px 8px}
.find-bar input{flex:1 1 200px;max-width:320px}.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
.chart{margin:0;border:1px solid var(--line);border-radius:8px;padding:10px 12px;min-width:0}.chart figcaption{font-weight:600;margin-bottom:6px}
.chart .box{position:relative;height:220px;display:none}.chart.drawn .box{display:block}.chart summary{color:var(--mut);font-size:13px;cursor:pointer}"""

# Plain JavaScript: a search box (and a filter for marked columns) on long tables, then each chart drawn from its table.
SCRIPT = r"""<script>(function(){
function rows(t){return [].filter.call(t.rows,function(r){return !r.querySelector('th')})}
function find(t){var body=rows(t);if(body.length<6)return;
var bar=document.createElement('div');bar.className='find-bar';
var q=document.createElement('input');q.type='search';q.placeholder='Filter rows';q.setAttribute('aria-label','Filter rows');bar.appendChild(q);
var picks=[];[].forEach.call(t.rows[0].cells,function(h,i){if(!h.hasAttribute('data-filter'))return;
var s=document.createElement('select'),seen={};s.setAttribute('aria-label','Filter by '+h.textContent);s.add(new Option('Any '+h.textContent.toLowerCase(),''));
body.forEach(function(r){var v=r.cells[i]?r.cells[i].textContent.trim():'';if(v&&!seen[v]){seen[v]=1;s.add(new Option(v,v))}});
picks.push([s,i]);bar.appendChild(s)});
var n=document.createElement('span');n.className='mut';n.setAttribute('aria-live','polite');bar.appendChild(n);
function apply(){var w=q.value.trim().toLowerCase(),shown=0;body.forEach(function(r){
var ok=!w||r.textContent.toLowerCase().indexOf(w)>=0;picks.forEach(function(p){if(p[0].value&&(r.cells[p[1]]?r.cells[p[1]].textContent.trim():'')!==p[0].value)ok=false});
r.hidden=!ok;shown+=ok?1:0});n.textContent=shown+' of '+body.length+' rows'}
q.addEventListener('input',apply);picks.forEach(function(p){p[0].addEventListener('change',apply)});
var at=t.closest('.tbl')||t;at.parentNode.insertBefore(bar,at);apply()}
function draw(){if(!window.Chart)return;var cs=getComputedStyle(document.documentElement),v=function(k){return cs.getPropertyValue(k).trim()};
Chart.defaults.color=v('--mut');Chart.defaults.borderColor=v('--line');Chart.defaults.font.family=getComputedStyle(document.body).fontFamily;
var colors=[v('--c1'),v('--c2'),v('--c3')];
document.querySelectorAll('figure[data-chart]').forEach(function(f){var t=f.querySelector('table'),body=rows(t),head=[].slice.call(t.rows[0].cells,1);
var sets=head.map(function(h,i){var c=colors[i%colors.length];return{label:h.textContent,borderColor:c,backgroundColor:c,spanGaps:false,cubicInterpolationMode:'monotone',pointRadius:2,
data:body.map(function(r){var x=r.cells[i+1].getAttribute('data-v');return x===null||x===''?null:+x}),text:body.map(function(r){return r.cells[i+1].textContent})}});
f.classList.add('drawn');try{new Chart(f.querySelector('canvas'),{type:f.getAttribute('data-chart'),data:{labels:body.map(function(r){return r.cells[0].textContent}),datasets:sets},
options:{animation:false,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},scales:{y:{beginAtZero:true,title:{display:!!f.dataset.y,text:f.dataset.y}}},
plugins:{legend:{display:sets.length>1},tooltip:{callbacks:{label:function(c){return c.dataset.label+': '+c.dataset.text[c.dataIndex]}}}}}});
f.querySelector('details').open=false}catch(e){f.classList.remove('drawn')}})}
document.addEventListener('DOMContentLoaded',function(){document.querySelectorAll('table.find').forEach(find);draw()})})()</script>"""


def present(docs: Path) -> set[str]:
    """The module pages (and the app) already in this docs folder, so the header never links to a page that isn't there."""
    return {name for name in [*(m for m, _ in MODULES), "index.html"] if (Path(docs) / name).exists()}


def nav(current: str | None, pages=(), root: str = "", app_route: str | None = None) -> str:
    links = []
    for name, label in MODULES:
        if name == current:
            links.append(f"<a href='{root}{name}' aria-current=page>{label}</a>")
        elif name in pages:
            links.append(f"<a href='{root}{name}'>{label}</a>")
    # These pages are the printable view; the app (index.html, when it's beside them) is where the decisions live.
    route = html.escape(app_route if app_route is not None else APP_ROUTES.get(current, ""), quote=True)
    app = "index.html" in pages
    brand = f"<a href='{root}index.html'>StackVitals</a>" if app else "StackVitals"
    return (f"<header class=top><nav aria-label='StackVitals pages'><b>{brand}</b>{''.join(links)}"
            + (f"<a class=app href='{root}index.html#/{route}'>Open in the app</a>" if app else "") + "</nav></header>")


def page(title: str, repo: str, current: str | None, sub: str, body: str, pages=(), root: str = "",
         app_route: str | None = None) -> str:
    """A whole page; `sub` and `body` are HTML the caller already escaped."""
    e = html.escape
    charts = (f"<script defer src='{CHART_JS}' integrity='{CHART_SRI}' crossorigin=anonymous referrerpolicy=no-referrer></script>"
              if "data-chart=" in body else "")
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{e(title)}: {e(repo)}</title><style>{CSS}</style>{charts}</head><body>{nav(current, pages, root, app_route)}<main>"
            f"<h1>{e(title)}: {e(repo)}</h1>" + (f"<div class=mut>{sub}</div>" if sub else "") + body + f"</main>{SCRIPT}</body></html>")


def _v(value) -> str:
    return "" if value is None else str(value)


def chart(title: str, x: str, labels: list[str], series: list[tuple[str, list]], y: str = "", fmt=str, kind: str = "line") -> str:
    """A chart drawn in the browser from the table below it, so its points are the table's numbers; no JavaScript, the table."""
    e = html.escape
    head = f"<tr><th>{e(x)}</th>" + "".join(f"<th>{e(name)}</th>" for name, _ in series) + "</tr>"
    rows = "".join(f"<tr><td>{e(str(label))}</td>" + "".join(
        f"<td data-v='{_v(values[i])}'>{e('-' if values[i] is None else fmt(values[i]))}</td>" for _, values in series) + "</tr>"
        for i, label in enumerate(labels))
    return (f"<figure class=chart data-chart={kind} data-y='{e(y)}'><figcaption>{e(title)}</figcaption>"
            f"<div class=box><canvas role=img aria-label='{e(title)}'></canvas></div>"
            f"<details open><summary>Numbers</summary><div class=tbl><table>{head}{rows}</table></div></details></figure>")


def charts(figures: list[str]) -> str:
    return f"<div class=charts>{''.join(figures)}</div>" if figures else ""
