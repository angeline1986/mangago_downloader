# Investigação técnica — Provider Lezhin

**Repositório analisado:** `angeline1986/mangago_downloader`
**Commit de referência:** `b4b4e4e3f5080f42e689d1fe279c4c136f130b61`
**Checkout analisado:** `e0e034e0b477aff8e428e11a7d57fe549e20185f` (o commit de referência é ancestral)
**Data:** 2026-10-20
**Escopo:** diagnóstico somente. Nenhum código do aplicativo foi alterado.

## 1. Resumo executivo

O Ridi não usa um “servidor de login”. Há dois processos de aplicação distintos: o backend Python da Central Web atende a interface e coordena operações; um Chrome real, dedicado ao Ridi, é iniciado como subprocesso com depuração remota em `127.0.0.1:9222`. A sessão autenticada fica no perfil desse Chrome. O Playwright conecta-se ao Chrome existente por CDP para operar páginas nessa sessão, sem encerrar o navegador. Não foi encontrado outro serviço auxiliar de login.

No piloto prático de `2026-10-20`, a instância Chrome isolada em `/private/tmp/lezhin_pilot_profile_20261020`, CDP `127.0.0.1:9223`, reutilizou a sessão manual: o episódio autorizado abriu e permaneceu acessível após reload. O leitor mostrou 68 cortes indexados de `0` a `67`, com imagens HTTPS carregadas conforme a rolagem; não foram encontrados `blob:`. O DOM mantém os contêineres indexados e remove imagens fora da região carregada. O acesso por CDP é viável e adequado para manter a sessão isolada neste projeto, mas ainda não foi demonstrado que Lezhin o exige em vez de outro contexto autenticado.

**Resultado global do piloto:** leitura do segundo episódio gratuito, continuidade dos 68 índices, virtualização, respostas WebP, opções `1x`/`1.5x`/`2x`, gravação atômica e verificação SHA-256 **CONFIRMADAS** nos limites descritos nas seções 19–20. **Parecer final: APTO para iniciar a implementação**, com captura incremental por índice e preservação direta do corpo WebP. A escala de leitura não alterou bytes, hash ou dimensões da amostra; seu efeito de rolagem não foi medido. O canvas permanece bloqueado por CORS e não é necessário. A persistência após reiniciar Chrome e a memória nativa do navegador continuam não medidas.

**Conclusão:** o parecer final é **APTO para iniciar a implementação**. A leitura autorizada, o scroll e a obtenção dos bytes originais servidos são viáveis com Playwright conectado ao Chrome isolado. Recomenda-se um provider Lezhin separado, usando perfil e porta CDP exclusivos para reutilizar a sessão manual sem tocar no Ridi, e o motor comum para fila, progresso, validação e destino. A captura deve guardar o corpo WebP diretamente, sem conversão, usando gravação incremental atômica por índice. As seções 18–20 registram evidências e pendências para acompanhar durante o desenvolvimento.

## 2. Legenda de evidência

- **Confirmado no código:** observado diretamente no checkout e, quando aplicável, coberto por testes automatizados existentes.
- **Confirmado externamente:** observado em página pública oficial; não implica acesso ao leitor nem autenticação.
- **Hipótese:** direção técnica plausível que precisa de experimento.
- **Pendente:** sem teste ou evidência suficiente nesta investigação.

Os testes existentes do Ridi são testes de contrato/offline com mocks. Eles demonstram o comportamento programado, mas não provam o comportamento atual dos sites em uma sessão real.

## 3. Arquitetura Ridi atual: navegador, sessão e backend

### 3.1 Processos e responsabilidades

**Confirmado no código:**

1. A interface (`webapp/static/app.js`) chama endpoints HTTP do backend Python (`webapp/server.py`), por exemplo `GET /api/ridi/session`, `POST /api/ridi/session/start` e `POST /api/ridi/chapters`.
2. `start_ridi_chrome()` inicia o executável Google Chrome via `subprocess.Popen`, com `--user-data-dir=<perfil>` e `--remote-debugging-port=9222`. O processo é destacado da vida útil da requisição e seus streams são descartados.
3. O próprio backend Python fornece os endpoints da Central Web e coordena o downloader. O Chrome não fornece esses endpoints e não é um serviço de autenticação separado.
4. `ridi_cdp_browser_page()` conecta Playwright a `http://127.0.0.1:9222` com `connect_over_cdp`, reutiliza um contexto e uma página Ridi existentes (ou cria uma página), e ao sair encerra somente a conexão/driver Playwright. Não fecha o processo Chrome nem o contexto externo.
5. O perfil padrão é `~/.cache/ridibooks_chrome_profile`, separado do perfil pessoal padrão do Chrome. Isso preserva cookies e outros dados do perfil entre execuções.

`ridi_browser_page()` existe para abrir um contexto persistente próprio com `channel="chrome"`, mas fecha o contexto no fim. A documentação da função recomenda anexar ao Chrome que já está aberto para coleta autenticada, em vez de fechar/reabrir o perfil.

### 3.2 Como o estado autenticado é inferido

**Confirmado no código:** `get_ridi_session_status()` tenta conectar ao CDP e verifica se há cookie de nome `ridi_auth` no domínio Ridi. Retorna apenas os estados e uma mensagem; o valor do cookie não é retornado. Se o CDP/contexto não puder ser acessado, informa Chrome parado.

**Limite:** a presença desse cookie é um indicador operacional, não uma prova de que a sessão ainda autoriza determinada obra ou capítulo. A descoberta/leitura também verifica redirecionamento para a tela de login. O teste unitário verifica que o segredo não aparece no retorno; não valida autorização real no site.

### 3.3 Inicialização e dependências

**Confirmado no código:** o backend procura Chrome real (ou `RIDI_CHROME_EXECUTABLE`), inicia o perfil dedicado e aguarda a porta CDP por até 8 segundos. Se já há um Chrome respondendo no CDP, não inicia outra instância. O endpoint de sessão/start é servido pelo mesmo backend Web da aplicação.

**Não identificado:** processo auxiliar de login, serviço externo local, API de autenticação própria ou backend independente do site. A dependência adicional específica do Ridi é o Chrome real iniciado com CDP; Playwright é biblioteca usada pelo backend para conectar-se.

### 3.4 Captura e preservação de imagens no Ridi

**Confirmado no código:** o provider instala um script de inicialização antes da navegação. O script observa `URL.createObjectURL`, lê bytes do `Blob` via `arrayBuffer()`, associa a URL de objeto ao `img[data-index]` e entrega os bytes ao Python em base64. O Python decodifica, detecta formato e guarda conteúdo bruto. A estrutura é validada como índices inteiros contíguos iniciados em zero; cada índice ausente causa erro. O coletor tenta materializar cada imagem com scroll e aguarda eventos por página.

O salvamento mantém a extensão/formato detectado e bytes originais no modo `image_format="original"`. A configuração padrão do downloader é `original`; se PNG for escolhido, o fluxo compartilhado converte a imagem, e a cópia original só é mantida com `keep_originals` ativo.

**Limites observados:** os bytes passam por cópia/base64 entre a página e o processo Python, o que pode elevar uso de memória. A captura inteira é coletada antes do início do salvamento; o marcador `.download-in-progress.json` é escrito depois dessa captura. Interrupção durante a captura não tem checkpoint por página, e a retomada/reconciliação precisa ser comprovada em teste.

## 4. Evidência disponível sobre Lezhin

### 4.1 Site e episódios

