"""
SurveyCXM RAG Service — Documentation & Application Knowledge Base

Indexes and retrieves official SurveyCXM module documentation from `documentation_categories`
to power application-aware, general-purpose questions in Ask AI.
Uses ChromaDB with native local embeddings for high performance and zero external API dependencies.
"""

import hashlib
import html
import json
import logging
import os
import re
from typing import Any

import chromadb
from chromadb.utils import embedding_functions

from database import get_db_service

logger = logging.getLogger(__name__)

CHROMA_PERSIST_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "chroma_db")
META_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "doc_index_meta.json")
COLLECTION_NAME = "surveycxm_documentation"


def _clean_html_text(raw_html: str) -> str:
    """Converts HTML snippets to clean, readable plain text while preserving structure."""
    if not raw_html:
        return ""
    # Convert lists to bullets
    text = re.sub(r'<\s*li[^>]*>', '\n• ', raw_html)
    # Convert paragraph and break tags to newlines
    text = re.sub(r'<\s*/?\s*(?:p|br|div|tr|table|thead|tbody)[^>]*>', '\n', text)
    # Remove remaining HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Unescape HTML entities (&amp;, &nbsp;, &gt;, etc.)
    text = html.unescape(text)
    # Normalize multiple newlines and spaces
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n\n', text)
    return text.strip()


