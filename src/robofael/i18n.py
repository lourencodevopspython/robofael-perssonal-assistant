"""Internacionalização: idiomas suportados, catálogo de mensagens e o `Tradutor`.

Regras do projeto:
- **entender** é independente de idioma: os comandos ("anota tarefa"/"add task", "o que eu fiz"/
  "what did I do"...) são reconhecidos nos dois idiomas, sempre;
- **responder** (fala, interface, instruções do modelo) usa o idioma configurado no `Tradutor`,
  que pode ser trocado ao vivo pela tela de configurações.

Cada mensagem traz os dois idiomas lado a lado; um teste garante que nenhuma fica faltando e que
os campos de formatação ({n}, {texto}...) são os mesmos nas duas versões."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date, datetime
from enum import Enum
from typing import Any


class Idioma(str, Enum):
    PT_BR = "pt-BR"
    EN_US = "en-US"

    @property
    def nome(self) -> str:
        return {Idioma.PT_BR: "Português (Brasil)", Idioma.EN_US: "English (US)"}[self]

    @property
    def voz_padrao(self) -> str:
        return {Idioma.PT_BR: "pt-BR-AntonioNeural", Idioma.EN_US: "en-US-AndrewNeural"}[self]

    @property
    def codigo_gtts(self) -> tuple[str, str]:
        """(lang, tld) para a voz de reserva (gTTS)."""
        return {Idioma.PT_BR: ("pt", "com.br"), Idioma.EN_US: ("en", "com")}[self]

    @classmethod
    def de_texto(cls, texto: str | None, padrao: Idioma | None = None) -> Idioma:
        """'pt', 'pt_BR', 'PT-br', 'en', 'en-us'... -> Idioma (padrão: português)."""
        t = (texto or "").strip().lower().replace("_", "-")
        if t.startswith("en"):
            return cls.EN_US
        if t.startswith("pt"):
            return cls.PT_BR
        return padrao or cls.PT_BR


PT, EN = Idioma.PT_BR, Idioma.EN_US

VOZES: dict[Idioma, dict[str, str]] = {
    PT: {"pt-BR-AntonioNeural": "Antonio (masculina)", "pt-BR-FranciscaNeural": "Francisca (feminina)",
         "pt-BR-ThalitaMultilingualNeural": "Thalita (feminina)"},
    EN: {"en-US-AndrewNeural": "Andrew (male)", "en-US-BrianNeural": "Brian (male)",
         "en-US-GuyNeural": "Guy (male)", "en-US-JennyNeural": "Jenny (female)"},
}

DIAS_SEMANA = {
    PT: ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"),
    EN: ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
}

# chave -> {idioma: texto}. Plurais: tupla (singular, plural).
CATALOGO: dict[str, dict[Idioma, str | tuple[str, str]]] = {
    # ---------- unidades ----------
    "un.tarefa": {PT: ("tarefa", "tarefas"), EN: ("task", "tasks")},
    "un.pendente": {PT: ("pendente", "pendentes"), EN: ("pending", "pending")},
    "un.minuto": {PT: ("minuto", "minutos"), EN: ("minute", "minutes")},
    "un.lembrete": {PT: ("lembrete", "lembretes"), EN: ("reminder", "reminders")},
    "conector.e": {PT: "e", EN: "and"},
    # ---------- formatos ----------
    "fmt.data": {PT: "%d/%m/%Y", EN: "%m/%d/%Y"},
    "fmt.dia_mes": {PT: "%d/%m", EN: "%m/%d"},
    "fmt.lembrete": {PT: "%d/%m %H:%M", EN: "%m/%d %I:%M %p"},
    # ---------- estados (barra de status) ----------
    "estado.iniciando": {PT: "Iniciando...", EN: "Starting..."},
    "estado.parado": {PT: "Pressione ESPAÇO para falar", EN: "Press SPACE to talk"},
    "estado.parado_ativacao": {PT: "Diga “{frase}” ou aperte ESPAÇO", EN: "Say “{frase}” or press SPACE"},
    "estado.ouvindo": {PT: "Ouvindo... (ESPAÇO cancela)", EN: "Listening... (SPACE cancels)"},
    "estado.pensando": {PT: "Pensando...", EN: "Thinking..."},
    "estado.falando": {PT: "Falando... (ESPAÇO interrompe)", EN: "Speaking... (SPACE interrupts)"},
    # ---------- interface ----------
    "ui.titulo_janela": {PT: "{nome} — assistente pessoal", EN: "{nome} — personal assistant"},
    "ui.preparando_avatar": {PT: "Preparando avatar...", EN: "Loading avatar..."},
    "ui.voce": {PT: "Você: {texto}", EN: "You: {texto}"},
    "ui.placeholder": {PT: "Digite uma mensagem e pressione Enter…", EN: "Type a message and press Enter…"},
    "ui.botao_falar": {PT: "🎤  Falar", EN: "🎤  Talk"},
    "ui.botao_cancelar": {PT: "■  Cancelar", EN: "■  Cancel"},
    "ui.botao_parar": {PT: "■  Parar", EN: "■  Stop"},
    "ui.botao_interromper": {PT: "■  Interromper", EN: "■  Interrupt"},
    "ui.atalhos": {
        PT: "ESPAÇO falar/interromper  ·  T trocar avatar  ·  ⚙ configurações  ·  ESC interromper  ·  Ctrl+Q sair",
        EN: "SPACE talk/interrupt  ·  T switch avatar  ·  ⚙ settings  ·  ESC interrupt  ·  Ctrl+Q quit"},
    "ui.configuracoes_salvas": {PT: "Configurações salvas", EN: "Settings saved"},
    "ui.banco_nao_encontrado": {PT: "Banco não encontrado em {arquivo}: usando o padrão nesta vez.",
                                EN: "Database not found at {arquivo}: using the default this time."},
    "ui.falha_inicializacao": {PT: "Não consegui mudar a inicialização (veja o log).",
                               EN: "I couldn't change the startup settings (see the log)."},
    "ui.trocando_avatar": {PT: "Trocando avatar...", EN: "Switching avatar..."},
    "ui.falha_audio": {PT: "Não consegui iniciar o áudio.", EN: "I couldn't start the audio."},
    "ui.falha_avatar": {PT: "Não consegui carregar o avatar.", EN: "I couldn't load the avatar."},
    "painel.tarefas": {PT: "TAREFAS", EN: "TASKS"},
    "painel.lembretes": {PT: "PRÓXIMOS LEMBRETES", EN: "UPCOMING REMINDERS"},
    "painel.dica": {PT: "duplo clique: concluir · Del: remover", EN: "double-click: complete · Del: remove"},
    "painel.sem_tarefas": {PT: "Nenhuma tarefa. Diga: \"anota tarefa ...\"", EN: "No tasks. Say: \"add task ...\""},
    "painel.sem_lembretes": {PT: "Nenhum lembrete.", EN: "No reminders."},
    # ---------- configurações ----------
    "cfg.titulo": {PT: "Configurações", EN: "Settings"},
    "cfg.avatar": {PT: "AVATAR", EN: "AVATAR"},
    "cfg.avatar.cracha": {PT: "Crachá", EN: "Badge"},
    "cfg.avatar.selfie": {PT: "Selfie", EN: "Selfie"},
    "cfg.idioma": {PT: "IDIOMA", EN: "LANGUAGE"},
    "cfg.voz": {PT: "VOZ", EN: "VOICE"},
    "cfg.tom": {PT: "Tom (Hz)", EN: "Pitch (Hz)"},
    "cfg.ritmo": {PT: "Ritmo (%)", EN: "Rate (%)"},
    "cfg.ouvir": {PT: "▶ Ouvir", EN: "▶ Listen"},
    "cfg.perfil": {PT: "Usar meu perfil gravado", EN: "Use my recorded profile"},
    "cfg.ativacao": {PT: "ATIVAÇÃO POR VOZ", EN: "VOICE ACTIVATION"},
    "cfg.ativacao_texto": {PT: "Ouvir “{frase}” para me chamar sem apertar ESPAÇO",
                           EN: "Listen for “{frase}” so you can call me without pressing SPACE"},
    "cfg.ativacao_indisponivel": {
        PT: "Indisponível: falta o modelo local (make baixar-modelo-voz) ou o microfone.",
        EN: "Unavailable: the local model (make baixar-modelo-voz) or the microphone is missing."},
    "cfg.microfone": {PT: "MICROFONE", EN: "MICROPHONE"},
    "cfg.microfone_padrao": {PT: "Padrão do sistema", EN: "System default"},
    "cfg.microfone_desconectado": {PT: "{nome} (desconectado)", EN: "{nome} (disconnected)"},
    "cfg.microfone_dica": {PT: "Vale na próxima vez que eu ouvir.", EN: "Takes effect the next time I listen."},
    "cfg.inicializacao": {PT: "INICIALIZAÇÃO", EN: "STARTUP"},
    "cfg.abrir_ao_entrar": {PT: "Abrir ao entrar no computador", EN: "Open when I log in to the computer"},
    "cfg.comando_terminal": {PT: "Abrir com o comando “robofael” no terminal",
                             EN: "Open with the “robofael” command in the terminal"},
    "cfg.comando_dica": {PT: "Vale nos terminais abertos depois de salvar.",
                         EN: "Works in terminals opened after saving."},
    "cfg.comando_do_sistema": {PT: "Já instalado pelo pacote .deb.", EN: "Already installed by the .deb package."},
    "cfg.cerebro": {PT: "ASSISTENTE (MODELO DE LINGUAGEM)", EN: "ASSISTANT (LANGUAGE MODEL)"},
    "cfg.cerebro_em_uso": {PT: "Em uso: {nome}", EN: "In use: {nome}"},
    "cfg.cerebro_iniciando": {PT: "Em uso: iniciando…", EN: "In use: starting…"},
    "cfg.modelos_compativeis": {PT: "Modelos compatíveis (conversa + ferramentas):",
                                EN: "Compatible models (chat + tools):"},
    "cfg.modelos_procurando": {PT: "Procurando modelos…", EN: "Looking for models…"},
    "cfg.modelos_nenhum": {PT: "nenhum compatível instalado", EN: "none compatible installed"},
    "cfg.modelo_em_uso": {PT: "em uso", EN: "in use"},
    "cfg.cerebro_dica": {
        PT: "Para trocar: ROBOFAEL_CEREBRO, ROBOFAEL_MODELO e ROBOFAEL_OLLAMA_MODELO (vale ao reabrir).",
        EN: "To change: ROBOFAEL_CEREBRO, ROBOFAEL_MODELO and ROBOFAEL_OLLAMA_MODELO (on next start)."},
    "cerebro.claude": {PT: "Claude (nuvem)", EN: "Claude (cloud)"},
    "cerebro.ollama": {PT: "Ollama (local)", EN: "Ollama (local)"},
    "cerebro.offline": {PT: "modo offline (comandos básicos, sem modelo de linguagem)",
                        EN: "offline mode (basic commands, no language model)"},
    "modelos.claude_sem_chave": {PT: "sem chave: defina ANTHROPIC_API_KEY", EN: "no key: set ANTHROPIC_API_KEY"},
    "modelos.claude_chave_invalida": {PT: "chave recusada pela API", EN: "key rejected by the API"},
    "modelos.claude_sem_conexao": {PT: "sem conexão com a API", EN: "no connection to the API"},
    "modelos.ollama_fora": {PT: "não respondeu em {url} (instalado e rodando?)",
                            EN: "no answer at {url} (installed and running?)"},
    "modelos.erro": {PT: "erro ao listar ({detalhe})", EN: "error listing ({detalhe})"},
    "cfg.memoria": {PT: "MEMÓRIA (BANCO SQLITE)", EN: "MEMORY (SQLITE DATABASE)"},
    "cfg.banco_em_memoria": {PT: "banco em memória (nada é salvo)", EN: "in-memory database (nothing is saved)"},
    "cfg.mudar_local": {PT: "Mudar local…", EN: "Change location…"},
    "cfg.fazer_backup": {PT: "Fazer backup…", EN: "Back up…"},
    "cfg.escolher_pasta_banco": {PT: "Pasta onde guardar o banco", EN: "Folder to keep the database in"},
    "cfg.salvar_backup": {PT: "Salvar backup do banco", EN: "Save database backup"},
    "cfg.banco_dica": {PT: "Valem na hora (não dependem de Salvar).", EN: "Take effect immediately (no need to Save)."},
    "cfg.banco_movido": {PT: "Banco movido. O anterior foi guardado como {antigo}.",
                         EN: "Database moved. The previous one was kept as {antigo}."},
    "cfg.banco_ja_existe": {PT: "Já existe um memoria.db nessa pasta: escolha outra ou mova o arquivo de lá.",
                            EN: "There is already a memoria.db in that folder: pick another or move it away."},
    "cfg.backup_feito": {PT: "Backup salvo e conferido: {arquivo} ({n} registros no histórico).",
                         EN: "Backup saved and checked: {arquivo} ({n} history records)."},
    "cfg.falha_arquivo": {PT: "Não consegui: {erro}", EN: "I couldn't: {erro}"},
    "cfg.salvar": {PT: "Salvar", EN: "Save"},
    "cfg.cancelar": {PT: "Cancelar", EN: "Cancel"},
    "cfg.frase_teste": {PT: "Olá! Esta é a voz que eu vou usar para conversar com você.",
                        EN: "Hi! This is the voice I'll use to talk with you."},
    # ---------- falas do assistente ----------
    "fala.saudacao": {PT: "Olá, {usuario}! Eu sou o {assistente}, seu assistente do dia a dia.",
                      EN: "Hi, {usuario}! I'm {assistente}, your everyday assistant."},
    "fala.saudacao_pendentes": {PT: " Você tem {n} {tarefas} {pendentes}.", EN: " You have {n} {pendentes} {tarefas}."},
    "fala.saudacao_offline": {PT: " Estou no modo offline, com comandos básicos.",
                              EN: " I'm in offline mode, with basic commands."},
    "fala.saudacao_ativacao": {PT: " Para me chamar, é só dizer: {frase}.", EN: " To call me, just say: {frase}."},
    "fala.lembrete": {PT: "{usuario}, lembrete: {texto}.", EN: "{usuario}, reminder: {texto}."},
    "orq.falha": {PT: "Tive um problema para responder agora.", EN: "I had a problem answering right now."},
    "orq.sem_microfone": {PT: "Microfone indisponível. Digite sua mensagem.",
                          EN: "Microphone unavailable. Type your message."},
    "orq.falha_microfone": {PT: "Falha no microfone.", EN: "Microphone failure."},
    "orq.vigia_desligada": {PT: "Ativação por voz desligada: falha no microfone.",
                            EN: "Voice activation turned off: microphone failure."},
    "mic.sem_internet": {PT: "Não consegui acessar o reconhecimento de voz. Verifique a internet.",
                         EN: "I couldn't reach speech recognition. Check your internet connection."},
    "mic.nao_encontrado": {PT: "Microfone não encontrado: use a caixa de texto.",
                           EN: "Microphone not found: use the text box."},
    "mic.voz_baixa": {
        PT: "Sua voz está chegando baixa ao microfone (pico ~{pico}). Aumente o volume de entrada para 80–100% "
            "ou escolha outro microfone nas configurações de som do sistema.",
        EN: "Your voice is reaching the microphone too quietly (peak ~{pico}). Raise the input volume to 80–100% "
            "or choose another microphone in the system sound settings."},
    # ---------- modo offline ----------
    "off.ajuda": {
        PT: "Estou no modo offline. Posso dizer a hora, a data, anotar tarefa, listar tarefas, concluir tarefa pelo "
            "número, lembrar daqui a alguns minutos, contar o que você fez num dia ou semana, abrir programas e "
            "salvar a última resposta num documento, se você disser gerar doc.",
        EN: "I'm in offline mode. I can tell the time and date, add, list and complete tasks by number, remind you "
            "in a few minutes, tell you what you did on a day or week, open programs, and save my last answer to a "
            "document when you say generate doc."},
    "off.anotei": {PT: "Anotei: {texto}.", EN: "Added: {texto}."},
    "off.concluida": {PT: "Boa! Tarefa {texto} concluída.", EN: "Nice! Task {texto} completed."},
    "off.tarefa_nao_achada": {PT: "Não achei essa tarefa.", EN: "I couldn't find that task."},
    "off.lembrete_criado": {PT: "Combinado, te lembro daqui a {n} {minutos}.",
                            EN: "Okay, I'll remind you in {n} {minutos}."},
    "off.sem_pendentes": {PT: "Você não tem tarefas pendentes.", EN: "You have no pending tasks."},
    "off.pendentes": {PT: "Você tem {n} {tarefas} {pendentes}. {itens}.",
                      EN: "You have {n} {pendentes} {tarefas}. {itens}."},
    "doc.pedido_modelo": {
        PT: "Escreva o texto de um documento sobre: {assunto}. Ele será salvo em arquivo e não lido em voz alta, "
            "então pode ter vários parágrafos com informações úteis, organizados e sem markdown.",
        EN: "Write the text of a document about: {assunto}. It will be saved to a file, not read aloud, so it may "
            "have several useful, well-organized paragraphs, without markdown.",
    },
    "doc.instrucoes": {
        PT: "Você escreve documentos claros e bem organizados em português do Brasil, com título nas seções "
            "quando fizer sentido. Escreva só o conteúdo do documento, sem comentários sobre ele.",
        EN: "You write clear, well-organized documents in American English, with section headings when "
            "useful. Write only the document's content, with no comments about it.",
    },
    "doc.escrevendo": {PT: "Certo, vou escrever o documento sobre {assunto}.",
                       EN: "Sure, I'll write the document about {assunto}."},
    "doc.salvo": {PT: "Pronto, salvei o documento na pasta {pasta}.",
                  EN: "Done, I saved the document in the {pasta} folder."},
    "doc.salvo_aviso": {PT: "Documento salvo: {caminho}", EN: "Document saved: {caminho}"},
    "doc.nada": {PT: "Ainda não tenho nenhuma resposta para salvar. Me pergunte algo e depois diga gerar doc.",
                 EN: "I don't have an answer to save yet. Ask me something, then say generate doc."},
    "doc.falha": {PT: "Não consegui salvar o documento.", EN: "I couldn't save the document."},
    "doc.vazio": {PT: "Não consegui escrever esse documento. Pode tentar de outro jeito?",
                  EN: "I couldn't write that document. Could you try another way?"},
    "doc.gerado_em": {PT: "Gerado pelo {assistente} em {data} às {h:%H:%M}.",
                      EN: "Generated by {assistente} on {data} at {h:%I:%M %p}."},
    "doc.pedido": {PT: "Pedido", EN: "Request"},
    "off.hora": {PT: "Agora são {h:%H} horas e {h:%M} minutos.", EN: "It's {h:%I}:{h:%M} {h:%p}."},
    "off.data": {PT: "Hoje é {dia}, {data}.", EN: "Today is {dia}, {data}."},
    "off.sem_historico": {PT: "Ainda não tenho acesso ao histórico.", EN: "I don't have access to the history yet."},
    "off.lembrete_padrao": {PT: "seu lembrete", EN: "your reminder"},
    "off.lembrete_criado_em": {PT: "Combinado, te lembro {quando}.", EN: "Okay, I'll remind you {quando}."},
    "off.quando_hoje": {PT: "hoje às {h:%H:%M}", EN: "today at {h:%I:%M %p}"},
    "off.quando_amanha": {PT: "amanhã às {h:%H:%M}", EN: "tomorrow at {h:%I:%M %p}"},
    "off.quando_data": {PT: "em {data} às {h:%H:%M}", EN: "on {data} at {h:%I:%M %p}"},
    # ---------- memória ("o que eu fiz") ----------
    "mem.nenhuma": {PT: "Não encontrei tarefas concluídas {quando}.",
                    EN: "I didn't find any completed tasks {quando}."},
    "mem.mas_criou": {PT: " Mas você criou {n} {tarefas}: {lista}.", EN: " But you created {n} {tarefas}: {lista}."},
    "mem.concluiu": {PT: "{quando} você concluiu {n} {tarefas}: {lista}.",
                     EN: "{quando} you completed {n} {tarefas}: {lista}."},
    "mem.tambem": {PT: " Também {extras}.", EN: " You also {extras}."},
    "mem.criou": {PT: "criou {n} {tarefas}", EN: "created {n} {tarefas}"},
    "mem.recebeu": {PT: "recebeu {n} {lembretes}", EN: "received {n} {lembretes}"},
    "mem.mais": {PT: "mais {n}", EN: "{n} more"},
    # ---------- períodos ----------
    "per.hoje": {PT: "hoje ({d})", EN: "today ({d})"},
    "per.ontem": {PT: "ontem ({d})", EN: "yesterday ({d})"},
    "per.anteontem": {PT: "anteontem ({d})", EN: "the day before yesterday ({d})"},
    "per.semana_passada": {PT: "na semana passada ({i} a {f})", EN: "last week ({i} to {f})"},
    "per.esta_semana": {PT: "nesta semana ({i} a {f})", EN: "this week ({i} to {f})"},
    "per.semana_de": {PT: "na semana de {i} a {f}", EN: "in the week of {i} to {f}"},
    "per.ultimos_dias": {PT: "nos últimos {n} dias ({i} a {f})", EN: "in the last {n} days ({i} to {f})"},
    "per.mes_passado": {PT: "no mês passado ({m})", EN: "last month ({m})"},
    "per.este_mes": {PT: "neste mês ({m})", EN: "this month ({m})"},
    "per.data": {PT: "em {d}", EN: "on {d}"},
    "per.dia": {PT: "no dia {d}", EN: "on {d}"},
    "per.dia_util": {PT: "na {nome} ({d})", EN: "on {nome} ({d})"},
    "per.fim_de_semana": {PT: "no {nome} ({d})", EN: "on {nome} ({d})"},
    # ---------- programas ----------
    "prog.abrindo": {PT: "Abrindo {nome}.", EN: "Opening {nome}."},
    "prog.nao_encontrado": {PT: "Não encontrei nenhum programa chamado {pedido} instalado.",
                            EN: "I couldn't find any installed program called {pedido}."},
    "prog.opcoes": {PT: "Encontrei mais de uma opção: {lista}. Qual delas?",
                    EN: "I found more than one option: {lista}. Which one?"},
    "prog.falha": {PT: "Não consegui abrir o {nome}.", EN: "I couldn't open {nome}."},
    # ---------- Claude ----------
    "claude.agora": {PT: "[Agora: {agora}]", EN: "[Now: {agora}]"},
    "claude.nova_conversa": {PT: "Pronto, comecei uma conversa nova.", EN: "Done, I started a new conversation."},
    "claude.recusa": {PT: "Desculpe, não posso ajudar com isso.", EN: "Sorry, I can't help with that."},
    "claude.perdido": {PT: "Me perdi no raciocínio. Pode repetir?",
                       EN: "I lost my train of thought. Could you repeat?"},
    "claude.limite": {PT: "Estou recebendo pedidos demais agora. Tenta de novo em alguns segundos.",
                      EN: "I'm getting too many requests right now. Try again in a few seconds."},
    "claude.chave": {PT: "Minha chave de acesso ao Claude não é válida.", EN: "My Claude access key isn't valid."},
    "claude.erro_api": {PT: "Tive um erro na API, código {codigo}.", EN: "I got an API error, code {codigo}."},
    "claude.sem_internet": {PT: "Não consegui me conectar à internet.", EN: "I couldn't connect to the internet."},
    "claude.problema": {PT: "Tive um problema para pensar agora.", EN: "I had a problem thinking right now."},
    "local.instrucoes": {
        PT: """Você é o {assistente}, assistente pessoal por voz de {usuario}. Suas respostas são faladas em voz alta.
