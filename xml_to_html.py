#!/usr/bin/env python3
"""
Convert the PDF-derived XML into a readable HTML file you can open in a browser.
Renders actual content (headers, paragraphs, footers, images) instead of raw XML/metadata.
"""

import argparse
import html
import xml.etree.ElementTree as ET
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output_files"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ font-family: system-ui, -apple-system, sans-serif; line-height: 1.5; color: #1a1a1a; }}
    body {{ max-width: 720px; margin: 0 auto; padding: 2rem; background: #fafafa; }}
    .doc-title {{ font-size: 0.9rem; color: #666; margin-bottom: 2rem; }}
    .page {{ background: #fff; padding: 2rem; margin-bottom: 2rem; box-shadow: 0 1px 3px rgba(0,0,0,0.08); border-radius: 8px; }}
    .page-number {{ font-size: 0.85rem; color: #888; margin-bottom: 1rem; }}
    header {{ font-weight: 600; font-size: 1.05rem; margin-bottom: 0.75rem; color: #111; }}
    .header-meta {{ font-size: 0.9rem; color: #444; }}
    p {{ margin: 0 0 1rem; text-align: justify; }}
    footer {{ font-size: 0.9rem; color: #555; margin-top: 0.5rem; border-top: 1px solid #eee; padding-top: 0.5rem; }}
    .doc-footer {{ margin-top: 0.25rem; }}
    img {{ max-width: 100%; height: auto; display: block; margin: 1rem 0; border-radius: 4px; }}
  </style>
</head>
<body>
  <div class="doc-title">Document: {title} ({pages} page(s))</div>
  {body}
</body>
</html>
"""


def text_or_empty(el: ET.Element) -> str:
    return (el.text or "").strip()


def elem_to_html(el: ET.Element, tag: str) -> str:
    content = text_or_empty(el)
    if not content and tag != "image":
        return ""
    if tag == "image":
        # Content is data URI for img src
        if content.startswith("data:"):
            return f'<img src="{html.escape(content)}" alt="Image" />'
        return ""
    content = html.escape(content)
    if tag == "header":
        return f"<header>{content}</header>"
    if tag == "footer":
        return f"<footer>{content}</footer>"
    return f"<p>{content}</p>"


def xml_to_html(xml_path: Path, out_path: Path | None = None) -> Path:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    source = root.get("source", "document")
    pages_attr = root.get("pages", "0")
    title = source.replace(".pdf", "")

    parts = []
    for page in root.findall("page"):
        num = page.get("number", "?")
        parts.append(f'<section class="page">')
        parts.append(f'<div class="page-number">Page {num}</div>')
        for child in page:
            tag = child.tag
            if tag in ("header", "paragraph", "footer", "image"):
                parts.append(elem_to_html(child, tag))
            elif tag == "links":
                for link in child.findall("link"):
                    uri = link.get("uri", "")
                    anchor = link.get("anchor", "") or uri
                    if uri:
                        parts.append(f'<p class="link"><a href="{html.escape(uri)}">{html.escape(anchor)}</a></p>')
        parts.append("</section>")

    body = "\n".join(parts)
    html_content = HTML_TEMPLATE.format(
        title=title,
        pages=pages_attr,
        body=body,
    )
    if out_path is None:
        out_path = xml_path.parent / f"{xml_path.stem}.html"
    out_path.write_text(html_content, encoding="utf-8")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Convert XML to HTML for browser viewing")
    parser.add_argument("xml", nargs="?", help="XML file (under output_files) or full path")
    parser.add_argument("-o", "--output", help="Output HTML path")
    args = parser.parse_args()

    if not args.xml:
        print("Usage: python xml_to_html.py <file.xml>")
        print("Example: python xml_to_html.py 11415832.xml")
        print("  (Looks for output_files/11415832.xml if path is not absolute)")
        return

    xml_path = Path(args.xml)
    if not xml_path.is_absolute():
        xml_path = OUTPUT_DIR / xml_path.name
    if not xml_path.is_file():
        print(f"Error: XML not found: {xml_path}")
        return

    out = Path(args.output) if args.output else None
    path = xml_to_html(xml_path, out)
    print(f"Created: {path}")
    print("Open this file in your browser to view the actual content.")


if __name__ == "__main__":
    main()
