
import json
from pathlib import Path
from collections import Counter, defaultdict
from html import escape

import folium
from folium.plugins import Fullscreen, MousePosition
from branca.element import Element
from shapely.geometry import shape


# =====================================================
# 1. CAMINHOS DOS ARQUIVOS
# =====================================================

BASE = Path(__file__).resolve().parent
RESULTADOS = BASE / "resultados"

ARQUIVO_LIMITE = (
    BASE / "dados_reais" / "resex_chico_mendes" / "limite.geojson"
)

ARQUIVO_PRODES = RESULTADOS / "intersecoes_prodes.geojson"
ARQUIVO_RESUMO = RESULTADOS / "resumo.json"
ARQUIVO_AREA = RESULTADOS / "area_unica.json"


def carregar_json(caminho):
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo nao encontrado: {caminho}")

    with caminho.open(encoding="utf-8") as arquivo:
        return json.load(arquivo)


def numero(valor, casas=2):
    return (
        f"{float(valor):,.{casas}f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def valor_texto(valor):
    if valor is None or valor == "":
        return "Nao informado"
    return str(valor)


print("=" * 55)
print("CARBON FORENSICS PREMIUM")
print("Mapa ambiental com satelite, relevo e estradas")
print("=" * 55)


# =====================================================
# 2. CARREGAR DADOS REAIS
# =====================================================

limite = carregar_json(ARQUIVO_LIMITE)
prodes = carregar_json(ARQUIVO_PRODES)
resumo = carregar_json(ARQUIVO_RESUMO)
area_unica = carregar_json(ARQUIVO_AREA)

feicoes = prodes.get("features", [])

if not feicoes:
    raise ValueError("O GeoJSON PRODES nao possui feicoes.")

geometria_reserva = shape(limite["features"][0]["geometry"])
centro = geometria_reserva.centroid

print("Poligonos carregados:", len(feicoes))


# =====================================================
# 3. CRIAR MAPA
# =====================================================

mapa = folium.Map(
    location=[centro.y, centro.x],
    zoom_start=9,
    tiles=None,
    zoom_control=True,
    control_scale=True,
    prefer_canvas=True
)


# =====================================================
# 4. MAPAS DE FUNDO
# =====================================================

# Satelite: cobertura florestal, clareiras e rios
folium.TileLayer(
    tiles=(
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Imagery/MapServer/tile/{z}/{y}/{x}"
    ),
    attr="Esri, Maxar, Earthstar Geographics e colaboradores",
    name="01 - Satelite",
    overlay=False,
    control=True,
    show=True,
    max_zoom=19
).add_to(mapa)


# Topografico: estradas, rios e referencias
folium.TileLayer(
    tiles=(
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Topo_Map/MapServer/tile/{z}/{y}/{x}"
    ),
    attr="Esri e colaboradores",
    name="02 - Topografico",
    overlay=False,
    control=True,
    show=False,
    max_zoom=19
).add_to(mapa)


# Relevo sombreado
folium.TileLayer(
    tiles=(
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Shaded_Relief/MapServer/tile/{z}/{y}/{x}"
    ),
    attr="Esri e colaboradores",
    name="03 - Relevo sombreado",
    overlay=False,
    control=True,
    show=False,
    max_zoom=13
).add_to(mapa)


# Estradas sobre a imagem de satelite
folium.TileLayer(
    tiles=(
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}"
    ),
    attr="Esri e colaboradores",
    name="Estradas e transportes",
    overlay=True,
    control=True,
    show=True,
    max_zoom=19
).add_to(mapa)


# Nomes de lugares e referencias
folium.TileLayer(
    tiles=(
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "Reference/World_Boundaries_and_Places/"
        "MapServer/tile/{z}/{y}/{x}"
    ),
    attr="Esri e colaboradores",
    name="Nomes de lugares",
    overlay=True,
    control=True,
    show=True,
    max_zoom=19
).add_to(mapa)


# =====================================================
# 5. LIMITE DA RESERVA
# =====================================================

folium.GeoJson(
    limite,
    name="Reserva Extrativista Chico Mendes",
    style_function=lambda f: {
        "color": "#38bdf8",
        "weight": 3,
        "fillColor": "#38bdf8",
        "fillOpacity": 0.04
    },
    tooltip="Limite da Reserva Extrativista Chico Mendes"
).add_to(mapa)


# =====================================================
# 6. CLASSES DE DESMATAMENTO
# =====================================================

