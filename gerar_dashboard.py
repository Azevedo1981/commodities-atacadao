"""
============================================================
DASHBOARD COMMODITIES CEPEA — Atacadão
gerar_dashboard.py  (v3 · sparklines 4 semanas)

Fluxo:
  1. Lê precos.json  (histórico de semanas)
  2. Calcula variação semana vs anterior
  3. Gera sparkline SVG de tendência (4 semanas) por commodity
  4. Publica em docs/index.html  →  GitHub Pages
  5. Envia e-mail HTML com tabela comparativa

Uso diário:
  1. Adicione nova entrada em precos.json
  2. python gerar_dashboard.py
============================================================
"""
import json, os, subprocess, smtplib, sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

BASE        = Path(__file__).parent
PRECOS_FILE = BASE / "precos.json"
CONFIG_FILE = BASE / "config.json"
OUTPUT_HTML = BASE / "docs" / "index.html"
N_SEMANAS   = 4   # quantas semanas exibir no gráfico

# ── Config ───────────────────────────────────────────────────
def carregar_config():
    if not CONFIG_FILE.exists():
        modelo = {
            "email": {
                "remetente": "seu_email@gmail.com",
                "senha_app": "xxxx xxxx xxxx xxxx",
                "_dica": "myaccount.google.com/apppasswords",
                "destinatarios": ["diretor@atacadao.com.br"],
                "assunto_prefixo": "📊 Commodities da Semana"
            },
            "github": {"usuario": "seu_usuario", "repositorio": "commodities-atacadao"}
        }
        CONFIG_FILE.write_text(json.dumps(modelo, ensure_ascii=False, indent=2))
        print("✅ config.json criado. Preencha e rode novamente.")
        sys.exit(0)
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

# ── Preços ───────────────────────────────────────────────────
def carregar_dados():
    dados     = json.loads(PRECOS_FILE.read_text(encoding="utf-8"))
    historico = dados["historico"]
    # pega as últimas N semanas
    janela    = historico[-N_SEMANAS:]
    atual     = janela[-1]
    anterior  = janela[-2] if len(janela) >= 2 else None
    return janela, atual, anterior

# ── Sparkline SVG ────────────────────────────────────────────
def sparkline_svg(valores, cor, w=80, h=32):
    """
    Gera um SVG inline de linha (sparkline) para os valores fornecidos.
    Inclui área de preenchimento semitransparente e ponto final destacado.
    """
    if len(valores) < 2:
        return ""
    mn, mx = min(valores), max(valores)
    rng    = mx - mn if mx != mn else 1.0
    pad    = 3

    def px(i):  # x
        return pad + (i / (len(valores) - 1)) * (w - 2 * pad)
    def py(v):  # y (invertido: menor valor = mais alto)
        return pad + (1 - (v - mn) / rng) * (h - 2 * pad)

    pts       = [(px(i), py(v)) for i, v in enumerate(valores)]
    polyline  = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    # área de preenchimento (fecha pelo fundo)
    area_pts  = polyline + f" {pts[-1][0]:.1f},{h} {pts[0][0]:.1f},{h}"

    # cor mais clara para o fill
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block">'
        f'<polygon points="{area_pts}" fill="{cor}" fill-opacity="0.12"/>'
        f'<polyline points="{polyline}" fill="none" stroke="{cor}" '
        f'stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="2.8" '
        f'fill="{cor}"/>'
        f'</svg>'
    )

