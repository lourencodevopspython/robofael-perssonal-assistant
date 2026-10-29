#!/usr/bin/env bash
# Testa o .deb sem instalar no sistema: extrai numa pasta temporária, roda os scripts do pacote
# apontando para ela (ROBOFAEL_PREFIXO) e verifica instalação, execução e remoção.
# Uso: empacotamento/testar_deb.sh [dist/robofael_X_Y.deb]
set -euo pipefail
cd "$(dirname "$0")/.."
DEB="${1:-$(ls -t dist/robofael_*.deb | head -1)}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
RAIZ="$TMP/raiz"; CONTROLE="$TMP/controle"; CASA="$TMP/casa"
export ROBOFAEL_PREFIXO="$RAIZ/opt/robofael"
ok() { echo "  ✔ $*"; }

echo "==> Pacote: $DEB"
dpkg-deb -x "$DEB" "$RAIZ"; dpkg-deb -e "$DEB" "$CONTROLE"
(cd "$RAIZ" && md5sum --quiet -c "$CONTROLE/md5sums") && ok "md5sums conferem"
desktop-file-validate "$RAIZ"/usr/share/applications/*.desktop && ok "atalhos do menu válidos"

echo "==> postinst configure (sem internet: só as wheels do pacote)"
sh "$CONTROLE/postinst" configure
"$ROBOFAEL_PREFIXO/venv/bin/python" - <<'PYEOF'
import importlib
for m in ("robofael", "robofael.apresentacao.app", "robofael.adaptadores.ativacao_vosk", "vosk", "pygame",
          "speech_recognition", "pyaudio", "anthropic", "edge_tts", "gtts", "numpy", "PIL.ImageTk", "tkinter"):
    importlib.import_module(m)
import robofael
print(f"  ✔ ambiente Python completo (robofael {robofael.__version__})")
PYEOF

echo "==> Lançadores"
"$RAIZ/usr/bin/robofael" --help | head -1 | grep -q "usage: robofael" && ok "robofael --help"
HOME="$CASA" XDG_DATA_HOME="" XDG_CACHE_HOME="" "$ROBOFAEL_PREFIXO/venv/bin/python" - <<PYEOF
import os, subprocess
env = dict(os.environ, HOME="$CASA")
saida = subprocess.run(["sh", "-c", ". /dev/stdin; env | grep ^ROBOFAEL_ | sort"], input=open("$RAIZ/usr/bin/robofael").read().replace('exec "', '# exec "'), env=env, capture_output=True, text=True).stdout
assert "ROBOFAEL_DADOS=$CASA/.local/share/robofael" in saida and "ROBOFAEL_CACHE=$CASA/.cache/robofael" in saida, saida
assert "ROBOFAEL_MODELOS=$ROBOFAEL_PREFIXO/modelos" in saida and "ROBOFAEL_ASSETS=$ROBOFAEL_PREFIXO/assets" in saida, saida
print("  ✔ dados do usuário em ~/.local/share/robofael; programa e modelo em /opt/robofael")
legado = subprocess.run(["sh", "-c", ". /dev/stdin; env | grep ^ROBOFAEL_DADOS="], input=open("$RAIZ/usr/bin/robofael").read().replace('exec "', '# exec "'), env=dict(env, EUROBO_DADOS="/legado"), capture_output=True, text=True).stdout
assert legado.strip() == "ROBOFAEL_DADOS=/legado", legado
print("  ✔ EUROBO_DADOS (nome antigo) ainda respeitado pelo lançador")
PYEOF
HOME="$CASA" "$ROBOFAEL_PREFIXO/venv/bin/python" - <<PYEOF
import os
os.environ.update(ROBOFAEL_DADOS="$CASA/.local/share/robofael", ROBOFAEL_CACHE="$CASA/.cache/robofael",
                  ROBOFAEL_MODELOS="$ROBOFAEL_PREFIXO/modelos", ROBOFAEL_ASSETS="$ROBOFAEL_PREFIXO/assets")
from robofael.bootstrap import montar_nucleo
from robofael.configuracao import Configuracao
from robofael.avatar.renderizador import gerar_quadros
cfg = Configuracao.do_ambiente()
n = montar_nucleo(cfg)
n.agenda.adicionar_tarefa("testar o pacote")
assert cfg.arquivo_banco.exists() and n.banco.verificar_integridade().ok
assert cfg.pasta_modelo_ativacao.is_dir()
quadros, _ = gerar_quadros("cracha", 160, cfg.pasta_cache_avatar, cfg.pasta_avatares)
print("  ✔ agenda, histórico (SQLite), modelo de voz e avatar funcionando a partir de /opt/robofael")
PYEOF

echo "==> Remoção"
sh "$CONTROLE/prerm" remove && sh "$CONTROLE/postrm" remove
[ ! -d "$ROBOFAEL_PREFIXO/venv" ] && ok "remove: ambiente apagado"
[ -d "$CASA/.local/share/robofael" ] && ok "remove: dados do usuário preservados"
sh "$CONTROLE/postrm" purge
[ ! -d "$ROBOFAEL_PREFIXO" ] && ok "purge: /opt/robofael apagado"
echo "==> Tudo certo"
