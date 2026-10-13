"""Relatório HTML autocontido (um único arquivo, abre direto no navegador).

Segurança: todo texto vindo das fontes é escapado no Python (html.escape) e
só URLs http(s) viram links. O JavaScript embutido apenas filtra e ordena as
linhas já renderizadas; a página funciona (sem filtros) mesmo com JS desligado.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from jobcrawler.text import fold

AREAS = [  # ordem de exibição na barra
    ("security", "Segurança"),
    ("devops_sre_platform", "DevOps / SRE"),
    ("infra_cloud_sysadmin", "Infra / Cloud"),
]
AREA_NAMES = dict(AREAS)
REGION_NAMES = {"US": "EUA", "CA": "Canadá", "AU": "Austrália", "GLOBAL": "Global",
                "NÃO INFORMADO": "Não informado"}
REGION_ORDER = ["US", "CA", "AU", "GLOBAL"]
WORKPLACE_NAMES = {"hybrid": "Híbrido", "onsite": "Presencial", "remote": "Remoto"}


def _e(value) -> str:
    return html.escape(str(value or ""), quote=True)


def _safe_url(url: str) -> str:
    parsed = urlparse(url or "")
    return url if parsed.scheme in ("http", "https") and parsed.netloc else ""


def _regions(rec: dict) -> list[str]:
    raw = rec.get("regions") or ""
    if isinstance(raw, list):
        items = raw
    else:  # " | " é o separador atual; "," fica para bancos antigos (US, CA)
        items = raw.split("|") if "|" in raw else raw.split(",")
    return [r.strip() for r in items if r.strip()]


def _date_label(iso: str | None) -> str:
    if not iso:
        return "data não informada"
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y")
    except ValueError:
        return iso[:10]


def _junior_label(signal: str) -> str:
    """'título: 'junior'' -> '“junior” no título' (texto mais natural no relatório)."""
    m = re.match(r"(título|fonte|descrição): '(.+)'$", signal or "")
    if not m:
        return signal or ""
    where, term = m.groups()
    return {"título": f"“{term}” no título", "fonte": f"nível “{term}” na fonte",
            "descrição": f"“{term}” na descrição"}[where]


def _row(rec: dict) -> str:
    area = rec.get("area") or ""
    regions = _regions(rec)
    is_new = rec.get("is_new") in (True, "sim", 1)
    url = _safe_url(rec.get("url", ""))
    title = _e(rec.get("title"))
    title_html = (f'<a class="title" href="{_e(url)}" target="_blank" rel="noopener noreferrer">{title}</a>'
                  if url else f'<span class="title">{title}</span>')
    search = fold(" ".join(str(rec.get(k) or "") for k in
                           ("title", "company", "location", "tags", "source", "description")))

    facts = []
    if rec.get("location"):
        facts.append(f'<span class="fact"><span class="k">Local</span> {_e(rec["location"])}</span>')
    if rec.get("timezone"):
        facts.append(f'<span class="fact"><span class="k">Fuso</span> {_e(rec["timezone"])}</span>')
    if rec.get("salary"):
        facts.append(f'<span class="fact"><span class="k">Salário</span> {_e(rec["salary"])}</span>')
    if rec.get("junior_signal"):
        facts.append(f'<span class="fact"><span class="k">Júnior por</span> '
                     f'{_e(_junior_label(rec["junior_signal"]))}</span>')

    region_tags = "".join(f'<span class="region">{_e(REGION_NAMES.get(r, r))}</span>' for r in regions)
    excerpt = (rec.get("description") or "").strip()
    details = (f'<details class="excerpt"><summary>Trecho da descrição</summary>'
               f'<p>{_e(excerpt[:600])}{"…" if len(excerpt) > 600 else ""}</p></details>'
               if excerpt else "")

    return f"""
<li class="job" data-area="{_e(area)}" data-regions="{_e('|'.join(regions))}"
    data-new="{'1' if is_new else '0'}" data-date="{_e(rec.get('published_at') or '')}"
    data-search="{_e(search)}">
  <div class="job-head">
    {title_html}
    {'<span class="new">Nova</span>' if is_new else ''}
    <time datetime="{_e(rec.get('published_at') or '')}">{_e(_date_label(rec.get('published_at')))}</time>
  </div>
  <div class="job-sub">
    <span class="company">{_e(rec.get('company'))}</span>
    <span class="area-name">{_e(AREA_NAMES.get(area, area))}</span>
    {f'<span class="wp wp-{_e(rec.get("workplace"))}">{_e(WORKPLACE_NAMES[rec.get("workplace")])}</span>'
     if rec.get("workplace") in WORKPLACE_NAMES else ''}
    {region_tags}
  </div>
  {'<div class="facts">' + ''.join(facts) + '</div>' if facts else ''}
  {f'<p class="note">{_e(rec["note"])}</p>' if rec.get("note") else ''}
  <div class="job-foot">
    <span class="source">via {_e(rec.get('source'))}</span>
    {details}
  </div>
