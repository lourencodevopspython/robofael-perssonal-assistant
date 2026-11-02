# Avatares

As duas ilustrações do avatar fazem parte do repositório:

| Arquivo | O que é |
|---|---|
| `cracha.png` | Ilustração de 500×500, **sem fundo** (PNG com transparência), braços cruzados |
| `selfie.png` | Ilustração de 500×500, sem fundo, de frente |

As posições do rosto (topo e centro da cabeça, boca, queixo e pescoço) de cada imagem ficam em
[`src/robofael/avatar/catalogo.py`](../../src/robofael/avatar/catalogo.py). Nas ilustrações a boca já está aberta
num sorriso, então o ponto `boca` fica na fresta entre os dentes de cima e os de baixo: é ali que a fala abre o vão.

Para trocar uma imagem, mantenha o fundo transparente, meça os pontos de novo e confira com `make previa`.
Opcionalmente, `arquivo_hd` no catálogo aponta para a mesma imagem em resolução maior, ainda com fundo: o recorte
da PNG é aplicado sobre ela para dar mais nitidez.

Qualquer outro arquivo desta pasta (originais, rascunhos) é ignorado pelo git.
