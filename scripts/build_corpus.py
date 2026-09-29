#!/usr/bin/env python3
"""Download a small, explicitly OGL-licensed policy corpus and build page-aware chunks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "corpus"
OGL = "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/"
SOURCES = [
    {
        "id": "ctp-mou-2024",
        "title": "Critical third parties: Bank of England / FCA Memorandum of Understanding (2024)",
        "publisher": "Bank of England and Financial Conduct Authority",
        "published": "2024-11-12",
        "url": "https://assets.publishing.service.gov.uk/media/672b3d35f03408fa7966d1cb/Memorandum_of_Understanding_between_the_FCA_and_the_Bank_of_England-critical-third-party.pdf",
        "filename": "critical-third-party-mou.pdf",
        "format": "pdf",
        "licence": "OGL-3.0",
        "licence_evidence": "Explicit Open Government Licence v3.0 statement on PDF page 2.",
        "attribution": "© Bank of England and Financial Conduct Authority copyright 2024. Contains public sector information licensed under the Open Government Licence v3.0.",
    },
    {
        "id": "digital-pound-2024",
        "title": "Response to the digital pound consultation (January 2024)",
        "publisher": "Bank of England and HM Treasury",
        "published": "2024-01-25",
        "url": "https://www.bankofengland.co.uk/-/media/boe/files/paper/2024/responses-to-the-digital-pound-consultation-paper.pdf",
        "filename": "digital-pound-response.pdf",
        "format": "pdf",
        "licence": "OGL-3.0",
        "licence_evidence": "Explicit Crown copyright / Open Government Licence v3.0 statement on PDF page 4.",
        "attribution": "© Crown copyright 2024. Contains public sector information licensed under the Open Government Licence v3.0.",
    },
    {
        "id": "mpc-remit-2025",
        "title": "Remit for the Monetary Policy Committee: Budget 2025",
        "publisher": "HM Treasury (letter to the Bank of England)",
        "published": "2025-11-26",
        "url": "https://www.gov.uk/government/publications/monetary-policy-remit-budget-2025/letter-from-chancellor-of-the-exchequer-to-govenor-of-the-bank-of-england",
        "filename": "mpc-remit-2025.html",
        "format": "html",
        "licence": "OGL-3.0",
        "licence_evidence": "GOV.UK Crown copyright and OGL footer; no separate restriction on this document.",
        "attribution": "© Crown copyright 2025. Contains public sector information licensed under the Open Government Licence v3.0.",
    },
    {
        "id": "crisis-mou-2025",
        "title": "Memorandum of Understanding on financial crisis management (2025)",
        "publisher": "HM Treasury and Bank of England",
        "published": "2025-09-01",
        "url": "https://www.gov.uk/government/publications/memorandum-of-understanding-on-financial-crisis-management/memorandum-of-understanding-on-financial-crisis-management",
        "filename": "crisis-mou-2025.html",
        "format": "html",
        "licence": "OGL-3.0",
        "licence_evidence": "Explicit Crown copyright / Open Government Licence v3.0 statement in document.",
        "attribution": "© Crown copyright 2025. Contains public sector information licensed under the Open Government Licence v3.0.",
    },
]


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xad", "").replace("−", "-")).strip()


def extract(source: dict, raw: bytes) -> list[tuple[str, str]]:
    """Keep PDF page references and HTML heading anchors; omit boilerplate and logos."""
    if source["format"] == "pdf":
        from io import BytesIO

        from pypdf import PdfReader

        pages = PdfReader(BytesIO(raw)).pages
        result = []
        for i, page in enumerate(pages, 1):
            text = normalise(page.extract_text() or "")
            # Skip title, publishing/copyright, contents pages and footnote-only pages.
            if (
                len(text.split()) < 60
                or "This publication is licensed" in text
                or (i <= 6 and "Contents" in text)
            ):
                continue
            text = re.sub(r"Bank of England\s*(?:and HM Treasury)?\s*(?:Page\s*)?\d+\s*", "", text)
            result.append((str(i), text))
        return result
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(raw, "html.parser")
    main = soup.select_one(".gem-c-govspeak")
    if main is None:
        raise ValueError(f"Missing document content for {source['id']}")
    for node in main.select(
        "script, style, .gem-c-govspeak__contact, .app-c-contents-list, figure"
    ):
        node.decompose()
    # Read blocks to avoid overlapping parent elements; document headings retained.
    pieces = [
        normalise(n.get_text(" ", strip=True))
        for n in main.select("h2, h3, p, li")
        if not any(a.name in {"h2", "h3", "p", "li"} for a in n.parents if a is not main)
    ]
    return [("document", "\n".join(p for p in pieces if len(p) > 20))]


def chunk_text(text: str, max_words: int = 155, overlap: int = 25) -> list[str]:
    # Sentence boundaries first; hard split only a long paragraph/sentence.
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9“‘(])|\n+", text)
    chunks, current = [], []
    for sentence in sentences:
        words = sentence.split()
        if not words:
            continue
        if len(words) > max_words:
            if current:
                chunks.append(" ".join(current))
                current = []
            for offset in range(0, len(words), max_words - overlap):
                part = words[offset : offset + max_words]
                if len(part) >= 15:
                    chunks.append(" ".join(part))
            continue
        if current and len(current) + len(words) > max_words:
            chunks.append(" ".join(current))
            current = current[-overlap:]
        current.extend(words)
    if len(current) >= 15:
        chunks.append(" ".join(current))
    return chunks


def build(refresh: bool = False) -> dict:
    raw_dir = CORPUS / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    previous = {}
    if (CORPUS / "manifest.json").exists():
        previous = {
            x["id"]: x for x in json.loads((CORPUS / "manifest.json").read_text())["documents"]
        }
    retrieved = datetime.now(timezone.utc).isoformat(timespec="seconds")
    documents, passages = [], []
    for source in SOURCES:
        path = raw_dir / source["filename"]
        if refresh or not path.exists():
            request = Request(
                source["url"],
                headers={
                    "User-Agent": "OpenFinanceIntelligence/1.0 (public academic portfolio corpus)"
                },
            )
            with urlopen(request, timeout=45) as response:
                raw = response.read(12_000_001)
            if len(raw) > 12_000_000:
                raise ValueError("Source exceeds 12 MB safety limit")
            path.write_bytes(raw)
            retrieved_at = retrieved
        else:
            raw = path.read_bytes()
            retrieved_at = previous.get(source["id"], {}).get("retrieved_at", retrieved)
        doc = dict(
            source,
            retrieved_at=retrieved_at,
            sha256=hashlib.sha256(raw).hexdigest(),
            licence_url=OGL,
        )
        count = 0
        for page, section in extract(source, raw):
            for chunk in chunk_text(section):
                count += 1
                passages.append(
                    {
                        "id": f"{source['id']}-p{page}-{count:03d}",
                        "document_id": source["id"],
                        "page": page,
                        "text": chunk,
                        "sha256": hashlib.sha256(chunk.encode()).hexdigest(),
                    }
                )
        if count < 4:
            raise ValueError(f"Too few passages extracted from {source['id']}")
        doc["passages"] = count
        documents.append(doc)
    manifest = {
        "built_at": retrieved,
        "corpus_as_of": max(d["published"] for d in documents),
        "licence": "OGL-3.0",
        "documents": documents,
        "passage_count": len(passages),
    }
    (CORPUS / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    (CORPUS / "passages.json").write_text(json.dumps(passages, indent=2, ensure_ascii=False) + "\n")
    return {"documents": len(documents), "passages": len(passages)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Refetch official documents; review their licences and changed contents before publishing.",
    )
    args = parser.parse_args()
    print(json.dumps(build(args.refresh)))
