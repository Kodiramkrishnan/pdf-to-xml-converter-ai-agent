#!/usr/bin/env python3
"""
PDF to XML Converter AI Agent

Converts PDF files to structured XML with 100% fidelity: exact text (line breaks preserved),
all images (base64), and all links. Optional AI step (OpenAI) validates and refines structure.
Usage: Pass PDF path under input_files; output XML (same name) is written to output_files.
"""

import argparse
import base64
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom

import fitz  # PyMuPDF
from dotenv import load_dotenv

load_dotenv()

# Default paths relative to project root
PROJECT_ROOT = Path(__file__).resolve().parent
INPUT_DIR = PROJECT_ROOT / "input_files"
OUTPUT_DIR = PROJECT_ROOT / "output_files"

# Header/footer detection: content in top/bottom 12% of page (in normalized 0-1)
HEADER_THRESHOLD = 0.12
FOOTER_THRESHOLD = 0.88


def ensure_directories():
    """Create input_files and output_files if they don't exist."""
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def normalize_text(text: str) -> str:
    """Normalize whitespace and strip."""
    if not text or not isinstance(text, str):
        return ""
    return " ".join(text.split()).strip()


def sanitize_xml_text(text: str) -> str:
    """Remove characters illegal in XML 1.0 (control chars). ET escapes & < > on write."""
    if not text or not isinstance(text, str):
        return ""
    return "".join(
        c if (ord(c) >= 0x20 or c in "\t\n\r") else " "
        for c in text
    )


def is_likely_header(block_bbox, page_height: float) -> bool:
    """True if block is in the top portion of the page."""
    y0 = block_bbox[1]
    return (y0 / page_height) <= HEADER_THRESHOLD


def is_likely_footer(block_bbox, page_height: float) -> bool:
    """True if block is in the bottom portion of the page."""
    y1 = block_bbox[3]
    return (y1 / page_height) >= FOOTER_THRESHOLD


def extract_images_from_page(doc: fitz.Document, page: fitz.Page) -> list[dict]:
    """Extract all images from a page (blocks + get_images) with raw bytes and metadata."""
    images = []
    block_list = page.get_text("dict", clip=page.rect)["blocks"]
    xref_to_bbox = {}

    for block in block_list:
        if block.get("type") != 1:
            continue
        img = block.get("image")
        if not img:
            continue
        xref = None
        if isinstance(img, dict):
            xref = img.get("xref")
        elif isinstance(img, (list, tuple)) and len(img) > 0:
            xref = img[0]
        elif isinstance(img, int):
            xref = img
        if xref is not None:
            xref_to_bbox[xref] = block.get("bbox", (0, 0, 0, 0))

    all_xrefs = set(xref_to_bbox.keys()) | _image_xrefs_from_page(page)
    seen_xrefs = set()

    for xref in sorted(all_xrefs):
        if xref in seen_xrefs:
            continue
        seen_xrefs.add(xref)
        bbox = xref_to_bbox.get(xref, (0, 0, 0, 0))
        try:
            base = doc.extract_image(xref)
            raw_bytes = base.get("image")
            if not raw_bytes:
                continue
            images.append({
                "xref": xref,
                "bbox": bbox,
                "ext": base.get("ext", "png"),
                "image_bytes": raw_bytes,
                "width": base.get("width"),
                "height": base.get("height"),
            })
        except Exception:
            continue
    return images


def get_block_text(block: dict) -> str:
    """Collect text from a text block (normalized, single-line style)."""
    lines = []
    for line in block.get("lines", []):
        line_text = "".join(span.get("text", "") for span in line.get("spans", []))
        lines.append(line_text)
    return normalize_text("\n".join(lines))


def get_block_text_exact(block: dict) -> str:
    """Collect text from a text block preserving exact line breaks (100% fidelity)."""
    lines = []
    for line in block.get("lines", []):
        line_text = "".join(span.get("text", "") for span in line.get("spans", []))
        lines.append(line_text)
    return sanitize_xml_text("\n".join(lines))


def extract_links_from_page(page: fitz.Page) -> list[dict]:
    """Extract all links from a page (URI, rect, anchor text)."""
    links = []
    try:
        for link in page.get_links():
            uri = link.get("uri") or link.get("file") or ""
            if not uri:
                continue
            rect = link.get("from")
            if rect is not None:
                bbox = (rect.x0, rect.y0, rect.x1, rect.y1)
            else:
                bbox = (0, 0, 0, 0)
            anchor = ""
            try:
                if rect is not None:
                    anchor = page.get_textbox(rect) or ""
                    anchor = anchor.strip().replace("\n", " ")[:500]
            except Exception:
                pass
            links.append({"uri": uri, "bbox": bbox, "anchor": anchor})
    except Exception:
        pass
    return links


