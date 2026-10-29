"""Detecção da frase de ativação ("ok Robofael") em transcrições aproximadas.

"Robofael" não existe no vocabulário do reconhecedor local, que o transcreve por
aproximação ("o que roubou fel", "ok robô fel", "ok roubou fiel"...). Por isso a busca é
fonética: texto e frase passam pela mesma normalização (qu→k, ou→o, ie→e...) e a frase
é procurada em janelas de palavras por similaridade, não por igualdade."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

LIMIAR_PADRAO = 0.8
# No início da fala aceitamos uma semelhança menor, desde que o "rob" esteja lá: vozes graves
# viram "o que roubou a nota..." quando o comando vem emendado. Sem o "rob", "ok Rafael"
# (o nome do usuário) também chegaria a 0,75 e dispararia por engano.
LIMIAR_INICIO = 0.72
# No meio da fala, só uma semelhança quase exata: "hoje o robô fez tudo" contém "o robô fez",
# foneticamente muito parecido com "ok robofael" (0,82). Quem chama o assistente diz a frase
# no começo, depois de uma pausa (que é onde o reconhecedor separa as falas).
LIMIAR_MEIO = 0.9
NUCLEO_FONETICO = "rob"
_REGRAS = [
    (r"qu", "k"), (r"c(?=[aou])", "k"), (r"ck", "k"), (r"ch", "x"), (r"ph", "f"), (r"y", "i"), (r"w", "u"),
    (r"h", ""), (r"ou", "o"), (r"ei", "e"), (r"ie", "e"), (r"ae", "e"), (r"(.)\1+", r"\1"),
]


def _sem_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def normalizar_fonetico(texto: str) -> str:
    """Forma fonética compacta, sem espaços: 'o que roubou fel' -> 'okerobofel'."""
    s = re.sub(r"[^a-z]", "", _sem_acentos(texto.lower()))
    for padrao, troca in _REGRAS:
        s = re.sub(padrao, troca, s)
    return s


def similaridade(a: str, b: str) -> float:
    return SequenceMatcher(None, normalizar_fonetico(a), normalizar_fonetico(b)).ratio()


def localizar_ativacao(texto: str, frase: str, limiar: float = LIMIAR_PADRAO,
                       limiar_inicio: float = LIMIAR_INICIO, limiar_meio: float = LIMIAR_MEIO) -> str | None:
    """Procura a frase de ativação no texto.

    Devolve o que foi dito DEPOIS dela (string vazia se só a frase foi dita), ou None se a
    frase não estiver lá. Ex.: ('ok roubou fiel anota tarefa x', 'ok robofael') -> 'anota tarefa x'."""
    palavras = texto.split()
    alvo = normalizar_fonetico(frase)
    if not palavras or not alvo:
        return None
    max_janela = len(frase.split()) + 2  # a transcrição costuma quebrar a palavra em pedaços
    melhor, fim_melhor = 0.0, -1
    for inicio in range(len(palavras)):
        for fim in range(inicio + 1, min(len(palavras), inicio + max_janela) + 1):
            candidato = normalizar_fonetico(" ".join(palavras[inicio:fim]))
            r = SequenceMatcher(None, candidato, alvo).ratio()
            if inicio == 0:
                aceito = r >= limiar or (r >= limiar_inicio and NUCLEO_FONETICO in candidato)
            else:
                aceito = r >= limiar_meio
            if aceito and (r > melhor or (r == melhor and fim > fim_melhor)):
                melhor, fim_melhor = r, fim
    if fim_melhor < 0:
        return None
    return " ".join(palavras[fim_melhor:]).strip(" ,.!?")


LIMIAR_FIM_DA_FRASE = 0.8  # "Fael" no começo do áudio do comando
LIMIAR_ALINHAMENTO = 0.6  # trecho da transcrição precisa parecido com o início do comando local
LIMIAR_PREFIXO_FRASE = 0.5  # trecho inicial que ainda se parece com a frase de ativação


def extrair_comando(transcricao_precisa: str, comando_aproximado: str, frase: str,
                    comeca_com_frase: bool = False) -> str:
    """Combina as duas transcrições da fala "ok Robofael, <comando>".

    A transcrição precisa (Google) acerta o comando, mas às vezes erra a frase de ativação
    ("Ok Google Fael me lembra..."); a local (Vosk) acerta onde o comando começa. Então:
    1. se a frase aparece na precisa, usa o que vem depois dela;
    2. senão, procura na precisa o trecho que mais se parece com o início do comando local;
    3. se o áudio sabidamente começa com a frase (`comeca_com_frase`), descarta o trecho
       inicial mais longo que ainda se parece com ela ("o que Israel anota..." -> "anota...");
    4. em último caso, usa a transcrição precisa inteira."""
    resto = localizar_ativacao(transcricao_precisa, frase)
    if resto is not None:
        return resto
    palavras = transcricao_precisa.split()
    # O áudio do comando pode começar com o finzinho da frase ("Fael anota tarefa...")
    if _comeca_com_fim_da_frase(palavras, frase):
        palavras = palavras[1:]
        if not comando_aproximado:
            return " ".join(palavras)
    posicao = _alinhar_com_comando_local(palavras, comando_aproximado)
    if posicao is None and comeca_com_frase:
        posicao = _fim_do_prefixo_parecido_com_a_frase(palavras, frase)
    return " ".join(palavras[posicao or 0:])


def _comeca_com_fim_da_frase(palavras: list[str], frase: str) -> bool:
    ultima = normalizar_fonetico(frase.split()[-1])
    return bool(palavras) and SequenceMatcher(None, normalizar_fonetico(palavras[0]), ultima).ratio() \
        >= LIMIAR_FIM_DA_FRASE


def _alinhar_com_comando_local(palavras: list[str], comando_aproximado: str) -> int | None:
    """Posição na transcrição precisa onde começa o comando que o Vosk transcreveu."""
    inicio_local = normalizar_fonetico(" ".join(comando_aproximado.split()[:3]))
    if not palavras or not inicio_local:
        return None
    melhor, posicao = 0.0, 0
    for i in range(len(palavras)):
        candidato = normalizar_fonetico(" ".join(palavras[i:i + 3]))
        r = SequenceMatcher(None, candidato, inicio_local).ratio()
        if r > melhor:
            melhor, posicao = r, i
    return posicao if melhor >= LIMIAR_ALINHAMENTO else None


def _fim_do_prefixo_parecido_com_a_frase(palavras: list[str], frase: str) -> int | None:
    """Prefere o trecho que termina com o som final da frase; depois, o mais parecido."""
    if not palavras:
        return None
    alvo = normalizar_fonetico(frase)
    final = normalizar_fonetico(frase.split()[-1])[-2:]  # "fael" -> "el" (Israel, Rafael...)
    candidatos = []
    for k in range(1, min(len(palavras) - 1, len(frase.split()) + 2) + 1):
        r = SequenceMatcher(None, normalizar_fonetico(" ".join(palavras[:k])), alvo).ratio()
        if r >= LIMIAR_PREFIXO_FRASE:
            candidatos.append((normalizar_fonetico(palavras[k - 1]).endswith(final), r, k))
    return max(candidatos)[2] if candidatos else None


# ---------------------------------------------------------------- gramáticas restritas
@dataclass(frozen=True)
class GramaticaAtivacao:
    """Frases curtas (como "ok Fael") se perdem na transcrição livre ("ok", "o que saiu").
    Com uma gramática restrita o reconhecedor só escolhe entre as variantes aceitas e frases
    DISTRATORAS — parecidas, mas comuns ("o que foi", "ok rafael"...), que absorvem o que
    não é a frase de ativação. Calibrada com vozes sintéticas: 0 falsos positivos em 90."""

    aceitas: tuple[str, ...]
    distratores: tuple[str, ...]

    def frases(self) -> list[str]:
        return [*self.aceitas, *self.distratores, "[unk]"]

    def analisar(self, texto: str) -> str | None:
        """None se o texto não começa com uma variante aceita; senão, o que veio depois
        (pode conter "[unk]": fala que existe, mas está fora da gramática)."""
        texto = " ".join(texto.split())
        for aceita in sorted(self.aceitas, key=len, reverse=True):
            if texto == aceita or texto.startswith(aceita + " "):
                return texto[len(aceita):].strip()
        return None


GRAMATICAS: dict[str, GramaticaAtivacao] = {
    "ok fael": GramaticaAtivacao(
        aceitas=("ok fel", "ok fiel", "o que fel", "o que fiel"),
        distratores=(
            "ok", "o que", "que", "o", "o que foi", "o que fez", "o que faz", "o que falta", "o que fala",
            "o que falou", "o que fica", "o que fazer", "o que saiu", "que foi", "que fez", "quero", "rafael",
            "o rafael", "ok rafael", "fiel", "o fiel", "ok feito", "falei", "feito", "foi", "fez", "faz",
            "falta", "fala", "fazer",
        ),
    ),
}


def gramatica_para(frase: str) -> GramaticaAtivacao | None:
    """Gramática calibrada para a frase, se houver (senão usa-se a busca fonética livre)."""
    return GRAMATICAS.get(" ".join(_sem_acentos(frase.lower()).split()))


def limpar_desconhecidas(texto: str) -> str:
    return " ".join(p for p in texto.split() if p != "[unk]")