</li>"""


def _area_bar(records: list[dict]) -> str:
    segs = []
    for key, name in AREAS:
        n = sum(1 for r in records if r.get("area") == key)
        if not n:
            continue
        segs.append(
            f'<button type="button" class="seg" data-area="{key}" aria-pressed="false" '
            f'style="flex-grow:{n}" title="Filtrar por {_e(name)}">'
            f'<span class="seg-name">{_e(name)}</span><span class="seg-n">{n}</span></button>')
    if not segs:
        return ""
    return (f'<div class="areabar" role="group" aria-label="Filtrar por área '
            f'({len(records)} vagas no total)">{"".join(segs)}</div>')


def _run_details(meta: dict) -> str:
    per_source = meta.get("per_source") or {}
    errors = meta.get("errors") or {}
    if not per_source and not errors:
        return ""
    rows = "".join(
        f"<tr><td>{_e(name)}</td><td>{st.get('fetched', 0)}</td><td>{st.get('accepted', 0)}</td>"
        f"<td>{st.get('errors', 0)}</td></tr>"
        for name, st in sorted(per_source.items()))
    err_items = "".join(f"<li><strong>{_e(src)}</strong>: {_e(msg)}</li>"
                        for src, msgs in errors.items() for msg in msgs)
    stages = meta.get("rejection_stages") or {}
    stage_names = {"age": "antigas", "workplace": "modalidade", "remote": "não remotas", "area": "fora da área",
                   "seniority_title": "senioridade no título", "seniority_source": "nível da fonte",
                   "seniority_description": "nível na descrição", "experience": "anos de experiência",
                   "junior_marker": "sem marcador júnior", "region": "localização"}
    stage_txt = ", ".join(f"{stage_names.get(k, k)}: {v}" for k, v in
                          sorted(stages.items(), key=lambda kv: -kv[1]))
    return f"""
<details class="run">
  <summary>Detalhes da execução</summary>
  <p>Coletadas {meta.get('fetched', 0)} vagas, {meta.get('unique', 0)} únicas depois de remover duplicatas.</p>
  {f'<p>Descartadas por: {_e(stage_txt)}.</p>' if stage_txt else ''}
  <table><thead><tr><th>Fonte</th><th>Coletadas</th><th>Aceitas</th><th>Erros</th></tr></thead>
  <tbody>{rows}</tbody></table>
  {f'<p>Erros:</p><ul class="errors">{err_items}</ul>' if err_items else ''}
