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
import math
import os
import re
from collections import Counter
import threading
import time
from typing import Any

import chromadb
from chromadb.utils import embedding_functions

from database import get_db_service

logger = logging.getLogger(__name__)

CHROMA_PERSIST_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "chroma_db")
META_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "doc_index_meta.json")
COLLECTION_NAME = "surveycxm_documentation"
FLASHRANK_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "flashrank_cache")


def _safe_cat_id(cat_id: Any) -> int:
    """Safely converts category id to int, defaulting to 0 on None or invalid input."""
    if cat_id is None:
        return 0
    try:
        return int(cat_id)
    except (ValueError, TypeError):
        return 0


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


def _split_into_subunits(text: str, max_unit: int = 1500) -> list[str]:
    """
    Splits text into units of at most max_unit chars.
    First splits by paragraphs (\n\n). If a single paragraph exceeds max_unit
    (e.g. continuous bulleted lists without blank lines), splits by line.
    """
    units = []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    for p in paragraphs:
        if len(p) <= max_unit:
            units.append(p)
        else:
            # Paragraph is too long (e.g. long bullet list), split by line
            lines = [line.strip() for line in p.split("\n") if line.strip()]
            curr = ""
            for line in lines:
                if len(curr) + len(line) + 1 > max_unit and curr:
                    units.append(curr.strip())
                    curr = line + "\n"
                else:
                    curr += line + "\n"
            if curr.strip():
                units.append(curr.strip())
    return units


