PY ?= .venv/bin/python
ARGS ?=

.DEFAULT_GOAL := ajuda
.PHONY: midia monografia deb testar-deb integridade baixar-modelo-voz ajuda instalar executar gravar-voz testar testar-rapido cobertura lint formatar tipos verificar previa limpar

ajuda:             ## Lista os comandos disponíveis
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

instalar:          ## Cria o .venv e instala o projeto + ferramentas de desenvolvimento
	python3 -m venv --system-site-packages .venv
	$(PY) -m pip install -e ".[dev]"
	-.venv/bin/pre-commit install
	$(MAKE) baixar-modelo-voz

executar:          ## Abre o assistente (ex.: make executar ARGS="--avatar selfie --continuo")
	$(PY) -m robofael $(ARGS)

gravar-voz:        ## Abre a tela para registrar a sua voz
	$(PY) -m robofael.apresentacao.gravador

testar:            ## Todos os testes
	$(PY) -m pytest

testar-rapido:     ## Testes sem renderização de imagem nem interface
	$(PY) -m pytest -m "not lento"

cobertura:         ## Testes com relatório de cobertura
	$(PY) -m pytest --cov --cov-report=term-missing

lint:              ## Estilo e erros comuns (ruff)
	$(PY) -m ruff check src tests

formatar:          ## Corrige automaticamente o que for possível
	$(PY) -m ruff check src tests --fix

tipos:             ## Checagem de tipos (mypy)
	$(PY) -m mypy

verificar: lint tipos testar  ## Tudo o que a CI roda

midia:             ## Refaz os prints e GIFs do README (docs/imagens) a partir do app real
	$(PY) scripts/capturar_midia.py docs/imagens

previa:            ## Gera prévias dos avatares (previa_<nome>.png)
	$(PY) -c "from robofael.avatar import AVATARES; from robofael.avatar.renderizador import gerar_previa; [gerar_previa(n, f'previa_{n}.png') for n in AVATARES]"

limpar:            ## Apaga caches gerados (não toca em dados/)
	rm -rf .cache .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	find . -path ./.venv -prune -o -name __pycache__ -type d -prune -exec rm -rf {} +

MODELO_VOZ := vosk-model-small-pt-0.3
baixar-modelo-voz: ## Baixa o modelo local (~31 MB) usado para ouvir "ok Fael"
	@mkdir -p modelos
	@if [ -d modelos/$(MODELO_VOZ) ]; then echo "Modelo já instalado em modelos/$(MODELO_VOZ)"; else \
		tmp=$$(mktemp -d) && curl -fSL -o $$tmp/m.zip https://alphacephei.com/vosk/models/$(MODELO_VOZ).zip && \
		unzip -q $$tmp/m.zip -d $$tmp/x && mv $$tmp/x/$(MODELO_VOZ) modelos/ && rm -rf $$tmp && \
		echo "Modelo instalado em modelos/$(MODELO_VOZ)"; fi

integridade:       ## Verifica a cadeia de hashes do histórico auditável (o banco em uso, ⚙ → Memória)
	@$(PY) -c "from robofael.adaptadores.sqlite import BancoSqlite; from robofael.configuracao import Configuracao; \
	r = BancoSqlite(Configuracao.do_ambiente().arquivo_banco).verificar_integridade(); \
	print(('Histórico íntegro: %d registros' % r.registros) if r.ok else ('ADULTERADO no registro %s: %s' % (r.primeiro_problema, r.motivo))); \
	raise SystemExit(0 if r.ok else 1)"

deb:               ## Constrói o instalador para Ubuntu (dist/robofael_<versão>_<arq>.deb)
	empacotamento/construir_deb.sh

testar-deb: deb    ## Constrói e testa o .deb sem instalar no sistema (instala numa pasta temporária)
	empacotamento/testar_deb.sh

monografia:        ## Gera a monografia (TCC no padrão ABNT) em docs/monografia/monografia.pdf
	cd docs/monografia && mkdir -p build && for i in 1 2 3; do \
		xelatex -interaction=nonstopmode -halt-on-error -output-directory=build monografia.tex > /dev/null \
		|| { grep -A5 '^!' build/monografia.log; exit 1; }; done
	cp docs/monografia/build/monografia.pdf docs/monografia/monografia.pdf
