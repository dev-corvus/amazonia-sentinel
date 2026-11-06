from pathlib import Path

import shapefile
import shapely
import pyproj

# Pasta principal do projeto
BASE = Path(__file__).resolve().parent

# Pastas para os dados geograficos
PASTA_DADOS = BASE / "dados_reais"
PASTA_PRODES = PASTA_DADOS / "prodes"
PASTA_RESERVA = PASTA_DADOS / "resex_chico_mendes"
PASTA_RESULTADOS = BASE / "resultados"

# Criar as pastas automaticamente
for pasta in [
    PASTA_DADOS,
    PASTA_PRODES,
    PASTA_RESERVA,
    PASTA_RESULTADOS
]:
    pasta.mkdir(parents=True, exist_ok=True)

print("===================================")
print("CARBON FORENSICS - MVP")
print("===================================")
print("Python e bibliotecas funcionando!")
print("Pastas criadas com sucesso!")
print("Pasta principal:", BASE)
print("Proximo passo: integrar os dados do INPE.")