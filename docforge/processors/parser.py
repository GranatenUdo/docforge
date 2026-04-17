"""Confluence storage-format HTML parser — yields Section objects."""

from __future__ import annotations

from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag


@dataclass
class Section:
    title: str
    text: str
    level: int = 0


def parse_confluence_html(html: str) -> list[Section]:
    """Parse Confluence storage-format HTML into a list of text sections.

    Handles Confluence-specific elements:
    - Headings become section boundaries
    - Tables are converted to readable text
    - Custom macros (smartlinks, status, emoji) are handled
    - Empty sections are dropped
    """
    soup = BeautifulSoup(html, "html.parser")

    _clean_confluence_macros(soup)

    sections: list[Section] = []
    current_title = ""
    current_level = 0
    current_parts: list[str] = []

    for element in soup.children:
        if not isinstance(element, Tag):
            text = element.get_text(strip=True)
            if text:
                current_parts.append(text)
            continue

        if element.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            # Flush previous section
            if current_parts:
                combined = "\n".join(current_parts).strip()
                if combined:
                    sections.append(
                        Section(title=current_title, text=combined, level=current_level)
                    )
                current_parts = []

            current_title = element.get_text(strip=True)
            current_level = int(element.name[1])

        elif element.name == "table":
            current_parts.append(_table_to_text(element))

        else:
            text = element.get_text(separator=" ", strip=True)
            if text:
                current_parts.append(text)

    # Flush last section
    if current_parts:
        combined = "\n".join(current_parts).strip()
        if combined:
            sections.append(Section(title=current_title, text=combined, level=current_level))

    return sections


def _clean_confluence_macros(soup: BeautifulSoup) -> None:
    """Process Confluence custom elements in-place."""
    for custom in soup.find_all("custom"):
        data_type = custom.get("data-type", "")

        if data_type == "smartlink":
            # Replace smart links with their URL
            href = custom.get_text(strip=True)
            if href.startswith("http"):
                custom.replace_with(href)
            else:
                custom.replace_with(custom.get_text(strip=True))

        elif data_type == "emoji":
            # Strip emojis
            custom.decompose()

        elif data_type == "status":
            # Convert status badges to text
            status_text = custom.get_text(strip=True)
            custom.replace_with(f"[{status_text}]")

        else:
            # Unknown custom element — keep as text
            custom.replace_with(custom.get_text(strip=True))

    # Also handle ac:structured-macro, ac:rich-text-body etc. (Confluence Server format)
    for macro in soup.find_all("ac:structured-macro"):
        body = macro.find("ac:rich-text-body")
        if body:
            macro.replace_with(body.get_text(separator=" ", strip=True))
        else:
            macro.decompose()


def _table_to_text(table: Tag) -> str:
    """Convert an HTML table to readable plain text.

    For tables with headers, produces "header: value" pairs per row.
    For tables without headers, produces pipe-separated rows.
    """
    rows = table.find_all("tr")
    if not rows:
        return ""

    # Extract headers from first row
    headers: list[str] = []
    first_row = rows[0]
    header_cells = first_row.find_all(["th"])
    if header_cells:
        headers = [cell.get_text(separator=" ", strip=True) for cell in header_cells]
        data_rows = rows[1:]
    else:
        data_rows = rows

    lines: list[str] = []

    for row in data_rows:
        cells = row.find_all(["td", "th"])
        values = [cell.get_text(separator=" ", strip=True) for cell in cells]

        if headers and len(values) == len(headers):
            # Format as "header: value" pairs, skip empty values
            pairs = [
                f"{h}: {v}" for h, v in zip(headers, values) if v
            ]
            if pairs:
                lines.append(" | ".join(pairs))
        elif values:
            non_empty = [v for v in values if v]
            if non_empty:
                lines.append(" | ".join(non_empty))

    return "\n".join(lines)