def chunk_category_documentation(category: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Parses a documentation category and splits its HTML content into meaningful
    logical section chunks based on <h1>, <h2>, <h3>, <h4> headers.
    Preserves intro text before the first header and retains module overview in sub-chunks.
    """
    cat_id = _safe_cat_id(category.get("id"))
    name = (category.get("name") or "").strip()
    desc = (category.get("description") or "").strip()
    raw_content = category.get("content") or ""

    if not raw_content:
        return []

    # Regex to split by <h1>, <h2>, <h3>, or <h4> tags while capturing the header text
    pattern = re.compile(r'<h([1-4])[^>]*>(.*?)</h\1>', re.DOTALL | re.IGNORECASE)
    matches = list(pattern.finditer(raw_content))

    chunks = []
    if not matches:
        clean_text = _clean_html_text(raw_content)
        if clean_text:
            chunks.append({
                "id": f"doc_{cat_id}_full",
                "text": f"Module: {name}\nSummary: {desc}\n\n{clean_text}" if desc else f"Module: {name}\n\n{clean_text}",
                "metadata": {
                    "category_id": cat_id,
                    "module_name": name,
                    "section_title": name,
                    "description": desc,
                }
            })
        return chunks

    # 1. Capture introductory text before the first heading match (if any)
    if matches[0].start() > 0:
        intro_html = raw_content[:matches[0].start()]
        intro_text = _clean_html_text(intro_html)
        if intro_text:
            intro_chunk_text = f"Module: {name}\nSection: Overview\n"
            if desc:
                intro_chunk_text += f"Module Overview: {desc}\n"
            intro_chunk_text += f"\n{intro_text}"
            chunks.append({
                "id": f"doc_{cat_id}_intro",
                "text": intro_chunk_text.strip(),
                "metadata": {
                    "category_id": cat_id,
                    "module_name": name,
                    "section_title": f"{name} - Overview",
                    "description": desc,
                }
            })

    # 2. Iterate through matched headers
    for i, match in enumerate(matches):
        heading_text = _clean_html_text(match.group(2))
        start_idx = match.end()
        end_idx = matches[i + 1].start() if (i + 1) < len(matches) else len(raw_content)

        body_html = raw_content[start_idx:end_idx]
        body_text = _clean_html_text(body_html)

        if not body_text and not heading_text:
            continue

        full_chunk_text = f"Module: {name}\nSection: {heading_text}\n"
        if desc:
            full_chunk_text += f"Module Overview: {desc}\n"
        full_chunk_text += f"\n{body_text}"

        # If a single section is very large (> 3500 chars), split into sub-chunks
        if len(full_chunk_text) > 3500:
            subunits = _split_into_subunits(body_text, max_unit=1800)
            sub_chunk = ""
            sub_idx = 1
            for unit in subunits:
                if len(sub_chunk) + len(unit) > 2200 and sub_chunk:
                    sub_prefix = f"Module: {name}\nSection: {heading_text} (Part {sub_idx})\n"
                    if desc:
                        sub_prefix += f"Module Overview: {desc}\n"
                    chunks.append({
                        "id": f"doc_{cat_id}_sec_{i}_{sub_idx}",
                        "text": f"{sub_prefix}\n{sub_chunk.strip()}",
                        "metadata": {
                            "category_id": cat_id,
                            "module_name": name,
                            "section_title": f"{heading_text} (Part {sub_idx})",
                            "description": desc,
                        }
                    })
                    sub_idx += 1
                    sub_chunk = unit + "\n\n"
                else:
                    sub_chunk += unit + "\n\n"
            if sub_chunk.strip():
                sub_prefix = f"Module: {name}\nSection: {heading_text} (Part {sub_idx})\n"
                if desc:
                    sub_prefix += f"Module Overview: {desc}\n"
                chunks.append({
                    "id": f"doc_{cat_id}_sec_{i}_{sub_idx}",
                    "text": f"{sub_prefix}\n{sub_chunk.strip()}",
                    "metadata": {
                        "category_id": cat_id,
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
                    "category_id": cat_id,
                    "module_name": name,
                    "section_title": heading_text,
                    "description": desc,
                }
            })

    return chunks


class BM25Index:
    """
    In-memory Okapi BM25 index for sparse keyword search.
    Provides fast, zero-dependency lexical retrieval alongside ChromaDB dense vectors.
    """
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus_size = 0
        self.avgdl = 0.0
        self.doc_lengths = []
        self.doc_ids = []
        self.doc_freqs = []
        self.idf = {}
        self.metadatas = []
        self.documents = []

    @staticmethod
    def tokenize(text: str) -> list[str]:
        """Extract lowercase alphanumeric tokens, including template placeholders (e.g. {{VAR}})."""
        if not text:
            return []
        return re.findall(r'\{\{[^}]+\}\}|\b\w+\b', text.lower())

    def index(self, doc_ids: list[str], documents: list[str], metadatas: list[dict[str, Any]]):
        """Constructs document frequencies and IDF lookup table from corpus."""
        self.doc_ids = doc_ids
        self.documents = documents
        self.metadatas = metadatas
        self.corpus_size = len(documents)
        if self.corpus_size == 0:
            return

        self.doc_freqs = []
        self.doc_lengths = []
        df = Counter()
        for doc in documents:
            tokens = self.tokenize(doc)
            self.doc_lengths.append(len(tokens))
            freq = Counter(tokens)
            self.doc_freqs.append(freq)
            for token in freq.keys():
                df[token] += 1

        self.avgdl = sum(self.doc_lengths) / self.corpus_size
        self.idf = {}
        for token, count in df.items():
            self.idf[token] = math.log(((self.corpus_size - count + 0.5) / (count + 0.5)) + 1.0)

    def search(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        """Scores all indexed chunks against query terms and returns ranked candidates."""
        if not query or self.corpus_size == 0:
            return []
        tokens = self.tokenize(query)
        if not tokens:
            return []
        scores = []
        for idx in range(self.corpus_size):
            score = 0.0
            doc_len = self.doc_lengths[idx]
            freq = self.doc_freqs[idx]
            len_norm = 1.0 - self.b + self.b * (doc_len / self.avgdl if self.avgdl > 0 else 1.0)
            for token in tokens:
                if token not in freq:
                    continue
                tf = freq[token]
                idf = self.idf.get(token, 0.0)
                score += idf * (tf * (self.k1 + 1.0) / (tf + self.k1 * len_norm))
            if score > 0.0:
                scores.append((idx, score))
        scores.sort(key=lambda x: x[1], reverse=True)
        results = []
        for rank, (idx, bm25_score) in enumerate(scores[:top_k], 1):
            results.append({
                "id": self.doc_ids[idx],
                "score": bm25_score,
                "text": self.documents[idx],
                "metadata": self.metadatas[idx],
                "rank": rank
            })
        return results


class DocRAGService:
    """Manages document chunking, embeddings, ChromaDB vector store, and semantic retrieval."""

    def __init__(self):
        self.chroma_client = None
        self.collection = None
        self.embedding_fn = None
        self.bm25 = BM25Index()
        self.ranker = None
        self._initialized = False
        self._lock = threading.RLock()
        self._is_syncing = False
        self._last_auto_check_time = 0.0
        self._auto_check_interval = 30.0
        self._worker_thread = None
        self._worker_started = False

    def _ensure_ranker(self):
        """Initializes local FlashRank cross-encoder for high-precision reranking."""
        if self.ranker is not None:
            return self.ranker
        try:
            from flashrank import Ranker
            os.makedirs(FLASHRANK_CACHE_DIR, exist_ok=True)
            self.ranker = Ranker(model_name="ms-marco-TinyBERT-L-2-v2", cache_dir=FLASHRANK_CACHE_DIR)
            logger.info("⚡ FlashRank local cross-encoder initialized successfully.")
        except Exception as e:
            logger.warning(f"Could not initialize FlashRank cross-encoder: {e}")
            self.ranker = None
        return self.ranker

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
            # Ensure in-memory BM25 index is populated from persistent collection
            if self.bm25.corpus_size == 0 and self.collection.count() > 0:
                try:
                    all_data = self.collection.get(include=["documents", "metadatas"])
                    if all_data and all_data.get("ids"):
                        self.bm25.index(all_data["ids"], all_data["documents"], all_data["metadatas"])
                        logger.info(f"⚡ BM25 sparse index loaded with {self.bm25.corpus_size} chunks.")
                except Exception as bm_err:
                    logger.warning(f"Could not load BM25 index: {bm_err}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to initialize ChromaDB: {e}")
            return False

    def _compute_data_hash(self, categories: list[dict[str, Any]]) -> str:
        """Computes MD5 hash of category content to detect changes."""
        hasher = hashlib.md5()
        for c in sorted(categories, key=lambda x: _safe_cat_id(x.get("id"))):
            hasher.update(str(_safe_cat_id(c.get("id"))).encode())
            hasher.update(str(c.get("name", "")).encode())
            hasher.update(str(c.get("description", "")).encode())
            hasher.update(str(c.get("content", "")).encode())
        return hasher.hexdigest()

    def sync_documentation_index(self, force: bool = False) -> dict[str, Any]:
        """
        Pulls all active categories from MySQL `documentation_categories`,
        chunks them, generates local embeddings, and updates ChromaDB.
        Skips indexing if the database content hash has not changed (unless force=True).
        Thread-safe to prevent race conditions and SQLite locks.
        """
        with self._lock:
            self._is_syncing = True
            try:
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

                # Index in-memory BM25 index for sparse hybrid retrieval
                self.bm25.index(chunk_ids, chunk_texts, chunk_metas)
                logger.info(f"⚡ BM25 sparse index built with {len(all_chunks)} chunks.")

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

                # Automatically invalidate cached documentation answers upon reindexing
                try:
                    from services.cache_service import cache_service
                    cache_service.invalidate_namespace("doc_rag")
                    logger.info("⚡ Invalidation completed: doc_rag semantic cache cleared for fresh documentation.")
                except Exception as cache_err:
                    logger.warning(f"Failed to invalidate cache after documentation reindex: {cache_err}")

                return {
                    "success": True,
                    "status": "reindexed",
                    "total_chunks": len(all_chunks),
                    "categories_count": len(categories)
                }
            finally:
                self._is_syncing = False

    def start_auto_sync_worker(self, interval_seconds: int = 60):
        """Starts a background daemon thread that periodically checks MySQL for documentation updates."""
        with self._lock:
            if self._worker_started:
                return
            self._worker_started = True

        def _worker_loop():
            logger.info(f"🔄 Documentation RAG auto-sync worker started (interval: {interval_seconds}s)")
            import time
            while True:
                try:
                    time.sleep(interval_seconds)
                    self.sync_documentation_index(force=False)
                except Exception as worker_err:
                    logger.warning(f"Error in documentation auto-sync worker loop: {worker_err}")

        self._worker_thread = threading.Thread(target=_worker_loop, daemon=True, name="rag_doc_auto_sync")
        self._worker_thread.start()

    def check_and_sync_if_needed(self):
        """Lightweight non-blocking check called on query arrival. If > 30s since last check, verify hash."""
        now = time.time()
        if (now - self._last_auto_check_time) < self._auto_check_interval or self._is_syncing:
            return
        self._last_auto_check_time = now
        try:
            if not self.collection or self.collection.count() == 0:
                self.sync_documentation_index(force=False)
                return
            # Non-blocking background sync check when index is already populated
            threading.Thread(target=self.sync_documentation_index, kwargs={"force": False}, daemon=True, name="rag_doc_ttl_sync").start()
        except Exception as e:
            logger.debug(f"Doc RAG check_and_sync_if_needed notice: {e}")

    def search_documentation(self, query: str, top_k: int = 3, min_similarity: float = 0.42) -> list[dict[str, Any]]:
        """
        Performs Hybrid Search combining Dense Vector Retrieval (ONNX all-MiniLM-L6-v2)
        and Sparse Lexical Retrieval (Okapi BM25) fused via Reciprocal Rank Fusion (RRF).
        Yields superior precision for both conceptual semantic queries and exact keywords.
        """
        if not query or not query.strip():
            return []

        with self._lock:
            # Check if database documentation was updated (TTL 30s)
            self.check_and_sync_if_needed()

            if not self._ensure_chroma():
                return []

            try:
                count = self.collection.count()
            except Exception as e:
                logger.warning(f"Error checking collection count: {e}")
                count = 0

            # If collection is empty and not already syncing, trigger a sync
            if count == 0 and not self._is_syncing:
                logger.info("ChromaDB documentation collection is empty. Syncing now...")
                self.sync_documentation_index()
                try:
                    count = self.collection.count()
                except Exception:
                    count = 0

            if count == 0:
                return []

            candidate_k = min(max(top_k * 4, 10), count)
            if candidate_k <= 0:
                return []

            try:
                # 1. Dense Semantic Vector Search (ChromaDB)
                results = self.collection.query(
                    query_texts=[query.strip()],
                    n_results=candidate_k,
                    include=["documents", "metadatas", "distances"]
                )

                dense_docs = results["documents"][0] if results and results.get("documents") else []
                dense_ids = results["ids"][0] if results and results.get("ids") else []
                dense_metas = results["metadatas"][0] if results and results.get("metadatas") else []
                dense_dists = results["distances"][0] if results and results.get("distances") else []

                dense_ranks = {}
                dense_sims = {}
                doc_lookup = {}

                for rank, (did, doc, meta, dist) in enumerate(zip(dense_ids, dense_docs, dense_metas, dense_dists), 1):
                    sim = round(max(0.0, 1.0 - float(dist)), 4)
                    dense_ranks[did] = rank
                    dense_sims[did] = sim
                    doc_lookup[did] = (doc, meta)

                # 2. Sparse Lexical Search (Okapi BM25)
                sparse_res = self.bm25.search(query.strip(), top_k=candidate_k)
                sparse_ranks = {}
                sparse_scores = {}

                for item in sparse_res:
                    did = item["id"]
                    sparse_ranks[did] = item["rank"]
                    sparse_scores[did] = item["score"]
                    if did not in doc_lookup:
                        doc_lookup[did] = (item["text"], item["metadata"])

                # 3. Reciprocal Rank Fusion (RRF) with k=60
                RRF_K = 60
                all_candidate_ids = set(dense_ranks.keys()) | set(sparse_ranks.keys())
                scored_candidates = []

                for did in all_candidate_ids:
                    r_dense = dense_ranks.get(did)
                    r_sparse = sparse_ranks.get(did)

                    score_dense = (1.0 / (RRF_K + r_dense)) if r_dense is not None else 0.0
                    score_sparse = (1.0 / (RRF_K + r_sparse)) if r_sparse is not None else 0.0
                    total_rrf = score_dense + score_sparse

                    sim = dense_sims.get(did, 0.0)
                    bm25_score = sparse_scores.get(did, 0.0)

                    # Domain Guardrail / Quality Threshold:
                    # Keep if dense similarity meets min_similarity, OR
                    # if strong keyword match with reasonable semantic context, OR
                    # if both dense and sparse matched
                    is_relevant = False
                    if sim >= min_similarity:
                        is_relevant = True
                    elif bm25_score >= 3.0:
                        is_relevant = True
                    elif r_dense is not None and r_sparse is not None and (sim >= 0.20 or bm25_score >= 1.5):
                        is_relevant = True

                    if is_relevant:
                        scored_candidates.append({
                            "id": did,
                            "rrf": total_rrf,
                            "similarity": sim,
                            "bm25_score": bm25_score
                        })

                # Sort candidates by descending RRF score
                scored_candidates.sort(key=lambda x: x["rrf"], reverse=True)

                # 4. Local Cross-Encoder Reranking (FlashRank)
                ranker = self._ensure_ranker()
                if ranker and len(scored_candidates) > 1:
                    try:
                        passages = []
                        for cand in scored_candidates[:12]:
                            did = cand["id"]
                            doc_text, meta = doc_lookup[did]
                            passages.append({
                                "id": did,
                                "text": doc_text,
                                "cand": cand
                            })
                        from flashrank import RerankRequest
                        rerank_req = RerankRequest(query=query.strip(), passages=passages)
                        rerank_results = ranker.rerank(rerank_req)

                        matched = []
                        for r in rerank_results[:top_k]:
                            did = r["id"]
                            doc_text, meta = doc_lookup[did]
                            cand = r["cand"]
                            matched.append({
                                "module": meta.get("module_name", "General"),
                                "section": meta.get("section_title", ""),
                                "description": meta.get("description", ""),
                                "text": doc_text,
                                "similarity": cand["similarity"],
                                "category_id": meta.get("category_id"),
                                "rrf_score": round(cand["rrf"], 5),
                                "bm25_score": round(cand["bm25_score"], 2),
                                "rerank_score": round(float(r["score"]), 5)
                            })
                        return matched
                    except Exception as rerank_err:
                        logger.warning(f"FlashRank reranking error, falling back to RRF: {rerank_err}")

                # Fallback to RRF ranked selection
                matched = []
                for cand in scored_candidates[:top_k]:
                    did = cand["id"]
                    doc_text, meta = doc_lookup[did]
                    matched.append({
                        "module": meta.get("module_name", "General"),
                        "section": meta.get("section_title", ""),
                        "description": meta.get("description", ""),
                        "text": doc_text,
                        "similarity": cand["similarity"],
                        "category_id": meta.get("category_id"),
                        "rrf_score": round(cand["rrf"], 5),
                        "bm25_score": round(cand["bm25_score"], 2)
                    })

                return matched

            except Exception as e:
                logger.error(f"❌ Error during hybrid documentation search: {e}")
                return []

    def test_health(self) -> dict[str, Any]:
        """Returns the health status and chunk count of the ChromaDB RAG vector store."""
        with self._lock:
            try:
                if not self._ensure_chroma():
                    return {
                        "status": "error",
                        "initialized": False,
                        "error": "Failed to initialize ChromaDB client"
                    }
                count = self.collection.count()
                meta = {}
                if os.path.exists(META_FILE_PATH):
                    try:
                        with open(META_FILE_PATH, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                    except Exception:
                        pass

                return {
                    "status": "healthy" if count > 0 else "uninitialized",
                    "initialized": True,
                    "collection": COLLECTION_NAME,
                    "total_chunks": count,
                    "categories_count": meta.get("categories_count", 0)
                }
            except Exception as e:
                logger.error(f"RAG health check error: {e}")
                return {
                    "status": "error",
                    "initialized": False,
                    "error": str(e)
                }

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
