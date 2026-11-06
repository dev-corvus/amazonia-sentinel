from pathlib import Path

arquivo = Path("criar_mapa.py")
codigo = arquivo.read_text(encoding="utf-8-sig")

if "import adicionar_painel" in codigo:
    print("O painel automatico ja esta configurado!")
else:
    codigo += """

# Gerar automaticamente a versao com painel
import adicionar_painel
"""
    arquivo.write_text(codigo, encoding="utf-8")
    print("PAINEL AUTOMATICO CONFIGURADO!")
