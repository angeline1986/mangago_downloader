**Diagnóstico**

Não alterei arquivos, não gerei patch e não fiz commit.

A causa provável da quebra no Playwright não é “headless” isoladamente. O comportamento observado aponta para detecção de automação pelo JavaScript seguro do Comix.

Sem mitigação de automação:

| Modo | `.rpage-page__img` | Erros JS | `wowpic` |
|---|---:|---|---|
| Playwright headless normal | 0 | sim | 0 |
| Playwright headed normal | 0 | sim | 0 |
| Playwright Chrome channel headed | 0 | sim | 0 |

Erro observado:

```text
Cannot read properties of undefined (reading '0')
secure-tkempc-HovQ1K40.js:1:63078
```

Com mitigação mínima:

```js
navigator.webdriver = undefined
navigator.languages = ['en-US', 'en']
navigator.plugins = [1,2,3,4,5]
window.chrome.runtime presente
--disable-blink-features=AutomationControlled
```

Resultado:

| Modo | `.rpage-page__img` | Erros JS | `wowpic` |
|---|---:|---|---|
| Playwright headed stealth | 3 | não | sim |
| Playwright headless stealth | 3 | não | sim |

Ou seja: o mesmo headless que quebrava passa a hidratar quando o fingerprint de automação é reduzido. Isso confirma que o problema está no JS/secure layer do Comix reagindo ao ambiente automatizado, não no seletor em si.

**Resultado Da Página**

URL analisada:

```text
https://comix.to/title/0kgln-emergency-youth-record-book/11256940-chapter-2
```

Metadados observados pelo Playwright:

```text
document.title = Emergency! Youth Record Book · Ch.2
```

O HTML inicial contém dados de bootstrap, incluindo:

```text
page = read
mangaId = 52069
mangaHid = 0kgln
chapterId = 11256940
chapterNumber = 2
title = Emergency! Youth Record Book
```

Mas o HTML inicial não contém diretamente as URLs `wowpic`. Elas aparecem após o app React hidratar e chamar a API interna.

**Origem Das Imagens**

O bundle `ReadPage*.js` usa a API:

```text
/api/v1/chapters/{chapterId}
```

O fluxo interno monta páginas a partir de:

```js
pages.baseUrl + item.url
```

A API comum sem token retornou:

```text
/api/v1/chapters/11256940
403 {"message":"Missing token."}
```

Com o app hidratado, foram vistas chamadas como:

```text
https://comix.to/api/v1/chapters/11256940?_=...
```

A resposta é JSON criptografado/encapsulado com chave `e`, decodificado pelo JS seguro do site. Portanto existe uma API estruturada, mas ela depende de token/parâmetro gerado pelo frontend e de decodificação no cliente.

**Seletor Recomendado**

Para extração via DOM renderizado:

```css
.rpage-page__img
```

Esse seletor bate com o resultado manual no Chrome real e com o Playwright após mitigação.

Atributos relevantes a extrair:

```js
src
currentSrc
data-src
data-original
srcset
naturalWidth
naturalHeight
complete
```

No Chrome real, você confirmou:

```text
Total real: 5
.rpage-page__img: 5
src/currentSrc preenchidos: sim
complete: true
naturalWidth: 1280
naturalHeight: 1500
scroll necessário: não
ordem DOM: página 1..5
```

No meu Playwright stealth, com configuração padrão do leitor, apareceram 3 imagens inicialmente. Quando forcei `preload: "all"` no localStorage, o DOM materializou 122 imagens, o que não deve ser assumido como total real deste capítulo. Isso mostra que a configuração de preload do reader altera fortemente o que aparece no DOM e precisa ser controlada com cuidado numa futura implementação.

**Exemplos De URLs Reais**

URLs frescas observadas no Playwright stealth:

```text
https://j24n.wowpic1.store/i5/bEqPbYfoPT0Gm1HlCmafoD5cxqUFZu6i3R0VvpLI6y4AiVMhaGDNl_Pk4wkijRuo

https://j24n.wowpic1.store/i5/bEqPbYfoPT0Gm1HlCmafoD5cxqUFZu6i3R0VvpLI6y4AiV8haGDNl_Pk4wkijRuo

https://j24n.wowpic1.store/i5/bEqPbYfoPT0Gm1HlCmafoD5cxqUFZu6i3R0VvpLI6y4AiVshaGDNl_Pk4wkijRuo
```

A quarta URL observada durante preload tinha sufixo `?8`, coerente com o que você viu no Chrome real.