# ── Variações & enriquecimento ───────────────────────────────
def enriquecer(janela, atual, anterior):
    # índice de valor por semana  {id: [v_s1, v_s2, v_s3, v_s4]}
    serie = {}
    for semana in janela:
        for c in semana["commodities"]:
            serie.setdefault(c["id"], []).append(c["valor_num"])

    idx_ant = {}
    if anterior:
        for c in anterior["commodities"]:
            idx_ant[c["id"]] = c["valor_num"]

    resultado = []
    for c in atual["commodities"]:
        c = dict(c)
        vant = idx_ant.get(c["id"])

        # variação semanal
        if vant and vant != 0:
            pct = ((c["valor_num"] - vant) / vant) * 100
            sinal = "+" if pct >= 0 else ""
            c["var_sem_pct"]  = pct
            c["var_sem_str"]  = f"{sinal}{pct:.2f}%".replace(".", ",")
            c["tend_sem"]     = "alta" if pct > 0.05 else "baixa" if pct < -0.05 else "neutro"
            c["preco_ant"]    = _fmt_preco(vant)
        else:
            c["var_sem_pct"]  = 0.0
            c["var_sem_str"]  = "—"
            c["tend_sem"]     = "neutro"
            c["preco_ant"]    = "—"

        # variação vs 4 semanas atrás
        serie_id = serie.get(c["id"], [])
        if len(serie_id) >= 2:
            v4 = serie_id[0]
            pct4 = ((c["valor_num"] - v4) / v4) * 100 if v4 else 0
            sinal4 = "+" if pct4 >= 0 else ""
            c["var_4s_str"] = f"{sinal4}{pct4:.2f}%".replace(".", ",")
            c["tend_4s"]    = "alta" if pct4 > 0.05 else "baixa" if pct4 < -0.05 else "neutro"
        else:
            c["var_4s_str"] = "—"
            c["tend_4s"]    = "neutro"

        # sparkline
        c["spark_svg"]   = sparkline_svg(serie_id, c.get("cor", "#16a34a"))
        c["serie"]       = serie_id
        c["datas_serie"] = [s["data"] for s in janela]

        resultado.append(c)
    return resultado

def _fmt_preco(v):
    if v >= 1000:
        s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R${s}"
    return f"R$ {v:.2f}".replace(".", ",")

