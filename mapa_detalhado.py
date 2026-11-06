import json
from pathlib import Path
from collections import Counter, defaultdict
from html import escape

import folium
from folium.plugins import Fullscreen, MiniMap, MousePosition
from shapely.geometry import shape

BASE = Path(__file__).resolve().parent
RESULTADOS = BASE / "resultados"

with (BASE / "dados_reais" / "resex_chico_mendes" / "limite.geojson").open(encoding="utf-8") as f:
    limite = json.load(f)

with (RESULTADOS / "intersecoes_prodes.geojson").open(encoding="utf-8") as f:
    prodes = json.load(f)

with (RESULTADOS / "area_unica.json").open(encoding="utf-8") as f:
    resumo = json.load(f)

geom_reserva = shape(limite["features"][0]["geometry"])
centro = geom_reserva.centroid

mapa = folium.Map(
    location=[centro.y, centro.x],
    zoom_start=9,
    tiles=None,
    control_scale=True
)

folium.GeoJson(
    limite,
    name="Limite da Reserva Chico Mendes",
    style_function=lambda f: {
        "color": "#1565C0",
        "weight": 3,
        "fillColor": "#1565C0",
        "fillOpacity": 0.04
    }
).add_to(mapa)

cores = {
    "corte raso com solo exposto": "#D32F2F",
    "corte raso com vegetação": "#FF9800",
    "desmatamento por degradação progressiva": "#8E24AA"
}

grupos = {}
contagens = Counter()
areas = defaultdict(float)

for classe, cor in cores.items():
    grupos[classe] = folium.FeatureGroup(
        name=classe.title(),
        show=True
    )
    grupos[classe].add_to(mapa)

for feicao in prodes["features"]:
    p = feicao["properties"]
    classe = p.get("sub_class", "Não informada")
    cor = cores.get(classe, "#616161")

    area = float(p.get("area_ha", 0))
    contagens[classe] += 1
    areas[classe] += area

    campos = [
        ("Classe", classe),
        ("Área de interseção (ha)", f"{area:.4f}"),
        ("Ano", p.get("year", "")),
        ("Data da imagem", p.get("image_date", "")),
        ("Satélite", p.get("satellite", "")),
        ("Sensor", p.get("sensor", "")),
        ("Estado", p.get("state", "")),
        ("Identificador", p.get("uuid", "")),
    ]

    linhas = "".join(
        f"<tr><td><b>{escape(str(k))}</b></td>"
        f"<td>{escape(str(v))}</td></tr>"
        for k, v in campos
    )

    popup = folium.Popup(
        f"<div style='width:310px;font-family:Arial'>"
        f"<h4>Registro PRODES</h4>"
        f"<table>{linhas}</table></div>",
        max_width=360
    )

    camada = grupos.get(classe)

    if camada is None:
        camada = grupos.setdefault(
            classe,
            folium.FeatureGroup(name=classe, show=True)
        )
        camada.add_to(mapa)

    folium.GeoJson(
        feicao,
        style_function=lambda f, cor=cor: {
            "color": cor,
            "weight": 1.5,
            "fillColor": cor,
            "fillOpacity": 0.7
        },
        popup=popup,
        tooltip=f"{classe} | {area:.4f} ha"
    ).add_to(camada)

Fullscreen(position="topleft").add_to(mapa)

MousePosition(
    position="bottomright",
    separator=" | ",
    prefix="Coordenadas:",
    num_digits=5
).add_to(mapa)

folium.LayerControl(collapsed=False).add_to(mapa)

minx, miny, maxx, maxy = geom_reserva.bounds
mapa.fit_bounds([[miny, minx], [maxy, maxx]])

def numero(valor, casas=2):
    return f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")

linhas_painel = ""

for classe, cor in cores.items():
    linhas_painel += (
        f"<p><span style='color:{cor}'>■</span> "
        f"{escape(classe.capitalize())}<br>"
        f"<small>{contagens[classe]} interseções | "
        f"{numero(areas[classe])} ha</small></p>"
    )

painel = f"""
<div style="
position:fixed;
top:15px;
right:15px;
width:290px;
max-width:75vw;
max-height:65vh;
overflow-y:auto;
background:white;
padding:16px;
border-radius:10px;
box-shadow:0 2px 12px #777;
z-index:9999;
font-family:Arial;
font-size:13px;
color:#222;
">
<h2 style="margin-top:0">Carbon Forensics</h2>
<b>PRODES Amazônia Legal — 2026</b>
<p>Registros analisados: <b>26.381</b></p>
<p>Interseções: <b>{len(prodes["features"])}</b></p>
<p>Área única: <b>{numero(resumo["area_unica_ha"])} ha</b></p>
<hr>
<b>Classes de desmatamento</b>
{linhas_painel}
<p><span style="color:#1565C0">■</span> Limite da reserva</p>
<hr>
<small>
Clique nos polígonos para ver detalhes.
Use o controle de camadas para filtrar categorias.
<br><br>
Fontes: INPE/PRODES e ICMBio.
Interseções não comprovam ilegalidade ou fraude.
</small>
</div>
"""

from branca.element import Element
mapa.get_root().html.add_child(Element(painel))

saida = RESULTADOS / "mapa_detalhado.html"
mapa.save(str(saida))

print("MAPA DETALHADO CRIADO COM SUCESSO!")
print("Interseções:", len(prodes["features"]))
print("Arquivo:", saida)
