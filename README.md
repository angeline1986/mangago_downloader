# Mangago Downloader

A manga downloader for Mangago.me with an interactive CLI (Typer + Rich), PyQt6 GUI, and local Web V2 interface. Supports search or direct URLs, chapter selection, image downloads, PDF/CBZ conversion, and progress tracking.

## Features

- 🔍 Search: Search manga by title, displaying results with index, title, author, genre, and total chapters.
- ⬇️ Download: Select all chapters, a single chapter, or a range of chapters.
- ⚡ Threading: Parallel and concurrent downloads for speed.
- 📚 Conversion: Save as PDF or CBZ.
- 🗑️ Cleanup: Option to delete images after successful conversion.
- 🖥️ Local Web V2: Search, chapter selection, download settings, and live progress in a browser.
- 🎨 **User Interfaces:**
  - **CLI (Command Line Interface):** Built with `Typer` and `Rich`, offering a fully interactive, menu-driven experience with rich tables, live progress bars, and stylized prompts.
  - **GUI (Graphical User Interface):** Developed using `PyQt6`, providing a visual interface with dedicated sections for Search, Details, Configuration, and Progress monitoring.

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/Yui007/mangago_downloader.git
   cd mangago_downloader
   ```

2. Install the required dependencies:
   ```bash
   pip install -e .
   ```

   Or install dependencies directly:
   ```bash
   pip install httpx beautifulsoup4 typer rich PyQt6 img2pdf Pillow playwright
   ```

3. Install the Playwright Chromium runtime:
   ```bash
   playwright install chromium
   ```

## Usage

### CLI Interface

Run the interactive CLI:
```bash
python -m cli.main_cli
```

Or using the launcher:
```bash
python launcher.py
```

Or if installed as a package:
```bash
mangago-downloader
```

The CLI will guide you through:
1. Searching for manga by title
2. Selecting a manga from the search results
3. Choosing which chapters to download
4. Selecting the output format (PDF or CBZ)
5. Deciding whether to delete images after conversion

### GUI Interface

Run the GUI application:
```bash
python -m gui.main_gui
```

Or using the launcher:
```bash
python launcher.py --gui
```

Or if installed as a package:
```bash
mangago-downloader-gui
```

The GUI provides a comprehensive visual interface with the following key sections:
- **Search Section:** Search for manga by title or direct URL.
- **Details Section:** View manga details, including cover art and chapter list, and select chapters for download.
- **Configure Section:** Customize download settings (location, concurrent downloads, retry, timeout, overwrite) and select output format (Images Only, PDF, CBZ). Settings are saved automatically.
- **Progress Section:** Monitor the real-time progress of ongoing downloads and conversions.

Here's a preview of the GUI:
![Mangago Downloader GUI](gui/GUI.PNG)

## Project Structure

```
mangago_downloader/
│
│── cli/
│   └── main_cli.py        # Typer + Rich interactive menu
│
│── gui/
│   ├── __init__.py        # GUI package initialization
│   ├── main_gui.py        # PyQt6 application entry point
│   ├── main_window.py     # Main application window
│   ├── search_widget.py   # Search interface components
│   ├── results_widget.py  # Results display components
│   ├── details_widget.py  # Manga details components
│   ├── download_widget.py # Download configuration components
│   ├── progress_widget.py # Progress tracking components
│   ├── config.py          # Configuration management
│   ├── controllers.py     # Business logic controllers
│   ├── workers.py         # Background workers
│   └── styles.py          # Styling and themes
│
│── src/
│   ├── search.py          # Manga search and metadata
│   ├── downloader.py      # Mangago reader discovery and image downloads
│   ├── browser.py         # Isolated Playwright browser contexts
│   ├── chapter_validation.py # Image-set integrity and completion markers
│   ├── output_paths.py    # Canonical image/PDF/CBZ directories
│   ├── converter.py       # PDF/CBZ conversion
│   ├── utils.py           # HTTP sessions, headers, and helpers
│   └── models.py          # Manga, Chapter, and DownloadResult data classes
│
├── webapp/                # Local Web V2 frontend and HTTP server
├── data/saved_works/      # Saved-title lists
├── output/                # Default download destination
│
│── launcher.py            # Unified launcher for CLI/GUI
│── gui_config.json        # GUI configuration file
│── README.md
│── pyproject.toml
│── LICENSE
```

## Dependencies

- Python 3.11+
- httpx (for HTTP requests)
- BeautifulSoup4 (for HTML parsing)
- Typer (for CLI)
- Rich (for CLI interface)
- PyQt6 (for GUI)
- img2pdf (for PDF conversion)
- Pillow (for image processing)
- playwright (browser automation and dynamic reader scraping)
- zipfile (built-in, for CBZ conversion)

## License

This project is licensed under the MIT License - see the LICENSE file for details.
## Mangago reader and image pipeline

The Mangago provider uses Playwright with an isolated headless Chromium context; it does not use the user's personal Chrome profile. Chapter discovery expands the site's “show all chapters” control when present, removes duplicate links, and orders numbered chapters numerically.

Two reader layouts are supported:

- **Paginated reader (`/pg-N/`):** reads links from the reader's page selector, keeps pages belonging to the current chapter, and resolves each image from `#pic_container` with visible-image and CDN fallbacks. If no page selector exists, it falls back to the current page image.
- **Long-strip reader:** scrolls to load images, collects unique image URLs in DOM order, and stops after the image count stabilizes.

