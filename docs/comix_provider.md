# Provider Comix — fase 1

Este módulo adiciona suporte de download a URLs diretas de capítulo do `comix.to` sem
alterar o motor V4 do Mangago.

## O que está implementado

- Playwright isolado para Comix com os ajustes mínimos de compatibilidade observados
  durante a investigação.
- Fonte estrutural de total e ordem: `.rpage-page[data-page]`.
- Detecção dinâmica por wrapper:
  - `img.rpage-page__img`: download normal via `BrowserContext.request.get()`;
  - `canvas.rpage-page__img`: fluxo de imagem embaralhada.
- Para páginas canvas:
  - captura das chamadas `drawImage()` antes do código da página;
  - re-materialização controlada para gerar uma captura nova;
  - identificação do `fetch` de imagem `wowpic`;
  - download da imagem scrambled;
  - remontagem em Python usando exatamente a geometria `source -> destination`
    capturada do reader;
  - saída reconstruída em PNG lossless.
- Não existe regra de "múltiplos de 10". O tipo é detectado no DOM em runtime.
- A grade não é fixada em 5x5 no algoritmo de reconstrução; ela é validada a partir
  das coordenadas capturadas.

## Limite deliberado desta fase

O pacote suporta **URL direta de capítulo Comix**. A enumeração de capítulos a partir
de uma página de obra do Comix não foi implementada porque essa parte ainda não foi
investigada/validada e não será inventada no patch.

Exemplo conhecido durante a investigação:

`https://comix.to/title/0kgln-emergency-youth-record-book/11256940-chapter-2`

## Segurança de escopo

O patch só:
1. cria `src/comix_provider.py`;
2. cria testes e esta documentação;
3. adiciona três pontos pequenos em `src/downloader.py`:
   - import do provider;
   - compatibilidade de `fetch_chapter_image_urls()` para URL direta Comix;
   - roteamento no início de `ChapterDownloader.download_chapter()`.

O corpo de `_download_reader_chapter_playwright_async()` do Mangago não é alterado.
Rate limiter, `page_delay` V4, PDF, Web e GUI não são modificados.

## Validação

Após aplicar:

```bash
python -m unittest tests.test_comix_provider
python -m unittest discover -s tests
python -m compileall src tests
```

Depois faça um runtime com **um capítulo Comix** antes de versionar.
