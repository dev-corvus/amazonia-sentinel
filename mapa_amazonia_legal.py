
# ============================================================
# CARBON FORENSICS - DASHBOARD AMAZONIA LEGAL
# PRODES / TerraBrasilis + IBGE
# ============================================================

import json
import re
from pathlib import Path
from collections import defaultdict, Counter
from html import escape

import folium
import shapefile

from branca.element import Element
from folium.plugins import Fullscreen, MousePosition

from shapely.geometry import shape, mapping
from shapely.ops import transform
from pyproj import CRS, Transformer, Geod


# ============================================================
# 1. CAMINHOS
# ============================================================

BASE = Path(__file__).resolve().parent
DADOS = BASE / "dados_reais"
PRODES = DADOS / "prodes"
RESULTADOS = BASE / "resultados"

RESULTADOS.mkdir(exist_ok=True)

ARQUIVOS = {
    "limite": (
        DADOS / "amazonia_legal"
        / "Limites_Amazonia_Legal_2024.shp"
    ),
    "historico": (
        PRODES
        / "yearly_deforestation_amazonia_legal_v20261016.shp"
    ),
    "hidrografia": (
        PRODES
        / "hydrography_amazonia_legal_v20261016.shp"
    ),
    "mascara_2007": (
        PRODES
        / "accumulated_deforestation_2007_amazonia_legal_v20261016.shp"
    ),
    "residual_2026": (
        PRODES
        / "residual_2026_pri_amazonia_legal_v20261015.shp"
    )
}

SAIDA_HTML = RESULTADOS / "carbon_forensics_dashboard.html"
SAIDA_JSON = RESULTADOS / "carbon_forensics_resumo.json"

# Simplificacao apenas para visualizacao.
# Os calculos de area usam a geometria original.
SIMPLIFICACAO = 0.001

GEOD = Geod(ellps="WGS84")


# ============================================================
# 2. FUNCOES
# ============================================================

