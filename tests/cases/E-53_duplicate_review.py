"""E-53: two accounts cannot publish near-identical reviews for the same business."""

from __future__ import annotations

from flows.warmup import ReviewGenerator, ngrams


def test_E53_5gram_overlap_is_capped():
    generator = ReviewGenerator()
    first, _ = generator.generate(business_id="biz-42", account_id="acc-a")
    second, _ = generator.generate(business_id="biz-42", account_id="acc-b")
    overlap = len(ngrams(first) & ngrams(second)) / max(len(ngrams(second)), 1)
    assert overlap <= 0.6


def test_E53_different_businesses_may_reuse_templates():
    generator = ReviewGenerator()
    generator.generate(business_id="biz-1", account_id="acc-a")
    text, _ = generator.generate(business_id="biz-2", account_id="acc-a")
    assert 80 <= len(text.split()) <= 200
