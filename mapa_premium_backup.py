
import json
from pathlib import Path
from collections import Counter, defaultdict
from html import escape

import folium
from folium.plugins import Fullscreen, MousePosition
from branca.element import Element
from shapely.geometry import shape

BASE = Path(__file__).resolve().parent
RESULTADOS = BASE / "resultados"

def carregar(caminho):
    with caminho.open(encoding="utf-8") as arquivo:
        return json.load(arquivo)

def numero(valor, casas=2):
    return f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")

limite = carregar(BASE / "dados_reais" / "resex_chico_mendes" / "limite.geojson")
prodes = carregar(RESULTADOS / "intersecoes_prodes.geojson")
resumo = carregar(RESULTADOS / "resumo.json")
area_unica = carregar(RESULTADOS / "area_unica.json")

geometria = shape(limite["features"][0]["geometry"])
centro = geometria.centroid

mapa = folium.Map(
    location=[centro.y, centro.x],
    zoom_start=9,
    tiles=None,
    zoom_control=True,
    control_scale=True
)

cores = {
    "corte raso com solo exposto": "#ef5350",
    "corte raso com vegetação": "#ffb74d",
    "desmatamento por degradação progressiva": "#ab78d0"
}

nomes = {
    "corte raso com solo exposto": "Corte raso — solo exposto",
    "corte raso com vegetação": "Corte raso — com vegetação",
    "desmatamento por degradação progressiva": "Degradação progressiva"
}

folium.GeoJson(
    limite,
    name="Limite da Reserva Chico Mendes",
    style_function=lambda f: {
        "color": "#35b6d5",
        "weight": 3,
        "fillColor": "#35b6d5",
        "fillOpacity": 0.05
    }
).add_to(mapa)

grupos = {}
contagens = Counter()
areas = defaultdict(float)

for classe in cores:
    grupo = folium.FeatureGroup(
        name=nomes[classe],
        show=True
    )
    grupo.add_to(mapa)
    grupos[classe] = grupo

for feicao in prodes["features"]:
    propriedades = feicao.get("properties", {})
    classe = propriedades.get("sub_class", "Não informada")
    cor = cores.get(classe, "#9ca3af")

    try:
        area = float(propriedades.get("area_ha") or 0)
    except (ValueError, TypeError):
        area = 0.0

    contagens[classe] += 1
    areas[classe] += area

    detalhes = [
        ("Classificação", classe),
        ("Área de interseção", numero(area, 4) + " ha"),
        ("Ano PRODES", propriedades.get("year")),
        ("Data da imagem", propriedades.get("image_date")),
        ("Satélite", propriedades.get("satellite")),
        ("Sensor", propriedades.get("sensor")),
        ("Estado", propriedades.get("state")),
        ("Identificador", propriedades.get("uuid"))
    ]

    linhas = "".join(
        f"<tr><td style='padding:6px;color:#64748b'>{escape(str(k))}</td>"
        f"<td style='padding:6px'>{escape(str(v if v is not None else 'Não informado'))}</td></tr>"
        for k, v in detalhes
    )

    popup = folium.Popup(
        "<div style='font-family:Arial;width:320px'>"
        "<h3 style='color:#0f172a'>Detalhes do registro</h3>"
        f"<table style='font-size:12px'>{linhas}</table>"
        "</div>",
        max_width=380
    )

    if classe not in grupos:
        grupo = folium.FeatureGroup(name=classe, show=True)
        grupo.add_to(mapa)
        grupos[classe] = grupo

    folium.GeoJson(
        feicao,
        style_function=lambda f, cor=cor: {
            "color": cor,
            "weight": 1.2,
            "fillColor": cor,
            "fillOpacity": 0.75
        },
        highlight_function=lambda f: {
            "weight": 3,
            "color": "#ffffff",
            "fillOpacity": 0.95
        },
        popup=popup,
        tooltip=f"{nomes.get(classe, classe)} | {numero(area, 2)} ha"
    ).add_to(grupos[classe])

Fullscreen(position="topleft").add_to(mapa)

MousePosition(
    position="bottomleft",
    prefix="Latitude / Longitude:",
    num_digits=5
).add_to(mapa)

folium.LayerControl(collapsed=True, position="topleft").add_to(mapa)

minx, miny, maxx, maxy = geometria.bounds
mapa.fit_bounds([[miny, minx], [maxy, maxx]])

# Indicadores e barras calculados dos dados reais
total = len(prodes["features"])
soma = sum(areas.values())

barras = ""
for classe, cor in cores.items():
    valor = areas[classe]
    percentual = (valor / soma * 100) if soma else 0

    barras += f"""
    <div class="categoria">
      <div class="categoria-titulo">
        <span>{escape(nomes[classe])}</span>
        <b>{percentual:.1f}%</b>
      </div>
      <div class="barra-fundo">
        <div class="barra" style="width:{percentual:.2f}%;background:{cor}"></div>
      </div>
      <div class="categoria-sub">
        {contagens[classe]} polígonos · {numero(valor)} ha
      </div>
    </div>
    """

# O resumo de área única vem do cálculo anterior.
# Verificamos qual campo foi gravado no JSON.
area_unica_valor = area_unica.get("area_unica_ha")

if area_unica_valor is None:
    area_unica_valor = area_unica.get("area_unica")

