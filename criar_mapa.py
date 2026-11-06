
import json
from pathlib import Path

import folium
from shapely.geometry import shape

BASE = Path(__file__).resolve().parent
RESULTADOS = BASE / "resultados"

ARQUIVO_LIMITE = (
    BASE / "dados_reais" / "resex_chico_mendes" / "limite.geojson"
)

ARQUIVO_PRODES = (
    RESULTADOS / "intersecoes_prodes.geojson"
)

print("CARBON FORENSICS - MAPA INTERATIVO")

# Carregar limite da reserva
with ARQUIVO_LIMITE.open(encoding="utf-8") as arquivo:
    limite = json.load(arquivo)

# Carregar intersecoes do PRODES
with ARQUIVO_PRODES.open(encoding="utf-8") as arquivo:
    prodes = json.load(arquivo)

# Calcular o centro aproximado da reserva
geometria_reserva = shape(limite["features"][0]["geometry"])
centro = geometria_reserva.centroid

mapa = folium.Map(
    location=[centro.y, centro.x],
    zoom_start=9,
    tiles=None
)
    
# Camada do limite da reserva
folium.GeoJson(
    limite,
    name="Limite da Reserva Chico Mendes",
    style_function=lambda feature: {
        "color": "#1565C0",
        "weight": 3,
        "fillColor": "#2196F3",
        "fillOpacity": 0.08
    }
).add_to(mapa)

# Cores por tipo de desmatamento
cores = {
    "corte raso com solo exposto": "#D32F2F",
    "corte raso com vegetação": "#FF9800",
    "desmatamento por degradação progressiva": "#8E24AA"
}

# Adicionar as intersecoes
for feicao in prodes["features"]:
    propriedades = feicao["properties"]

    classe = propriedades.get(
        "sub_class", "Nao informada"
    )

    cor = cores.get(classe, "#616161")

    area = propriedades.get("area_ha", 0)
    ano = propriedades.get("year", "Nao informado")
    data = propriedades.get("image_date", "Nao informada")

    descricao = (
        f"<b>Classe:</b> {classe}<br>"
        f"<b>Area de intersecao:</b> {area} ha<br>"
        f"<b>Ano:</b> {ano}<br>"
        f"<b>Data da imagem:</b> {data}"
    )

    folium.GeoJson(
        feicao,
        style_function=lambda feature, cor=cor: {
            "color": cor,
            "weight": 1.5,
            "fillColor": cor,
            "fillOpacity": 0.6
        },
        tooltip=folium.Tooltip(descricao)
    ).add_to(mapa)

folium.LayerControl().add_to(mapa)

# Ajustar visualizacao ao limite da reserva
minx, miny, maxx, maxy = geometria_reserva.bounds
mapa.fit_bounds([[miny, minx], [maxy, maxx]])

# Salvar mapa
saida = RESULTADOS / "mapa_carbon_forensics.html"
mapa.save(str(saida))

print("MAPA CRIADO COM SUCESSO!")
print("Intersecoes no mapa:", len(prodes["features"]))
print("Arquivo:", saida)


# Gerar automaticamente a versao com painel
import adicionar_painel
