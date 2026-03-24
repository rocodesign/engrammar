"""Tests for extraction benchmark matching."""

import importlib.util
from pathlib import Path

import numpy as np


def load_eval_module():
    """Load benchmark/eval_extraction_quality.py as a test module."""
    module_path = (
        Path(__file__).resolve().parents[1]
        / "benchmark"
        / "eval_extraction_quality.py"
    )
    spec = importlib.util.spec_from_file_location(
        "benchmark_eval_extraction_quality",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_find_best_match_uses_fastembed_backend():
    mod = load_eval_module()
    vectors = {
        "labeled": np.array([1.0, 0.0], dtype=np.float32),
        "good paraphrase": np.array([0.97, 0.03], dtype=np.float32),
        "different": np.array([0.0, 1.0], dtype=np.float32),
    }

    def fake_embed_batch(texts):
        return np.array([vectors[text] for text in texts], dtype=np.float32)

    matcher = mod.SimilarityMatcher(
        backend="fastembed",
        embed_batch_fn=fake_embed_batch,
    )
    score, text = mod.find_best_match(
        "labeled",
        [{"engram": "different"}, {"engram": "good paraphrase"}],
        matcher,
    )

    assert matcher.backend == "fastembed"
    assert text == "good paraphrase"
    assert score > 0.99


def test_evaluate_match_returns_borderline_without_judge():
    mod = load_eval_module()
    vectors = {
        "labeled": np.array([1.0, 0.0], dtype=np.float32),
        "candidate": np.array([0.78, 0.625], dtype=np.float32),
    }

    def fake_embed_batch(texts):
        return np.array([vectors[text] for text in texts], dtype=np.float32)

    matcher = mod.SimilarityMatcher(
        backend="fastembed",
        embed_batch_fn=fake_embed_batch,
    )
    result = mod.evaluate_match(
        "labeled",
        [{"engram": "candidate"}],
        matcher,
        threshold=0.82,
        borderline_threshold=0.72,
    )

    assert result.outcome == "borderline"
    assert result.candidate_text == "candidate"


def test_evaluate_match_uses_judge_for_borderline_pair(monkeypatch):
    mod = load_eval_module()
    vectors = {
        "labeled": np.array([1.0, 0.0], dtype=np.float32),
        "candidate": np.array([0.78, 0.625], dtype=np.float32),
    }

    def fake_embed_batch(texts):
        return np.array([vectors[text] for text in texts], dtype=np.float32)

    matcher = mod.SimilarityMatcher(
        backend="fastembed",
        embed_batch_fn=fake_embed_batch,
    )
    monkeypatch.setattr(
        mod,
        "judge_same_learning",
        lambda labeled, candidate, model: mod.JudgeResult(
            same_learning=True,
            confidence=0.91,
            reason="same advice, different wording",
        ),
    )

    result = mod.evaluate_match(
        "labeled",
        [{"engram": "candidate"}],
        matcher,
        threshold=0.82,
        borderline_threshold=0.72,
        judge_model="sonnet",
    )

    assert result.outcome == "judge_match"
    assert result.judge_result.confidence == 0.91


def test_parse_json_object_extracts_payload_from_fenced_text():
    mod = load_eval_module()
    parsed = mod.parse_json_object(
        """```json
{"same_learning": true, "confidence": 0.8, "reason": "same idea"}
```"""
    )

    assert parsed == {
        "same_learning": True,
        "confidence": 0.8,
        "reason": "same idea",
    }