# ── HTML ─────────────────────────────────────────────────────
def gerar_html(janela, atual, anterior, commodities):
    data_atual = atual["data"]
    data_ant   = anterior["data"] if anterior else "—"
    datas      = [s["data"] for s in janela]
    tem_hist   = anterior is not None

    def cls(t):  return {"alta":"alta","baixa":"baixa"}.get(t,"neutro")
    def seta(t): return {"alta":"▲","baixa":"▼"}.get(t,"—")

    # ── CARDS ──
    cards = ""
    for c in commodities:
        t_sem = c["tend_sem"]
        t_4s  = c["tend_4s"]

        comp = ""
        if tem_hist:
            comp = f"""
        <div class="comp-bloco">
          <div class="comp-row">
            <span class="comp-lbl">Semana ant.</span>
            <span class="comp-val">{c['preco_ant']}</span>
            <span class="badge-sm {cls(t_sem)}">{seta(t_sem)} {c['var_sem_str']}</span>
          </div>
          <div class="comp-row" style="margin-top:3px">
            <span class="comp-lbl">vs 4 semanas</span>
            <span class="badge-sm {cls(t_4s)}">{seta(t_4s)} {c['var_4s_str']}</span>
          </div>
        </div>"""

        # rótulos das datas abaixo do sparkline
        n = len(c['datas_serie'])
        rotulos = ""
        if n >= 2:
            rotulos = (
                f'<div class="spark-datas">'
                f'<span>{c["datas_serie"][0]}</span>'
                f'<span>{c["datas_serie"][-1]}</span>'
                f'</div>'
            )

        cards += f"""
      <a href="{c['cepea']}" target="_blank" class="card" style="--cor:{c['cor']}">
        <div class="card-topo"></div>
        <div class="card-head">
          <span class="card-icon">{c['icon']}</span>
          <div class="card-spark">
            {c['spark_svg']}
            {rotulos}
          </div>
        </div>
        <div class="card-nome">{c['nome']}</div>
        <div class="card-preco">{c['preco']}</div>
        <div class="card-unidade">{c['unidade']}</div>
        {comp}
        <div class="card-fonte">CEPEA/ESALQ · {data_atual}</div>
      </a>"""

    # ── TABELA COMPARATIVA ──
    linhas_tab = ""
    for c in commodities:
        t = c["tend_sem"]
        bg  = {"alta":"#dcfce7","baixa":"#fee2e2"}.get(t,"#f1f5f9")
        cor = {"alta":"#16a34a","baixa":"#dc2626"}.get(t,"#64748b")
        t4  = c["tend_4s"]
        bg4 = {"alta":"#dcfce7","baixa":"#fee2e2"}.get(t4,"#f1f5f9")
        cr4 = {"alta":"#16a34a","baixa":"#dc2626"}.get(t4,"#64748b")
        spark_mini = sparkline_svg(c["serie"], c.get("cor","#16a34a"), w=64, h=24)
        linhas_tab += f"""<tr>
          <td style="padding:10px 12px">{c['icon']} <strong>{c['nome']}</strong></td>
          <td style="padding:10px 12px">{spark_mini}</td>
          <td style="padding:10px 12px;color:#777">{c.get('preco_ant','—')}</td>
          <td style="padding:10px 12px;font-weight:600">{c['preco']}</td>
          <td style="padding:10px 12px">
            <span style="background:{bg};color:{cor};padding:2px 9px;border-radius:12px;font-size:12px;font-weight:700">{seta(t)} {c['var_sem_str']}</span>
          </td>
          <td style="padding:10px 12px">
            <span style="background:{bg4};color:{cr4};padding:2px 9px;border-radius:12px;font-size:12px;font-weight:700">{seta(t4)} {c['var_4s_str']}</span>
          </td>
        </tr>"""

    datas_header = " · ".join(datas)
    tab_comp = ""
    if tem_hist:
        tab_comp = f"""
    <div class="sec">📅 Comparativo · {datas_header}</div>
    <div class="tabela-wrap">
      <table class="tabela">
        <thead><tr>
          <th>Commodity</th>
          <th>4 semanas</th>
          <th>{data_ant}</th>
          <th>{data_atual}</th>
          <th>Var. semana</th>
          <th>Var. 4 sem.</th>
        </tr></thead>
        <tbody>{linhas_tab}</tbody>
      </table>
    </div>"""

    links = "".join(
        f'<a href="{c["cepea"]}" target="_blank" class="link-btn">{c["icon"]} {c["nome"]}</a>'
        for c in commodities
    )

    altas  = sorted([c for c in commodities if c["tend_sem"]=="alta"],
                    key=lambda x: x["var_sem_pct"], reverse=True)
    baixas = sorted([c for c in commodities if c["tend_sem"]=="baixa"],
                    key=lambda x: x["var_sem_pct"])
    res_a = " · ".join(f"{c['icon']} {c['nome']} {c['var_sem_str']}" for c in altas)  or "—"
    res_b = " · ".join(f"{c['icon']} {c['nome']} {c['var_sem_str']}" for c in baixas) or "—"

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta name="theme-color" content="#1a4d2e">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Commodities">
<title>Commodities Monitor · Atacadão</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600&display=swap" rel="stylesheet">
<style>
:root{{--verde:#1a4d2e;--verde2:#2d7a4f;--menta:#4caf7d;--ouro:#c8960c;
      --creme:#fdf6e9;--creme2:#f0e6cc;--cinza:#6b7280;--escuro:#0f1f0f;
      --alta:#16a34a;--baixa:#dc2626;--neutro:#64748b;}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:'DM Sans',sans-serif;background:var(--creme);color:var(--escuro);}}

/* HEADER */
header{{background:var(--verde);padding:0 20px;height:62px;display:flex;
        align-items:center;justify-content:space-between;position:sticky;
        top:0;z-index:99;box-shadow:0 2px 14px rgba(0,0,0,.28);}}
.logo{{display:flex;align-items:center;gap:11px;}}
.logo-icon{{width:38px;height:38px;background:var(--ouro);border-radius:9px;
            display:flex;align-items:center;justify-content:center;font-size:19px;}}
.logo-nome{{font-family:'DM Serif Display',serif;font-size:18px;color:var(--creme);line-height:1.1;}}
.logo-sub{{font-size:9.5px;color:var(--menta);letter-spacing:1.2px;text-transform:uppercase;}}
.badge-data{{background:rgba(255,255,255,.11);border:1px solid rgba(255,255,255,.18);
             border-radius:20px;padding:5px 13px;font-size:11px;color:var(--creme);
             display:flex;align-items:center;gap:6px;white-space:nowrap;}}
.dot{{width:7px;height:7px;background:var(--menta);border-radius:50%;animation:pulsar 2s infinite;}}
@keyframes pulsar{{0%,100%{{opacity:1;transform:scale(1)}}50%{{opacity:.4;transform:scale(.75)}}}}

/* RESUMO BAR */
.resumo-bar{{background:var(--verde2);display:flex;}}
.resumo-item{{flex:1;padding:9px 16px;font-size:11px;color:rgba(255,255,255,.9);
              border-right:1px solid rgba(255,255,255,.1);line-height:1.5;}}
.resumo-item:last-child{{border-right:none;}}
.resumo-label{{font-weight:600;font-size:10px;opacity:.7;text-transform:uppercase;
               letter-spacing:.5px;margin-bottom:2px;}}
.rv-alta{{color:#86efac;}} .rv-baixa{{color:#fca5a5;}}

/* MAIN */
main{{max-width:960px;margin:0 auto;padding:18px 14px 60px;}}
.aviso{{background:#fffbeb;border:1px solid #fde68a;border-radius:10px;
        padding:10px 14px;font-size:11.5px;color:#92400e;
        margin-bottom:18px;display:flex;gap:8px;align-items:flex-start;line-height:1.5;}}
.sec{{font-size:10.5px;font-weight:600;text-transform:uppercase;letter-spacing:2px;
      color:var(--verde);margin-bottom:12px;display:flex;align-items:center;gap:8px;}}
.sec::after{{content:'';flex:1;height:1px;background:var(--creme2);}}

/* CARDS */
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(175px,1fr));
       gap:12px;margin-bottom:28px;}}
.card{{background:#fff;border-radius:14px;padding:14px 13px 12px;
       border:1.5px solid var(--creme2);text-decoration:none;color:var(--escuro);
       display:block;transition:all .18s;position:relative;overflow:hidden;}}
.card:hover,.card:active{{border-color:var(--cor,var(--menta));
  box-shadow:0 6px 22px rgba(0,0,0,.1);transform:translateY(-2px);}}
.card-topo{{position:absolute;top:0;left:0;right:0;height:3px;
            background:var(--cor);border-radius:14px 14px 0 0;}}
.card-head{{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:8px;}}
.card-icon{{font-size:24px;line-height:1;}}
.card-spark{{display:flex;flex-direction:column;align-items:flex-end;gap:2px;}}
.spark-datas{{display:flex;justify-content:space-between;width:80px;
              font-size:7.5px;color:#bbb;}}
.card-nome{{font-size:9.5px;font-weight:600;text-transform:uppercase;
            letter-spacing:.8px;color:var(--cinza);margin-bottom:3px;}}
.card-preco{{font-family:'DM Serif Display',serif;font-size:20px;margin-bottom:1px;}}
.card-unidade{{font-size:9.5px;color:var(--cinza);margin-bottom:7px;}}
.comp-bloco{{border-top:1px solid var(--creme2);padding-top:7px;margin-top:4px;}}
.comp-row{{display:flex;align-items:center;gap:5px;flex-wrap:wrap;}}
.comp-lbl{{font-size:9px;color:#bbb;width:72px;flex-shrink:0;}}
.comp-val{{font-size:11px;color:var(--cinza);font-weight:500;}}
.badge-sm{{display:inline-flex;align-items:center;font-size:11px;font-weight:700;
           padding:2px 7px;border-radius:12px;}}
.alta{{background:#dcfce7;color:var(--alta);}}
.baixa{{background:#fee2e2;color:var(--baixa);}}
.neutro{{background:#f1f5f9;color:var(--neutro);}}
.card-fonte{{font-size:8.5px;color:#ccc;margin-top:7px;}}

/* TABELA */
.tabela-wrap{{background:#fff;border-radius:14px;border:1.5px solid var(--creme2);
              overflow-x:auto;margin-bottom:22px;}}
.tabela{{width:100%;border-collapse:collapse;font-size:13px;}}
.tabela thead tr{{background:var(--verde);}}
.tabela thead th{{padding:11px 12px;text-align:left;font-size:10px;font-weight:600;
                  color:var(--creme);letter-spacing:.5px;text-transform:uppercase;white-space:nowrap;}}
.tabela tbody tr{{border-bottom:1px solid var(--creme2);transition:background .12s;}}
.tabela tbody tr:last-child{{border-bottom:none;}}
.tabela tbody tr:hover{{background:var(--creme);}}
.tabela tbody td{{padding:10px 12px;white-space:nowrap;vertical-align:middle;}}

/* LINKS */
.links-panel{{background:#fff;border-radius:14px;border:1.5px solid var(--creme2);
              padding:18px;margin-bottom:18px;}}
.links-panel h3{{font-family:'DM Serif Display',serif;font-size:15px;
                 color:var(--verde);margin-bottom:13px;}}
.links-wrap{{display:flex;flex-wrap:wrap;gap:7px;}}
.link-btn{{display:inline-block;padding:7px 13px;border-radius:22px;background:var(--creme);
           border:1.5px solid var(--creme2);text-decoration:none;color:var(--verde);
           font-size:12.5px;font-weight:500;transition:all .18s;}}
.link-btn:hover,.link-btn:active{{background:var(--verde);color:var(--creme);border-color:var(--verde);}}

footer{{text-align:center;font-size:10.5px;color:var(--cinza);
        margin-top:28px;line-height:1.9;padding:0 16px 32px;}}

@media(max-width:520px){{
  .grid{{grid-template-columns:repeat(2,1fr);}}
  .resumo-bar{{flex-direction:column;}}
  .resumo-item{{border-right:none;border-bottom:1px solid rgba(255,255,255,.1);}}
  .tabela{{font-size:11px;}}
  .tabela thead th,.tabela tbody td{{padding:8px 9px;}}
  .logo-nome{{font-size:16px;}}
}}
</style>
</head>
<body>

<header>
  <div class="logo">
    <div class="logo-icon">🌾</div>
    <div>
      <div class="logo-nome">Commodities Monitor</div>
      <div class="logo-sub">Atacadão · Mercado</div>
    </div>
  </div>
  <div class="badge-data"><span class="dot"></span><span>{data_atual}</span></div>
</header>

<div class="resumo-bar">
  <div class="resumo-item">
    <div class="resumo-label">⬆ Altas na semana</div>
    <div class="rv-alta">{res_a}</div>
  </div>
  <div class="resumo-item">
    <div class="resumo-label">⬇ Baixas na semana</div>
    <div class="rv-baixa">{res_b}</div>
  </div>
</div>

<main>
  <div class="aviso">⚠️ <span>Preços de referência <strong>CEPEA/ESALQ-USP</strong>.
  Toque em qualquer commodity para o indicador oficial.</span></div>

  <div class="sec">📊 Preços · {data_atual} · tendência 4 semanas</div>
  <div class="grid">{cards}</div>

  {tab_comp}

  <div class="sec">🔗 Acesso Direto CEPEA</div>
  <div class="links-panel">
    <h3>Indicadores Oficiais ESALQ-USP</h3>
    <div class="links-wrap">{links}</div>
  </div>
</main>

<footer>
  Fonte: CEPEA/ESALQ-USP ·
  <a href="https://cepea.org.br/br" target="_blank" style="color:var(--verde)">cepea.org.br</a><br>
  Inteligência de Mercado · Atacadão · {datetime.now().year}
</footer>
</body>
</html>"""

# ── GitHub Pages ─────────────────────────────────────────────
def publicar_github(config, data_ref):
    repo = config["github"].get("repositorio","")
    if not repo:
        print("⚠️  GitHub não configurado — pulando."); return
    print("\n📤 Publicando no GitHub Pages...")
    for cmd in [
        ["git","add","docs/index.html"],
        ["git","commit","-m",f"update: commodities {data_ref}"],
        ["git","push"],
    ]:
        r = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True)
        if r.returncode != 0 and "nothing to commit" not in r.stdout:
            print(f"   ⚠️  {r.stderr.strip()}")
    u = config["github"].get("usuario","")
    print(f"   ✅ https://{u}.github.io/{repo}/")

# ── E-mail ───────────────────────────────────────────────────
def enviar_email(config, atual, anterior, commodities, link):
    cfg = config.get("email",{})
    rem, senha, dest = cfg.get("remetente",""), cfg.get("senha_app",""), cfg.get("destinatarios",[])
    if not rem or not senha or not dest:
        print("⚠️  E-mail não configurado — pulando."); return

    data_a = atual["data"]; data_ant = anterior["data"] if anterior else "—"

    def seta(t): return {"alta":"▲","baixa":"▼"}.get(t,"—")
    def bg(t):   return {"alta":"#dcfce7","baixa":"#fee2e2"}.get(t,"#f1f5f9")
    def cr(t):   return {"alta":"#16a34a","baixa":"#dc2626"}.get(t,"#64748b")

    linhas = "".join(f"""<tr style="border-bottom:1px solid #f0e6cc">
      <td style="padding:9px 12px">{c['icon']} <strong>{c['nome']}</strong></td>
      <td style="padding:9px 12px;color:#999">{c.get('preco_ant','—')}</td>
      <td style="padding:9px 12px;font-family:Georgia,serif;font-size:15px">{c['preco']}</td>
      <td style="padding:9px 12px">
        <span style="background:{bg(c['tend_sem'])};color:{cr(c['tend_sem'])};
          padding:2px 9px;border-radius:12px;font-size:12px;font-weight:700">
          {seta(c['tend_sem'])} {c['var_sem_str']}
        </span>
      </td>
      <td style="padding:9px 12px">
        <span style="background:{bg(c['tend_4s'])};color:{cr(c['tend_4s'])};
          padding:2px 9px;border-radius:12px;font-size:12px;font-weight:700">
          {seta(c['tend_4s'])} {c['var_4s_str']}
        </span>
      </td>
    </tr>""" for c in commodities)

    assunto = f"{cfg.get('assunto_prefixo','📊 Commodities')} · {data_a} · Atacadão"
    corpo   = f"""<!DOCTYPE html><html lang="pt-BR"><body style="margin:0;background:#f5f5f0;font-family:Helvetica,Arial,sans-serif">
<div style="max-width:640px;margin:28px auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.08)">
  <div style="background:#1a4d2e;padding:22px 26px;display:flex;align-items:center;gap:12px">
    <div style="width:42px;height:42px;background:#c8960c;border-radius:9px;font-size:21px;display:flex;align-items:center;justify-content:center;flex-shrink:0">🌾</div>
    <div>
      <div style="font-size:19px;color:#fdf6e9;font-weight:700">Commodities Monitor</div>
      <div style="font-size:10px;color:#4caf7d;letter-spacing:1px;text-transform:uppercase">Atacadão · Inteligência de Mercado</div>
    </div>
  </div>
  <div style="background:#2d7a4f;padding:8px 26px;font-size:12px;color:rgba(255,255,255,.85)">
    Semana: {data_ant} → {data_a}
  </div>
  <div style="padding:20px 26px">
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">
      <thead><tr style="background:#f8f4ee">
        <th style="padding:9px 12px;text-align:left;font-size:10px;color:#888;text-transform:uppercase">Commodity</th>
        <th style="padding:9px 12px;text-align:left;font-size:10px;color:#888;text-transform:uppercase">{data_ant}</th>
        <th style="padding:9px 12px;text-align:left;font-size:10px;color:#888;text-transform:uppercase">{data_a}</th>
        <th style="padding:9px 12px;text-align:left;font-size:10px;color:#888;text-transform:uppercase">Var. semana</th>
        <th style="padding:9px 12px;text-align:left;font-size:10px;color:#888;text-transform:uppercase">Var. 4 sem.</th>
      </tr></thead>
      <tbody>{linhas}</tbody>
    </table>
  </div>
  <div style="padding:4px 26px 24px">
    <a href="{link}" style="display:block;background:#1a4d2e;color:#fdf6e9;text-align:center;
       padding:13px;border-radius:10px;text-decoration:none;font-weight:600;font-size:14px">
      📱 Abrir Dashboard Completo →
    </a>
  </div>
  <div style="background:#fdf6e9;padding:12px 26px;font-size:10px;color:#aaa;text-align:center;line-height:1.8">
    Fonte: CEPEA/ESALQ-USP · cepea.org.br · Atacadão {datetime.now().year}
  </div>
</div></body></html>"""

    print("\n📧 Enviando e-mail...")
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"], msg["From"], msg["To"] = assunto, rem, ", ".join(dest)
        msg.attach(MIMEText(corpo, "html", "utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(rem, senha); srv.sendmail(rem, dest, msg.as_string())
        print(f"   ✅ Enviado para: {', '.join(dest)}")
    except Exception as e:
        print(f"   ❌ Erro: {e}")

# ── Main ─────────────────────────────────────────────────────
def main():
    print("\n" + "="*52)
    print("  🌾 COMMODITIES MONITOR — ATACADÃO")
    print("="*52)
    config = carregar_config()
    janela, atual, anterior = carregar_dados()
    commodities = enriquecer(janela, atual, anterior)
    data_ref = atual["data"]

    print(f"\n📄 Gerando dashboard — {data_ref} ({len(janela)} semanas)...")
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(
        gerar_html(janela, atual, anterior, commodities), encoding="utf-8"
    )
    print(f"   ✅ {OUTPUT_HTML}")

    publicar_github(config, data_ref)

    u    = config["github"].get("usuario","")
    repo = config["github"].get("repositorio","")
    link = f"https://{u}.github.io/{repo}/" if (u and repo) else str(OUTPUT_HTML)

    enviar_email(config, atual, anterior, commodities, link)
    print(f"\n✅ Concluído! {link}\n")

if __name__ == "__main__":
    main()
