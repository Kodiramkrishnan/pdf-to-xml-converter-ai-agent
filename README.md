# PDF to XML Converter AI Agent

Converts PDF files to structured XML with **100% fidelity**: exact text (line breaks preserved), all images (base64), and all links. Optional **AI validation** (OpenAI) checks the extraction. Output is suitable to upload and publish on any website.

## Setup

1. **Create a virtual environment (recommended):**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # On Windows: .venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure OpenAI API key (optional, for --ai):**  
   Copy `.env.example` to `.env` and set your key:
   ```bash
   cp .env.example .env
   # Edit .env and set OPENAI_API_KEY=... or API_KEY=...
   ```

## Usage

- Place your PDF under **`input_files/`** (or pass a full path).
- Run the agent with the PDF name or path. The output XML will have the **same name** as the PDF and be written to **`output_files/`**.

```bash
# PDF in input_files (use filename only)
python pdf_to_xml_agent.py 11415832.pdf

# Or full path to PDF
python pdf_to_xml_agent.py /path/to/input_files/myfile.pdf

# Override directories
python pdf_to_xml_agent.py myfile.pdf --input-dir /path/to/inputs --output-dir /path/to/outputs

# Run with AI validation (uses OPENAI_API_KEY or API_KEY from .env)
python pdf_to_xml_agent.py myfile.pdf --ai

# Both optional: AI validation + HTML view in one run
python pdf_to_xml_agent.py myfile.pdf --ai --html

# Convert all PDFs in input_files/ in a single run (optional: add --html and/or --ai)
python pdf_to_xml_agent.py --all
python pdf_to_xml_agent.py --all --html
python pdf_to_xml_agent.py --all --ai --html
```

## Output XML Structure

- **`<document>`** – Root; attributes: `source`, `pages`
- **`<page>`** – Per page; attributes: `number`, `width`, `height`
- **`<header>`** / **`<footer>`** / **`<paragraph>`** – Text with **exact line breaks** as in the PDF
- **`<image>`** – Every image; element text is a **data URI** for use in HTML `<img src="...">`
- **`<links>`** – Per page; contains **`<link>`** elements with `uri`, `anchor` (visible text), and position (`x0`, `y0`, `x1`, `y1`)

Text is XML-safe; links and images are included so the conversion matches the PDF 1:1.

## View actual content in the browser

The XML file is structured data. To see the **actual content** (text and images) in a browser:

**Option 1 – Generate HTML after conversion**
```bash
python xml_to_html.py 11415832.xml
# Creates output_files/11415832.html — open this file in your browser
```

**Option 2 – Generate XML and HTML in one step**
```bash
python pdf_to_xml_agent.py 11415832.pdf --html
# Creates both .xml and .html in output_files/
```

Then **open the `.html` file** in any browser (double-click or drag into the browser window). You’ll see the document content (headers, paragraphs, footers, and any images) instead of raw XML or metadata.

## Showing the XML on a Website

- **Text:** Use the `<header>`, `<footer>`, and `<paragraph>` content in your HTML/CMS.
- **Images:** Use the `<image>` element’s text as the `src` of an `<img>` tag, e.g. in XSLT:  
  `<img src="{image}" alt="..." />`  
  or in JavaScript:  
  `imgElement.src = imageElement.textContent;`  
  That displays the full image on the page.

## Directory Layout

```
input_files/    ← Put PDFs here (or pass full path)
output_files/   ← XML files (same name as PDF) are written here
```

## Requirements

- Python 3.10+
- See `requirements.txt` for package dependencies.