</details>"""


def render_html(records: list[dict], meta: dict | None = None) -> str:
    meta = meta or {}
    texts = {"title": "Vagas encontradas", "scope": "", "footer": "Cada link abre a vaga na fonte original.",
             **{k: v for k, v in (meta.get("report") or {}).items() if v}}
    records = sorted(records, key=lambda r: r.get("published_at") or "", reverse=True)
    n_new = sum(1 for r in records if r.get("is_new") in (True, "sim", 1))
    generated = meta.get("generated_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        gen_label = datetime.fromisoformat(generated).astimezone().strftime("%d/%m/%Y às %H:%M")
    except ValueError:
        gen_label = generated

    if records:
        word = "vaga" if len(records) == 1 else "vagas"
        new_txt = ("nenhuma nova desde a última execução" if n_new == 0
                   else f"{n_new} {'nova' if n_new == 1 else 'novas'} desde a última execução")
        lede = f"{len(records)} {word} {'encontrada' if len(records) == 1 else 'encontradas'}, {new_txt}."
    else:
        lede = "Nenhuma vaga passou nos filtros desta vez."

    # Chips de região/cidade: códigos conhecidos primeiro (US, CA...), depois as
    # cidades por número de vagas, e "não informado" por último.
    counts: dict[str, int] = {}
    for rec in records:
        for r in _regions(rec):
            counts[r] = counts.get(r, 0) + 1
    known = [r for r in REGION_ORDER if r in counts]
    others = sorted((r for r in counts if r not in REGION_ORDER), key=lambda r: (
        r.startswith("NÃO INFORMADO") or "não informada" in r, -counts[r], r))
    region_buttons = "".join(
        f'<button type="button" class="chip" data-region="{_e(r)}" aria-pressed="false">'
        f'{_e(REGION_NAMES.get(r, r))} <span class="n">{counts[r]}</span></button>'
        for r in known + others) if len(counts) > 1 else ""

    if records:
        body = f'<ol class="queue" id="queue">{"".join(_row(r) for r in records)}</ol>'
    else:
        body = ('<div class="empty"><p>Nenhuma vaga passou nos filtros nesta execução.</p>'
                '<p>Para ver por que cada vaga foi descartada, rode '
                '<code>python -m jobcrawler run --explain</code> e abra '
                '<code>output/rejections.csv</code>.</p></div>')

    return TEMPLATE.format(
        lede=_e(lede),
        heading=_e(texts["title"]),
        scope=_e(texts["scope"]),
        footer=_e(texts["footer"]),
        generated=_e(gen_label),
        title_suffix=f" ({n_new} novas)" if n_new else "",
        area_bar=_area_bar(records),
        region_buttons=region_buttons,
        toolbar_hidden="" if records else " hidden",
        body=body,
        run_details=_run_details(meta),
    )


def write_html(path: str | Path, records: list[dict], meta: dict | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(records, meta), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Template (chaves literais de CSS/JS duplicadas por causa do str.format)
# ---------------------------------------------------------------------------
TEMPLATE = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{heading}{title_suffix}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">
<style>
:root {{
  --paper: #EEF2F6;
  --surface: #FFFFFF;
  --ink: #16213A;
  --muted: #56617A;
  --line: #D5DCE6;
  --focus: #2F5BD3;
  --sec: #A3245E;
  --devops: #0E7479;
  --infra: #A8620C;
  --new-bg: #16213A;
  --new-ink: #FFFFFF;
  --note-bg: #FFF3D6;
  --note-ink: #5C3B00;
  color-scheme: light;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --paper: #0F1A2E;
    --surface: #16233B;
    --ink: #E6ECF5;
    --muted: #9AA8BF;
    --line: #2A3A57;
    --focus: #8DB0FF;
    --sec: #E86FA6;
    --devops: #4CC3C8;
    --infra: #E7A24A;
    --new-bg: #E6ECF5;
    --new-ink: #0F1A2E;
    --note-bg: #3A2E14;
    --note-ink: #F5D99A;
    color-scheme: dark;
  }}
}}
* {{ box-sizing: border-box; }}
html {{ -webkit-text-size-adjust: 100%; }}
body {{
  margin: 0; background: var(--paper); color: var(--ink);
  font: 16px/1.5 "Atkinson Hyperlegible", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  font-variant-numeric: tabular-nums;
}}
.wrap {{ max-width: 980px; margin: 0 auto; padding: 40px 20px 64px; }}
header h1 {{ font-size: 2rem; line-height: 1.15; margin: 0 0 8px; letter-spacing: -0.01em; }}
.lede {{ font-size: 1.125rem; margin: 0 0 4px; max-width: 60ch; }}
.stamp {{ color: var(--muted); margin: 0 0 28px; font-size: .9375rem; }}

/* Barra de áreas: proporção + filtro */
.areabar {{ display: flex; gap: 3px; height: 56px; margin-bottom: 20px; }}
.seg {{
  flex-basis: 0; min-width: 160px; white-space: nowrap; border: 0; border-radius: 4px; cursor: pointer;
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 0 14px; color: #fff; font: inherit; font-weight: 700; text-align: left;
  transition: opacity .15s;
}}
.seg[data-area="security"] {{ background: var(--sec); }}
.seg[data-area="devops_sre_platform"] {{ background: var(--devops); }}
.seg[data-area="infra_cloud_sysadmin"] {{ background: var(--infra); }}
@media (prefers-color-scheme: dark) {{ .seg {{ color: #0F1A2E; }} }}
.seg-n {{ font-size: 1.375rem; }}
.areabar.filtering .seg[aria-pressed="false"] {{ opacity: .35; }}

/* Barra de ferramentas */
.toolbar {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 8px; }}
.search {{
  flex: 1 1 100%; font: inherit; color: var(--ink); background: var(--surface);
  border: 1px solid var(--line); border-radius: 6px; padding: 9px 12px;
}}
.chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
.chip, .toggle, select {{
  font: inherit; font-size: .9375rem; color: var(--ink); background: var(--surface);
  border: 1px solid var(--line); border-radius: 999px; padding: 6px 12px; cursor: pointer;
}}
select {{ border-radius: 6px; }}
.chip[aria-pressed="true"], .toggle[aria-pressed="true"] {{
  background: var(--ink); color: var(--paper); border-color: var(--ink);
}}
.count {{ color: var(--muted); font-size: .9375rem; margin: 8px 0 12px; }}
.clear {{ font: inherit; font-size: .9375rem; background: none; border: 0; color: var(--focus);
  text-decoration: underline; cursor: pointer; padding: 0; margin-left: 6px; }}
:focus-visible {{ outline: 3px solid var(--focus); outline-offset: 2px; }}

/* Fila de vagas */
.queue {{ list-style: none; margin: 0; padding: 0; background: var(--surface);
  border: 1px solid var(--line); border-radius: 6px; overflow: hidden; }}
.job {{ position: relative; padding: 16px 18px 14px 24px; border-top: 1px solid var(--line); }}
.job:first-child {{ border-top: 0; }}
.job::before {{ content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 6px; background: var(--line); }}
.job[data-area="security"]::before {{ background: var(--sec); }}
.job[data-area="devops_sre_platform"]::before {{ background: var(--devops); }}
.job[data-area="infra_cloud_sysadmin"]::before {{ background: var(--infra); }}
.job-head {{ display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }}
.title {{ font-size: 1.125rem; font-weight: 700; color: var(--ink); text-decoration: none; }}
a.title:hover {{ text-decoration: underline; text-underline-offset: 3px; }}
.new {{ background: var(--new-bg); color: var(--new-ink); font-size: .8125rem; font-weight: 700;
  border-radius: 3px; padding: 1px 7px; }}
.job-head time {{ margin-left: auto; color: var(--muted); font-size: .9375rem; white-space: nowrap; }}
.job-sub {{ display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: center; margin-top: 2px; }}
.company {{ font-weight: 700; }}
.area-name {{ color: var(--muted); }}
.wp {{ font-size: .8125rem; font-weight: 700; color: var(--ink); }}
.chip .n {{ color: var(--muted); font-size: .8125rem; }}
.chip[aria-pressed="true"] .n {{ color: inherit; }}
.region {{ font-size: .8125rem; border: 1px solid var(--line); border-radius: 3px; padding: 0 6px; }}
.facts {{ display: flex; flex-wrap: wrap; gap: 4px 18px; margin-top: 8px; font-size: .9375rem; }}
.k {{ color: var(--muted); }}
.note {{ margin: 8px 0 0; padding: 6px 10px; font-size: .9375rem; max-width: 72ch;
  background: var(--note-bg); color: var(--note-ink); border-radius: 4px; }}
.job-foot {{ display: flex; flex-wrap: wrap; gap: 6px 16px; align-items: baseline; margin-top: 8px;
  font-size: .875rem; color: var(--muted); }}
.excerpt summary {{ cursor: pointer; color: var(--focus); }}
.excerpt p {{ color: var(--ink); max-width: 72ch; margin: 6px 0 0; font-size: .9375rem; }}
.job[hidden] {{ display: none; }}

.empty {{ background: var(--surface); border: 1px dashed var(--line); border-radius: 6px; padding: 24px; }}
.empty p {{ margin: 0 0 8px; max-width: 64ch; }}
code {{ font-size: .9em; background: var(--paper); padding: 1px 5px; border-radius: 3px; }}

.run {{ margin-top: 32px; color: var(--muted); font-size: .9375rem; }}
.run summary {{ cursor: pointer; color: var(--ink); }}
.run table {{ border-collapse: collapse; margin: 8px 0; }}
.run th, .run td {{ text-align: left; padding: 4px 16px 4px 0; border-bottom: 1px solid var(--line); }}
.run td:not(:first-child), .run th:not(:first-child) {{ text-align: right; }}
.errors {{ padding-left: 18px; }}
footer {{ margin-top: 24px; color: var(--muted); font-size: .875rem; max-width: 72ch; }}

@media (max-width: 640px) {{
  .wrap {{ padding: 24px 16px 48px; }}
  header h1 {{ font-size: 1.625rem; }}
  .areabar {{ flex-direction: column; height: auto; }}
  .seg {{ min-height: 44px; flex-grow: 0 !important; }}
  .job-head time {{ margin-left: 0; width: 100%; }}
}}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; }} }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>{heading}</h1>
    <p class="lede">{lede}</p>
    <p class="stamp">Gerado em {generated}. {scope}</p>
  </header>

  {area_bar}

  <div class="toolbar"{toolbar_hidden}>
    <input class="search" id="q" type="search" placeholder="Buscar por cargo, empresa, tecnologia…" aria-label="Buscar vagas">
    <div class="chips" role="group" aria-label="Filtrar por local">{region_buttons}</div>
    <button type="button" class="toggle" id="only-new" aria-pressed="false">Só novas</button>
    <select id="sort" aria-label="Ordenar">
      <option value="desc">Mais recentes primeiro</option>
      <option value="asc">Mais antigas primeiro</option>
    </select>
  </div>
  <p class="count" id="count" aria-live="polite"></p>

  {body}

  {run_details}

  <footer>{footer}</footer>
</div>

<script>
(function () {{
  var queue = document.getElementById("queue");
  if (!queue) return;
  var jobs = Array.prototype.slice.call(queue.children);
  var q = document.getElementById("q");
  var onlyNew = document.getElementById("only-new");
  var sort = document.getElementById("sort");
  var count = document.getElementById("count");
  var areabar = document.querySelector(".areabar");
  var areaBtns = Array.prototype.slice.call(document.querySelectorAll(".seg"));
  var regionBtns = Array.prototype.slice.call(document.querySelectorAll(".chip"));

  function fold(s) {{
    return (s || "").normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").toLowerCase();
  }}
  function pressed(btns) {{
    return btns.filter(function (b) {{ return b.getAttribute("aria-pressed") === "true"; }});
  }}
  function toggle(btn) {{
    btn.setAttribute("aria-pressed", btn.getAttribute("aria-pressed") === "true" ? "false" : "true");
    apply();
  }}

  // Datas relativas ("hoje", "há 3 dias"), mantendo a data exata no title
  var now = Date.now();
  jobs.forEach(function (li) {{
    var t = li.querySelector("time");
    var iso = li.getAttribute("data-date");
    if (!t || !iso) return;
    var days = Math.floor((now - Date.parse(iso)) / 86400000);
    if (isNaN(days)) return;
    t.title = t.textContent;
    t.textContent = days <= 0 ? "hoje" : days === 1 ? "ontem" : "há " + days + " dias";
  }});

  function apply() {{
    var terms = fold(q.value).split(/\\s+/).filter(Boolean);
    var areas = pressed(areaBtns).map(function (b) {{ return b.dataset.area; }});
    var regions = pressed(regionBtns).map(function (b) {{ return b.dataset.region; }});
    var newOnly = onlyNew.getAttribute("aria-pressed") === "true";
    if (areabar) areabar.classList.toggle("filtering", areas.length > 0);

    var shown = 0;
    jobs.forEach(function (li) {{
      var hay = li.dataset.search;
      var jobRegions = li.dataset.regions.split("|");
      var ok = terms.every(function (t) {{ return hay.indexOf(t) !== -1; }})
        && (!areas.length || areas.indexOf(li.dataset.area) !== -1)
        && (!regions.length || regions.some(function (r) {{ return jobRegions.indexOf(r) !== -1; }}))
        && (!newOnly || li.dataset.new === "1");
      li.hidden = !ok;
      if (ok) shown++;
    }});
    var filtered = terms.length || areas.length || regions.length || newOnly;
    count.textContent = "";
    if (filtered) {{
      count.append(shown === 0 ? "Nenhuma vaga com esses filtros." :
        "Mostrando " + shown + " de " + jobs.length + " vagas.");
      var clear = document.createElement("button");
      clear.type = "button"; clear.className = "clear"; clear.textContent = "Limpar filtros";
      clear.onclick = function () {{
        q.value = "";
        areaBtns.concat(regionBtns, [onlyNew]).forEach(function (b) {{ b.setAttribute("aria-pressed", "false"); }});
        apply(); q.focus();
      }};
      count.append(clear);
    }}
  }}

  function resort() {{
    var dir = sort.value === "asc" ? 1 : -1;
    jobs.sort(function (a, b) {{
      return dir * ((a.dataset.date || "").localeCompare(b.dataset.date || ""));
    }});
    jobs.forEach(function (li) {{ queue.appendChild(li); }});
  }}

  q.addEventListener("input", apply);
  onlyNew.addEventListener("click", function () {{ toggle(onlyNew); }});
  areaBtns.forEach(function (b) {{ b.addEventListener("click", function () {{ toggle(b); }}); }});
  regionBtns.forEach(function (b) {{ b.addEventListener("click", function () {{ toggle(b); }}); }});
  sort.addEventListener("change", resort);
  apply();
}})();
</script>
</body>
</html>
"""
