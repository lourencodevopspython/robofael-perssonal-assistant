# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões seguem [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado
- **Trocar o idioma por voz:** "ok Fael, mudar para inglês" e "ok Fael, mudar para português" (também
  "fale em inglês", "change to English", "switch to Portuguese"...) trocam respostas, voz, reconhecimento de
  fala e interface na hora, confirmam já no idioma novo e ficam salvos para as próximas aberturas. Falas
  parecidas que não são pedidos ("como se fala cachorro em inglês?", "anota tarefa estudar inglês") seguem
  para o modelo como antes.
- **Tarefas e lembretes no idioma da interface:** cada item continua guardado como foi dito, e o painel e os
  lembretes falados mostram a tradução para o idioma em uso ("comprar pão" ↔ "buy bread"). Quem traduz é o
  modelo de linguagem em uso (Claude ou Ollama), em segundo plano e fora do histórico da conversa; cada texto
  é traduzido uma vez por idioma e guardado no banco (tabela `traducoes`, migração v2 do esquema). Os itens vão
  numerados, para um modelo pequeno não trocar uma tarefa pela outra. No modo offline, aparece o original.
- **"Concluir todas as tarefas"** ("complete all tasks", "marca todas as tarefas como feitas"): conclui todas
  as pendentes de uma vez, numa só transação, com um registro no histórico para cada uma. Também é uma
  ferramenta do Claude (`concluir_todas_tarefas`); no Ollama, como as outras ações que alteram a agenda, vale
  só o comando explícito.

### Testes
- O Ollama instalado na máquina não entra mais nos testes (aparece como fora do ar na porta padrão): o
  resultado era diferente em cada máquina e ele recebia pedidos de verdade.

### Alterado
- **Avatares com as fotos novas** (ilustrações de 500x500, com a boca já aberta num sorriso): os pontos do
  rosto do catálogo (`avatar/catalogo.py`) foram medidos de novo. A boca fica na fresta entre os dentes de
  cima e os de baixo, então a fala abre um vão escuro sob os dentes de cima, e não por cima deles; a cabeça
  volta a ficar no centro do anel. Nitidez menor (as ilustrações já têm contorno definido) e a selfie deixa
  de usar `selfie_hd.jpeg`, que agora tem a mesma resolução da PNG.

### Documentação
- README mais visual: apresentação com o avatar falando (GIF), "Veja em ação" com a conversa completa em GIF,
  prints da janela e das configurações, quadro dos avatares com as formas da boca, recursos em grade,
  diagrama de como funciona, sumário em tabela e seções longas (fluxos, testes, pacote) em blocos que abrem
  com um clique. Números atualizados (742 testes) e o endereço do repositório corrigido.
- `make midia` (`scripts/capturar_midia.py`) refaz os prints e GIFs com o app real, dados de exemplo numa pasta
  temporária e áudio mudo.

### Corrigido
- Foto que acaba antes do fim do recorte do busto (a selfie nova): a base da camisa aparecia cortada reta.
  O esmaecimento da moldura agora termina onde a foto acaba.
- Voz que virava feminina no meio de uma resposta e voltava à masculina: uma falha passageira do edge-tts
  numa frase fazia só aquela frase cair na voz de reserva (gTTS), e esse áudio ainda era guardado no cache
  como se fosse da voz configurada. Agora o edge-tts é tentado 3 vezes antes da reserva; se ele cair de vez,
  a reserva segue por 1 minuto em vez de alternar frase a frase; e o áudio da reserva não entra mais no
  cache (o formato da chave mudou, o que descarta as frases já gravadas na voz errada).

## [3.9.1] — 2026-10-29

