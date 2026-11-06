from pathlib import Path

pasta = Path(__file__).resolve().parent
origem = pasta / "resultados" / "mapa_carbon_forensics.html"
destino = pasta / "resultados" / "mapa_com_painel.html"

html = origem.read_text(encoding="utf-8")

painel = """
<div style="
position:fixed;
top:20px;
right:20px;
width:280px;
max-width:75vw;
max-height:80vh;
overflow-y:auto;
background:white;
padding:16px;
border-radius:10px;
box-shadow:0 2px 12px #888;
z-index:9999;
font-family:Arial;
font-size:13px;
">
<h2>Carbon Forensics</h2>
<p><b>PRODES 2026</b></p>
<p>Registros analisados: <b>26.381</b></p>
<p>Intersecoes: <b>367</b></p>
<p>Area geografica unica: <b>1.519,58 ha</b></p>
<hr>
<h3>Legenda</h3>
<p style="color:#1565C0">■ Limite da reserva</p>
<p style="color:#D32F2F">■ Corte raso com solo exposto</p>
<p style="color:#FF9800">■ Corte raso com vegetacao</p>
<p style="color:#8E24AA">■ Degradacao progressiva</p>
<hr>
<small>
Fontes: INPE/PRODES e ICMBio.
As intersecoes nao comprovam ilegalidade
ou fraude de carbono.
</small>
</div>
"""

if "</body>" not in html:
    raise RuntimeError("Nao foi encontrado o final do HTML.")

html = html.replace("</body>", painel + "\n</body>", 1)
destino.write_text(html, encoding="utf-8")

print("PAINEL CRIADO COM SUCESSO!")
print("Arquivo:", destino)
