"""Extract content tags from user prompts via vector similarity against tag vocabulary."""

import math

import numpy as np

from engrammar.core.embeddings import embed_text, load_tag_vocab_index


# Tags that match too broadly — penalize their similarity score
_COMMON_TAG_PENALTY = 0.10


def detect_prompt_tags(query, top_k=3, threshold=0.60):
    """Match a user prompt against the content tag vocabulary.

    Embeds the query and compares via cosine similarity against the
    tag vocabulary index (one embedding per unique content tag).
    Applies IDF-based downweighting so high-frequency tags need
    stronger similarity to pass the threshold.

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

    # Load tag frequencies for IDF weighting
    tag_freqs = _load_tag_frequencies()
    total_engrams = max(sum(tag_freqs.values()) / max(len(tag_freqs), 1), 1)

    # Apply IDF-weighted scoring: penalize high-frequency tags
    # IDF is a soft tiebreaker, not a hard gate — scales 0.7-1.0
    max_freq = max(tag_freqs.values()) if tag_freqs else 1
    weighted_scores = []
    for i, (label, sim) in enumerate(zip(vocab_labels, similarities)):
        sim_f = float(sim)
        freq = tag_freqs.get(label, 1)
        # Soft IDF: linear scale from 0.7 (most common) to 1.0 (rare)
        freq_ratio = freq / max(max_freq, 1)
        idf_weight = 1.0 - 0.3 * freq_ratio  # range [0.7, 1.0]
        adjusted_sim = sim_f * idf_weight
        if adjusted_sim >= threshold:
            weighted_scores.append((i, label, adjusted_sim))

    if not weighted_scores:
        return []

    # Selectivity check: if too many tags pass threshold, query is vague — abstain
    # Allow more matches for longer queries (more semantic content → more legit matches)
    query_words = len(query.strip().split())
    selectivity_limit = min(0.30 + query_words * 0.03, 0.55)
    selectivity = len(weighted_scores) / max(len(vocab_labels), 1)
    if selectivity > selectivity_limit:
        return []

    # Sort by adjusted score
    weighted_scores.sort(key=lambda x: x[2], reverse=True)

    # Gap-based filtering: only keep tags significantly above the pack
    # This handles the high baseline (~0.55-0.65) of BGE embeddings
    if len(weighted_scores) >= 2:
        top_score = weighted_scores[0][2]
        # Compute median of all above-threshold scores
        median_score = weighted_scores[len(weighted_scores) // 2][2]
        gap = top_score - median_score
        # If the gap is too small, all scores are in the noise band — abstain
        min_gap = 0.03
        if gap < min_gap:
            return []
        # Only keep tags within 60% of the gap from the top
        cutoff = top_score - gap * 0.6
        weighted_scores = [(i, l, s) for i, l, s in weighted_scores if s >= cutoff]

    return [(label, score) for _, label, score in weighted_scores[:top_k]]


def _load_tag_frequencies():
    """Load tag → engram count from the database.

    Returns:
        dict mapping tag string to number of engrams it appears on
    """
    try:
        from engrammar.core.db import get_all_content_tags_vocab
        vocab = get_all_content_tags_vocab(min_frequency=1)
        return {tag: count for tag, count in vocab}
    except Exception:
        return {}