if area_unica_valor is None:
    area_unica_valor = soma

painel = f"""
<style>
.cf-painel {{
    position:fixed;
    top:16px;
    right:16px;
    z-index:9999;
    width:330px;
    max-width:calc(100vw - 32px);
    max-height:85vh;
    overflow-y:auto;
    background:#101b2b;
    color:#e5edf6;
    border:1px solid #304158;
    border-radius:16px;
    box-shadow:0 12px 40px rgba(0,0,0,.35);
    padding:20px;
    font-family:Arial,sans-serif;
    box-sizing:border-box;
}}
.cf-painel h2 {{
    font-size:19px;
    margin:0 0 5px;
    color:#fff;
}}
.cf-subtitulo {{
    color:#91a4bb;
    font-size:12px;
    margin-bottom:18px;
}}
.cf-etiqueta {{
    display:inline-block;
    color:#7ee4c0;
    background:#143d3b;
    padding:5px 9px;
    border-radius:20px;
    font-size:10px;
    margin-bottom:12px;
}}
.cf-cards {{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:9px;
}}
.cf-card {{
    background:#1b2a3d;
    padding:12px;
    border-radius:10px;
}}
.cf-card.grande {{
    grid-column:span 2;
}}
.cf-valor {{
    font-size:23px;
    font-weight:bold;
    color:#fff;
}}
.cf-label {{
    font-size:11px;
    color:#9eb0c4;
    margin-top:5px;
}}
.cf-painel h3 {{
    font-size:13px;
    margin:20px 0 13px;
    color:#fff;
}}
.categoria {{
    margin-bottom:15px;
}}
.categoria-titulo {{
    display:flex;
    justify-content:space-between;
    gap:10px;
    font-size:11px;
    margin-bottom:7px;
}}
.barra-fundo {{
    height:7px;
    background:#304158;
    border-radius:10px;
    overflow:hidden;
}}
.barra {{
    height:100%;
    border-radius:10px;
}}
.categoria-sub {{
    font-size:10px;
    color:#9eb0c4;
    margin-top:5px;
}}
.cf-rodape {{
    border-top:1px solid #304158;
    padding-top:13px;
    margin-top:16px;
    font-size:10px;
    line-height:1.6;
    color:#9eb0c4;
}}
.cf-fechar {{
    float:right;
    background:transparent;
    color:#cbd5e1;
    border:0;
    cursor:pointer;
    font-size:20px;
}}
.cf-abrir {{
    display:none;
    position:fixed;
    top:16px;
    right:16px;
    z-index:9999;
    background:#101b2b;
    color:white;
    border:1px solid #304158;
    padding:12px 16px;
    border-radius:10px;
    cursor:pointer;
}}
</style>

<button class="cf-abrir" id="cf-abrir"
 onclick="document.getElementById('cf-painel').style.display='block';this.style.display='none'">
 ☰ Abrir painel
</button>

<div class="cf-painel" id="cf-painel">
    <button class="cf-fechar"
      onclick="document.getElementById('cf-painel').style.display='none';document.getElementById('cf-abrir').style.display='block'">
      ×
    </button>

    <div class="cf-etiqueta">● MONITORAMENTO AMBIENTAL</div>
    <h2>CARBON FORENSICS</h2>
    <div class="cf-subtitulo">
      Reserva Extrativista Chico Mendes · Acre<br>
      PRODES Amazônia Legal · 2026
    </div>

    <div class="cf-cards">
      <div class="cf-card">
        <div class="cf-valor">{numero(resumo.get("registros_lidos", 26381), 0)}</div>
        <div class="cf-label">Registros analisados</div>
      </div>
      <div class="cf-card">
        <div class="cf-valor">{numero(total, 0)}</div>
        <div class="cf-label">Interseções espaciais</div>
      </div>
      <div class="cf-card grande">
        <div class="cf-valor">{numero(float(area_unica_valor))} ha</div>
        <div class="cf-label">Área geográfica única estimada</div>
      </div>
    </div>

    <h3>DISTRIBUIÇÃO POR CLASSE</h3>
    {barras}

    <h3>LEGENDA DO MAPA</h3>
    <div style="font-size:12px;line-height:2">
      <div><span style="color:#35b6d5">■</span> Limite da reserva</div>
      <div><span style="color:#ef5350">■</span> Corte raso — solo exposto</div>
      <div><span style="color:#ffb74d">■</span> Corte raso — com vegetação</div>
      <div><span style="color:#ab78d0">■</span> Degradação progressiva</div>
    </div>

    <div class="cf-rodape">
      <b>Como explorar:</b> clique nos polígonos para ver
      os detalhes. Use o controle de camadas para filtrar
      as categorias.<br><br>
      <b>Fontes:</b> INPE/PRODES e ICMBio.<br>
      <b>Nota:</b> interseções espaciais não comprovam
      ilegalidade, fraude ou vínculo com créditos de carbono.
    </div>
</div>
"""

mapa.get_root().html.add_child(Element(painel))

saida = RESULTADOS / "mapa_premium.html"
mapa.save(str(saida))

print("MAPA PREMIUM CRIADO COM SUCESSO!")
print("Polígonos:", total)
print("Área única (ha):", numero(float(area_unica_valor)))
print("Arquivo:", saida)