def formatar_numero(valor, casas=2):
    return (
        f"{valor:,.{casas}f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def abrir_arquivo(caminho):
    if not caminho.exists():
        raise FileNotFoundError(
            f"Arquivo nao encontrado:\n{caminho}"
        )

    for extensao in [".shx", ".dbf", ".prj"]:
        auxiliar = caminho.with_suffix(extensao)
        if not auxiliar.exists():
            raise FileNotFoundError(
                f"Arquivo auxiliar ausente:\n{auxiliar}"
            )

    leitor = shapefile.Reader(
        str(caminho),
        encoding="latin1",
        encodingErrors="replace"
    )

    prj = caminho.with_suffix(".prj")
    crs_origem = CRS.from_wkt(
        prj.read_text(encoding="utf-8-sig")
    )

    conversor = Transformer.from_crs(
        crs_origem,
        CRS.from_epsg(4326),
        always_xy=True
    )

    campos = [
        item[0] for item in leitor.fields[1:]
    ]

    return leitor, conversor, campos


def extrair_ano(atributos):
    """
    Procura o ano em campos tipicos do PRODES.
    Nao usa datas de processamento como ano de desmatamento.
    """
    candidatos = [
        "year",
        "ano",
        "year_def",
        "year_deforestation",
        "def_year",
        "ano_desmatamento",
        "image_year"
    ]

    atributos_normalizados = {
        str(chave).lower(): valor
        for chave, valor in atributos.items()
    }

    for nome in candidatos:
        valor = atributos_normalizados.get(nome)

        if valor is None:
            continue

        texto = str(valor).strip()

        if re.fullmatch(r"\d{4}(\.0+)?", texto):
            ano = int(float(texto))

            if 1980 <= ano <= 2100:
                return ano

    return None


def extrair_classe(atributos):
    candidatos = [
        "sub_class",
        "subclass",
        "class_name",
        "class",
        "classe"
    ]

    dados = {
        str(chave).lower(): valor
        for chave, valor in atributos.items()
    }

    for nome in candidatos:
        valor = dados.get(nome)

        if valor is not None and str(valor).strip():
            return str(valor)

    return "Nao informada"


def extrair_estado(atributos):
    dados = {
        str(chave).lower(): valor
        for chave, valor in atributos.items()
    }

    for nome in ["state", "uf", "estado"]:
        valor = dados.get(nome)

        if valor is not None and str(valor).strip():
            return str(valor).upper()

    return "Nao informado"


def preparar_atributos(atributos):
    resultado = {}

    for chave, valor in atributos.items():
        if valor is None:
            resultado[str(chave)] = ""
        elif isinstance(valor, (str, int, float, bool)):
            resultado[str(chave)] = valor
        else:
            resultado[str(chave)] = str(valor)

    return resultado


def ler_camada(nome, caminho, calcular_area=False):
    print(f"\nCarregando: {nome}")

    leitor, conversor, campos = abrir_arquivo(caminho)

    print("Registros no arquivo:", len(leitor))
    print("Campos encontrados:", campos)

    features = []
    erros = 0

    for indice, item in enumerate(
        leitor.iterShapeRecords(), start=1
    ):
        try:
            atributos = preparar_atributos(
                dict(zip(campos, list(item.record)))
            )

            geometria = shape(
                item.shape.__geo_interface__
            )

            if geometria.is_empty:
                continue

            geometria = transform(
                conversor.transform,
                geometria
            )

            if geometria.is_empty:
                continue

            # Calcula antes de simplificar.
            area_ha = None

            if calcular_area and geometria.geom_type in [
                "Polygon", "MultiPolygon"
            ]:
                area_m2, _ = GEOD.geometry_area_perimeter(
                    geometria
                )
                area_ha = abs(area_m2) / 10000

            # Reduz o tamanho do HTML sem alterar a area calculada.
            geometria_visual = geometria.simplify(
                SIMPLIFICACAO,
                preserve_topology=True
            )

            if geometria_visual.is_empty:
                continue

            atributos["_cf_id"] = indice
            atributos["_cf_fonte"] = nome

            if area_ha is not None:
                atributos["_cf_area_ha"] = round(
                    area_ha, 4
                )

            ano = extrair_ano(atributos)

            if ano is not None:
                atributos["_cf_ano"] = ano

            atributos["_cf_classe"] = extrair_classe(
                atributos
            )
            atributos["_cf_estado"] = extrair_estado(
                atributos
            )

            features.append({
                "type": "Feature",
                "properties": atributos,
                "geometry": mapping(geometria_visual)
            })

            if indice % 10000 == 0:
                print(
                    f"  {indice} registros examinados..."
                )

        except Exception as erro:
            erros += 1

            if erros <= 5:
                print(
                    f"Aviso no registro {indice}: {erro}"
                )

    leitor.close()

    print("Geometrias carregadas:", len(features))
    print("Registros com erro:", erros)

    return {
        "type": "FeatureCollection",
        "features": features
    }


def estilo_historico(feature):
    classe = str(
        feature["properties"].get(
            "_cf_classe", ""
        )
    ).lower()

    if "solo exposto" in classe:
        cor = "#ef4444"
    elif "veget" in classe:
        cor = "#f59e0b"
    elif "degrad" in classe:
        cor = "#a855f7"
    else:
        cor = "#ff6347"

    return {
        "color": cor,
        "weight": 0.7,
        "fillColor": cor,
        "fillOpacity": 0.58,
        "opacity": 0.8
    }


def estilo_hidrografia(feature):
    return {
        "color": "#38bdf8",
        "weight": 1.3,
        "opacity": 0.9,
        "fillColor": "#38bdf8",
        "fillOpacity": 0.4
    }


def estilo_mascara(feature):
    return {
        "color": "#facc15",
        "weight": 0.3,
        "opacity": 0.4,
        "fillColor": "#facc15",
        "fillOpacity": 0.25
    }


def estilo_residual(feature):
    return {
        "color": "#e879f9",
        "weight": 1,
        "opacity": 0.9,
        "fillColor": "#e879f9",
        "fillOpacity": 0.55
    }


def estilo_limite(feature):
    return {
        "color": "#00BFFF",
        "weight": 4,
        "opacity": 1,
        "fillOpacity": 0
    }


# ============================================================
# 3. CARREGAR DADOS
# ============================================================

print("=" * 65)
print("CARBON FORENSICS - DASHBOARD INTERATIVO")
print("=" * 65)

historico = ler_camada(
    "Incremento anual PRODES",
    ARQUIVOS["historico"],
    calcular_area=True
)

hidrografia = ler_camada(
    "Hidrografia",
    ARQUIVOS["hidrografia"]
)

mascara = ler_camada(
    "Mascara acumulada 2007",
    ARQUIVOS["mascara_2007"]
)

residual = ler_camada(
    "Residual preliminar 2026",
    ARQUIVOS["residual_2026"],
    calcular_area=True
)

limite = ler_camada(
    "Limite Amazonia Legal IBGE 2024",
    ARQUIVOS["limite"]
)


# ============================================================
# 4. INDICADORES HISTORICOS
# ============================================================

areas_por_ano = defaultdict(float)
registros_por_ano = Counter()
areas_por_estado = defaultdict(float)
registros_por_estado = Counter()

sem_ano = 0
total_area_historica = 0.0

for feature in historico["features"]:
    p = feature["properties"]

    area = float(p.get("_cf_area_ha", 0))
    ano = p.get("_cf_ano")
    estado = p.get("_cf_estado", "Nao informado")

    total_area_historica += area
    areas_por_estado[estado] += area
    registros_por_estado[estado] += 1

    if ano is None:
        sem_ano += 1
    else:
        areas_por_ano[ano] += area
        registros_por_ano[ano] += 1

anos = sorted(areas_por_ano)

if not anos:
    print(
        "\nATENCAO: nenhum campo de ano reconhecido."
    )
    print(
        "O mapa funcionara, mas o filtro anual "
        "ficara desabilitado."
    )
else:
    print("\nAnos encontrados:", anos)

print("Registros sem ano:", sem_ano)


# ============================================================
# 5. CRIAR MAPA
# ============================================================

mapa = folium.Map(
    location=[-5.5, -59],
    zoom_start=5,
    tiles=None,
    control_scale=True,
    prefer_canvas=True
)

folium.TileLayer(
    tiles=(
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Imagery/MapServer/tile/{z}/{y}/{x}"
    ),
    attr="Esri",
    name="Satelite",
    overlay=False,
    show=True,
    max_zoom=19
).add_to(mapa)

folium.TileLayer(
    tiles=(
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Topo_Map/MapServer/tile/{z}/{y}/{x}"
    ),
    attr="Esri",
    name="Topografico",
    overlay=False,
    show=False,
    max_zoom=19
).add_to(mapa)

folium.TileLayer(
    tiles=(
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Shaded_Relief/MapServer/tile/{z}/{y}/{x}"
    ),
    attr="Esri",
    name="Relevo",
    overlay=False,
    show=False,
    max_zoom=13
).add_to(mapa)

folium.TileLayer(
    tiles=(
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "Reference/World_Boundaries_and_Places/"
        "MapServer/tile/{z}/{y}/{x}"
    ),
    attr="Esri",
    name="Nomes dos lugares",
    overlay=True,
    show=True
).add_to(mapa)


# ============================================================
# 6. CAMADAS GEOGRAFICAS
# ============================================================

print("\nMontando camadas do mapa...")

camada_historica = folium.FeatureGroup(
    name="Desmatamento anual - historico",
    show=True
)

geo_historico = folium.GeoJson(
    historico,
    name="Poligonos historicos",
    style_function=estilo_historico,
    highlight_function=lambda f: {
        "color": "#ffffff",
        "weight": 2,
        "fillOpacity": 0.85
    },
    smooth_factor=1
)

geo_historico.add_to(camada_historica)
camada_historica.add_to(mapa)

camada_mascara = folium.FeatureGroup(
    name="Mascara acumulada ate 2007",
    show=False
)

folium.GeoJson(
    mascara,
    style_function=estilo_mascara
).add_to(camada_mascara)

camada_mascara.add_to(mapa)

camada_residual = folium.FeatureGroup(
    name="Residual preliminar 2026",
    show=False
)

folium.GeoJson(
    residual,
    style_function=estilo_residual
).add_to(camada_residual)

camada_residual.add_to(mapa)

camada_rios = folium.FeatureGroup(
    name="Hidrografia - rios e corpos d'agua",
    show=False
)

folium.GeoJson(
    hidrografia,
    style_function=estilo_hidrografia
).add_to(camada_rios)

camada_rios.add_to(mapa)

# O limite entra por ultimo para ficar visivel
# sobre as demais camadas.
camada_limite = folium.FeatureGroup(
    name="Limite oficial da Amazonia Legal - azul",
    show=True
)

folium.GeoJson(
    limite,
    style_function=estilo_limite,
    tooltip="Limite oficial IBGE 2024"
).add_to(camada_limite)

camada_limite.add_to(mapa)


# ============================================================
# 7. AJUSTAR EXTENSAO DO MAPA
# ============================================================

bounds = [
    float("inf"),
    float("inf"),
    float("-inf"),
    float("-inf")
]

for feature in limite["features"]:
    geometria = shape(feature["geometry"])

    minx, miny, maxx, maxy = geometria.bounds

    bounds[0] = min(bounds[0], minx)
    bounds[1] = min(bounds[1], miny)
    bounds[2] = max(bounds[2], maxx)
    bounds[3] = max(bounds[3], maxy)

if bounds[0] != float("inf"):
    mapa.fit_bounds([
        [bounds[1], bounds[0]],
        [bounds[3], bounds[2]]
    ])

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


# ============================================================
# 8. DASHBOARD HTML
# ============================================================

opcoes_anos = (
    '<option value="todos">Todos os anos</option>'
)

for ano in anos:
    opcoes_anos += (
        f'<option value="{ano}">{ano}</option>'
    )

if not anos:
    opcoes_anos = (
        '<option value="todos">'
        'Ano nao identificado no arquivo'
        '</option>'
    )

dados_grafico = [
    {
        "ano": ano,
        "area": round(areas_por_ano[ano], 2),
        "registros": registros_por_ano[ano]
    }
    for ano in anos
]

dashboard_html = """
<style>
#cf-dashboard {
    position:fixed;
    top:15px;
    right:15px;
    width:370px;
    max-width:calc(100vw - 30px);
    max-height:92vh;
    overflow-y:auto;
    background:#0f172a;
    color:#e2e8f0;
    border:1px solid #334155;
    border-radius:16px;
    padding:18px;
    z-index:9999;
    font-family:Arial,sans-serif;
    box-sizing:border-box;
    box-shadow:0 15px 40px rgba(0,0,0,.4);
}
#cf-dashboard * {
    box-sizing:border-box;
}
#cf-dashboard h2 {
    margin:0 0 5px;
    font-size:21px;
    color:white;
}
#cf-dashboard h3 {
    font-size:13px;
    margin:20px 0 10px;
    color:#f8fafc;
}
.cf-muted {
    font-size:11px;
    color:#94a3b8;
    line-height:1.6;
}
.cf-grid {
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:9px;
    margin-top:15px;
}
.cf-card {
    background:#1e293b;
    padding:12px;
    border-radius:10px;
    border:1px solid #334155;
}
.cf-number {
    color:white;
    font-size:18px;
    font-weight:bold;
    overflow-wrap:anywhere;
}
.cf-label {
    font-size:10px;
    color:#94a3b8;
    margin-top:5px;
}
#cf-ano {
    width:100%;
    background:#1e293b;
    color:white;
    border:1px solid #475569;
    border-radius:8px;
    padding:10px;
    margin-top:7px;
}
#cf-grafico {
    display:flex;
    align-items:flex-end;
    gap:3px;
    height:115px;
    overflow-x:auto;
    border-bottom:1px solid #475569;
    padding-top:5px;
}
.cf-coluna {
    flex:1 0 7px;
    min-width:7px;
    background:#38bdf8;
    border-radius:3px 3px 0 0;
    cursor:pointer;
}
.cf-coluna:hover {
    background:#facc15;
}
#cf-info {
    background:#1e293b;
    border:1px solid #334155;
    padding:12px;
    border-radius:10px;
    max-height:220px;
    overflow-y:auto;
    overflow-wrap:anywhere;
}
.cf-linha {
    display:flex;
    justify-content:space-between;
    gap:12px;
    padding:6px 0;
    border-bottom:1px solid #334155;
    font-size:11px;
}
.cf-linha span:first-child {
    color:#94a3b8;
}
.cf-linha span:last-child {
    text-align:right;
    font-weight:bold;
}
.cf-aviso {
    margin-top:16px;
    padding-top:12px;
    border-top:1px solid #334155;
    font-size:10px;
    color:#94a3b8;
    line-height:1.6;
}
#cf-toggle {
    position:fixed;
    top:15px;
    right:15px;
    z-index:10000;
    background:#0f172a;
    color:white;
    border:1px solid #334155;
    border-radius:10px;
    padding:10px 14px;
    cursor:pointer;
    display:none;
}
#cf-fechar {
    float:right;
    background:transparent;
    border:0;
    color:white;
    cursor:pointer;
    font-size:20px;
}
</style>

<button id="cf-toggle"
onclick="
document.getElementById('cf-dashboard').style.display='block';
this.style.display='none';
">
Abrir dashboard
</button>

<div id="cf-dashboard">

<button id="cf-fechar"
onclick="
document.getElementById('cf-dashboard').style.display='none';
document.getElementById('cf-toggle').style.display='block';
">×</button>

<h2>CARBON FORENSICS</h2>
<div class="cf-muted">
Amazonia Legal brasileira<br>
INPE / TerraBrasilis + IBGE<br>
Dashboard de analise geoespacial
</div>

<div class="cf-grid">
    <div class="cf-card">
        <div class="cf-number" id="cf-total-registros">--</div>
        <div class="cf-label">Poligonos historicos</div>
    </div>
    <div class="cf-card">
        <div class="cf-number" id="cf-total-area">--</div>
        <div class="cf-label">Soma das areas (ha)</div>
    </div>
    <div class="cf-card">
        <div class="cf-number" id="cf-ano-selecionado">Todos</div>
        <div class="cf-label">Ano selecionado</div>
    </div>
    <div class="cf-card">
        <div class="cf-number" id="cf-registros-selecionados">--</div>
        <div class="cf-label">Registros do filtro</div>
    </div>
</div>

<h3>FILTRO POR ANO</h3>
<select id="cf-ano">
__OPCOES_ANOS__
</select>

<h3>EVOLUCAO ANUAL DO DESMATAMENTO</h3>
<div id="cf-grafico"></div>
<div class="cf-muted">
Passe o mouse sobre as barras para consultar
a area calculada de cada ano.
Clique numa barra para filtrar o mapa.
</div>

<h3>INFORMACOES DA AREA SOB O CURSOR</h3>
<div id="cf-info">
    <div class="cf-muted">
        Passe o mouse sobre um poligono colorido
        do mapa para consultar os atributos oficiais.
    </div>
</div>

<div class="cf-aviso">
    A borda azul representa a Amazonia Legal do IBGE.
    Os dados historicos e residuais sao camadas distintas.
    A mascara de 2007 nao e um incremento anual.
    As areas apresentadas sao somas de areas geodesicas
    dos poligonos, nao areas unicas dissolvidas.
    A presenca de desmatamento nao comprova
    ilegalidade ou fraude em creditos de carbono.
</div>

</div>
"""

dashboard_html = dashboard_html.replace(
    "__OPCOES_ANOS__",
    opcoes_anos
)

mapa.get_root().html.add_child(
    Element(dashboard_html)
)


# ============================================================
# 9. JAVASCRIPT INTERATIVO
# ============================================================

dados_js = {
    "grafico": dados_grafico,
    "totalRegistros": len(historico["features"]),
    "totalArea": round(total_area_historica, 2),
    "semAno": sem_ano
}

javascript = """
(function() {

const mapa = __MAPA__;
const historico = __HISTORICO__;
const dados = __DADOS__;

const painel = document.getElementById("cf-info");
const seletor = document.getElementById("cf-ano");

const formato = new Intl.NumberFormat("pt-BR", {
    maximumFractionDigits:2
});

document.getElementById("cf-total-registros").textContent =
    formato.format(dados.totalRegistros);

document.getElementById("cf-total-area").textContent =
    formato.format(dados.totalArea);

const grafico = document.getElementById("cf-grafico");

const maior = Math.max(
    1,
    ...dados.grafico.map(item => item.area)
);

dados.grafico.forEach(function(item) {
    const barra = document.createElement("div");

    barra.className = "cf-coluna";

    barra.style.height =
        Math.max(2, item.area / maior * 100) + "%";

    barra.title =
        item.ano + ": " +
        formato.format(item.area) + " ha | " +
        formato.format(item.registros) + " registros";

    barra.onclick = function() {
        seletor.value = String(item.ano);
        aplicarFiltro();
    };

    grafico.appendChild(barra);
});

function linha(rotulo, valor) {
    const div = document.createElement("div");
    div.className = "cf-linha";

    const esquerda = document.createElement("span");
    esquerda.textContent = rotulo;

    const direita = document.createElement("span");
    direita.textContent =
        valor === null ||
        valor === undefined ||
        valor === "" ? "Nao informado" : String(valor);

    div.appendChild(esquerda);
    div.appendChild(direita);

    painel.appendChild(div);
}

function mostrarAtributos(props) {
    painel.replaceChildren();

    const nomes = {
        "_cf_id":"Registro",
        "_cf_fonte":"Fonte",
        "_cf_area_ha":"Area calculada (ha)",
        "_cf_ano":"Ano",
        "_cf_classe":"Classificacao",
        "_cf_estado":"Estado"
    };

    const prioridades = [
        "_cf_id",
        "_cf_ano",
        "_cf_area_ha",
        "_cf_classe",
        "_cf_estado",
        "_cf_fonte"
    ];

    prioridades.forEach(function(chave) {
        if (props[chave] !== undefined) {
            let valor = props[chave];

            if (chave === "_cf_area_ha") {
                valor = formato.format(Number(valor));
            }

            linha(nomes[chave], valor);
        }
    });

    Object.entries(props).forEach(function(entrada) {
        const chave = entrada[0];
        const valor = entrada[1];

        if (!chave.startsWith("_cf_")) {
            linha(chave, valor);
        }
    });
}

function limparPainel() {
    painel.replaceChildren();

    const aviso = document.createElement("div");
    aviso.className = "cf-muted";
    aviso.textContent =
        "Passe o mouse sobre um poligono colorido " +
        "para consultar suas informacoes.";

    painel.appendChild(aviso);
}

// Guardamos as referencias das feicoes historicas.
const feicoes = [];

historico.eachLayer(function(layer) {
    if (!layer.feature) {
        return;
    }

    const props = layer.feature.properties || {};

    feicoes.push({
        layer:layer,
        props:props
    });

    layer.on("mouseover", function() {
        mostrarAtributos(props);
    });

    layer.on("mouseout", function() {
        limparPainel();
    });
});

function aplicarFiltro() {
    const selecionado = seletor.value;

    let quantidade = 0;
    let area = 0;

    // Remove ou reinsere as feicoes no grupo GeoJSON.
    // Assim o filtro altera efetivamente o mapa.
    feicoes.forEach(function(item) {
        const ano = item.props._cf_ano;

        const mostrar =
            selecionado === "todos" ||
            String(ano) === selecionado;

        const presente = historico.hasLayer(item.layer);

        if (mostrar) {
            quantidade++;

            area += Number(
                item.props._cf_area_ha || 0
            );

            if (!presente) {
                historico.addLayer(item.layer);
            }
        } else if (presente) {
            historico.removeLayer(item.layer);
        }
    });

    document.getElementById(
        "cf-ano-selecionado"
    ).textContent =
        selecionado === "todos" ?
        "Todos" : selecionado;

    document.getElementById(
        "cf-registros-selecionados"
    ).textContent = formato.format(quantidade);

    // Atualiza o indicador de area para o filtro.
    document.getElementById(
        "cf-total-area"
    ).textContent = formato.format(area);

    limparPainel();
}

seletor.addEventListener("change", aplicarFiltro);

aplicarFiltro();

})();
"""

javascript = javascript.replace(
    "__MAPA__",
    mapa.get_name()
)

javascript = javascript.replace(
    "__HISTORICO__",
    geo_historico.get_name()
)

javascript = javascript.replace(
    "__DADOS__",
    json.dumps(dados_js, ensure_ascii=False)
)

mapa.get_root().script.add_child(
    Element(javascript)
)


# ============================================================
# 10. SALVAR
# ============================================================

resumo = {
    "fontes": {
        chave: str(caminho)
        for chave, caminho in ARQUIVOS.items()
    },
    "historico": {
        "registros": len(historico["features"]),
        "soma_areas_ha": round(
            total_area_historica, 2
        ),
        "registros_sem_ano": sem_ano,
        "por_ano": {
            str(ano): {
                "registros": registros_por_ano[ano],
                "soma_areas_ha": round(
                    areas_por_ano[ano], 2
                )
            }
            for ano in anos
        },
        "por_estado": {
            estado: {
                "registros": registros_por_estado[estado],
                "soma_areas_ha": round(
                    areas_por_estado[estado], 2
                )
            }
            for estado in areas_por_estado
        }
    },
    "camadas": {
        "hidrografia": len(
            hidrografia["features"]
        ),
        "mascara_2007": len(
            mascara["features"]
        ),
        "residual_2026": len(
            residual["features"]
        ),
        "limite": len(
            limite["features"]
        )
    },
    "observacao": (
        "Areas calculadas por poligono, "
        "sem dissolucao de sobreposicoes."
    )
}

SAIDA_JSON.write_text(
    json.dumps(
        resumo,
        ensure_ascii=False,
        indent=2
    ),
    encoding="utf-8"
)

print("\nSalvando mapa HTML...")
mapa.save(str(SAIDA_HTML))

print("\n" + "=" * 65)
print("CARBON FORENSICS - DASHBOARD CRIADO!")
print("=" * 65)

print("Historico:", len(historico["features"]))
print("Anos identificados:", anos)
print("Registros sem ano:", sem_ano)

print(
    "Soma das areas historicas:",
    formatar_numero(total_area_historica),
    "ha"
)

print("\nMapa salvo em:")
print(SAIDA_HTML)

print("\nResumo salvo em:")
print(SAIDA_JSON)

print("\nPROCESSAMENTO CONCLUIDO!")
    