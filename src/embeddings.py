"""FastEmbed wrapper + numpy vector index."""

import os

import numpy as np

from .config import INDEX_PATH, IDS_PATH, TAG_INDEX_PATH, TAG_IDS_PATH

_model = None


def get_model():
    """Lazy-load FastEmbed model (cached after first call)."""
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    return _model


def embed_text(text):
    """Embed a single text string, return numpy array."""
    model = get_model()
    embeddings = list(model.embed([text]))
    return np.array(embeddings[0], dtype=np.float32)


def embed_batch(texts):
    """Embed multiple texts, return numpy array of shape (n, dim)."""
    if not texts:
        return np.array([], dtype=np.float32)
    model = get_model()
    embeddings = list(model.embed(texts))
    return np.array(embeddings, dtype=np.float32)


def build_index(engrams, index_path=None, ids_path=None):
    """Embed all engrams and save to .npy files.

    Args:
        engrams: list of dicts with 'id' and 'text' keys
        index_path: path for embeddings .npy file
        ids_path: path for engram IDs .npy file
    """
    idx_path = index_path or INDEX_PATH
    id_path = ids_path or IDS_PATH

    if not engrams:
        # Save empty arrays
        np.save(idx_path, np.array([], dtype=np.float32).reshape(0, 0))
        np.save(id_path, np.array([], dtype=np.int64))
        return 0

    texts = [l["text"] for l in engrams]
    ids = [l["id"] for l in engrams]

    embeddings = embed_batch(texts)
    np.save(idx_path, embeddings)
    np.save(id_path, np.array(ids, dtype=np.int64))

    return len(engrams)


def build_tag_index(engrams, index_path=None, ids_path=None):
    """Embed engram prerequisite tags and save to .npy files.

    Only engrams with non-empty prerequisite tags are included.

    Args:
        engrams: list of dicts with 'id' and 'prerequisites' keys
        index_path: path for tag embeddings .npy file
        ids_path: path for engram IDs .npy file

    Returns:
        number of engrams with tag embeddings
    """
    import json

    idx_path = index_path or TAG_INDEX_PATH
    id_path = ids_path or TAG_IDS_PATH

    # Collect engrams that have prerequisite tags
    tag_texts = []
    tag_ids = []
    for engram in engrams:
        prereqs = engram.get("prerequisites")
        if not prereqs:
            continue
        prereq_dict = json.loads(prereqs) if isinstance(prereqs, str) else prereqs
        tags = prereq_dict.get("tags", [])
        if tags:
            tag_texts.append(" ".join(tags))
            tag_ids.append(engram["id"])

    if not tag_texts:
        np.save(idx_path, np.array([], dtype=np.float32).reshape(0, 0))
        np.save(id_path, np.array([], dtype=np.int64))
        return 0

    embeddings = embed_batch(tag_texts)
    np.save(idx_path, embeddings)
    np.save(id_path, np.array(tag_ids, dtype=np.int64))

    return len(tag_ids)


def load_tag_index(index_path=None, ids_path=None):
    """Load precomputed tag embeddings.

    Returns:
        (embeddings, ids) tuple or (None, None) if files don't exist
    """
    idx_path = index_path or TAG_INDEX_PATH
    id_path = ids_path or TAG_IDS_PATH

    if not os.path.exists(idx_path) or not os.path.exists(id_path):
        return None, None

    embeddings = np.load(idx_path, mmap_mode="r")
    ids = np.load(id_path, mmap_mode="r")

    if embeddings.size == 0:
        return None, None

    return embeddings, ids


def load_index(index_path=None, ids_path=None):
    """Load memory-mapped .npy files for zero-copy access.

    Returns:
        (embeddings, ids) tuple or (None, None) if files don't exist
    """
    idx_path = index_path or INDEX_PATH
    id_path = ids_path or IDS_PATH

    if not os.path.exists(idx_path) or not os.path.exists(id_path):
        return None, None

    embeddings = np.load(idx_path, mmap_mode="r")
    ids = np.load(id_path, mmap_mode="r")

    if embeddings.size == 0:
        return None, None

    return embeddings, ids


def vector_search(query_embedding, embeddings, ids, top_k=5):
    """Cosine similarity search.

    Args:
        query_embedding: numpy array of shape (dim,)
        embeddings: numpy array of shape (n, dim)
        ids: numpy array of engram IDs
        top_k: number of results to return

    Returns:
        list of (engram_id, score) tuples sorted by score descending
    """
    if embeddings is None or embeddings.size == 0:
        return []

    # Normalize for cosine similarity
    query_norm = query_embedding / (np.linalg.norm(query_embedding) + 1e-10)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-10
    emb_norm = embeddings / norms

    scores = emb_norm @ query_norm
    top_indices = np.argsort(scores)[::-1][:top_k]

    return [(int(ids[i]), float(scores[i])) for i in top_indices]