Responda sempre em português do Brasil, em no máximo duas frases curtas, sem markdown, listas, emojis ou URLs.
Só use uma ferramenta quando o pedido for claramente sobre tarefas, lembretes ou o que foi feito; \
nunca invente o estado da agenda. Para lembretes, calcule a data e a hora a partir do horário atual \
informado na mensagem.""",
        EN: """You are {assistente}, {usuario}'s personal voice assistant. Your answers are spoken aloud.
Always answer in American English, in at most two short sentences, with no markdown, lists, emojis or URLs.
Only use a tool when the request is clearly about tasks, reminders or what was done; never make up the \
agenda. For reminders, work out the date and time from the current time given in the message.""",
    },
    "local.nao_criou": {
        PT: "Não consegui criar isso. Tente, por exemplo: me lembra daqui a 10 minutos de beber água.",
        EN: "I couldn't create that. Try, for example: remind me in 10 minutes to drink water.",
    },
    "local.aguarde": {PT: "Só um instante.", EN: "One moment."},
    "local.problema": {PT: "Meu modelo local teve um problema agora. Pode repetir?",
                       EN: "My local model had a problem just now. Could you say that again?"},
    "claude.instrucoes": {
        PT: """Você é o {assistente}, o assistente pessoal de atividades diárias de {usuario}, \