### Corrigido
- **Tarefas e lembretes em inglês não eram criados.** Com o modelo local, frases como "remind me to drink
  water in 5 minutes" ou "remind me tomorrow at 9 about the meeting" iam para o llama3.2, que chamava a
  ferramenta com dados inválidos (`quando="tomorrow 09:00"`) e, mesmo com a criação recusada, respondia
  "I've set a reminder".
  - Novo intérprete de tempo (`dominio/quando.py`), em português e inglês: "in 5 minutes", "in five minutes",
    "in an hour", "in half an hour", "at 3 pm", "tomorrow at 9", "tonight at 8", "next friday", "on monday at 3",
    "daqui a meia hora", "amanhã às 9h30", "às 3 da tarde", "na sexta que vem às 10h". Sem am/pm, 1–7 h é
    tarde/noite; horário que já passou vira amanhã; dia sem horário vira 9h.
  - O modo offline cria lembretes com o horário em qualquer posição da frase ("remind me to X in 5 minutes")
    e responde quando será ("tomorrow at 09:00 AM", "amanhã às 09:30"); perguntas ("tenho algum lembrete
    amanhã?") nunca criam lembretes.
  - Tarefas: "make/create/add a task to buy milk" cria "buy milk" (sem o "to").
  - Modelo local: datas em linguagem natural e textos em lista são convertidos antes de validar; se nenhuma
    criação der certo, o assistente diz que não conseguiu, em vez de repetir que criou.
- `tests/test_quando.py` e novos testes no modo offline e no modelo local.

## [3.9.0] — 2026-10-29

### Adicionado
- **Gerar documento** ("gerar doc"): salva em arquivo uma resposta do assistente.
  - "gerar doc" (ou "gerar doc dessa resposta") salva a última resposta; "gerar doc sobre <assunto>" pede ao
    modelo um texto completo e o salva, sem lê-lo em voz alta: só a confirmação é falada, e a legenda mostra
    o texto enquanto ele é escrito.
  - Arquivos em Markdown em `<Documentos>/Robofael` (pasta XDG do usuário; `ROBOFAEL_DOCUMENTOS` muda),
    com título, data, pedido e conteúdo; nome com data e assunto, sem sobrescrever outro arquivo; gravação
    atômica. O caminho aparece na tela.
  - Entende variações em português e inglês ("gera um documento sobre…", "generate a doc about…") e
    "gerar dock". Funciona com Claude, modelo local e modo offline.
  - Nova porta `RedatorDocumentos`: Claude e Ollama escrevem o documento com instruções e limite de tamanho
    próprios (no Ollama, 1500 tokens em vez dos 200 das respostas faladas), sem mexer no histórico da
    conversa. Antes disso, o documento do modelo local saía cortado no meio de uma frase.
  - Camadas: `dominio/documentos.py` (reconhecer o pedido, título e nome do arquivo),
    `aplicacao/documentos.py` (montar o documento e lembrar a última troca), `adaptadores/documentos.py`
    (gravar), coordenados pelo orquestrador.
- `tests/test_documentos.py` e testes do redator no Claude e no Ollama.

## [3.8.0] — 2026-10-26

### Adicionado
- **Local do banco** (⚙ → Memória → "Mudar local…"): o `memoria.db` passa para a pasta escolhida com o
  assistente aberto.
  - A cópia é feita pela API de backup do SQLite e conferida (`integrity_check`) antes da troca.
  - O antigo é guardado como `memoria.db.movido-<data>`, nunca apagado.
  - A mudança é recusada se a pasta já tiver um `memoria.db`.
  - A escolha fica em `<dados>/local_banco.json` e vale nas próximas aberturas (app, gravador de voz e
    `make integridade`).
  - Banco escolhido ausente ao abrir (disco desconectado): aviso e banco padrão só naquela vez, sem criar um
    banco vazio no lugar.
- **Backup do banco** (⚙ → Memória → "Fazer backup…"): cópia consistente com o app em uso, num arquivo único
  (sem `-wal`), conferida e com o total de registros do histórico.
- **Modelo de linguagem em uso** (⚙ → Assistente): mostra Claude, Ollama ou modo offline e o modelo. Também
  lista os modelos compatíveis de cada provedor, consultados em segundo plano:
  - Claude: os liberados para a chave (`models.list`);
  - Ollama: os instalados com `completion` e `tools`, com o tamanho.
  Sem chave, servidor fora do ar ou erro, a linha diz o motivo.
- Portas `ArquivoBanco` (parte de `PersistenciaAssistente`) e `CatalogoModelos`. Os modelos de linguagem
  informam `provedor` e `modelo`.

### Detalhes técnicos
- A tela de configurações ganhou as duas seções no fim das colunas, sem ficar mais larga.

## [3.7.0] — 2026-10-26

### Adicionado
- **Escolha do microfone** (⚙ → Microfone): lista os microfones conectados (PipeWire ou PulseAudio, via
  `pactl`), com a opção "Padrão do sistema". A troca vale na próxima escuta, sem reabrir o app:
  - o microfone é recalibrado (limiar de fala e ganho automático) quando muda;
  - a escuta de "ok Fael" é reaberta no microfone novo;
  - o `robofael-gravar-voz` usa o mesmo microfone;
  - um microfone escolhido e desconectado continua selecionado, marcado como "(desconectado)"; enquanto
    isso, vale o padrão do sistema.
- **Inicialização** (⚙ → Inicialização):
  - "Abrir ao entrar no computador": atalho XDG em `~/.config/autostart/robofael.desktop`;
  - "Abrir com o comando `robofael` no terminal": atalhos em `~/.local/bin` para `robofael` e
    `robofael-gravar-voz`. Instalado pelo `.deb`, o comando já existe e a opção fica bloqueada.
  - O estado é lido dos próprios arquivos; desligar só apaga atalhos criados para este programa.
- Novas portas `DispositivosAudio` e `InicializacaoSistema`; preferência `microfone` salva no SQLite.

### Corrigido
- Combos da tela de configurações: o texto ficava claro sobre cinza-claro (ilegível) no modo somente leitura.

### Detalhes técnicos
- O microfone continua sendo aberto pelo dispositivo padrão do ALSA; a escolha vai em `PIPEWIRE_NODE` e
  `PULSE_SOURCE`, definidas só durante a abertura do stream (não passam para os programas abertos pelo
  assistente). Abrir o `hw:` direto disputaria o aparelho com o PipeWire.
- A tela de configurações passou a ter duas colunas, para caber as seções novas.
- Testes não tocam a pasta pessoal: `HOME` e `XDG_CONFIG_HOME` apontam para uma pasta temporária.

## [3.6.0] — 2026-10-23

### Adicionado
- **Cérebro local com o Ollama** (`adaptadores/ollama.py`): sem o Claude, um modelo local (padrão
  `llama3.2:3b`) conversa e entende pedidos de agenda em linguagem livre. Se o Ollama não responder, ao
  abrir ou no meio do uso, vale o modo offline de sempre.
  - Respostas em camadas: os comandos que o modo offline reconhece continuam com ele; pedidos de agenda vão
    ao modelo só com as ferramentas do assunto, e só as seguras (criar e consultar); conversa vai sem
    ferramentas, em streaming.
  - Chamadas de ferramenta escritas como texto JSON são executadas ou descartadas, nunca faladas;
    temperatura 0 nas chamadas; argumentos óbvios convertidos ("false" → False).
  - "Só um instante." na hora em pedidos com ferramentas, que no processador levam dezenas de segundos.
  - Histórico compactado depois de cada troca e limitado a 16 mensagens; o modelo é pré-carregado com as
    mesmas opções da conversa (antes ele era recarregado na primeira fala).
  - Usa só a biblioteca padrão (HTTP + JSON): nenhuma dependência nova.
- `ROBOFAEL_CEREBRO` (`auto`, `claude`, `ollama`, `offline`), `ROBOFAEL_OLLAMA_URL` e
  `ROBOFAEL_OLLAMA_MODELO`.
- `tests/test_ollama.py`: camadas, ferramentas seguras, JSON no texto, queda para o modo offline,
  interrupção, histórico, idioma, cliente HTTP contra um servidor falso e escolha do cérebro.

### Alterado
- Com o modelo local ativo, a saudação não anuncia mais "modo offline".

## [3.5.0] — 2026-10-23

### Mudança incompatível: nome técnico `eurobo` → `robofael`
O produto já se chamava Robofael desde a 2.1.0; agora o nome técnico acompanha.
- Pacote Python: `eurobo` → `robofael` (`python -m robofael`, `from robofael... import ...`). Código que
  importava `eurobo` precisa ser atualizado: não há módulo `eurobo` de compatibilidade.
- Comandos: `robofael` e `robofael-gravar-voz`.
- Variáveis de ambiente: `EUROBO_*` → `ROBOFAEL_*` (ex.: `ROBOFAEL_DADOS`, `ROBOFAEL_IDIOMA`).
- Distribuição no pip: `robofael`. Quem já tem o `.venv` deve rodar `.venv/bin/pip uninstall -y eurobo`
  e depois `make instalar`.

### Alternativas mantidas
- `eurobo` e `eurobo-gravar-voz` continuam instalados como apelidos dos comandos novos.
- As variáveis `EUROBO_*` ainda são lidas quando a `ROBOFAEL_*` correspondente não está definida, com um
  aviso de depreciação no log. O lançador do `.deb` faz o mesmo, então um `EUROBO_DADOS` já configurado
  continua apontando para os mesmos dados.
- Dados e caches não mudam de lugar (`./dados`, `~/.local/share/robofael`, `~/.cache/robofael`).

## [3.4.0] — 2026-10-23

### Desempenho
- **CPU em repouso de 29% para 5% de um núcleo.** O redesenho do Tk recompunha, a cada quadro, duas
  imagens grandes com transparência (halo e avatar), mesmo sem nada mudar.
  - `CenaCanvas` (`apresentacao/cena.py`): só envia ao Tk o que mudou (coordenadas em pixels inteiros,
    opções com valor novo).
  - Halo opaco, já misturado com o fundo: o Tk copia os pixels em vez de misturar transparência
    (redesenho sob o halo caiu de ~8 ms para ~0,1 ms).
  - Taxa de quadros adaptativa: 60 FPS ouvindo, pensando, falando ou em transição; 30 FPS em repouso.
- **Janela visível em 0,6 s** (antes 1,7–2,4 s): os 40 halos são gerados fora da thread da interface e
  convertidos para o Tk aos poucos.
- **Trocar de avatar sem engasgo:** a conversão dos quadros para o Tk (~170 ms) passou para a
  `FilaTrabalhoUI`, com orçamento de 4 ms por quadro.

### Fala mais natural
- O silêncio que a voz sintetizada traz nas pontas (~0,25 s antes e ~1 s depois de cada frase) é aparado
  com margens de 30 ms e 150 ms: as frases se emendam como na fala natural, a primeira palavra sai antes e
  o estado "falando" termina junto com a voz. A saudação ficou ~1,6 s mais curta.
- Síntese de até duas frases em paralelo, tocadas na ordem: frases curtas seguidas não esperam mais a
  síntese da anterior.

### Usabilidade
- Enviar um texto com o assistente ocupado (ouvindo, pensando ou falando) interrompe o que ele está
  fazendo e atende o pedido novo. Antes, o pedido era descartado em silêncio. Vários envios seguidos:
  vale o mais recente.

### Arquitetura e qualidade
- `LacoQuadros` e `FilaTrabalhoUI` (`apresentacao/laco.py`) extraídos da janela principal.
- Tipagem completa obrigatória (`disallow_untyped_defs`): todas as funções dos 56 módulos têm assinatura tipada.
- `tests/test_renderizacao.py`: canvas diferencial, fila com orçamento, laço adaptativo e uma regressão
  de desempenho determinística (comandos enviados ao Tk por segundo em repouso). Novos testes de corte de
  silêncio, síntese paralela e pedidos digitados durante a fala: 546 testes, 85,9% de cobertura.

## [3.3.0] — 2026-10-22

### Alterado (SOLID e código limpo, sem mudança de comportamento)
- **Responsabilidade única**: o `Orquestrador` passou a só coordenar. O pipeline de fala virou `PipelineFala`
  (`aplicacao/pipeline.py`) e a escuta passiva, `VigiaAtivacao` (`aplicacao/vigia.py`). As políticas da sessão
  (voz, idioma, ativação, saudação, aplicar preferências) saíram do `bootstrap.py` e da janela para
  `aplicacao/sessao.py`; o `bootstrap.py` só compõe.
- **Aberto/fechado**: modo offline como cadeia de intenções, ferramentas do Claude como tabela de ações,
  expressões de período como lista de interpretadores.
- **Inversão de dependência e segregação de interfaces**: o `Nucleo` depende da porta `PersistenciaAssistente`
  (não do `BancoSqlite`); novas portas `SintetizadorConfiguravel` e `CapturaAudio` (fim dos `getattr` e `Any`);
  `RepositorioAgenda` e `Programa` passaram para o domínio; o gravador de voz obtém microfone e voz pela raiz
  de composição.
- **Substituição de Liskov**: o `RepositorioJson` (formato legado, sem histórico) deixou de fingir ser um
  repositório da agenda.
- Funções longas divididas (camisa do avatar — saída idêntica pixel a pixel —, extração do comando de voz);
  limiares nomeados; diálogo de configurações recebe `OpcoesConfiguracoes` e `AcoesConfiguracoes`.

### Adicionado
- `tests/test_arquitetura.py`: regra de dependência entre camadas e princípios SOLID verificados no CI.
- `tests/test_sessao_pipeline_vigia.py`: testes unitários dos colaboradores extraídos.
- Regras do ruff: complexidade ciclomática ≤ 10, funções curtas, nomes no padrão e parâmetros sem uso.
- Cobertura mínima de 80% exigida (`fail_under`).
- **Monografia** (TCC no padrão ABNT) em `docs/monografia/`: requisitos funcionais e não funcionais,
  arquitetura, construção passo a passo, revisão SOLID e validação; `make monografia` gera o PDF.

### Corrigido
- Teste de interface intermitente: imagens Tk de janelas anteriores eram recolhidas pelo coletor de lixo numa
  thread de trabalho e a travavam; a coleta agora acontece na thread principal (fixture `raiz` unificada).

## [3.2.0] — 2026-10-22

### Adicionado
- **Instalador para Ubuntu (.deb)**: `make deb` gera `dist/robofael_<versão>_<arq>.deb`, instalável com
  `sudo apt install ./dist/...deb`. Traz as dependências Python (wheels) e o modelo de voz: instala sem
  internet e de forma determinística em `/opt/robofael`; comandos `robofael` e `robofael-gravar-voz`;
  atalhos no menu e ícone; dados de cada usuário em `~/.local/share/robofael` (preservados no `remove`).
- `make testar-deb`: testa o pacote numa pasta temporária (integridade, ambiente, lançadores, dados,
  remoção e purge) sem instalar no sistema.
- A janela usa a classe `robofael`, para o Ubuntu associá-la ao ícone do menu.

## [3.1.0] — 2026-10-22

### Adicionado
- **Internacionalização (pt-BR / en-US)**: o assistente responde, fala e exibe a interface em inglês quando
  configurado (⚙ → Idioma, `--idioma en-US` ou `EUROBO_IDIOMA=en-US`), com troca ao vivo.
  - Catálogo central (`i18n.py`) com as duas línguas lado a lado e `Tradutor` injetado em todos os componentes;
    teste que garante tradução completa e os mesmos campos de formatação.
  - Comandos entendidos nos dois idiomas sempre ("add task", "what did I do last week?", "open the calculator").
  - Períodos em inglês ("yesterday", "last week", "on Monday", "October 5th", "the week of 10/5"); datas
    numéricas seguem o idioma (dia/mês × mês/dia).
  - Reconhecimento de fala, voz neural (Andrew, Brian, Guy, Jenny), voz de reserva e instruções do Claude
    acompanham o idioma; trocar de idioma recomeça a conversa com o Claude.

### Corrigido
- O diálogo de configurações podia falhar ao virar modal antes de aparecer na tela (agora tenta de novo).
- A instrução ao modelo deixou de atribuir gênero ao usuário.

## [3.0.1] — 2026-10-22

### Adicionado
- **Ganho automático** do microfone (escuta passiva e captura do comando): amplifica até 8× a voz que
  chega baixa antes de enviá-la aos reconhecedores; resistente a picos isolados (batidas no microfone).
- **Aviso de voz baixa** (terminal e tela) quando o volume de entrada é insuficiente, com a orientação
  de aumentar a entrada ou trocar de microfone. Logs de `-v` mostram o pico e o ganho de cada fala.

### Corrigido
- Variáveis Tk da tela de configurações eram liberadas fora da thread principal.

## [3.0.0] — 2026-10-22

### Adicionado
- **Memória de longo prazo em SQLite** (`dados/memoria.db`): agenda, histórico e preferências.
  - Histórico **auditável**: somente acréscimo (triggers recusam UPDATE/DELETE) e cadeia de hashes SHA-256
    que detecta adulteração (`make integridade`); estado e registros gravados na mesma transação.
  - Esquema versionado (`PRAGMA user_version`); importação automática do `agenda.json` anterior.
- **"O que eu fiz?"** em um dia, semana ou período ("ontem", "na segunda", "dia 20/10", "semana passada",
  "últimos 7 dias", "mês passado"...), no modo offline e via ferramenta `consultar_historico` do Claude.
- **Abrir programas instalados** no Linux ("abre o navegador", "abre a calculadora"): entradas `.desktop`
  (XDG, Snap, Flatpak), sinônimos PT→EN, navegador padrão, desambiguação e abertura sem shell
  (`gtk-launch`). Ferramentas `abrir_programa` e `listar_programas` para o Claude.
- **Tela de configurações (⚙)**: avatar, voz base, tom, ritmo (com "Ouvir"), "usar meu perfil gravado"
  e ativação por voz — aplicadas na hora e salvas entre sessões.

### Alterado
- Janela com **tamanho fixo** (não maximiza nem entra em tela cheia, o que deslocava o avatar).
- Tarefas registram a data de conclusão (`concluida_em`).
- `--avatar` passa a ter como padrão o avatar salvo nas configurações.

### Migração
- Na primeira execução, `dados/agenda.json` é importado para `dados/memoria.db` e renomeado para
  `agenda.json.migrado-<data>` (nada é apagado).

## [2.3.0] — 2026-10-22

### Alterado
- A frase de ativação passa a ser **"ok Fael"** (antes "ok Robofael"), configurável em
  `EUROBO_FRASE_ATIVACAO` e independente do nome do assistente.
- Detecção por **gramática restrita** no Vosk para "ok Fael", com variantes aceitas e frases
  distratoras. Calibrada com 5 vozes: 0 falsos positivos em 115 frases parecidas e 8 de 8 na voz do usuário.
- Comando dito logo após a frase: a escuta passiva continua gravando enquanto há voz, e o texto do Google
  é limpo da frase mesmo quando ela é mal transcrita ("o que Israel anota tarefa..." → "anota tarefa...").
- Modo offline aceita "a nota tarefa ..." (como o Google às vezes transcreve "anota").

## [2.2.0] — 2026-10-21

### Adicionado
- **Ativação por voz**: diga "ok Robofael" (ou "ok Robofael, <comando>" numa frase só) em vez de apertar ESPAÇO.
  - Escuta passiva **local** com Vosk (`vosk-model-small-pt-0.3`): o áudio do ambiente não sai do computador.
  - Detecção **fonética** (`dominio/ativacao.py`), calibrada com transcrições reais; o nome do usuário
    ("ok Rafael") e frases parecidas no meio da fala não disparam.
  - O comando dito junto com a frase é transcrito com precisão pelo Google e alinhado com a transcrição local.
  - Bipe de dois tons confirma a ativação; status em repouso mostra "Diga “Ok robofael” ou aperte ESPAÇO".
  - `--sem-ativacao` / `EUROBO_ATIVACAO=0` desligam; `make baixar-modelo-voz` instala o modelo.

### Corrigido
- Ctrl+C e SIGTERM não fechavam o programa (o SDL do pygame capturava os sinais).
- Ruído do JACK/ALSA no terminal a cada abertura do microfone (stderr nativo silenciado).
- Aviso claro quando `ANTHROPIC_BASE_URL` aponta para outro servidor (ex.: Ollama local).

## [2.1.0] — 2026-10-21

### Alterado
- O assistente passa a se chamar **Robofael** (título da janela, saudação, instruções do modelo e logs).
  O nome agora fica centralizado em `Configuracao.nome_assistente` e pode ser trocado por `EUROBO_ASSISTENTE`.

## [2.0.0] — 2026-10-21

Reescrita completa da arquitetura com foco em latência, fluidez e testabilidade.

### Arquitetura
- Arquitetura hexagonal: `dominio` (regras puras) · `portas` (contratos) · `aplicacao` (casos de uso) ·
  `adaptadores` (Claude, Google Speech, edge-tts, pygame, JSON) · `apresentacao` (Tk) · `bootstrap` (composição).
- Domínio tipado com `dataclasses` (`Tarefa`, `Lembrete`, `DadosAgenda`) no lugar de dicionários soltos.
- Máquina de estados explícita (`Estado` + transições válidas) no lugar de strings mutáveis.
- Barramento de eventos: só a thread principal toca no Tk; workers publicam eventos.
- Configuração imutável e tipada (`Configuracao.do_ambiente()`), sem estado global.

### Desempenho e latência
- **Pipeline em streaming**: o Claude transmite o texto, as frases vão sendo sintetizadas e a primeira
  já toca enquanto as próximas são geradas (antes: esperava resposta inteira + voz inteira).
- Divisor de frases incremental (corta cedo a primeira frase; não quebra números nem abreviações).
- Áudio decodificado em memória (sem arquivos temporários) e envelope da boca calculado antes de tocar.
- Cache em disco das falas sintetizadas (LRU), saudações e lembretes saem instantâneos.
- Renderização do avatar em paralelo (1,6–1,9× mais rápida) e fora da thread da interface; leitura do
  cache em 0,1–0,2 s; quadro de boca fechada calculado uma única vez.
- Inicialização em paralelo (Claude, microfone e áudio) em segundo plano: janela visível em < 1 s.
- Lembretes disparados no horário exato (thread dorme até o próximo; antes: polling de 15 s).

### Usabilidade
- Microfone com detecção de fala própria: barras mostram o **nível real** da sua voz, pausa de fim de
  frase menor (0,7 s), ruídos curtos ignorados e escuta cancelável a qualquer momento.
- Legenda da resposta aparece enquanto é gerada.
- Transições suaves de cor entre estados; animação independente da taxa de quadros (laço com
  compensação de deriva); leve balanço do avatar em repouso.
- Painel interativo: duplo clique conclui/reabre tarefa, Delete remove; atualizado por evento.
- Botão contextual (Falar / Cancelar / Parar / Interromper), placeholder na caixa de texto, ESC
  interrompe, Ctrl+Q fecha, janela centralizada, troca de avatar sem travar.

### Confiabilidade
- Escrita atômica da agenda (`os.replace`) e preservação de arquivo corrompido; migração do formato v1.
- Histórico do Claude append-only com *rollback* da rodada em erro, recusa ou interrupção.
- Entradas das ferramentas validadas contra o schema (`eager_input_streaming`); entrada truncada
  (`max_tokens`) nunca é executada.
- Corrigidos: cancelamento perdido ao apertar ESPAÇO duas vezes rápido; notificação perdida no
  agendador; limiar de tempo do VAD por erro de ponto flutuante; UI do gravador acessada fora da
  thread principal; padrões da configuração com `slots`.

### Qualidade
- 168 testes (domínio, aplicação, adaptadores com dublês, interface com Tk real), `mypy` limpo,
  `ruff`, *pre-commit* e CI no GitHub Actions (Python 3.10 e 3.12, com Xvfb).

## [1.0.0]
- Primeira versão estruturada como pacote: avatar animado, voz, agenda, Claude com ferramentas, perfil de voz.