def chunk_category_documentation(category: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Parses a documentation category and splits its HTML content into meaningful
    logical section chunks based on <h2>, <h3>, <h4> headers.
    """
    cat_id = category.get("id")
    name = (category.get("name") or "").strip()
    desc = (category.get("description") or "").strip()
    raw_content = category.get("content") or ""

    if not raw_content:
        return []

    # Regex to split by <h2>, <h3>, or <h4> tags while capturing the header text
    pattern = re.compile(r'<h([2-4])[^>]*>(.*?)</h\1>', re.DOTALL | re.IGNORECASE)
    matches = list(pattern.finditer(raw_content))

    chunks = []
    if not matches:
        clean_text = _clean_html_text(raw_content)
        if clean_text:
            chunks.append({
                "id": f"doc_{cat_id}_full",
                "text": f"Module: {name}\nSummary: {desc}\n\n{clean_text}",
                "metadata": {
                    "category_id": int(cat_id),
                    "module_name": name,
                    "section_title": name,
                    "description": desc,
                }
            })
        return chunks

    for i, match in enumerate(matches):
        heading_text = _clean_html_text(match.group(2))
        start_idx = match.end()
        end_idx = matches[i + 1].start() if (i + 1) < len(matches) else len(raw_content)

        body_html = raw_content[start_idx:end_idx]
        body_text = _clean_html_text(body_html)

        if not body_text and not heading_text:
            continue

        full_chunk_text = f"Module: {name}\nSection: {heading_text}\n"
        if desc and i == 0:
            full_chunk_text += f"Module Overview: {desc}\n"
        full_chunk_text += f"\n{body_text}"

        # If a single section is very large (> 3500 chars), split into sub-chunks
        if len(full_chunk_text) > 3500:
            paragraphs = [p.strip() for p in body_text.split("\n\n") if p.strip()]
            sub_chunk = ""
            sub_idx = 1
            for p in paragraphs:
                if len(sub_chunk) + len(p) > 2200 and sub_chunk:
                    chunks.append({
                        "id": f"doc_{cat_id}_sec_{i}_{sub_idx}",
                        "text": f"Module: {name}\nSection: {heading_text} (Part {sub_idx})\n\n{sub_chunk.strip()}",
                        "metadata": {
                            "category_id": int(cat_id),
                            "module_name": name,
                            "section_title": f"{heading_text} (Part {sub_idx})",
                            "description": desc,
                        }
                    })
                    sub_idx += 1
                    sub_chunk = p + "\n\n"
                else:
                    sub_chunk += p + "\n\n"
            if sub_chunk.strip():
                chunks.append({
                    "id": f"doc_{cat_id}_sec_{i}_{sub_idx}",
                    "text": f"Module: {name}\nSection: {heading_text} (Part {sub_idx})\n\n{sub_chunk.strip()}",
                    "metadata": {
                        "category_id": int(cat_id),
                        "module_name": name,
                        "section_title": f"{heading_text} (Part {sub_idx})",
                        "description": desc,
                    }
                })
        else:
            chunks.append({
                "id": f"doc_{cat_id}_sec_{i}",
                "text": full_chunk_text.strip(),
                "metadata": {
                    "category_id": int(cat_id),
                    "module_name": name,
                    "section_title": heading_text,
                    "description": desc,
                }
            })

    return chunks


class DocRAGService:
    """Manages document chunking, embeddings, ChromaDB vector store, and semantic retrieval."""

    def __init__(self):
        self.chroma_client = None
        self.collection = None
        self.embedding_fn = None
        self._initialized = False

    def _ensure_chroma(self) -> bool:
        """Initializes ChromaDB persistent client and collection with local embeddings."""
        if self.chroma_client and self.collection:
            return True
        try:
            os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
            self.embedding_fn = embedding_functions.DefaultEmbeddingFunction()
            self.chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
            self.collection = self.chroma_client.get_or_create_collection(
                name=COLLECTION_NAME,
                embedding_function=self.embedding_fn,
                metadata={"hnsw:space": "cosine"}
            )
            return True
        except Exception as e:
            logger.error(f"❌ Failed to initialize ChromaDB: {e}")
            return False

    def _compute_data_hash(self, categories: list[dict[str, Any]]) -> str:
        """Computes MD5 hash of category content to detect changes."""
        hasher = hashlib.md5()
        for c in sorted(categories, key=lambda x: x.get("id", 0)):
            hasher.update(str(c.get("id")).encode())
            hasher.update(str(c.get("name", "")).encode())
            hasher.update(str(c.get("description", "")).encode())
            hasher.update(str(c.get("content", "")).encode())
        return hasher.hexdigest()

    def sync_documentation_index(self, force: bool = False) -> dict[str, Any]:
        """
        Pulls all active categories from MySQL `documentation_categories`,
        chunks them, generates local embeddings, and updates ChromaDB.
        Skips indexing if the database content hash has not changed (unless force=True).
        """
        if not self._ensure_chroma():
            return {"success": False, "error": "ChromaDB unavailable"}

        db = get_db_service()
        if not db:
            return {"success": False, "error": "Database service unavailable"}

        categories = db.get_documentation_categories(active_only=True)
        if not categories:
            logger.warning("No active documentation categories found to index.")
            return {"success": False, "error": "No documentation categories found"}

        current_hash = self._compute_data_hash(categories)

        # Check existing metadata file
        if not force and os.path.exists(META_FILE_PATH):
            try:
                with open(META_FILE_PATH, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    if meta.get("data_hash") == current_hash and self.collection.count() > 0:
                        logger.info(f"✅ Documentation vector index is up to date ({self.collection.count()} chunks indexed).")
                        return {
                            "success": True,
                            "status": "up_to_date",
                            "total_chunks": self.collection.count(),
                            "categories_count": len(categories)
                        }
            except Exception as e:
                logger.warning(f"Could not read doc_index_meta.json: {e}")

        logger.info(f"🔄 Re-indexing documentation categories ({len(categories)} categories)...")

        # Chunk all categories
        all_chunks = []
        for cat in categories:
            chunks = chunk_category_documentation(cat)
            all_chunks.extend(chunks)

        if not all_chunks:
            return {"success": False, "error": "No chunks generated from documentation"}

        logger.info(f"Generated {len(all_chunks)} chunks across {len(categories)} categories. Indexing into ChromaDB...")

        # Reset/rebuild collection
        try:
            self.chroma_client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        self.collection = self.chroma_client.create_collection(
            name=COLLECTION_NAME,
            embedding_function=self.embedding_fn,
            metadata={"hnsw:space": "cosine"}
        )

        chunk_ids = [c["id"] for c in all_chunks]
        chunk_texts = [c["text"] for c in all_chunks]
        chunk_metas = [c["metadata"] for c in all_chunks]

        # Add to ChromaDB in batches
        batch_size = 50
        for i in range(0, len(chunk_ids), batch_size):
            self.collection.add(
                ids=chunk_ids[i:i + batch_size],
                documents=chunk_texts[i:i + batch_size],
                metadatas=chunk_metas[i:i + batch_size]
            )

        # Save metadata file
        try:
            os.makedirs(os.path.dirname(META_FILE_PATH), exist_ok=True)
            with open(META_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump({
                    "data_hash": current_hash,
                    "total_chunks": len(all_chunks),
                    "categories_count": len(categories)
                }, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to write doc_index_meta.json: {e}")

        logger.info(f"✅ Successfully indexed {len(all_chunks)} documentation chunks into ChromaDB.")
        return {
            "success": True,
            "status": "reindexed",
            "total_chunks": len(all_chunks),
            "categories_count": len(categories)
        }

    def search_documentation(self, query: str, top_k: int = 3, min_similarity: float = 0.30) -> list[dict[str, Any]]:
        """
        Performs semantic search against indexed documentation chunks.
        Returns top matching chunks with similarity score.
        """
        if not query or not query.strip():
            return []

        if not self._ensure_chroma():
            return []

        # If collection is empty, trigger a sync
        if self.collection.count() == 0:
            logger.info("ChromaDB documentation collection is empty. Syncing now...")
            self.sync_documentation_index()

        if self.collection.count() == 0:
            return []

        try:
            results = self.collection.query(
                query_texts=[query.strip()],
                n_results=top_k,
                include=["documents", "metadatas", "distances"]
            )

            if not results or not results.get("documents") or not results["documents"][0]:
                return []

            docs = results["documents"][0]
            metas = results["metadatas"][0]
            distances = results["distances"][0]

            matched = []
            for doc_text, meta, dist in zip(docs, metas, distances):
                # In cosine space, similarity = 1.0 - distance
                similarity = round(max(0.0, 1.0 - float(dist)), 4)
                if similarity >= min_similarity:
                    matched.append({
                        "module": meta.get("module_name", "General"),
                        "section": meta.get("section_title", ""),
                        "description": meta.get("description", ""),
                        "text": doc_text,
                        "similarity": similarity,
                        "category_id": meta.get("category_id")
                    })

            return matched

        except Exception as e:
            logger.error(f"❌ Error during documentation vector search: {e}")
            return []

    def format_docs_for_prompt(self, docs: list[dict[str, Any]]) -> str:
        """Formats retrieved documentation chunks for LLM system prompt context."""
        if not docs:
            return ""

        lines = [
            "===========================================================",
            "OFFICIAL SURVEYCXM APPLICATION DOCUMENTATION (MODULE GUIDES):",
            "Use the following verified platform documentation to answer any questions about",
            "SurveyCXM features, creation methods, logic setups, multilingual support, roles/permissions, triggers, or workflows.",
            "===========================================================",
        ]

        for i, d in enumerate(docs, 1):
            lines.append(f"\n[REFERENCE {i}] MODULE: {d.get('module')} | SECTION: {d.get('section')} (Confidence: {d.get('similarity', 0):.2f})")
            lines.append(d.get("text", "").strip())

        lines.append("\n===========================================================")
        return "\n".join(lines)


# Singleton instance
rag_service = DocRAGService()
