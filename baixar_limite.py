
import hashlib
import json
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from pyproj import Geod
from shapely.geometry import Polygon, mapping
from shapely.ops import unary_union

BASE = Path(__file__).resolve().parent
PASTA = BASE / "dados_reais" / "resex_chico_mendes"
PASTA.mkdir(parents=True, exist_ok=True)

URL = (
    "https://www.gov.br/icmbio/pt-br/assuntos/biodiversidade/"
    "unidade-de-conservacao/unidades-de-biomas/amazonia/"
    "lista-de-ucs/resex-chico-mendes/arquivos/"
    "resex_chico_mendes.kml"
)

print("Baixando limite oficial do ICMBio...")

requisicao = urllib.request.Request(
    URL,
    headers={"User-Agent": "Mozilla/5.0"}
)

with urllib.request.urlopen(requisicao, timeout=60) as resposta:
    conteudo = resposta.read()

(PASTA / "limite_original.kml").write_bytes(conteudo)

raiz = ET.fromstring(conteudo)


def ler_coordenadas(elemento):
    for item in elemento.iter():
        if item.tag.split("}")[-1] == "coordinates":
            if not item.text:
                continue

            pontos = []
            for ponto in item.text.strip().split():
                partes = ponto.split(",")
                pontos.append((
                    float(partes[0]),
                    float(partes[1])
                ))
            return pontos

    return []


poligonos = []

for elemento in raiz.iter():
    if elemento.tag.split("}")[-1] != "Polygon":
        continue

    exterior = []
    buracos = []

    for parte in elemento:
        nome = parte.tag.split("}")[-1]

        if nome == "outerBoundaryIs":
            exterior = ler_coordenadas(parte)

        elif nome == "innerBoundaryIs":
            anel = ler_coordenadas(parte)
            if len(anel) >= 4:
                buracos.append(anel)

    if len(exterior) >= 4:
        poligono = Polygon(exterior, holes=buracos)

        if not poligono.is_valid:
            raise ValueError(
                "O KML contem um poligono invalido."
            )

        poligonos.append(poligono)

if not poligonos:
    raise RuntimeError("Nenhum poligono encontrado no KML.")

limite = unary_union(poligonos)

geod = Geod(ellps="WGS84")
area_m2, _ = geod.geometry_area_perimeter(limite)
area_ha = abs(area_m2) / 10000

geojson = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {
            "nome": "Reserva Extrativista Chico Mendes",
            "fonte": URL,
            "area_ha": round(area_ha, 2),
            "projeto_carbono": False
        },
        "geometry": mapping(limite)
    }]
}

saida = PASTA / "limite.geojson"

saida.write_text(
    json.dumps(geojson, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print("Limite salvo com sucesso!")
print("Arquivo:", saida)
print("Area calculada (ha):", round(area_ha, 2))
print("SHA256:", hashlib.sha256(conteudo).hexdigest())
