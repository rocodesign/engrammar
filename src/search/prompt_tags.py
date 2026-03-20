"""Extract content tags from user prompts via vector similarity against tag vocabulary."""

import numpy as np

from engrammar.core.embeddings import embed_text, load_tag_vocab_index


def detect_prompt_tags(query, top_k=5, threshold=0.3):
    """Match a user prompt against the content tag vocabulary.

    Embeds the query and compares via cosine similarity against the
    tag vocabulary index (one embedding per unique content tag).

    Args:
        query: user prompt text
        top_k: max number of tags to return
        threshold: minimum cosine similarity for inclusion

    Returns:
        list of (tag, score) tuples sorted by score descending,
        or empty list if vocab index not built
    """
    if not query or len(query.strip()) < 3:
        return []

    vocab_embeddings, vocab_labels = load_tag_vocab_index()
    if vocab_embeddings is None or not vocab_labels:
        return []

    # Embed query
    query_emb = embed_text(query)
    query_norm = query_emb / (np.linalg.norm(query_emb) + 1e-10)

    # Cosine similarity against all vocab tags
    vocab_norms = np.linalg.norm(vocab_embeddings, axis=1, keepdims=True) + 1e-10
    vocab_normed = vocab_embeddings / vocab_norms
    similarities = vocab_normed @ query_norm

    # Filter by threshold and take top_k
    above_threshold = np.where(similarities >= threshold)[0]
    if len(above_threshold) == 0:
        return []

    sorted_indices = above_threshold[np.argsort(similarities[above_threshold])[::-1]][:top_k]
    return [(vocab_labels[i], float(similarities[i])) for i in sorted_indices]