cores = {
    "corte raso com solo exposto": "#ef4444",
    "corte raso com vegetação": "#f59e0b",
    "desmatamento por degradação progressiva": "#a855f7"
}

nomes = {
    "corte raso com solo exposto": "Corte raso - solo exposto",
    "corte raso com vegetação": "Corte raso - com vegetacao",
    "desmatamento por degradação progressiva": "Degradacao progressiva"
}

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


# =====================================================
# 7. POLIGONOS COM INFORMACOES DETALHADAS
# =====================================================

for indice, feicao in enumerate(feicoes, start=1):

    propriedades = feicao.get("properties") or {}
    classe = propriedades.get("sub_class", "Nao informada")
    cor = cores.get(classe, "#94a3b8")

    try:
        area = float(propriedades.get("area_ha") or 0)
    except (ValueError, TypeError):
        area = 0.0

    contagens[classe] += 1
    areas[classe] += area

    # Centro aproximado da geometria de intersecao
    geometria_poligono = shape(feicao["geometry"])
    ponto = geometria_poligono.representative_point()

    latitude = ponto.y
    longitude = ponto.x

    detalhes = [
        ("Registro no mapa", indice),
        ("Classificacao PRODES", classe),
        ("Area dentro da reserva", numero(area, 4) + " ha"),
        ("Area em metros quadrados", numero(area * 10000) + " m²"),
        ("Ano de referencia", propriedades.get("year")),
        ("Data da imagem", propriedades.get("image_date")),
        ("Satelite", propriedades.get("satellite")),
        ("Sensor", propriedades.get("sensor")),
        ("Estado", propriedades.get("state")),
        ("Identificador UUID", propriedades.get("uuid")),
        ("Latitude aproximada", f"{latitude:.6f}"),
        ("Longitude aproximada", f"{longitude:.6f}")
    ]

    # Incluir todos os outros atributos disponiveis
    campos_exibidos = {
        "sub_class",
        "area_ha",
        "year",
        "image_date",
        "satellite",
        "sensor",
        "state",
        "uuid"
    }

    for chave, valor in propriedades.items():
        if chave not in campos_exibidos:
            if valor is not None and str(valor).strip():
                detalhes.append((chave, valor))

    linhas = ""

    for chave, valor in detalhes:
        linhas += (
            "<tr>"
            f"<td class='cf-popup-chave'>{escape(str(chave))}</td>"
            f"<td class='cf-popup-valor'>"
            f"{escape(valor_texto(valor))}</td>"
            "</tr>"
        )

    conteudo_popup = f"""
    <div class="cf-popup">
        <div class="cf-popup-topo">
            <div class="cf-popup-etiqueta">REGISTRO PRODES</div>
            <h3>Poligono #{indice}</h3>
            <div class="cf-popup-area">
                {numero(area, 4)} ha
            </div>
        </div>
        <div class="cf-popup-corpo">
            <table>{linhas}</table>
        </div>
        <div class="cf-popup-rodape">
            Area referente somente a intersecao com a reserva.
            A observacao espacial nao comprova ilegalidade.
        </div>
    </div>
    """

    popup = folium.Popup(
        conteudo_popup,
        max_width=430
    )

    if classe not in grupos:
        grupo = folium.FeatureGroup(
            name=classe,
            show=True
        )
        grupo.add_to(mapa)
        grupos[classe] = grupo

    folium.GeoJson(
        feicao,
        style_function=lambda f, cor=cor: {
            "color": cor,
            "weight": 1.4,
            "fillColor": cor,
            "fillOpacity": 0.65
        },
        highlight_function=lambda f: {
            "color": "#ffffff",
            "weight": 3,
            "fillOpacity": 0.9
        },
        popup=popup,
        tooltip=(
            f"Registro #{indice} | "
            f"{nomes.get(classe, classe)} | "
            f"{numero(area, 2)} ha"
        )
    ).add_to(grupos[classe])


# =====================================================
# 8. CONTROLES DO MAPA
# =====================================================

Fullscreen(position="topleft").add_to(mapa)

MousePosition(
    position="bottomleft",
    prefix="Coordenadas:",
    num_digits=5
).add_to(mapa)

folium.LayerControl(
    collapsed=True,
    position="topleft"
).add_to(mapa)

minx, miny, maxx, maxy = geometria_reserva.bounds

mapa.fit_bounds([
    [miny, minx],
    [maxy, maxx]
])


# =====================================================
# 9. CALCULAR INDICADORES
# =====================================================

