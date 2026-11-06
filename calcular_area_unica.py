
import json
from pathlib import Path

from pyproj import Geod
from shapely.geometry import shape
from shapely.ops import unary_union

BASE = Path(__file__).resolve().parent

ARQUIVO = BASE / "resultados" / "intersecoes_prodes.geojson"

print("CARBON FORENSICS - AREA GEOGRAFICA UNICA")

with ARQUIVO.open(encoding="utf-8") as arquivo:
    dados = json.load(arquivo)

geometrias = [
    shape(feicao["geometry"])
    for feicao in dados["features"]
]

print("Geometrias carregadas:", len(geometrias))

# Unir as geometrias para eliminar sobreposicoes
area_unificada = unary_union(geometrias)

# Calcular area geodesica em hectares
geod = Geod(ellps="WGS84")
area_m2, _ = geod.geometry_area_perimeter(area_unificada)
area_unica_ha = abs(area_m2) / 10000

# Comparar com a soma anterior
RESUMO = BASE / "resultados" / "resumo.json"

with RESUMO.open(encoding="utf-8") as arquivo:
    resumo_anterior = json.load(arquivo)

soma_ha = resumo_anterior["soma_areas_ha"]
diferenca = soma_ha - area_unica_ha

resultado = {
    "geometrias_analisadas": len(geometrias),
    "soma_areas_ha": soma_ha,
    "area_unica_ha": round(area_unica_ha, 2),
    "diferenca_ha": round(diferenca, 2),
    "observacao": (
        "Area geografica unica das intersecoes PRODES. "
        "Nao comprova ilegalidade ou fraude."
    )
}

saida = BASE / "resultados" / "area_unica.json"

saida.write_text(
    json.dumps(resultado, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print()
print("CALCULO CONCLUIDO!")
print("Soma das areas (ha):", soma_ha)
print("Area unica (ha):", round(area_unica_ha, 2))
print("Diferenca (ha):", round(diferenca, 2))
print("Resultado salvo em:", saida)