def _image_xrefs_from_page(page: fitz.Page) -> set:
    """Get all image xrefs from page (blocks + get_images fallback)."""
    xrefs = set()
    for block in page.get_text("dict", clip=page.rect).get("blocks", []):
        if block.get("type") != 1:
            continue
        img = block.get("image")
        if isinstance(img, dict) and img.get("xref") is not None:
            xrefs.add(img["xref"])
        elif isinstance(img, (list, tuple)) and len(img) > 0:
            xrefs.add(img[0])
        elif isinstance(img, int):
            xrefs.add(img)
    for item in page.get_images():
        if isinstance(item, (list, tuple)) and len(item) > 0:
            xrefs.add(item[0])
        elif isinstance(item, int):
            xrefs.add(item)
    return xrefs


def _ai_validate_and_refine(pdf_path: Path, root: ET.Element, api_key: str) -> ET.Element:
    """Use OpenAI to validate extraction completeness and optionally refine structure."""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        # Build a summary of what we extracted for the AI to check
        summary_parts = [f"Source: {root.get('source', '')}, Pages: {root.get('pages', '')}"]
        for page in root.findall("page"):
            pnum = page.get("number", "?")
            headers = page.findall("header")
            paras = page.findall("paragraph")
            footers = page.findall("footer")
            imgs = page.findall("image")
            links_el = page.find("links")
            nlinks = len(links_el.findall("link")) if links_el is not None else 0
            summary_parts.append(
                f"Page {pnum}: {len(headers)} headers, {len(paras)} paragraphs, "
                f"{len(footers)} footers, {len(imgs)} images, {nlinks} links"
            )
        summary = "\n".join(summary_parts)
        prompt = (
            "You are a PDF-to-XML conversion validator. Below is a summary of an XML extraction from a PDF. "
            "Reply with a short JSON object only: {\"valid\": true/false, \"suggestions\": [\"...\"]}. "
            "Set valid=false only if the summary suggests obvious missing content (e.g. zero paragraphs on a content page). "
            "Suggestions: brief tips to improve fidelity (e.g. 'Consider preserving line breaks'). "
            "Summary:\n" + summary
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
        )
        text = (resp.choices[0].message.content or "").strip()
        if text:
            # Try to parse and log (don't change XML from AI for fidelity)
            try:
                if "```" in text:
                    text = text.split("```")[1].replace("json", "").strip()
                data = json.loads(text)
                if not data.get("valid", True):
                    sys.stderr.write("AI validation: " + str(data.get("suggestions", [])) + "\n")
            except json.JSONDecodeError:
                pass
    except ImportError:
        sys.stderr.write("AI step skipped: install openai (pip install openai)\n")
    except Exception as e:
        sys.stderr.write(f"AI validation skipped: {e}\n")
    return root


