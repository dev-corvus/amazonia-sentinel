
from pathlib import Path
import json
import re

BASE = Path(__file__).resolve().parent
RESULTADOS = BASE / "resultados"

ORIGEM = RESULTADOS / "mapa_amazonia_legal.html"
DESTINO = RESULTADOS / "mapa_dashboard.html"

if not ORIGEM.exists():
    raise FileNotFoundError(
        "Execute primeiro mapa_amazonia_legal.py"
    )

html = ORIGEM.read_text(encoding="utf-8")

# Encontrar o nome da variavel do mapa Folium
resultado = re.search(
    r"var\s+(map_[a-f0-9]+)\s*=\s*L\.map\(",
    html
)

if not resultado:
    raise RuntimeError(
        "Nao foi possivel identificar o mapa Folium."
    )

nome_mapa = resultado.group(1)

dashboard = """
<style>
#cf-hover-dashboard {
    position:fixed;
    left:18px;
    bottom:35px;
    z-index:9999;
    width:300px;
    max-width:calc(100vw - 36px);
    background:#0f172a;
    color:#e2e8f0;
    border:1px solid #334155;
    border-radius:16px;
    box-shadow:0 12px 35px rgba(0,0,0,.4);
    padding:18px;
    font-family:Arial,sans-serif;
    box-sizing:border-box;
    pointer-events:none;
}
#cf-hover-dashboard h3 {
    margin:0 0 8px;
    font-size:16px;
    color:#fff;
}
#cf-hover-dashboard .cf-hint {
    font-size:12px;
    color:#94a3b8;
    line-height:1.6;
}
#cf-hover-dashboard .cf-row {
    display:flex;
    justify-content:space-between;
    gap:12px;
    padding:7px 0;
    border-bottom:1px solid #334155;
    font-size:12px;
}
#cf-hover-dashboard .cf-row span:first-child {
    color:#94a3b8;
}
#cf-hover-dashboard .cf-row span:last-child {
    font-weight:bold;
    text-align:right;
    overflow-wrap:anywhere;
}
</style>

<div id="cf-hover-dashboard">
    <h3>Investigação geoespacial</h3>
    <div class="cf-hint">
        Passe o mouse sobre um polígono colorido
        para consultar suas informações.
    </div>
    <div id="cf-hover-info"></div>
</div>
"""

script = """
<script>
(function() {
    const mapa = window[__MAP_NAME__];

    if (!mapa) {
        console.warn("Mapa Folium nao encontrado.");
        return;
    }

    const painel = document.getElementById("cf-hover-info");
    const dica = document.querySelector(
        "#cf-hover-dashboard .cf-hint"
    );

    function adicionarLinha(rotulo, valor) {
        const linha = document.createElement("div");
        linha.className = "cf-row";

        const nome = document.createElement("span");
        nome.textContent = rotulo;

        const dado = document.createElement("span");
        dado.textContent =
            valor === null || valor === undefined ||
            valor === "" ? "Nao informado" : String(valor);

        linha.appendChild(nome);
        linha.appendChild(dado);
        painel.appendChild(linha);
    }

    function mostrar(dados) {
        painel.replaceChildren();
        dica.style.display = "none";

        Object.entries(dados).forEach(([chave, valor]) => {
            adicionarLinha(chave, valor);
        });
    }

    function limpar() {
        painel.replaceChildren();
        dica.style.display = "block";
    }

    // Cada GeoJson do Folium contem uma camada por poligono.
    // A versao original gera um GeoJson por registro.
    mapa.eachLayer(function(camada) {
        if (!(camada instanceof L.GeoJSON)) {
            return;
        }

        camada.eachLayer(function(poligono) {
            if (!poligono.feature) {
                return;
            }

            // Os atributos podem estar no popup gerado pelo Python.
            // Recuperamos o conteudo da tabela existente.
            poligono.on("mouseover", function() {
                const popup = poligono.getPopup();

                if (!popup) {
                    return;
                }

                const conteudo = popup.getContent();
                const temporario = document.createElement("div");

                if (typeof conteudo === "string") {
                    temporario.innerHTML = conteudo;
                } else if (conteudo instanceof HTMLElement) {
                    temporario.appendChild(conteudo.cloneNode(true));
                }

                const dados = {};

                temporario.querySelectorAll("tr").forEach(function(tr) {
                    const colunas = tr.querySelectorAll("td");

                    if (colunas.length >= 2) {
                        const chave = colunas[0].textContent.trim();
                        const valor = colunas[1].textContent.trim();
                        dados[chave] = valor;
                    }
                });

                if (Object.keys(dados).length > 0) {
                    mostrar(dados);
                }
            });

            poligono.on("mouseout", limpar);
        });
    });
})();
</script>
"""

script = script.replace(
    "__MAP_NAME__",
    json.dumps(nome_mapa)
)

if 'id="cf-hover-dashboard"' in html:
    raise RuntimeError(
        "Este mapa ja possui o dashboard interativo."
    )

# O painel visual fica no corpo da pagina.
html = html.replace(
    "</body>",
    dashboard + "\n</body>",
    1
)

# O JavaScript deve executar depois da inicializacao do mapa.
html += "\n" + script

DESTINO.write_text(html, encoding="utf-8")

print("=" * 55)
print("DASHBOARD INTERATIVO CRIADO COM SUCESSO!")
print("=" * 55)
print("Arquivo:", DESTINO)
