#!/usr/bin/env bash
# Constrói o pacote .deb do Robofael para a versão do Python desta máquina (Ubuntu 24.04: 3.12).
# Uso: empacotamento/construir_deb.sh   -> dist/robofael_<versão>_<arquitetura>.deb
set -euo pipefail
cd "$(dirname "$0")/.."
RAIZ="$PWD"
PY="${PY:-.venv/bin/python}"
VERSAO=$("$PY" -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
ARQ=$(dpkg --print-architecture)
MODELO="vosk-model-small-pt-0.3"
CONSTRUCAO="$(mktemp -d)"
PACOTE="$CONSTRUCAO/robofael"
trap 'rm -rf "$CONSTRUCAO"' EXIT

echo "==> Robofael $VERSAO ($ARQ)"
[ -d "modelos/$MODELO" ] || make baixar-modelo-voz

OPT="$PACOTE/opt/robofael"
mkdir -p "$OPT/wheels" "$OPT/modelos" "$PACOTE/usr/bin" "$PACOTE/usr/share/applications" \
         "$PACOTE/usr/share/doc/robofael" "$PACOTE/DEBIAN"

echo "==> Dependências Python (wheels, para instalar sem internet)"
"$PY" -m pip wheel --quiet --no-deps --wheel-dir "$OPT/wheels" "$RAIZ"
# Todas as dependências, exceto o PyAudio, que vem do apt (python3-pyaudio)
"$PY" - > "$CONSTRUCAO/requisitos.txt" <<'PYEOF'
import re, tomllib
for dep in tomllib.load(open("pyproject.toml", "rb"))["project"]["dependencies"]:
    if not re.match(r"(?i)pyaudio\b", dep):
        print(dep)
PYEOF
# pip wheel: reaproveita wheels prontos e constrói os que só existem como código-fonte (ex.: srt)
"$PY" -m pip wheel --quiet --wheel-dir "$OPT/wheels" -r "$CONSTRUCAO/requisitos.txt"

echo "==> Arquivos do programa"
cp -r assets "$OPT/assets"
cp -r "modelos/$MODELO" "$OPT/modelos/"
for nome in robofael:robofael robofael-gravar-voz:robofael.apresentacao.gravador; do
    sed "s/@MODULO@/${nome#*:}/" empacotamento/deb/robofael > "$PACOTE/usr/bin/${nome%%:*}"
    chmod 755 "$PACOTE/usr/bin/${nome%%:*}"
done
cp empacotamento/deb/*.desktop "$PACOTE/usr/share/applications/"
"$PY" empacotamento/gerar_icone.py "$PACOTE/usr/share/icons/hicolor" >/dev/null
cp README.md CHANGELOG.md "$PACOTE/usr/share/doc/robofael/"
cp empacotamento/deb/copyright "$PACOTE/usr/share/doc/robofael/copyright"

echo "==> Metadados"
TAMANHO=$(du -sk --exclude=DEBIAN "$PACOTE" | cut -f1)
sed -e "s/@VERSAO@/$VERSAO/" -e "s/@ARQUITETURA@/$ARQ/" -e "s/@TAMANHO@/$TAMANHO/" \
    empacotamento/deb/control.in > "$PACOTE/DEBIAN/control"
for script in postinst prerm postrm; do
    install -m 755 "empacotamento/deb/$script" "$PACOTE/DEBIAN/$script"
done
(cd "$PACOTE" && find . -type f ! -path './DEBIAN/*' -printf '%P\0' | sort -z | xargs -0 md5sum > DEBIAN/md5sums)
find "$PACOTE" -type d -exec chmod 755 {} +
find "$PACOTE" -type f ! -path '*/DEBIAN/*' ! -path '*/usr/bin/*' -exec chmod 644 {} +

mkdir -p dist
SAIDA="dist/robofael_${VERSAO}_${ARQ}.deb"
fakeroot dpkg-deb --build -Zxz "$PACOTE" "$SAIDA" >/dev/null
echo "==> $SAIDA ($(du -h "$SAIDA" | cut -f1))"
