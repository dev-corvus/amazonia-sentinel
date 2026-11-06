
import csv
import json
from pathlib import Path

import shapefile
from pyproj import CRS, Geod, Transformer
from shapely.geometry import shape, mapping
from shapely.ops import transform

BASE = Path(__file__).resolve().parent

PASTA_PRODES = BASE / "dados_reais" / "prodes"
ARQUIVO_LIMITE = (
    BASE / "dados_reais" / "resex_chico_mendes" / "limite.geojson"
)
PASTA_RESULTADOS = BASE / "resultados"
PASTA_RESULTADOS.mkdir(parents=True, exist_ok=True)

print("CARBON FORENSICS - ANALISE PRODES")

# Ler limite da reserva
with ARQUIVO_LIMITE.open(encoding="utf-8") as arquivo:
    dados_limite = json.load(arquivo)

limite = shape(dados_limite["features"][0]["geometry"])

# Selecionar somente o PRODES anual
arquivos = sorted(
    PASTA_PRODES.glob("yearly_deforestation_*.shp")
)

if not arquivos:
    raise FileNotFoundError(
        "Arquivo yearly_deforestation SHP nao encontrado."
    )

geod = Geod(ellps="WGS84")

resultados = []
feicoes = []
total_lidos = 0

for caminho in arquivos:
    print("Lendo:", caminho.name)

    caminho_prj = caminho.with_suffix(".prj")

    if not caminho_prj.exists():
        raise FileNotFoundError(
            f"Arquivo PRJ nao encontrado: {caminho_prj}"
        )

    crs_origem = CRS.from_wkt(
        caminho_prj.read_text(encoding="utf-8-sig")
    )

    conversor = Transformer.from_crs(
        crs_origem,
        CRS.from_epsg(4326),
        always_xy=True
    )

    with shapefile.Reader(str(caminho), encoding="latin1") as leitor:
        campos = [campo[0] for campo in leitor.fields[1:]]

        for numero, registro in enumerate(
            leitor.iterShapeRecords(), start=1
        ):
            total_lidos += 1

            geometria = shape(
                registro.shape.__geo_interface__
            )

            if geometria.is_empty:
                continue

            geometria = transform(
                conversor.transform,
                geometria
            )

            if not geometria.is_valid:
                continue

            if not limite.intersects(geometria):
                continue

            intersecao = limite.intersection(geometria)

            if intersecao.is_empty:
                continue

            area_m2, _ = geod.geometry_area_perimeter(
                intersecao
            )
            area_ha = abs(area_m2) / 10000

            if area_ha <= 0:
                continue

            atributos = dict(
                zip(campos, registro.record)
            )

            identificador = f"{caminho.stem}_{numero}"

            resultados.append({
                "id": identificador,
                "area_ha": round(area_ha, 4),
                "atributos": json.dumps(
                    atributos,
                    ensure_ascii=False,
                    default=str
                )
            })

            feicoes.append({
                "type": "Feature",
                "properties": {
                    "id": identificador,
                    "area_ha": round(area_ha, 4),
                    **{
                        chave: str(valor)
                        for chave, valor in atributos.items()
                    }
                },
                "geometry": mapping(intersecao)
            })

# Salvar tabela CSV
with (PASTA_RESULTADOS / "intersecoes_prodes.csv").open(
    "w", newline="", encoding="utf-8-sig"
) as arquivo:
    escritor = csv.DictWriter(
        arquivo,
        fieldnames=["id", "area_ha", "atributos"]
    )
    escritor.writeheader()
    escritor.writerows(resultados)

# Salvar GeoJSON
(PASTA_RESULTADOS / "intersecoes_prodes.geojson").write_text(
    json.dumps(
        {"type": "FeatureCollection", "features": feicoes},
        ensure_ascii=False,
        indent=2
    ),
    encoding="utf-8"
)

# Salvar resumo
resumo = {
    "registros_lidos": total_lidos,
    "intersecoes_encontradas": len(resultados),
    "soma_areas_ha": round(
        sum(item["area_ha"] for item in resultados), 2
    ),
    "observacao": (
        "Soma de intersecoes, nao necessariamente area unica. "
        "Nao comprova fraude ou ilegalidade."
    )
}

(PASTA_RESULTADOS / "resumo.json").write_text(
    json.dumps(resumo, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print("\nANALISE CONCLUIDA!")
print("Registros lidos:", total_lidos)
print("Intersecoes encontradas:", len(resultados))
print("Soma das areas (ha):", resumo["soma_areas_ha"])
print("Resultados salvos em:", PASTA_RESULTADOS)


