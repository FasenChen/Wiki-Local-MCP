"""Convert Confluence storage XHTML to Markdown."""

from urllib.parse import quote

from bs4 import BeautifulSoup
from markdownify import markdownify


def storage_to_markdown(storage_xhtml: str) -> str:
    """Convert the storage representation to readable Markdown."""
    if "<ac:image" in storage_xhtml:
        soup = BeautifulSoup(storage_xhtml, "html.parser")
        for image in soup.find_all("ac:image"):
            attachment = image.find("ri:attachment")
            external = image.find("ri:url")
            if attachment is not None and attachment.get("ri:filename") and attachment.find() is None:
                src = "attachment:" + quote(attachment["ri:filename"], safe="")
            elif external is not None and external.get("ri:value"):
                src = external["ri:value"]
            else:
                continue
            replacement = soup.new_tag("img", src=src, alt=image.get("ac:alt", ""))
            if image.get("ac:title"):
                replacement["title"] = image["ac:title"]
            image.replace_with(replacement)
        storage_xhtml = str(soup)
    return markdownify(storage_xhtml, heading_style="ATX", bullets="-").strip()