com a aparência de {usuario}. Você conversa por VOZ: suas respostas são lidas em voz alta.

- Responda em português do Brasil, de forma curta e natural (1 a 3 frases).
- Nada de markdown, listas com marcadores, emojis ou URLs: só texto falado.
- Use as ferramentas para gerenciar tarefas e lembretes; nunca invente o estado da agenda.
- Antes de usar uma ferramenta, diga no máximo uma frase curta (ex.: "Vou anotar.").
- Para lembretes, converta expressões como "daqui a 20 minutos" ou "amanhã às 9" \
usando a data e hora atuais informadas em cada mensagem.
- Ao ler tarefas, cite no máximo 5 e diga quantas faltam.
- Para "o que eu fiz" em um dia, semana ou período, use consultar_historico (a memória de longo
prazo) e resuma só o que estiver lá; se não houver nada no período, diga isso.
- Para abrir programas do computador, use abrir_programa; não invente programas que não existam.""",
        EN: """You are {assistente}, {usuario}'s personal assistant for daily activities, \
who looks like {usuario}. You talk by VOICE: your answers are read aloud.

- Answer in American English, short and natural (1 to 3 sentences), even if the user speaks Portuguese.
- No markdown, bullet lists, emojis or URLs: spoken text only.
- Use the tools to manage tasks and reminders; never make up the state of the schedule.
- Before using a tool, say at most one short sentence (e.g. "Let me add that.").
- For reminders, convert expressions like "in 20 minutes" or "tomorrow at 9" \
using the current date and time given in each message.
- When reading tasks, mention at most 5 and say how many are left.
- For "what did I do" on a day, week or period, use consultar_historico (the long-term memory) \
and summarize only what is there; if there is nothing in the period, say so.
- To open programs on the computer, use abrir_programa; don't make up programs that don't exist.
- Task and reminder texts may be in Portuguese: keep them as they are."""},
}


class Tradutor:
    """Fornece as mensagens no idioma atual. Trocar `idioma` vale na hora para todos que o usam."""

    def __init__(self, idioma: Idioma = Idioma.PT_BR):
        self._idioma = idioma
        self._observadores: list[Callable[[Idioma], None]] = []
        self._trava = threading.Lock()

    @property
    def idioma(self) -> Idioma:
        return self._idioma

    @idioma.setter
    def idioma(self, novo: Idioma) -> None:
        with self._trava:
            if novo == self._idioma:
                return
            self._idioma = novo
        for cb in list(self._observadores):
            cb(novo)

    def observar(self, callback: Callable[[Idioma], None]) -> None:
        self._observadores.append(callback)

    def __call__(self, chave: str, **campos: Any) -> str:
        texto = CATALOGO[chave][self._idioma]
        assert isinstance(texto, str), f"{chave} é um plural: use plural()"
        return texto.format(**campos) if campos else texto

    def plural(self, n: int, chave: str) -> str:
        formas = CATALOGO[chave][self._idioma]
        assert isinstance(formas, tuple), f"{chave} não é um plural"
        return formas[0] if n == 1 else formas[1]

    def juntar(self, itens: list[str]) -> str:
        """['a', 'b', 'c'] -> 'a, b e c' / 'a, b and c'."""
        if len(itens) <= 1:
            return "".join(itens)
        return ", ".join(itens[:-1]) + f" {self('conector.e')} " + itens[-1]

    def data(self, d: date | datetime) -> str:
        return d.strftime(self("fmt.data"))

    def dia_mes(self, d: date | datetime) -> str:
        return d.strftime(self("fmt.dia_mes"))

    def dia_semana(self, d: date | datetime) -> str:
        return DIAS_SEMANA[self._idioma][d.weekday()]

    def vozes(self) -> dict[str, str]:
        return VOZES[self._idioma]