**Confirmado externamente:** páginas públicas do Lezhin Comics mostram título, lista numerada de episódios e indicação de episódio gratuito ou preço em Coins. Uma página pública consultada apresenta episódios 1–3 como gratuitos e os seguintes como pagos; a própria página disponibiliza fluxo de login. Isso confirma que listagem pública e acesso ao leitor são camadas distintas, e que a disponibilidade não pode ser inferida só pela existência de link de episódio. [Página oficial de The Secret Life of Empress Isana](https://www.lezhinus.com/en/comic/isana).

Essa inspeção pública não abriu nem capturou o leitor. O conteúdo da página retornado pela consulta pública não comprova que um episódio carregue sem login, que o acesso concedido seja persistente, nem como as imagens são transportadas.

### 4.2 Estrutura do leitor

**Relato recebido no roteiro, não reproduzido nesta investigação:** contêineres `[data-cut-index]`, imagens com `src` `blob:`, carregamento progressivo com scroll e conversão experimental para PNG por canvas.

**Pendente:**

- Confirmar se esses seletores ainda existem e em quais variantes/regiões do site.
- Identificar se o índice é zero-based, contínuo, único e representa a ordem final; medir o total sem confundir DOM parcialmente carregado com total do episódio.
- Confirmar lazy loading, comportamento após scroll até o fim e diferenças entre episódios.
- Verificar se os bytes originais podem ser obtidos e persistidos em formato original dentro do fluxo permitido pelo site e pela autorização da conta. Canvas pode alterar formato/qualidade e não deve ser pressuposto como caminho necessário.
- Avaliar se Playwright observa a página sem depender de seletor frágil ou temporização arbitrária.
- Validar episódio acessível à conta de teste, inclusive limite de autorização. A existência de sessão não deve ampliar acesso além do que a conta já pode ler.

**Hipótese:** se o leitor realmente cria `Blob` de imagem associados aos cuts, a observação de rede/DOM no Playwright pode confirmar se há bytes originais disponíveis no contexto. Só após isso se decide entre usar recursos do navegador conectado e outra estratégia permitida. Não há base para copiar diretamente o interceptador do Ridi: sua instrumentação é específica a `img[data-index]` e ao ciclo de `URL.createObjectURL` observado no Ridi.

## 5. Comparativo Ridi × Lezhin

| Área | Ridi — evidência local | Lezhin — estado desta investigação |
|---|---|---|
| Chrome / CDP | Chrome dedicado, perfil persistente e porta 9222 confirmados no código | Perfil isolado e CDP 9223 reutilizados com sucesso; necessidade intrínseca do CDP ainda não demonstrada |
| Login | Login manual no Chrome; sessão sondada pelo cookie `ridi_auth` e redirecionamento | Sessão existente abriu episódio gratuito e persistiu após reload; reinício do Chrome não testado |
| Backend Web | Backend Python recebe requests da UI e opera o Chrome via Playwright | O provider precisaria integrar-se ao backend existente; nenhum endpoint Lezhin presente |
| Descoberta de capítulos | Lista DOM da obra e links `/books/<id>/view`, com validações de domínio/rota | Página pública mostra episódios e estado de gratuidade/preço; sem parser comprovado |
| Leitor / ordem | `img[data-index]`; valida sequência 0..N-1; coleta Blob original | Dois episódios com 68 índices `0..67`; resposta WebP correlacionada pelo `data-cut-index` |
| Scroll/lazy load | Scroll explícito por índice, polling e atraso entre tentativas | Virtualização confirmada; os 68 cortes do segundo episódio decodificaram ao serem percorridos |
| Formato/qualidade | Bytes originais preservados no modo padrão; PNG opcional no motor compartilhado | `Response.body()` WebP salvo sem conversão; hash/arquivo verificados. Canvas bloqueado por CORS |
| Interrupção | Validação estrutural compartilhada; captura não checkpointa antes do fim | `.part`, falta e duplicata simulados; a política deve ser implementada incrementalmente por índice |

## 6. Reuso recomendado e pontos de extensão

### Reutilizar sem duplicar

- **Modelos:** `src/models.py` (`Manga`, `Chapter`, `DownloadResult`). O provider deve devolver capítulos com URL própria validada.
- **Fila e acompanhamento:** `webapp/server.py` cria jobs e delega a `ChapterDownloader`; callbacks atualizam o progresso por capítulo/página.
- **Roteamento:** `src/downloader.py::download_chapter()` já roteia Ridi e Comix a providers dedicados antes do fluxo genérico. Um provider Lezhin pode seguir o mesmo ponto de extensão, condicionado ao diagnóstico.
- **Destino e integridade:** `src/output_paths.py::chapter_image_dir`, `src/chapter_validation.py` e `ChapterDownloader._finalize_download_result()` fornecem diretório canônico, validação de imagem/quantidade, marcadores e conclusão.
- **Persistência de formato:** `ChapterDownloader._save_image_bytes()` valida imagem e preserva bytes se `image_format="original"`; requer cuidado para não converter blob desnecessariamente.
- **Formato de pastas:** `format_ridi_chapter_folder()` é específico do Ridi; reutilizar o padrão da UI/formatador comum onde compatível, sem copiar semântica de numeração Ridi.

### Isolar por provider

- Validadores de URL e hosts Lezhin próprios; não ampliar os validadores Ridi/Mangago.
- Perfil Chrome e porta CDP exclusivos para Lezhin **se o piloto confirmar** necessidade de Chrome dedicado. Não compartilhar o perfil Ridi nem a porta 9222 simultaneamente; definir comportamento se uma instância estiver em execução.
- Checagem de sessão com sinal verificável do Lezhin e teste de acesso a episódio permitido; não reutilizar o cookie `ridi_auth` nem tratar CDP aberto como autenticação.
- Descoberta de capítulos, identificação de cuts e captura de bytes em `lezhin_provider.py` (ou módulos pequenos por responsabilidade, respeitando o limite de 200 linhas de código por arquivo).
- Endpoint/sessão e UI com prefixo Lezhin próprios, seguindo os componentes Ridi da interface somente após a necessidade de sessão separada ser comprovada.

### Estado de obras salvas

**Confirmado no checkout:** existe `data/saved_works/lezhinus.json` com uma obra de exemplo. Porém, `src/saved_works.py` só aceita `comix`, `mangago` e `ridi`; portanto o backend Downloader atual não consegue carregar esse provider pelo endpoint existente. Há strings “lezhin” no catálogo de termos de busca do frontend, mas isso não implementa um provider. No repositório pai deste workspace, os contratos de obras salvas também já aceitam `lezhinus`; isso é outro componente e não substitui o suporte do `mangago_downloader`.

## 7. Lacunas ainda abertas

1. Sessão manual Lezhin preservada em perfil dedicado e consumida por Playwright/CDP.
2. Distinção confiável entre Chrome ativo, login válido e episódio efetivamente autorizado.
3. Forma e estabilidade de URLs de obra/episódio por região/idioma.
4. Disponibilidade e ordem total dos cuts, inclusive episódios com conteúdo extra ou segmentação diferente.
5. Fonte dos bytes originais, MIME/extensão, resolução e qualidade após o pipeline do site.
6. Custos de memória em episódio real e efeito do acúmulo de Blobs/base64.
7. Interrupção, retry e estado parcial durante descoberta/captura/salvamento.
8. Compatibilidade com acesso gratuito, desbloqueio/compra e limites próprios da conta.
9. Como uma porta/perfil Lezhin exclusivo coexistiria com Chrome Ridi já aberto.
10. Confirmação do contrato de frontend: atualmente há somente UI/rotas Ridi para sessão, descoberta e seleção.

## 8. Arquivos que provavelmente seriam impactados após aprovação

Relação preliminar, não ordem final:

- `src/lezhin_provider.py` (ou provider dividido em módulos coesos): URLs, sessão, descoberta, captura e persistência autorizada.
- `src/downloader.py`: roteamento do capítulo ao provider isolado.
- `src/saved_works.py` e `data/saved_works/lezhinus.json`: contrato do provider e arquivo de obras salvas.
- `webapp/server.py`: endpoints de status/start e descoberta, somente se CDP/sessão própria for necessária.
- `webapp/templates/index.html`, `webapp/static/app.js`, possivelmente `webapp/static/styles.css`: navegação, estado de sessão, lista de capítulos, seleção, configuração e fila, usando o padrão existente.
- `tests/test_lezhin_provider.py`, testes de roteamento e de contrato Web: testes offline com mocks após definição dos contratos.
- `docs/lezhin_provider_investigation.md`: este relatório deve ser atualizado com resultados do piloto antes de aprovação de implementação.

Não há indicação de alterar `chapter_validation.py`, `output_paths.py` ou `models.py` nesta fase: os contratos parecem suficientes para capítulos cujo total e páginas foram confirmados. Só mudar após lacuna concreta demonstrada.

## 9. Arquitetura proposta, condicionada ao piloto

1. **Primeiro decidir o ciclo de sessão:** usar CDP dedicado com perfil e porta próprios apenas se o login manual persistente for necessário e Playwright conseguir reutilizá-lo de forma estável. O backend da Central Web permanece responsável pelos endpoints; Chrome permanece um processo de navegador separado. Se o site funcionar em contexto Playwright isolado com sessão aceitável e persistente, registrar essa evidência e escolher o menor fluxo compatível.
2. **Manter provider isolado:** validar host/URL, consultar sessão, descobrir episódios autorizados e capturar cada episódio sem contaminar código Ridi/Mangago.
3. **Captura original primeiro:** determinar se a página permite acesso aos bytes originais no contexto autorizado. Persistir em formato original e só converter se usuário/configuração solicitar. Se apenas canvas fornecer imagem utilizável, medir dimensão, formato e perda antes de decisão.
4. **Validar antes de marcar conclusão:** confirmar conjunto completo, ordem e decodificação de cada arquivo; só então chamar validação compartilhada e marcar job como concluído.
5. **Integrar fila/UI:** reutilizar modelos, seleção, progresso, destinos e mensagens da aplicação, com endpoints e estado de sessão Lezhin independentes se necessários.

## 10. Plano de implementação em etapas

1. Executar sessão manual no Chrome de teste com perfil limpo; registrar apenas estados/URLs/tempos, nunca cookies, tokens ou headers sensíveis.
2. Abrir uma obra e um episódio de leitura autorizada; registrar seletor/URL, número de cuts antes e depois do scroll, índice mínimo/máximo, lacunas, mudança de DOM e carregamento completo.
3. Capturar somente metadados e um pequeno conjunto de imagens de teste permitido para comparar bytes, formato, resolução e memória; não executar lote nem tentar desbloquear conteúdo indisponível.
4. Repetir em episódio diferente para identificar variação e testar uma interrupção controlada no episódio piloto.
5. Decidir arquitetura de sessão e captura; atualizar este relatório com evidências e pendências residuais.
6. Submeter o relatório para aprovação antes de implementar.
7. Após aprovação: adicionar provider isolado, persistência de obras, rota de download e UI em mudanças pequenas, cobertas por testes offline/mock e por piloto manual autorizado.

## 11. Critérios de aceite do diagnóstico e da futura implementação

### Para aprovar a arquitetura

- Login manual é reutilizado de forma reproduzível sem misturar perfil/credencial Ridi.
- O relatório identifica processo do backend, processo Chrome e conexão CDP sem os confundir.
- Um episódio autorizado tem total, índices, ordem e condição de término demonstrados; os resultados são repetíveis em mais de um episódio.
- Estratégia escolhida mantém resolução/formato original quando permitido, ou documenta a conversão e a perda observada.
- Uso de memória, falha/interrupção e recuperação têm medidas ou comportamento reproduzível.
- Nenhum acesso pago/restrito é contornado; a verificação respeita o acesso concedido à conta.

### Para aprovar a implementação

- Provider valida domínio/URL e só lista episódios disponíveis à sessão/conta.
- Sessão Lezhin não compartilha perfil, porta, estado ou heurística de autenticação com Ridi.
- Captura rejeita índices ausentes/duplicados, imagens inválidas e quantidade diferente do esperado; falha não recebe marcador de conclusão.
- Bytes e extensão são preservados no modo original; progresso reporta páginas salvas e erros sem expor credenciais.
- Obras salvas, seleção, configuração de pastas, fila e acompanhamento funcionam no padrão existente.
- Testes offline cobrem contratos e falhas; piloto de um episódio permitido confirma integração end-to-end.

## 12. Conclusão preliminar (superada pela seção 18)

À época deste registro, apenas a infraestrutura isolada havia sido confirmada; a leitura ainda estava pendente. A evidência posterior e a conclusão atual estão na seção 18.

## 13. Piloto prático — tentativa de execução (2026-10-20)

### Resultado do ambiente

**CONFIRMADO:** o checkout usado continua em `e0e034e0b477aff8e428e11a7d57fe549e20185f`; o commit de referência é ancestral. A única alteração no checkout do downloader nesta etapa é este relatório.

**CONFIRMADO:** conexões TCP locais às portas `127.0.0.1:9222` e `127.0.0.1:9223` falharam (`nc -z` retornou status 1 nas duas). Não há endpoint CDP acessível nessas portas neste momento. A porta 9222 não está disponível para o piloto; 9223 também não tem listener após as duas tentativas de abertura. O perfil temporário foi criado, mas sua associação a um processo Chrome ativo não pôde ser confirmada.

**NÃO CONFIRMADO (erro registrado):** a listagem de processos foi tentada com `ps -axo pid,comm,args`, mas o sistema bloqueou a operação com `zsh: operation not permitted: ps`. Portanto, não foi possível confirmar por lista de processos se há algum Chrome aberto em outra configuração/porta.

**CONFIRMADO:** foi tentada a abertura via LaunchServices com perfil isolado em `/private/tmp/lezhin_pilot_profile_20261020` e porta `9223`; o diretório foi criado, mas não apareceu `DevToolsActivePort` e a conexão CDP continuou recusada. Uma segunda tentativa pelo executável informou `Abrindo em uma sessão de navegador existente.` e também não ativou a porta. Como a inspeção de processos está bloqueada, não é possível provar qual instância recebeu a abertura nem confirmar que a janela efetiva está isolada. Por segurança, nenhum login foi feito e nenhum cookie, token ou credencial foi consultado ou registrado. Consequentemente, não foi possível validar uma sessão autenticada, a abertura de episódio, o DOM do leitor ou a captura.

### Resultados por critério

| Item | Estado | Evidência desta tentativa |
|---|---|---|
| Login manual e persistência após login | **PENDENTE** | Não houve login manual; a janela/perfil efetivamente aberto não puderam ser confirmados. |
| Playwright via CDP com sessão existente | **PENDENTE** | Sem endpoint CDP ativo (`9222` e `9223` recusaram conexão); não houve contexto para anexar. |
| Acesso a episódio autorizado | **PENDENTE** | Não havia sessão autenticada disponível. Nenhum episódio foi aberto. |
| Perfil/porta exclusivos para Lezhin | **NÃO CONFIRMADO** | A porta 9222 e o perfil Ridi não foram usados; a necessidade de CDP exclusivo depende do piloto autenticado. |
| Reabertura do Chrome e renovação da sessão | **PENDENTE** | O perfil de teste não pôde ser confirmado nem fechado/reaberto com controle. |
| `[data-cut-index]`, imagens `blob:` e DOM real | **PENDENTE** | Nenhum DOM autenticado do leitor foi observado. Os seletores mencionados antes permanecem apenas como relato do roteiro. |
| Índices, total, ordem e remoção de nós | **PENDENTE** | Sem episódio aberto; nenhum índice ou mutação foi medido. |
| Scroll e carregamento progressivo | **PENDENTE** | Não observado em navegador. |
| Dados de imagem originais versus canvas | **PENDENTE** | Nenhum byte/imagem de episódio foi coletado; nenhuma comparação de resolução, MIME ou qualidade foi realizada. |
| Duplicatas, lacunas, término e falhas | **PENDENTE** | Não houve execução de coleta para exercitar essas condições. |
| Memória e interrupção/retomada | **PENDENTE** | Sem execução representativa, não há medição válida. |
| Roteamento, validação e paths do projeto | **CONFIRMADO no código** | A análise estática descrita nas seções 3 e 6 confirma os pontos de extensão existentes; não equivale a um teste end-to-end. |
| Registro de cookies/tokens | **CONFIRMADO** | Nenhum cookie, token ou credencial foi consultado ou registrado durante esta tentativa. |

### Decisão técnica provisória

**NÃO CONFIRMADO:** ainda não é possível afirmar que o Lezhin precisa da arquitetura Ridi (Chrome dedicado + CDP), nem que exista alternativa mais simples que satisfaça a persistência do login. A indisponibilidade local de CDP não é evidência de que CDP seja necessário ou desnecessário no Lezhin.

**PENDENTE para concluir o critério de conclusão:** disponibilizar interação manual com um Chrome de teste isolado, sem compartilhar o perfil Ridi e sem reutilizar a porta 9222. A porta `9223` foi sondada e estava livre neste momento; antes de iniciar, deve-se confirmar novamente que segue sem listener. O perfil temporário do piloto precisa ser exclusivo para Lezhin. Depois do login, só registrar status, URLs não sensíveis, atributos/índices do DOM, dimensões e metadados de imagem; não registrar conteúdo de cookies, tokens ou headers de autenticação.

Sem esse acesso interativo e um episódio autorizado, não há evidência real para recomendar captura, decidir sobre canvas ou fechar a arquitetura. O relatório permanece um diagnóstico parcial, não a demonstração solicitada.

**Atualização após retorno do usuário:** há uma janela do Chrome visível, mas o perfil é incerto. Isso confirma que a abertura GUI ocorreu, porém **NÃO CONFIRMA** que a janela use o perfil temporário Lezhin. Como `9223` ainda está sem listener e não é possível identificar o perfil por processo, o login foi suspenso para evitar autenticar na sessão errada. O caminho do perfil precisa ser conferido em `chrome://version` antes de qualquer login; não compartilhar perfil Ridi nem inserir credenciais até essa confirmação.

## 14. Inicialização isolada e validação de CDP (2026-10-20)

Os requisitos de isolamento foram revalidados antes de qualquer login:

| Requisito | Estado | Evidência |
|---|---|---|
| Processo Chrome separado para o perfil temporário | **CONFIRMADO** | `lsof` identificou processo Chrome PID `63376` com arquivos abertos sob `/private/tmp/lezhin_pilot_profile_20261020`; o perfil pessoal informado pelo usuário é `.../Google/Chrome/Default`, outro user-data-dir. |
| Perfil Lezhin exclusivo | **CONFIRMADO** | Playwright conectou por CDP e leu `chrome://version`: `Caminho de perfil /private/tmp/lezhin_pilot_profile_20261020/Default`; linha de comando contém `--user-data-dir=/private/tmp/lezhin_pilot_profile_20261020`. |
| CDP restrito a loopback na porta própria | **CONFIRMADO** | `lsof -nP -iTCP:9222,9223 -sTCP:LISTEN` mostrou apenas `127.0.0.1:9223 (LISTEN)` no Chrome PID `63376`; não havia listener em `9222`. |
| Conexão Playwright por CDP | **CONFIRMADO** | `chromium.connect_over_cdp("http://127.0.0.1:9223")` conectou; navegador reportou versão `155.0.8059.85` e um contexto. |
| Navegação inicial sem autenticação | **CONFIRMADO** | O contexto tem página `https://www.lezhinus.com/en` com título público “Lezhin Comics - Your Fantasy, Our Content”. Nenhum login foi feito. |
| Chrome pessoal/Ridi encerrados ou alterados | **CONFIRMADO: não** | Não enviei sinais para encerrar processos. A instância pessoal permaneceu aberta; 9222 não foi usado. |

Nota operacional: os probes locais executados dentro do sandbox não conseguiram conectar, embora `lsof` mostrasse o listener. A validação de conexão foi então executada fora dessa restrição e o Playwright conectou com sucesso. Nenhum cookie, token ou credencial foi lido ou registrado.

**Próxima etapa pendente:** login manual no Chrome do perfil temporário acima e indicação de uma URL de episódio que a conta tenha autorização para ler. Só então serão avaliados persistência da sessão e comportamento do leitor. Não iniciar captura antes de confirmar o login e a autorização do episódio.

## 15. Retomada após solicitação de login manual (2026-10-20)

**CONFIRMADO:** Playwright reconectou à instância existente em `9223` sem reiniciar o Chrome. O contexto continua no perfil temporário validado na seção 14.

**CONFIRMADO:** as abas observadas foram `https://www.lezhinus.com/en` e duas páginas `about:blank`; nenhuma aba apontava para episódio.

**NÃO CONFIRMADO:** a sessão não pôde ser confirmada como autenticada pelos rótulos visíveis inspecionados na homepage. Não apareceu texto/controle reconhecível de login, logout, account/profile ou my page; isso não prova que o usuário esteja desconectado, pois a homepage pode não expor esse estado de forma textual.

**PENDENTE:** não foi fornecida URL de episódio autorizado e nenhum leitor foi aberto. Nenhum cookie, token, local storage ou credencial foi lido. Não foi feita captura nem navegação a um episódio por suposição.

## 16. Episódio fornecido — autenticação no perfil CDP (2026-10-20)

**CONFIRMADO:** sem reiniciar o processo, o endereço `https://www.lezhinus.com/en/comic/presidentlonglegs/1` foi aberto como novo target na instância `9223`. O Chrome redirecionou para `https://www.lezhinus.com/en/login?redirect=https%3A%2F%2Fwww.lezhinus.com%2Fen%2Fcomic%2Fpresidentlonglegs%2F1`, com título `Login - Lezhin Comics`. Esse perfil, portanto, não tinha uma sessão que autorizasse a leitura do episódio naquele momento.

**CONFIRMADO:** a página de login foi ativada na janela do perfil isolado para login manual. Nenhum cookie, token, credencial, local storage ou byte de imagem foi consultado.

**PENDENTE:** a afirmação de que houve login manual não coincide com o estado observado no contexto CDP isolado; ainda não se sabe se o login foi realizado em outra janela/perfil ou se a autenticação não persistiu. A sessão só será reavaliada depois de login manual nesta janela e nova abertura do episódio.

**PENDENTE:** não inspecionei `data-cut-index`, `blob:`, ordem/total, scroll ou qualidade, pois o leitor não ficou acessível. Não foi feita captura.

## 17. Retomada com URL de episódio fornecida pelo usuário (2026-10-20)

**CONFIRMADO:** a conexão Playwright com o Chrome `9223` falhou durante a inicialização do contexto, antes de qualquer navegação ou leitura de DOM, com `Browser.setDownloadBehavior: Browser context management is not supported`. O browser CDP aceitou a conexão WebSocket, mas esta versão/configuração não completou o handshake de contexto do Playwright. Nenhum download foi acionado.

**CONFIRMADO:** consulta de metadados CDP inicialmente não listou alvos de página. Usei o protocolo CDP diretamente, na mesma porta e processo, para abrir o endereço exato informado (`/en/comic/presidentlonglegs/1`); o alvo foi redirecionado para `/en/login?redirect=.../presidentlonglegs/1`, título `Login - Lezhin Comics`. A página de login foi trazida para frente.

**CONFIRMADO para o perfil conectado:** o episódio não estava acessível naquela sessão CDP. Isso não confirma o estado de outra janela/perfil; há divergência entre o login informado pelo usuário e a sessão efetivamente observada na porta 9223. Não consultei cookies, tokens, armazenamento local nem credenciais.

**PENDENTE:** autenticar manualmente na janela do perfil temporário conectada à porta 9223 e reabrir o episódio. Até isso ocorrer, a estrutura real do leitor, `data-cut-index`, `blob:`, progressão de scroll, índices, total e qualidade não podem ser validados. Nenhum byte de imagem foi acessado.

## 18. Piloto autenticado e inspeção do leitor (2026-10-20)

### Autenticação, sessão e navegação Playwright

**CONFIRMADO:** sem reiniciar o Chrome, Playwright conectou ao CDP já ativo em `127.0.0.1:9223` e abriu `https://www.lezhinus.com/en/comic/presidentlonglegs/1`. O endereço permaneceu no episódio, com título `President Long-Legs - Episode 1 - 1 - Webtoons - Lezhin Comics - Lezhin Comics`, sem formulário de login; o DOM exibia a interface do leitor e o indicador `1 / 68` quando a página estava no topo. Isso demonstra que a sessão existente tinha acesso ao episódio autorizado.

**CONFIRMADO:** recarregar o episódio na mesma instância e contexto manteve o URL do leitor, o título e os 68 contêineres `[data-cut-index]`, sem redirecionamento ao login. Isso confirma reutilização e persistência da sessão durante navegação/reload no processo aberto. **PENDENTE:** a persistência depois de fechar e reabrir o Chrome não foi testada, pois o navegador deveria permanecer aberto durante este piloto.

**CONFIRMADO:** Playwright identificou o episódio, inspecionou o DOM, executou a rolagem e reconheceu o fim sem comandos no console do navegador. Em tentativas anteriores, houve uma falha transitória de handshake (`Browser.setDownloadBehavior: Browser context management is not supported`); a conexão posterior e a navegação completa funcionaram. A operação deve tratar falha de conexão como erro recuperável, sem declarar captura concluída.

### Estrutura observada e progressão

**CONFIRMADO neste episódio:** `document.querySelectorAll('[data-cut-index]')` retornou 68 contêineres `DIV`, indexados unicamente e em sequência contínua `0..67`. O mesmo total apareceu na UI do leitor (`1 / 68` no topo e `68 / 68` no final). Assim, para este episódio, o total real é 68 cortes e o índice começa em zero. Não se deve generalizar o número para outros episódios.

**CONFIRMADO:** os contêineres indexados continuam presentes no DOM durante a rolagem; os contêineres fora da região carregada aparecem sem `IMG`. No topo havia imagens de corte nos índices iniciais; no fim, nos índices `66` e `67`. Ao percorrer o leitor, os cortes com `IMG` observados progrediram por volta dos índices `12–14`, `26–28`, `39–41`, `52–54` e `65–67`. A união dos estados observados cobriu todos os 68 índices. Portanto, neste caso, há carregamento progressivo/virtualização das imagens: os elementos de imagem fora da região deixam de estar no DOM, embora os contêineres com `data-cut-index` permaneçam. Uma coleta deve observar/salvar cada corte quando seu `IMG` estiver efetivamente carregado, e não tentar ler todos os `IMG` ao final.

**CONFIRMADO:** a rolagem automatizada em passos de aproximadamente 85% da altura da viewport alcançou o limite inferior em 102 passos. O fim foi reconhecível pela combinação de `scrollY + innerHeight >= scrollHeight`, indicador `68 / 68` e controles `Next Episode`/`Episode 2`. Para evitar falso término, a automação deve ainda esperar estabilização do DOM e validar índices únicos/contíguos e `img.complete`/`naturalWidth > 0` para cada corte observado.

**CONFIRMADO:** nas amostras do leitor, as URLs de imagem observadas tinham esquema `https:` e nenhuma usava `blob:`. A amostra de um corte apresentou dimensão intrínseca de `1280×1849` e dimensão renderizada de `720×1041`, mantendo proporção. Não foram vistos índices duplicados nem lacunas. A dimensão renderizada é uma escala de apresentação da página, não evidência de que o arquivo de origem tenha sido reduzido.

### Bytes, canvas e qualidade

**CONFIRMADO:** ao desenhar em canvas uma imagem de corte renderizada, `getImageData()` falhou com `SecurityError: ... canvas has been tainted by cross-origin data`. Portanto, converter esse recurso por canvas no contexto observado não é uma estratégia viável sem permissão CORS do servidor; não tentar contornar essa restrição.

**CONFIRMADO na etapa seguinte (seção 19):** Playwright disponibiliza normalmente `Response.body()` para respostas HTTPS associadas a elementos `IMG` dentro de dois cortes específicos. O MIME foi `image/webp`, o status HTTP `200`, e a decodificação dos bytes em memória confirmou formato WebP e dimensão `1280×1849`. Uma resposta de miniatura não relacionada ao corte foi identificada separadamente como WebP de `164×219` e 8.454 bytes; ela não foi confundida com página do episódio. Nenhum arquivo de imagem foi salvo.

**CONFIRMADO como estratégia técnica, com escopo limitado:** manter e gravar sem transformação os bytes retornados por `Response.body()` conserva o recurso WebP servido pelo site, sem canvas, redimensionamento ou conversão. As dimensões e o formato do corpo coincidiram com `naturalWidth`/`naturalHeight` do elemento `IMG`. **PENDENTE:** teste de escrita do arquivo final e comparação visual independente; não foram alterados ou salvos dados neste piloto.

**PENDENTE:** não foi medido consumo de memória nem comportamento em interrupção. O leitor mostra poucos `IMG` simultaneamente, mas isso sozinho não demonstra a memória usada pelo cache do navegador ou pela captura.

### Arquitetura recomendada e integração

**CONFIRMADO:** CDP isolado com perfil Lezhin próprio e porta `9223` funciona com a sessão autenticada, sem encerrar o Chrome pessoal nem usar `9222`. Para a integração atual, recomenda-se manter essa separação e conectar o provider Lezhin ao processo Chrome existente, como o Ridi faz. Isto é uma recomendação operacional de isolamento/reuso de sessão; **NÃO CONFIRMADO** que o site exija CDP ou que um contexto Playwright novo não possa funcionar com autenticação equivalente.

**Recomendação para implementação (bytes confirmados na seção 19):** provider dedicado (por exemplo, `src/lezhin_provider.py`) com validação de host/URL, conexão à sessão própria, avanço controlado do leitor, associação estrita `data-cut-index → imagem`, detecção de ausência/duplicata e falha se uma imagem não completar. Reutilizar o fluxo comum de fila/progresso e validação depois de cada imagem permitida; não reutilizar cookie, perfil, porta ou heurística de autenticação Ridi. O número total deve vir do leitor/índices verificados por episódio, não de constante.

Pontos de integração já identificados no código, sem alterações nesta etapa:

- `src/downloader.py`: roteamento para o provider e retorno de progresso.
- `src/chapter_validation.py` e finalização do downloader: reaproveitar validação de quantidade/arquivo, verificando se atende ao conjunto indexado do Lezhin.
- `src/output_paths.py`: diretório canônico de capítulos.
- `src/saved_works.py` e `data/saved_works/lezhinus.json`: aceitar o identificador do provider no contrato existente.
- `webapp/server.py`: sessão, início/estado do Chrome e descoberta/executação, com endpoints Lezhin próprios se a UI precisar controlar a sessão.
- `webapp/templates/index.html`, `webapp/static/app.js` e, se necessário, `webapp/static/styles.css`: estado da sessão, descoberta, seleção e acompanhamento.
- Novo módulo de provider e testes offline de índices, virtualização, falhas e integração; não alterar o provider Ridi.

### Limitações, riscos e próximos passos

**CONFIRMADO:** não foram lidos ou registrados cookies, tokens, credenciais ou armazenamento do navegador; não foram acionados downloads em lote; nenhum arquivo de corte foi gravado; nenhum código de produção foi alterado. A navegação foi limitada ao episódio informado e autorizado.

**Pendências naquele estágio (tratadas em parte pela seção 20):** repetir em outro episódio, verificar as opções numéricas e validar bytes/gravação. A comparação de formato/bytes e a gravação foram concluídas; fechamento/reabertura do Chrome, descoberta/execução pelo backend e medições de memória nativa continuam pendentes para desenvolvimento/piloto de integração.

**Conclusão daquele estágio (atualizada pela seção 20):** o acesso e a estrutura do leitor foram demonstrados no episódio `President Long-Legs`, episódio 1. A captura original e as validações adicionais foram concluídas nas seções 19–20.

## 19. Origem HTTP e preservação dos bytes dos cortes (2026-10-20)

Esta rodada reutilizou a página já autenticada na sessão CDP `9223`. Não repetiu o login nem percorreu o episódio inteiro. Playwright avançou diretamente até os cortes `4` e `10`, aguardou os respectivos `IMG` e correlacionou, somente em memória, `img.src`/`img.currentSrc` com as URLs de resposta. URLs completas, parâmetros assinados e headers de autenticação não foram impressos nem registrados.

| `data-cut-index` | Match DOM ↔ resposta | Status | MIME HTTP | Bytes do corpo | Formato decodificado | Dimensão decodificada | `naturalWidth × naturalHeight` |
|---:|---|---:|---|---:|---|---:|---:|
| 4 | **CONFIRMADO** | 200 | `image/webp` | 97.332 | WebP | 1280×1849 | 1280×1849 |
| 10 | **CONFIRMADO** | 200 | `image/webp` | 166.438 | WebP | 1280×1849 | 1280×1849 |

**CONFIRMADO:** `page.on("response")` recebeu as requisições de imagem normalmente e `Response.body()` forneceu os bytes dos dois recursos correspondentes exatamente aos `IMG`s dentro dos cortes indicados. Pillow foi usado apenas em memória para ler assinatura/formato e dimensões; os bytes não foram modificados nem gravados. MIME, formato decodificado e dimensões intrínsecas concordaram nos dois exemplos. Ambos foram recursos do capítulo, não miniaturas: a associação foi feita pela URL de resposta igual à URL do elemento descendente do contêiner indexado, antes de consultar o corpo. A miniatura de `164×219` observada na rodada anterior estava fora de qualquer `[data-cut-index]` e foi tratada separadamente.

**CONFIRMADO:** a preservação tecnicamente viável é guardar diretamente os bytes de `Response.body()` com extensão `.webp`. Não decodificar/reencodar com canvas, PIL ou PNG/JPEG; isso evita alteração de qualidade e mantém o arquivo servido pelo Lezhin. A leitura via `Response.body()` é da resposta normal que o navegador carregou para o episódio autorizado; não houve requisição fabricada para endpoint oculto, contorno de CORS ou bypass de autenticação/DRM. O teste de canvas anterior continua válido: canvas permanece bloqueado por CORS e não é necessário para obter a resposta normal.

**CONFIRMADO:** a estratégia acompanha a virtualização porque associa cada resposta ao `data-cut-index` e captura o corpo quando o recurso daquele `IMG` é carregado durante o scroll; não depende de que imagens antigas continuem no DOM. A implementação deverá serializar imediatamente cada corpo, validar status/MIME/formato/dimensões, marcar o índice como recebido apenas após gravação íntegra e rejeitar duplicatas/lacunas antes de concluir o episódio.

**PENDENTE à época desta seção (resolvido em parte na seção 20):** consistência em outro episódio e nas opções `1x`, `1.5x` e `2x` foi validada para um corte do episódio 2, com corpo/hash/dimensões idênticos. Ainda não foram medidos o heap nativo do Chrome nem memória acumulada ao longo de um provider real. Limitar a retenção Python a um corpo por vez e persistir por índice; validar memória durante a implementação.

**Conclusão da investigação de imagem:** origem confirmada como resposta HTTPS `image/webp` normal do elemento do corte. Playwright expõe os bytes no evento `response`; para os dois cortes testados, o corpo decodificou em WebP `1280×1849` e status `200`. Captura por bytes sem transformação é viável e preserva o formato/qualidade servidos. Não houve download em lote nem arquivo salvo; código de produção permanece intacto.

## 20. Validação final antes da implementação (2026-10-20)

### Segundo episódio autorizado, total e virtualização

**CONFIRMADO:** a página de episódios da obra marcava o episódio 2 como `Free`; ele abriu diretamente no leitor normal, sem fluxo de compra. A inspeção encontrou 68 contêineres `[data-cut-index]`, índices únicos e contínuos `0..67`, e o leitor apresentou `1/68` no início e `68/68` no final.

**CONFIRMADO:** no episódio 2, a rolagem sequencial até cada índice fez os 68 elementos `IMG` aparecerem e completar (`complete=true`, `naturalWidth=1280`, `naturalHeight=1849`) quando o respectivo corte estava em vista. Em amostras rápidas, o DOM manteve os 68 contêineres indexados enquanto apenas os `IMG` da região atual apareciam; no início havia cortes `0–1`, em trecho intermediário `12–14` e no fim `66–67`. Isso confirma carregamento virtualizado e demonstra que a imagem deve ser associada/capturada enquanto o índice está visível. Uma primeira passagem com espera de apenas 110 ms por rolagem não observou todos os `IMG` prontos; o passe por índice com espera de decodificação encontrou os 68, sem lacunas.

**CONFIRMADO:** o corte 0 do episódio 2 foi mapeado para uma resposta normal do navegador: HTTP 200, MIME `image/webp`, formato WebP, `247.618` bytes e dimensão `1280×1849`, igual ao `naturalWidth × naturalHeight`. A resposta foi correlacionada ao `img` sob `[data-cut-index="0"]`; URL e query assinada ficaram apenas em memória e não foram registradas. O corte 4 também teve resposta correspondente HTTP 200/`image/webp` na inspeção de escala.

### Opções `1x`, `1.5x` e `2x`

**CONFIRMADO para o recurso amostrado:** as opções visíveis foram ativadas individualmente no menu do leitor em páginas novas do episódio 2. Em `1x`, `1.5x` e `2x`, o corte 0 permaneceu com dimensão intrínseca `1280×1849`, dimensão renderizada `720×1041`, MIME `image/webp`, `247.618` bytes e SHA-256 `83b50d74f1b4988cbb4ab35452fdfc74d7ed7020e097888670611464c528182f`. Portanto, nenhuma das opções alterou o recurso de imagem observado.

**INFERÊNCIA:** como o grupo mostra `Auto` e escolhas numéricas, e selecionar as opções não mudou o recurso/imagem, elas parecem controlar velocidade de rolagem automática, não resolução. O efeito da velocidade sobre a rolagem não foi medido; o que está confirmado é que não alterou os bytes/dimensões da amostra durante a leitura.

### Gravação atômica, integridade e memória

**CONFIRMADO:** um único corpo autorizado do corte 0 foi gravado em `/private/tmp/lezhin_validation_20261020/episode2_cut_000.webp`. O processo escreveu primeiro um `.part` no mesmo diretório, fez flush/fsync, validou WebP e dimensões, comparou o hash e promoveu o arquivo com `os.replace`. O arquivo final foi reaberto: formato WebP, `1280×1849`, `247.618` bytes. SHA-256 do corpo recebido e do arquivo salvo foi idêntico: `83b50d74f1b4988cbb4ab35452fdfc74d7ed7020e097888670611464c528182f`. Nenhum outro corte foi salvo.

**CONFIRMADO na simulação isolada (não é teste de código de produção):** interrupção antes da promoção deixou um `.part` e nenhum arquivo final; o capítulo não poderia ser marcado completo nesse estado. Um conjunto esperado `0..67` com o índice 67 ausente foi rejeitado como incompleto. Repetir o índice 4 foi identificado como duplicata. Os artefatos temporários de simulação foram removidos pelo escopo temporário; o único arquivo preservado é a amostra acima.

**CONFIRMADO com limite:** `tracemalloc` registrou pico Python de `1.332.718` bytes ao obter um corpo de `247.618` bytes por `Response.body()`. É uma medição de uma imagem e não inclui heap nativo do Chrome, cache HTTP ou todo o custo de decodificação. Não foi medido RSS/heap do processo durante uma captura real completa.

**Arquitetura recomendada para persistência:** observar respostas de imagem no navegador conectado; correlacionar a URL em memória com o `currentSrc/src` do `IMG` pertencente a `[data-cut-index]`; validar status 200, MIME/formato WebP e dimensões; tratar apenas um `Response.body()` por vez; escrever para arquivo `.part` do índice, calcular/verificar integridade, fazer fsync e rename atômico para o nome final indexado; liberar a referência ao corpo antes do próximo. Manter somente o conjunto de índices e metadados/hash em memória, nunca todos os bytes do episódio. Ao retomar, aceitar apenas finais WebP válidos; deixar `.part` fora da contagem e permitir limpeza/regravação controlada. Detectar e rejeitar índices fora do esperado, lacunas e duplicatas; marcar capítulo concluído somente se o conjunto final for exatamente `0..N-1` e todas as imagens decodificarem.

### Parecer final

**APTO para iniciar a implementação do provider Lezhin.** A origem e associação dos bytes foram confirmadas em dois episódios gratuitos; 68/68 cortes do segundo episódio carregaram por índice durante rolagem; as opções numéricas não alteraram a amostra; uma gravação WebP atômica foi reaberta e validada por dimensões e SHA-256; e a estratégia incremental evita acumular o episódio em RAM Python.

**Pendências para validar durante a implementação, sem bloquear o início:** medir memória nativa/cache do Chrome em execução real; codificar e exercitar recuperação de `.part`/retomada e política de duplicatas; verificar a extensão/formato em outros episódios; testar o efeito de rolagem das opções `1x`/`1.5x`/`2x`; manter o Chrome com perfil/porta exclusivos. Nenhuma implementação foi feita nesta investigação e nenhum provider existente foi alterado.

## 21. Etapa 3 — catálogo de obras e episódios (2026-10-20)

### Identificador e contratos

**CONFIRMADO no checkout:** `data/saved_works/lezhinus.json` já existe e contém uma obra (`Benevolent Violence`). `src/saved_works.py` não aceitava o nome do arquivo como provider. O identificador canônico adotado nesta etapa é **`lezhinus`**, exatamente igual ao arquivo de obras salvas. Ele também é usado pelo catálogo Lezhin e pelo diretório de saída do provider. Os módulos e nomes de funções permanecem `lezhin` por serem nomes do pacote, não identificadores de catálogo.

**CONFIRMADO no código/testes:** foram adicionados `is_lezhin_work_url` e `validate_work_url`, limitados ao domínio HTTPS oficial, portas padrão, forma `/locale/comic/slug` e sem credenciais embutidas; URLs de episódio continuam validadas pela forma `/locale/comic/slug/número`. O catálogo usa `Manga` e converte para `Chapter` somente episódios com numeração extraída de um rótulo confiável. Especiais sem número permanecem no resultado com `number=None` e não viram `Chapter`, evitando inventar um número que o modelo compartilhado tornaria obrigatório.

**CONFIRMADO no código/testes:** a descoberta coleta apenas links de episódio sob a URL da obra atual, normaliza host e caminho, remove links externos e duplicatas por URL, rejeita números conflitantes e ordena números crescentes. Para listagens exibidas em ordem decrescente, especiais sem número acompanham a posição observada ao inverter a lista, mas sua posição relativa só pode ser confirmada em uma página real. Indicadores textuais explícitos classificam linhas como `free`, `unlocked`, `unavailable` ou `listed_unverified`; não há inferência de acesso pelo simples fato de o episódio estar listado. Uma verificação separada navega a um episódio fornecido, não compra nem desbloqueia: leitor `[data-cut-index]` presente significa `accessible_verified`; redirecionamento a login significa `authentication_required`; estado não conclusivo permanece não verificado.

### Evidência real da obra e limite desta rodada

**CONFIRMADO em rodadas anteriores (seções 18 e 20):** a obra real `President Long-Legs` e seus episódios 1 e 2 foram abertos pela sessão autenticada em `https://www.lezhinus.com/en/comic/presidentlonglegs`. Na página do episódio 2, a interface indicou `Free`; o episódio abriu no leitor com 68 índices `0..67`. Isso comprova acesso aos dois episódios usados no piloto, não o acesso a todos os links da listagem. A evidência anterior não contém uma extração completa do catálogo da obra, dos títulos/URLs de todos os episódios nem do estado de cada linha.

**Resultado inicial daquela execução:** CDP indisponível e DNS sem resposta no sandbox. **Atualização pela validação final da Etapa 3 (seção 22):** o processo Chrome isolado e CDP `9223` foram encontrados ativos; o resolvedor do sistema retornou endereços para `www.lezhinus.com`; a obra real foi aberta e os episódios foram descobertos pela rolagem. O acesso a um episódio gratuito, porém, redirecionou para login e ficou não confirmado para a sessão atual.

**CONFIRMADO na obra real (seção 22):** a lista aparece progressivamente com a rolagem da página. A primeira posição materializou 15 links; deslocar a página materializou itens adicionais; a varredura limitada até o fim acumulou 169 URLs únicas. O catálogo terminou ordenado em 1–169. As três primeiras linhas exibiam `Free`; as outras 166 exibiam preço em Coins. Nenhuma linha observada indicava explicitamente `unlocked` ou `unavailable`. Episódios pagos foram classificados como `paid_access_unverified`, pois o preço listado não prova que a conta não tenha acesso por outro meio.

**CONFIRMADO no DOM real:** não havia `h1` nem metadado Open Graph de título; `document.title` era `President Long-Legs - CHOI MeeAe - Webtoons - Lezhin Comics`. O parser agora remove o sufixo de autor/site e preserva `President Long-Legs`. O seletor anterior `[class*=episode]` ascendia ao contêiner `.episode-list`, cujo texto agregava vários preços e contaminava o estado de cada episódio. A descoberta passou a usar o próprio link ou um contêiner de episódio individual. O acesso por rolagem é progressivo, sem botão de expansão acionado.

### Arquivos da Etapa 3

- **Novos:** `src/lezhin/catalog.py` (modelo do catálogo Lezhin, disponibilidade, ordenação e conversão segura a `Chapter`); `src/lezhin/discovery.py` (descoberta DOM limitada e verificação explícita de acesso); `tests/test_lezhin_discovery.py` (URLs, catálogo, especiais, duplicatas, estados, contratos e obras salvas).
- **Alterado:** `src/lezhin/urls.py` (URL de obra e constante `LEZHIN_PROVIDER_ID`); `src/lezhin/__init__.py` (exports); `src/lezhin/downloader.py` (diretório passa a usar `lezhinus`); `src/saved_works.py` (aceita `lezhinus` sem reescrever o JSON); `tests/test_lezhin_downloader_integration.py` (expectativas do caminho passam a corresponder ao identificador canônico).
- **Sem alterações nesta etapa:** `src/downloader.py`, `src/models.py`, providers existentes, arquivos da Central Web e `data/saved_works/lezhinus.json`. `Manga`/`Chapter` foram reutilizados; o identificador específico de provider é metadado de `LezhinCatalog`, porque o modelo compartilhado `Manga` não define provider.

### Testes, compatibilidade e regressões

**CONFIRMADO:** testes Lezhin (`discovery`, URLs, downloader, persistência e reader): **42 passaram** após acrescentar regressão de rolagem progressiva, limpeza do título e distinção entre preço e indisponibilidade. Testes direcionados a Ridi, Comix e downloader compartilhado: **67 passaram, 15 subtestes passaram**. A versão instalada do Playwright é **1.62.0**; o mínimo declarado no `pyproject.toml` é **1.60.0**, necessário para a opção `no_defaults` de `connect_over_cdp`. As suítes de contrato dos providers existentes passaram com a versão instalada; isso demonstra compatibilidade no ambiente testado, não em todas as versões permitidas acima do mínimo.

**CONFIRMADO após executar a suíte completa fora do sandbox:** **200 passaram, 15 subtestes passaram e um falhou**. A falha é `test_saved_works_read_only_contract`: espera 6 registros Comix, recebe 10. **CONFIRMADO como preexistente:** o arquivo `data/saved_works/comix.json` no HEAD e no checkout contém 10 obras; esta etapa não alterou o arquivo nem a expectativa. Não é regressão Lezhin. A tentativa inicial dentro do sandbox foi bloqueada ao abrir o socket do servidor Web (`PermissionError`); a repetição autorizada executou a suíte.

### Parecer da Etapa 3

**DESCOBERTA REAL DA ETAPA 3: APROVADA.** O catálogo real da obra autorizada encontrou 169 URLs únicas, ordenadas e convertidas em 169 objetos `Chapter`; todos os links passaram pelo validador de episódio e os títulos especiais numerados foram preservados. A sessão CDP estava funcional, mas o probe do episódio 1 terminou em `/en/login` (HTTP 200, formulário presente, zero cortes): o estado de autenticação atual é **AUTH_REQUIRED**. Portanto, `Free` na listagem não foi tratado como prova de leitura autorizada. Não houve compra, desbloqueio ou download. A validação da descoberta atende ao critério de aceite; o acesso efetivo ao leitor permanece não confirmado nesta sessão.

## 22. Validação final real da descoberta (2026-10-20)

### Ambiente e acesso

**CONFIRMADO:** o Chrome que respondia em `127.0.0.1:9223` usava o perfil exclusivo `/private/tmp/lezhin_pilot_profile_20261020`; o CDP respondeu com Chrome 155. Não reiniciei o processo e não toquei no Chrome pessoal ou no Ridi. A consulta de DNS do sistema passou a retornar resolução para `www.lezhinus.com`, e a página oficial carregou. Não consultei cookies, tokens ou valores de formulário.

**CONFIRMADO:** a navegação da obra foi aceita e o DOM identificou `President Long-Legs`. A tentativa autorizada de abrir `/en/comic/presidentlonglegs/1` retornou HTTP 200, mas a aplicação redirecionou para `/en/login`; havia formulário de senha e zero `[data-cut-index]`. O resultado do probe é `authentication_required`, não `accessible_verified`. A gratuidade do item 1 no catálogo não foi usada como prova de acesso ao leitor.

### Catálogo capturado da obra real

| Evidência | Resultado |
|---|---:|
| Título normalizado | `President Long-Legs` |
| URL canônica da obra | `/en/comic/presidentlonglegs` |
| Episódios acumulados pela rolagem | 169 |
| URLs distintas no catálogo | 169 |
| Objetos compatíveis com `Chapter` | 169 |
| Sequência numérica | 1–169, contínua e crescente |
| Títulos sem numeração confiável | 0 |
| URLs aprovadas por `is_lezhin_episode_url` | 169/169 |
| Duplicatas após deduplicação por URL | 0 |

Os cinco primeiros títulos foram `Episode 1` a `Episode 5`. Os últimos foram `Episode 165`, `Episode 166`, `Episode 167`, `Episode 168 (The End)` e `Episode 169 (Epilogue)`. Os especiais conservaram sua numeração explícita do site; não foi necessário criar número inferido.

| Estado do DOM da listagem | Quantidade |
|---|---:|
| `Free` | 3 |
| Preço `Coins` — `paid_access_unverified` | 166 |
| Marcados explicitamente como unlocked | 0 |
| Marcados explicitamente como indisponíveis | 0 |

Os itens com preço foram mantidos como acesso não verificado: um preço na lista não prova que a conta específica não tenha adquirido o episódio. O probe de leitura do primeiro episódio retornou `authentication_required`, logo nenhum episódio foi afirmado acessível nesta sessão.

### DOM, progressão e correções

**CONFIRMADO:** a primeira vista tinha 15 links. Ao rolar a página, novos links apareceram; a posição inferior expôs mais itens, e a descoberta completa reuniu os 169 episódios. O selo `77 EPS ON SALE` não corresponde ao total da lista: a navegação DOM percorreu links numerados até 169, incluindo `Episode 168 (The End)` e `Episode 169 (Epilogue)`. A coleta percorre a rolagem normal, acumula por URL canônica e não clica em compra, `Unlock all` ou `Purchase`.

**Divergência corrigida:** o parser inicial esperava um heading/metadado Open Graph que não existe nessa página. `document.title` inclui autor e sufixos do site; `normalize_work_title` removeu esse sufixo para produzir o título observado. Além disso, o seletor genérico `[class*=episode]` encontrava o contêiner `.episode-list`, cujo texto abrangia várias linhas e preços. A regra foi restringida a linha individual/link; assim, `Free` não é contaminado pelos `Coins` de outros episódios.

**Testes após a correção:** 42 testes Lezhin passaram, incluindo regressão de rolagem progressiva, título, separação de preço e indisponibilidade, ordenação, duplicatas, modelos e URLs. O conjunto real encontrou 169 episódios, 169 URLs únicas, 169 `Chapter`s, sem lacunas ou duplicatas. Nenhum conteúdo de episódio foi baixado nesta validação.

## 23. Etapa 4 — Central Web (2026-10-20)

**CONFIRMADO no código:** a Central Web usa o identificador `lezhinus`, carrega `data/saved_works/lezhinus.json`, expõe endpoints próprios de sessão/inicialização, descoberta e verificação de acesso, e encaminha somente episódios confirmados como acessíveis à fila compartilhada. A captura continua no módulo Lezhin e usa `Manga`, `Chapter`, `ChapterDownloader`, validação e diretório canônicos. O Chrome inicia com perfil exclusivo `/private/tmp/lezhin_pilot_profile_20261020` e CDP loopback `9223`; o estado consulta a identidade do processo/perfil antes de conectar, sem ler cookies ou encerrar processos.

**CONFIRMADO em smoke test isolado de interface:** navegador headless navegou ao painel Lezhin, renderizou 169 linhas de catálogo mockado, verificou acesso mockado para um item e enviou somente esse item à fila mockada compartilhada. Não houve request real ao Lezhin nem download de conteúdo nessa verificação.

**PENDENTE — validação real da Central Web:** no início desta etapa, `127.0.0.1:9223` estava indisponível. A integração não foi exercitada contra a sessão real, e a descoberta ao vivo pela Central Web não foi repetida. A validação real do catálogo de 169 episódios da seção 22 continua sendo evidência da Etapa 3, não um teste ao vivo da interface desta etapa.

**PENDENTE — regressão visual:** a página reutiliza classes e estrutura de fluxo do Ridi, mas ainda precisa de revisão visual comparativa e eventuais ajustes aprovados antes da próxima etapa.

**CONFIRMADO nos testes finais:** 212 testes passaram e 15 subtestes passaram. A única falha foi `test_saved_works_read_only_contract`, que espera 6 obras Comix e encontra 10 no JSON existente. Essa divergência preexistente permanece documentada e não foi alterada nesta etapa. Testes Lezhin direcionados: 54 passaram. `node --check`, compilação Python e `git diff --check` passaram.

**Pendências mantidas:** (1) a falha preexistente do contrato de obras salvas Comix; (2) validar a sessão e a descoberta pela Central Web com Chrome Lezhin real disponível em CDP `9223`; (3) comparar e padronizar visualmente o painel Lezhin com o Ridi. Não houve alteração nos providers Ridi, Comix ou Mangago, nem compra, desbloqueio ou download em lote.