Mangago reader pages are rendered in Playwright because direct requests to those pages can return HTTP 403. Image responses are validated before saving. A chapter is marked complete only after validation confirms every expected page is present, readable, and unique; missing, invalid, or duplicate page numbers leave it incomplete.

Downloads use at most **3 page workers** per chapter. The default minimum delay between page-processing starts is **2 seconds**, with configurable retries and timeout.

### Image quality and output layout

The default image mode is **Original**: it saves the received image bytes without conversion or recompression. Optional **PNG** mode converts the decoded image to PNG; this adds no further lossy compression but cannot restore detail already lost in a source JPEG/WebP. When PNG mode and `keep_originals` are both enabled, the source bytes are also kept under `originais/`.

The default output layout is:

```text
output/mangago/<title>/IMG/<chapter>/page-001.<ext>
output/mangago/<title>/PDF/<chapter>/<chapter>.pdf
output/mangago/<title>/PDF/<chapter>/<chapter>.cbz
```

Chapter image folders use an in-progress marker while downloading and a completion marker only after structural validation succeeds. Existing valid page files can be retained on retry; partial chapters are not reported as complete.

Relevant settings (shared by the GUI and Web V2) include:

```json
{
  "format": "images",
  "image_format": "original",
  "keep_originals": false,
  "max_workers": 3,
  "page_delay": 2.0,
  "retry_count": 3,
  "timeout": 30
}
```

Set `image_format` to `png` to convert saved pages, and enable `keep_originals` to preserve the source files alongside them. `format` selects image folders, PDF, or CBZ output.

## Web V2 (HTML/CSS/JS local)

A interface Web V2 é executada apenas em `127.0.0.1` e reutiliza o mesmo núcleo Python (Playwright, downloader, conversores e configuração). A GUI PyQt6 continua disponível como fallback.

```bash
python -m pip install -e .
playwright install chromium
mangago-downloader-web
```

O navegador abre automaticamente em `http://127.0.0.1:8765`. Para iniciar sem abrir o browser:

```bash
MANGAGO_WEB_NO_BROWSER=1 mangago-downloader-web
```

A Web V2 oferece busca por título ou URL direta, seleção de capítulos e intervalos, tema claro/escuro, ajustes com salvamento automático e progresso por capítulo e página. Ela compartilha o mesmo núcleo Mangago descrito acima; o atraso padrão entre o início do processamento das páginas é **2,0 segundos**.
