"""Tests for content-aware Ken Burns: salient_box + content_aware_path.

Pure geometry / numpy — no rendering. Mirrors the t -> Rect discipline of the
rest of the suite.
"""
import numpy as np
import pytest

from burns import content_aware_path, content_aware_path_for, salient_box


def _contains_center(rect, box):
    cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
    return rect.x <= cx <= rect.x + rect.w and rect.y <= cy <= rect.y + rect.h


class TestSalientBox:
    def test_tracks_the_bright_region_not_the_flat_field(self):
        a = np.zeros((100, 100), dtype="uint8")
        a[55:90, 35:65] = 255                       # a textured block low-left
        x, y, w, h = salient_box(a, min_size=0.0, pad=0.0)
        assert _contains_center(
            type("R", (), {"x": x, "y": y, "w": w, "h": h})(), (0.35, 0.55, 0.30, 0.35)
        )
        assert w < 0.9 and h < 0.9                  # not the whole frame

    def test_uniform_image_falls_back_to_center(self):
        a = np.full((80, 80), 128, dtype="uint8")
        x, y, w, h = salient_box(a)
        assert 0.0 <= x <= 0.3 and 0.4 <= (x + w) <= 1.0


class TestContentAwarePath:
    def test_deterministic(self):
        kw = dict(subject=(0.6, 0.55, 0.2, 0.25), index=1)
        assert content_aware_path(1600, 900, **kw) == content_aware_path(1600, 900, **kw)

    def test_index_parity_pushes_in_or_pulls_out(self):
        s = (0.5, 0.5, 0.3, 0.3)
        push = content_aware_path(1600, 900, subject=s, index=1)   # odd -> in
        pull = content_aware_path(1600, 900, subject=s, index=2)   # even -> out
        assert push.evaluate(1.0).zoom >= push.evaluate(0.0).zoom
        assert pull.evaluate(1.0).zoom <= pull.evaluate(0.0).zoom

    def test_mode_overrides_parity(self):
        s = (0.5, 0.5, 0.3, 0.3)
        assert content_aware_path(1600, 900, subject=s, index=2, mode="in") \
            .evaluate(1.0).zoom >= 1.0

    def test_keep_region_stays_framed_at_both_ends(self):
        subject = (0.7, 0.6, 0.18, 0.22)
        p = content_aware_path(1920, 1080, subject=subject, index=1, output_aspect=16 / 9)
        for t in (0.0, 0.5, 1.0):
            assert _contains_center(p.evaluate(t), subject)
            assert p.evaluate(t).is_contained()

    def test_faces_take_priority_over_subject(self):
        faces = [(0.1, 0.1, 0.1, 0.12), (0.2, 0.12, 0.1, 0.12)]
        p = content_aware_path(1600, 1200, subject=(0.8, 0.8, 0.1, 0.1), faces=faces, index=1)
        # centered on the faces' union, not the far-corner subject
        union_c = (0.2, 0.19)
        r = p.evaluate(1.0)
        assert r.x <= union_c[0] <= r.x + r.w and r.y <= union_c[1] <= r.y + r.h

    def test_window_matches_output_aspect(self):
        iw, ih, A = 1600, 1200, 16 / 9           # 4:3 image, 16:9 output
        p = content_aware_path(iw, ih, subject=(0.4, 0.4, 0.3, 0.3), index=1, output_aspect=A)
        r = p.evaluate(0.0)
        assert (r.w * iw) / (r.h * ih) == pytest.approx(A, rel=0.02)

    def test_no_subject_uses_centered_default(self):
        p = content_aware_path(1000, 1000, index=1)
        assert p.evaluate(0.0).is_contained() and p.evaluate(1.0).is_contained()


class TestContentAwarePathFor:
    def test_from_image_array_with_injected_faces(self):
        a = np.zeros((600, 800, 3), dtype="uint8"); a[300:500, 100:300] = 200
        called = {}

        def detector(img):
            called["yes"] = True
            return [(0.15, 0.5, 0.12, 0.15)]

        p = content_aware_path_for(a, faces_detector=detector, index=1)
        assert called.get("yes") and p.evaluate(1.0).is_contained()

    def test_saliency_only_when_no_detector(self):
        a = np.zeros((600, 800, 3), dtype="uint8"); a[350:520, 500:720] = 240
        p = content_aware_path_for(a, index=2)
        assert p.evaluate(0.0).is_contained()
