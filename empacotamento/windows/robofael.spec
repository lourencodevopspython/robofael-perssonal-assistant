# Executável do Windows (PyInstaller): uma pasta com Robofael.exe, as bibliotecas, os avatares e o modelo
# de voz. Rode pelo construir.ps1, que antes baixa o modelo e gera os ícones em build/windows.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

RAIZ = Path(SPECPATH).resolve().parents[1]
ICONES = RAIZ / "build" / "windows"
MODELO = "vosk-model-small-pt-0.3"

datas = [(str(RAIZ / "assets" / "avatares" / nome), "assets/avatares") for nome in ("cracha.png", "selfie.png")]
datas += [(str(ICONES / "robofael.png"), "assets"), (str(RAIZ / "modelos" / MODELO), f"modelos/{MODELO}")]
datas += collect_data_files("speech_recognition")  # flac-win32.exe: o áudio vai ao Google em FLAC
datas += collect_data_files("certifi")

a = Analysis(
    [str(RAIZ / "empacotamento" / "windows" / "iniciar.py")],
    pathex=[str(RAIZ / "src")],
    binaries=collect_dynamic_libs("vosk"),  # libvosk.dll e as dependências dela
    datas=datas,
    # PIL._tkinter_finder: o Pillow o carrega sob demanda para desenhar no Tk (sem ele, nenhuma imagem aparece)
    hiddenimports=collect_submodules("robofael") + ["pyaudio", "vosk", "edge_tts", "gtts", "anthropic",
                                                    "PIL._tkinter_finder"],
    # pkg_resources: ninguém usa e o hook dele quebra a abertura; boto3/botocore: só o Claude via AWS Bedrock
    excludes=["pytest", "mypy", "ruff", "IPython", "matplotlib", "pkg_resources", "setuptools", "boto3",
              "botocore", "pocketsphinx"],
    noarchive=False,
)
# Os dados do pocketsphinx (38 MB, reconhecimento offline em inglês) não são usados: o hook do PyInstaller
# para o speech_recognition os coleta junto, então saem aqui
a.datas = [d for d in a.datas if "pocketsphinx-data" not in d[0]]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Robofael",
    console=False,  # aplicativo de janela: sem o console preto atrás (o log vai para robofael.log)
    icon=str(ICONES / "robofael.ico"),
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Robofael", upx=False)