total = len(feicoes)
soma_areas = sum(areas.values())

area_unica_valor = area_unica.get("area_unica_ha")

if area_unica_valor is None:
    area_unica_valor = area_unica.get("area_unica")

if area_unica_valor is None:
    raise ValueError(
        "Nao encontrei a area unica no arquivo area_unica.json. "
        "Verifique o nome do campo antes de gerar o painel."
    )

area_unica_valor = float(area_unica_valor)

barras_html = ""

for classe, cor in cores.items():

    quantidade = contagens[classe]
    area_classe = areas[classe]

    percentual = (
        area_classe / soma_areas * 100
        if soma_areas > 0 else 0
    )

    barras_html += f"""
    <div class="cf-categoria">
        <div class="cf-categoria-titulo">
            <span>{escape(nomes[classe])}</span>
            <strong>{percentual:.1f}%</strong>
        </div>
        <div class="cf-barra-fundo">
            <div class="cf-barra"
                 style="width:{percentual:.2f}%;background:{cor}">
            </div>
        </div>
        <div class="cf-categoria-detalhe">
            {quantidade} registros | {numero(area_classe)} ha
        </div>
    </div>
    """


# =====================================================
# 10. PAINEL PREMIUM
# =====================================================

painel_html = f"""
<style>

.cf-painel {{
    position:fixed;
    top:16px;
    right:16px;
    width:345px;
    max-width:calc(100vw - 32px);
    max-height:88vh;
    overflow-y:auto;
    z-index:9999;
    background:#0f172a;
    color:#e2e8f0;
    border:1px solid #334155;
    border-radius:18px;
    padding:22px;
    box-sizing:border-box;
    box-shadow:0 15px 45px rgba(0,0,0,.4);
    font-family:Arial,sans-serif;
}}

.cf-painel h2 {{
    margin:0;
    font-size:21px;
    color:white;
    letter-spacing:.5px;
}}

.cf-subtitulo {{
    color:#94a3b8;
    font-size:12px;
    line-height:1.6;
    margin:9px 0 18px;
}}

.cf-etiqueta {{
    display:inline-block;
    padding:6px 10px;
    margin-bottom:13px;
    background:#134e4a;
    color:#99f6e4;
    font-size:10px;
    border-radius:20px;
    font-weight:bold;
}}

.cf-cards {{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:10px;
}}

.cf-card {{
    background:#1e293b;
    padding:13px;
    border-radius:12px;
    border:1px solid #334155;
}}

.cf-card-grande {{
    grid-column:span 2;
}}

.cf-numero {{
    font-size:23px;
    color:#fff;
    font-weight:bold;
}}

.cf-descricao {{
    font-size:11px;
    color:#94a3b8;
    margin-top:6px;
}}

.cf-painel h3 {{
    font-size:12px;
    color:#f8fafc;
    margin:23px 0 15px;
    letter-spacing:.6px;
}}

.cf-categoria {{
    margin-bottom:16px;
}}

.cf-categoria-titulo {{
    display:flex;
    justify-content:space-between;
    gap:8px;
    font-size:11px;
    margin-bottom:8px;
}}

.cf-barra-fundo {{
    height:8px;
    background:#334155;
    border-radius:8px;
    overflow:hidden;
}}

.cf-barra {{
    height:100%;
    border-radius:8px;
}}

.cf-categoria-detalhe {{
    font-size:10px;
    color:#94a3b8;
    margin-top:6px;
}}

.cf-legenda {{
    font-size:12px;
    line-height:2;
}}

.cf-rodape {{
    margin-top:20px;
    padding-top:14px;
    border-top:1px solid #334155;
    font-size:10px;
    line-height:1.7;
    color:#94a3b8;
}}

.cf-fechar {{
    float:right;
    background:transparent;
    color:#cbd5e1;
    border:0;
    font-size:23px;
    cursor:pointer;
}}

.cf-abrir {{
    display:none;
    position:fixed;
    top:16px;
    right:16px;
    z-index:9999;
    background:#0f172a;
    color:white;
    border:1px solid #334155;
    border-radius:10px;
    padding:12px 16px;
    cursor:pointer;
    font-family:Arial,sans-serif;
}}

.cf-popup {{
    font-family:Arial,sans-serif;
    width:350px;
    max-width:100%;
    color:#0f172a;
}}

.cf-popup-topo {{
    background:#0f172a;
    color:white;
    padding:15px;
    border-radius:8px 8px 0 0;
}}

.cf-popup-topo h3 {{
    margin:5px 0;
    font-size:17px;
}}

.cf-popup-etiqueta {{
    color:#5eead4;
    font-size:10px;
    font-weight:bold;
}}

.cf-popup-area {{
    font-size:21px;
    font-weight:bold;
    margin-top:8px;
}}

.cf-popup-corpo {{
    max-height:300px;
    overflow-y:auto;
}}

.cf-popup table {{
    width:100%;
    border-collapse:collapse;
    font-size:11px;
}}

.cf-popup td {{
    padding:8px;
    border-bottom:1px solid #e2e8f0;
    vertical-align:top;
    overflow-wrap:anywhere;
}}

.cf-popup-chave {{
    color:#64748b;
    width:45%;
}}

.cf-popup-valor {{
    font-weight:bold;
}}

.cf-popup-rodape {{
    padding:10px;
    font-size:10px;
    color:#64748b;
    background:#f1f5f9;
}}

</style>

<button
    class="cf-abrir"
    id="cf-abrir"
    onclick="
        document.getElementById('cf-painel').style.display='block';
        this.style.display='none';
    "
>
    Abrir painel
</button>

<div class="cf-painel" id="cf-painel">

    <button
        class="cf-fechar"
        onclick="
            document.getElementById('cf-painel').style.display='none';
            document.getElementById('cf-abrir').style.display='block';
        "
    >×</button>

    <div class="cf-etiqueta">
        MONITORAMENTO GEOESPACIAL
    </div>

    <h2>CARBON FORENSICS</h2>

    <div class="cf-subtitulo">
        Reserva Extrativista Chico Mendes<br>
        Acre - Brasil<br>
        PRODES Amazonia Legal - 2026
    </div>

    <div class="cf-cards">

        <div class="cf-card">
            <div class="cf-numero">
                {numero(resumo.get("registros_lidos", 0), 0)}
            </div>
            <div class="cf-descricao">
                Registros analisados
            </div>
        </div>

        <div class="cf-card">
            <div class="cf-numero">
                {numero(total, 0)}
            </div>
            <div class="cf-descricao">
                Intersecoes espaciais
            </div>
        </div>

        <div class="cf-card cf-card-grande">
            <div class="cf-numero">
                {numero(area_unica_valor)} ha
            </div>
            <div class="cf-descricao">
                Area geografica unica
            </div>
        </div>

    </div>

    <h3>DISTRIBUICAO POR CLASSE</h3>

    {barras_html}

    <h3>LEGENDA</h3>

    <div class="cf-legenda">
        <div>
            <span style="color:#38bdf8">■</span>
            Limite da reserva
        </div>
        <div>
            <span style="color:#ef4444">■</span>
            Corte raso - solo exposto
        </div>
        <div>
            <span style="color:#f59e0b">■</span>
            Corte raso - com vegetacao
        </div>
        <div>
            <span style="color:#a855f7">■</span>
            Degradacao progressiva
        </div>
    </div>

    <h3>COMO EXPLORAR</h3>

    <div style="font-size:11px;line-height:1.8;color:#cbd5e1">
        Clique nos poligonos para consultar os registros.<br>
        Use o controle de camadas para trocar o fundo.<br>
        Ative ou desative categorias de desmatamento.<br>
        Use o botao de tela cheia para ampliar a visualizacao.
    </div>

    <div class="cf-rodape">
        <b>Fontes:</b> INPE/PRODES e ICMBio.<br>
        <b>Fundos cartograficos:</b> Esri e colaboradores.<br><br>
        Imagens de fundo podem ter datas diferentes
        das imagens utilizadas pelo PRODES 2026.<br><br>
        As intersecoes espaciais nao comprovam
        ilegalidade, fraude ou vinculacao com
        projetos de credito de carbono.
    </div>

</div>
"""

mapa.get_root().html.add_child(Element(painel_html))


# =====================================================
# 11. SALVAR MAPA
# =====================================================

RESULTADOS.mkdir(exist_ok=True)

saida = RESULTADOS / "mapa_premium.html"

mapa.save(str(saida))

print()
print("=" * 55)
print("MAPA PREMIUM CRIADO COM SUCESSO!")
print("=" * 55)
print("Poligonos:", total)
print("Area unica:", numero(area_unica_valor), "ha")
print("Arquivo:", saida)
print()
print("Abra o HTML no navegador para explorar o mapa.")