**Download Direto**

Usando uma URL fresca descoberta pelo Playwright:

| Método | Referer | Status | Content-Type | Bytes | Imagem válida |
|---|---|---:|---|---:|---|
| `context.request.get()` | URL do capítulo | 200 | `image/webp` | 116248 | sim |
| `context.request.get()` | `https://comix.to/` | 200 | `image/webp` | 116248 | sim |
| `httpx.get()` | URL do capítulo | 200 | `image/webp` | 116248 | sim |
| `httpx.get()` | `https://comix.to/` | 200 | `image/webp` | 116248 | sim |

Conclusão: depois que a URL fresca da imagem é conhecida, tanto HTTP comum quanto `context.request.get()` conseguem baixar os bytes, pelo menos para essa imagem.

Mas a URL antiga fornecida manualmente retornou:

```text
404 text/html
```

Isso sugere que URLs `wowpic` podem ser temporárias, rotativas, dependentes de cache/session/host, ou expirar. O Chrome real mostrou `200 OK (from service worker)`, então o Service Worker/cache pode explicar por que uma URL antiga ainda funcionava naquele navegador.

**Service Worker**

No Chrome real: resposta observada `from service worker`.

No Playwright stealth: respostas `wowpic` vieram como:

```text
resource_type = image
from_service_worker = false
status = 200
content-type = image/webp
```

Então o Service Worker não parece obrigatório para baixar uma URL fresca, mas pode interferir em URLs já cacheadas no Chrome real.

**Ordem**

A melhor estratégia é preservar a ordem do DOM:

```text
document.querySelectorAll('.rpage-page__img')
```

Mapear diretamente:

```text
primeiro elemento -> page-001
segundo elemento -> page-002
terceiro elemento -> page-003
...
```

Não encontrei, neste diagnóstico, um índice explícito mais confiável do que a ordem DOM. O bundle também renderiza uma sequência de páginas a partir do array `pages`, então DOM order é uma estratégia coerente.

**Capítulos E Navegação**

O bootstrap inicial contém identificação da obra e capítulo:

```text
mangaHid = 0kgln
chapterId = 11256940
chapterNumber = 2
```

O bundle também referencia APIs de mangá/capítulos, incluindo algo equivalente a:

```text
/api/v1/manga/{hid}
```

e rotas de capítulos. Para uma futura implementação, a lista de capítulos provavelmente deve vir da API interna do app ou do DOM renderizado, mas isso exigirá lidar com o mesmo token/decode seguro.

**Veredito**

A causa da quebra em Playwright headless é:

```text
automação detectada pelo JS seguro do Comix
```

Evidência principal:

```text
Playwright headless normal: falha
Playwright headed normal: falha
Chrome channel headed via Playwright: falha
Playwright headless com stealth mínimo: funciona
Playwright headed com stealth mínimo: funciona
```

Portanto, a diferença não é simplesmente “headless vs headed”. A diferença é “Chrome real não automatizado vs Playwright automatizado”.

**Estratégia Recomendada Futura**

Para Comix, não reutilizar `pg-1/pg-2` do Mangago.

Estratégia mais segura:

```text
1. Abrir URL do capítulo com Playwright.
2. Mitigar fingerprint básico de automação.
3. Esperar hidratação do app.
4. Extrair `.rpage-page__img` em ordem DOM.
5. Usar `currentSrc || src`.
6. Baixar bytes com `context.request.get()` ou HTTP comum usando Referer `https://comix.to/`.
7. Salvar como page-001, page-002...
```

Eu daria preferência inicial a `context.request.get()` porque reaproveita cookies/contexto do navegador e reduz variações entre descoberta e download.

**Riscos**

- O site usa JS seguro, token `_=` e resposta criptografada/encapsulada.
- Automação Playwright sem mitigação quebra a hidratação.
- URLs `wowpic` podem expirar ou variar por sessão/host.
- Configuração de preload do reader pode alterar quantas imagens aparecem no DOM.
- Service Worker pode fazer o Chrome real parecer diferente do Playwright.
- Scraping direto da API exigiria engenharia reversa do token/decode, mais frágil do que DOM renderizado neste momento.

Conclusão operacional: para este capítulo, o Chrome real vê 5 imagens carregadas; o Playwright também consegue hidratar e baixar imagens quando o fingerprint de automação é mitigado. O bloqueio atual está antes do download: na hidratação do reader sob ambiente Playwright automatizado normal.