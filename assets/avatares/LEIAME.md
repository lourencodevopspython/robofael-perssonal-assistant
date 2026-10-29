# Fotos do avatar

As fotos do avatar são pessoais e **não fazem parte do repositório**. Para rodar o Robofael, coloque aqui:

| Arquivo | O que é |
|---|---|
| `cracha.png` | Foto de rosto **sem fundo** (PNG com transparência) |
| `selfie.png` | Outra foto de rosto sem fundo |
| `selfie_hd.jpeg` | (Opcional) a mesma selfie em alta resolução, ainda com fundo: o recorte da PNG é aplicado sobre ela para dar mais nitidez |

As posições do rosto (topo e centro da cabeça, boca, queixo e pescoço) de cada foto ficam em
[`src/robofael/avatar/catalogo.py`](../../src/robofael/avatar/catalogo.py). Com fotos novas, meça esses pontos e
ajuste o catálogo; `make previa` gera uma imagem para conferir o resultado.

Sem as fotos o assistente funciona (voz, agenda, memória), mas sem o avatar, e os testes que renderizam o
avatar são pulados.