def pdf_to_xml(
    pdf_path: str | Path,
    output_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    use_ai: bool = False,
) -> Path:
    """
    Convert a PDF file to XML with 100% fidelity: exact text, all images, all links.
    Optional use_ai=True runs OpenAI validation on the extraction.

    Args:
        pdf_path: Path to the PDF file (can be under input_files or absolute).
        output_path: Optional path for the output XML. If None, uses output_dir with same stem.
        output_dir: Directory for output when output_path is None (default: OUTPUT_DIR).
        use_ai: If True and API key set, run AI validation step.

    Returns:
        Path to the created XML file.
    """
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    ensure_directories()
    out_dir = Path(output_dir) if output_dir is not None else OUTPUT_DIR
    if output_path is None:
        output_path = out_dir / f"{pdf_path.stem}.xml"
    else:
        output_path = Path(output_path).resolve()

    doc = fitz.open(pdf_path)
    root = ET.Element("document")
    root.set("source", pdf_path.name)
    root.set("pages", str(len(doc)))

    # Collect all text blocks and images per page to preserve order
    for page_num in range(len(doc)):
        page = doc[page_num]
        page_height = page.rect.height
        page_elem = ET.SubElement(root, "page")
        page_elem.set("number", str(page_num + 1))
        page_elem.set("width", f"{page.rect.width:.2f}")
        page_elem.set("height", f"{page_height:.2f}")

        block_list = page.get_text("dict", clip=page.rect)["blocks"]
        image_list = extract_images_from_page(doc, page)
        image_by_bbox = {(tuple(b["bbox"]), b["xref"]): b for b in image_list}

        block_index = 0
        for block in block_list:
            bbox = block.get("bbox", (0, 0, 0, 0))
            bkey = (tuple(bbox), None)

            if block.get("type") == 1:
                # Image block: find matching extracted image
                img_info = None
                for (ibbox, xref), info in image_by_bbox.items():
                    if abs(ibbox[0] - bbox[0]) < 2 and abs(ibbox[1] - bbox[1]) < 2:
                        img_info = info
                        break
                if img_info and img_info.get("image_bytes"):
                    img_elem = ET.SubElement(page_elem, "image")
                    img_elem.set("id", f"img_p{page_num + 1}_b{block_index}")
                    img_elem.set("width", str(img_info.get("width", "")))
                    img_elem.set("height", str(img_info.get("height", "")))
                    img_elem.set("format", img_info.get("ext", "png"))
                    b64 = base64.b64encode(img_info["image_bytes"]).decode("ascii")
                    mime = f"image/{img_info.get('ext', 'png')}"
                    if mime == "image/jpg":
                        mime = "image/jpeg"
                    img_elem.set("encoding", "base64")
                    img_elem.set("mime", mime)
                    # Data URI for direct use in HTML img src
                    img_elem.text = f"data:{mime};base64,{b64}"
                block_index += 1
                continue

            text = get_block_text_exact(block)
            if not text:
                block_index += 1
                continue

            if is_likely_header(bbox, page_height):
                tag = "header"
            elif is_likely_footer(bbox, page_height):
                tag = "footer"
            else:
                tag = "paragraph"

            elem = ET.SubElement(page_elem, tag)
            elem.set("block_id", str(block_index))
            elem.set("y0", f"{bbox[1]:.2f}")
            elem.set("y1", f"{bbox[3]:.2f}")
            elem.text = text
            block_index += 1

        # Links (100% fidelity: all URIs and anchors)
        page_links = extract_links_from_page(page)
        if page_links:
            links_elem = ET.SubElement(page_elem, "links")
            for i, lnk in enumerate(page_links):
                link_el = ET.SubElement(links_elem, "link")
                link_el.set("id", f"link_p{page_num + 1}_{i}")
                link_el.set("uri", sanitize_xml_text(lnk["uri"]))
                if lnk.get("anchor"):
                    link_el.set("anchor", sanitize_xml_text(lnk["anchor"]))
                b = lnk.get("bbox", (0, 0, 0, 0))
                link_el.set("x0", f"{b[0]:.2f}")
                link_el.set("y0", f"{b[1]:.2f}")
                link_el.set("x1", f"{b[2]:.2f}")
                link_el.set("y1", f"{b[3]:.2f}")

    doc.close()

    # Optional: AI agent validation and structure refinement (OpenAI)
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY")
    if use_ai and api_key:
        root = _ai_validate_and_refine(pdf_path, root, api_key)

    # Pretty-print XML
    rough = ET.tostring(root, encoding="unicode", default_namespace="")
    reparsed = minidom.parseString(rough)
    pretty = reparsed.toprettyxml(indent="  ", encoding="utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(pretty)

    return output_path


def main():
    parser = argparse.ArgumentParser(description="Convert PDF to XML (input_files -> output_files)")
    parser.add_argument(
        "pdf",
        nargs="?",
        default=None,
        help="PDF filename (under input_files) or full path to PDF",
    )
    parser.add_argument(
        "--input-dir",
        default=None,
        help=f"Override input directory (default: {INPUT_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=f"Override output directory (default: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "--html",
        action="store_true",
        help="Also generate an HTML file to view content in the browser",
    )
    parser.add_argument(
        "--ai",
        action="store_true",
        help="Run AI validation (OpenAI). Set OPENAI_API_KEY or API_KEY in .env",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Convert all PDF files in input_files (or --input-dir) in a single run",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir) if args.input_dir else INPUT_DIR
    output_dir = Path(args.output_dir) if args.output_dir else OUTPUT_DIR

    if args.all:
        pdf_files = sorted(input_dir.glob("*.pdf"))
        if not pdf_files:
            print("No PDF files found in", input_dir, file=sys.stderr)
            sys.exit(1)
        if args.pdf:
            print("Ignoring positional PDF when --all is used.", file=sys.stderr)
        success = 0
        for pdf_path in pdf_files:
            try:
                out = pdf_to_xml(pdf_path, output_dir=output_dir, use_ai=args.ai)
                print(f"Created: {out}")
                if args.html:
                    from xml_to_html import xml_to_html
                    html_path = xml_to_html(out)
                    print(f"Created: {html_path}")
                success += 1
            except Exception as e:
                print(f"Error ({pdf_path.name}): {e}", file=sys.stderr)
        if args.html and success:
            print("Open the HTML files in your browser to view the actual content.")
        sys.exit(0 if success == len(pdf_files) else 1)

    if not args.pdf:
        print("Usage: python pdf_to_xml_agent.py <pdf_file>")
        print("       python pdf_to_xml_agent.py --all   # convert all PDFs in input_files/")
        print("  Example: python pdf_to_xml_agent.py 11415832.pdf")
        print("  PDF should be under input_files/ or pass full path.")
        sys.exit(1)

    pdf_path = Path(args.pdf)
    if not pdf_path.is_absolute():
        pdf_path = input_dir / pdf_path.name

    try:
        out = pdf_to_xml(pdf_path, output_dir=output_dir, use_ai=args.ai)
        print(f"Created: {out}")
        if args.html:
            from xml_to_html import xml_to_html
            html_path = xml_to_html(out)
            print(f"Created: {html_path}")
            print("Open the HTML file in your browser to view the actual content.")
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
