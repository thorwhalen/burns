"""Tests for the named-move vocabulary and `resolve_move`.

Pure geometry over synthetic numpy images, plus one render smoke test — offline,
free, deterministic. The headline guard is
`TestPositionIndependence`: it asserts the thing the vocabulary exists for, and
carries its own negative control, because a version of this test that passed
with the ordinal defect fully present would be worth nothing.
"""

import json

import numpy as np
import pytest

from burns import (
    MOVES,
    AUTO_WEIGHTS,
    BurnsPath,
    MoveError,
    Rect,
    choose_move,
    content_aware_path_for,
    ken_burns_video,
    move_kind,
    resolve_move,
)
from burns.moves import _AUTO_POOL, _MOVES, DRIFT_SPAN

A = 16 / 9


def image(seed: int = 0, *, w: int = 800, h: int = 600) -> np.ndarray:
    """A deterministic still with an off-centre textured block to frame on."""
    rng = np.random.default_rng(seed)
    img = np.zeros((h, w, 3), dtype="uint8")
    y0 = int(h * 0.45) + (seed % 3) * 10
    x0 = int(w * 0.55) + (seed % 5) * 10
    img[y0 : y0 + h // 5, x0 : x0 + w // 5] = rng.integers(
        150, 255, (h // 5, w // 5, 3), dtype="uint8"
    )
    return img


def travel(path: BurnsPath, axis: str) -> float:
    """Signed distance the window travels on ``axis``, in image units."""
    r0, r1 = path.evaluate(0.0), path.evaluate(1.0)
    return (r1.x - r0.x) if axis == "x" else (r1.y - r0.y)


class TestVocabulary:
    def test_every_name_resolves_without_raising(self):
        img = image()
        for name in MOVES:
            path = resolve_move(name, image=img, aspect=A, seed=7)
            assert isinstance(path, BurnsPath)
            assert path.evaluate(0.0).is_contained()
            assert path.evaluate(1.0).is_contained()

    def test_the_vocabulary_is_one_table(self):
        """MOVES is read off the dispatch table, so the two cannot disagree."""
        assert set(MOVES) == set(_MOVES)

    def test_every_concrete_move_has_a_builder(self):
        for name, spec in _MOVES.items():
            assert (spec.build is None) == (spec.kind == "select"), name

    def test_auto_weights_only_name_concrete_moves(self):
        """An 'auto' entry would recurse; a stray name would resolve to a refusal."""
        assert set(AUTO_WEIGHTS) <= set(MOVES) - {"auto"}
        assert all(m in MOVES and m != "auto" for m in _AUTO_POOL)

    def test_move_kind_covers_the_vocabulary(self):
        assert {move_kind(m) for m in MOVES} == {"zoom", "drift", "static", "select"}

    def test_an_unknown_move_names_the_vocabulary_and_the_escape_hatch(self):
        with pytest.raises(MoveError) as e:
            resolve_move("swoop", image=image(), aspect=A)
        assert "swoop" in str(e.value) and "push_in" in str(e.value)
        assert "BurnsPath" in str(e.value)


class TestDeterminism:
    def test_same_move_seed_and_image_gives_the_same_path(self):
        img = image(3)
        for name in MOVES:
            a = resolve_move(name, image=img, aspect=A, seed=11)
            b = resolve_move(name, image=img, aspect=A, seed=11)
            assert a == b, name

    def test_a_different_seed_gives_a_different_auto_path(self):
        """The seed's one job — and it must actually reach the geometry."""
        img = image(4)
        paths = {resolve_move("auto", image=img, aspect=A, seed=s) for s in range(24)}
        assert len(paths) > 1
        assert len({choose_move(s) for s in range(24)}) > 1

    def test_the_seed_does_not_touch_a_named_move(self):
        """A named move is a decision. A decision a seed can nudge is not one."""
        img = image(5)
        for name in [m for m in MOVES if m != "auto"]:
            assert resolve_move(name, image=img, aspect=A, seed=0) == resolve_move(
                name, image=img, aspect=A, seed=987654321
            ), name

    def test_choose_move_is_stable_arithmetic_not_a_salted_hash(self):
        """A persisted seed must resolve to the same move in the next process."""
        import subprocess
        import sys

        code = "import burns;print(','.join(burns.choose_move(s) for s in range(12)))"
        here = ",".join(choose_move(s) for s in range(12))
        for _ in range(2):  # PYTHONHASHSEED differs per process by default
            out = subprocess.run(
                [sys.executable, "-c", code], capture_output=True, text=True, check=True
            )
            assert out.stdout.strip() == here


class TestPositionIndependence:
    """The defect the vocabulary exists to remove.

    The picture track used to derive its motion from each panel's ordinal, so
    reordering one panel changed the camera on every panel after it.
    """

    def track(self):
        """Three panels, each carrying its own stable seed."""
        return [
            {"image": image(1), "move": "auto", "seed": 101},
            {"image": image(2), "move": "auto", "seed": 202},
            {"image": image(3), "move": "auto", "seed": 303},
        ]

    def test_reordering_the_callers_list_changes_nothing(self):
        track = self.track()
        before = {
            p["seed"]: resolve_move(
                p["move"], image=p["image"], aspect=A, seed=p["seed"]
            )
            for p in track
        }
        reordered = [track[2], track[0], track[1]]
        after = {
            p["seed"]: resolve_move(
                p["move"], image=p["image"], aspect=A, seed=p["seed"]
            )
            for p in reordered
        }
        assert before == after

    def test_the_ordinal_approach_fails_that_same_check(self):
        """The negative control.

        Without this, `test_reordering_the_callers_list_changes_nothing` would
        pass just as happily against the code it replaced, and would be proving
        nothing. `content_aware_path_for(index=i)` is what braidio called; its
        parity rule is exactly what a reorder flips.
        """
        track = self.track()
        before = [
            content_aware_path_for(p["image"], index=i, output_aspect=A)
            for i, p in enumerate(track)
        ]
        reordered = [track[2], track[0], track[1]]
        after_by_still = {
            id(p["image"]): content_aware_path_for(p["image"], index=i, output_aspect=A)
            for i, p in enumerate(reordered)
        }
        changed = [
            p
            for i, p in enumerate(track)
            if after_by_still[id(p["image"])] != before[i]
        ]
        assert changed, "the ordinal path was expected to be reorder-sensitive"

    def test_keeping_the_move_while_changing_the_picture(self):
        """The first thing the owner asked for: same intent, new still, new framing."""
        seed, move = 77, "push_in"
        a = resolve_move(move, image=image(1), aspect=A, seed=seed)
        b = resolve_move(move, image=image(9, w=1200, h=400), aspect=A, seed=seed)
        assert a != b  # re-framed against the new picture
        assert a.evaluate(1.0).zoom >= a.evaluate(0.0).zoom  # still a push
        assert b.evaluate(1.0).zoom >= b.evaluate(0.0).zoom


class TestFocus:
    def test_an_explicit_focus_overrides_the_saliency_box(self):
        """The still's salient block is bottom-right; the focus is top-left."""
        img = image(0)
        saliency = resolve_move("push_in", image=img, aspect=A)
        focused = resolve_move(
            "push_in", image=img, aspect=A, focus=(0.02, 0.02, 0.15, 0.15)
        )
        assert saliency != focused
        sx, sy = saliency.evaluate(1.0).center
        fx, fy = focused.evaluate(1.0).center
        assert fx < sx and fy < sy

    def test_saliency_is_not_even_computed_when_focus_is_given(self, monkeypatch):
        """A total override, not a computed-then-discarded one.

        Computing the estimate anyway is how a partial override quietly lets
        saliency back in on some path later.
        """
        import burns.moves

        monkeypatch.setattr(
            burns.moves,
            "salient_box",
            lambda *a, **k: pytest.fail("salient_box ran despite an explicit focus"),
        )
        resolve_move("push_in", image=image(), aspect=A, focus=Rect(0.3, 0.3, 0.2, 0.2))

    @pytest.mark.parametrize(
        "focus",
        [
            Rect(0.3, 0.3, 0.2, 0.2),
            (0.3, 0.3, 0.2, 0.2),
            [0.3, 0.3, 0.2, 0.2],
        ],
    )
    def test_focus_accepts_any_structural_rect(self, focus):
        """burns does not make a consumer import its rectangle type to say 'here'."""
        expected = resolve_move(
            "push_in", image=image(), aspect=A, focus=Rect(0.3, 0.3, 0.2, 0.2)
        )
        assert resolve_move("push_in", image=image(), aspect=A, focus=focus) == expected

    def test_focus_accepts_a_duck_typed_rect(self):
        class PanelFocus:  # what a pydantic body looks like from here
            x, y, w, h = 0.3, 0.3, 0.2, 0.2

        expected = resolve_move(
            "push_in", image=image(), aspect=A, focus=(0.3, 0.3, 0.2, 0.2)
        )
        assert (
            resolve_move("push_in", image=image(), aspect=A, focus=PanelFocus())
            == expected
        )

    @pytest.mark.parametrize(
        "bad, hint",
        [
            ((120, 80, 400, 300), "pixels"),  # the usual mistake
            ((0.1, 0.1, 0.0, 0.2), "positive"),
            ((0.1, 0.1, 0.2), "4 components"),
            ("nope", "4 components"),
            (object(), "4 components"),
        ],
    )
    def test_a_malformed_focus_says_what_is_wrong(self, bad, hint):
        with pytest.raises(MoveError) as e:
            resolve_move("push_in", image=image(), aspect=A, focus=bad)
        assert hint in str(e.value)

    def test_focus_accepts_a_mapping(self):
        """What a stored focus looks like after a JSON round-trip."""
        expected = resolve_move(
            "push_in", image=image(), aspect=A, focus=(0.3, 0.3, 0.2, 0.2)
        )
        got = resolve_move(
            "push_in",
            image=image(),
            aspect=A,
            focus={"x": 0.3, "y": 0.3, "w": 0.2, "h": 0.2},
        )
        assert got == expected

    def test_an_incomplete_focus_mapping_names_the_missing_keys(self):
        with pytest.raises(MoveError) as e:
            resolve_move("push_in", image=image(), aspect=A, focus={"x": 0.3, "y": 0.3})
        assert "'w'" in str(e.value) and "'h'" in str(e.value)

    def test_focus_none_is_no_focus_not_a_malformed_one(self):
        """The default. It must fall through to saliency, never refuse."""
        assert resolve_move(
            "push_in", image=image(), aspect=A, focus=None
        ) == resolve_move("push_in", image=image(), aspect=A)


class TestDrift:
    @pytest.mark.parametrize(
        "move, axis, sign",
        [
            ("drift_left", "x", -1),
            ("drift_right", "x", +1),
            ("drift_up", "y", -1),
            ("drift_down", "y", +1),
        ],
    )
    def test_the_name_is_the_direction_the_camera_travels(self, move, axis, sign):
        d = travel(resolve_move(move, image=image(), aspect=A), axis)
        assert d * sign > 0, f"{move} travelled {d:+.4f} on {axis}"

    def test_opposite_drifts_are_mirror_images(self):
        img = image(2)
        left = resolve_move("drift_left", image=img, aspect=A)
        right = resolve_move("drift_right", image=img, aspect=A)
        assert left.evaluate(0.0) == right.evaluate(1.0)
        assert left.evaluate(1.0) == right.evaluate(0.0)

    def test_a_drift_always_actually_travels(self):
        """A drift that silently becomes a hold is the failure DRIFT_MIN_ROOM prevents."""
        for zoom in (1.0, 1.01, 1.18, 1.6):
            for move, axis in (("drift_right", "x"), ("drift_down", "y")):
                d = travel(resolve_move(move, image=image(), aspect=A, zoom=zoom), axis)
                assert abs(d) > 1e-6, f"{move} at zoom={zoom} did not move"

    def test_both_axes_drift_at_the_same_speed_on_screen(self):
        """Regression: the travel was whatever room the picture's aspect left.

        A 4:3 still delivered at 16:9 has ~2x the vertical room, so an
        uncapped vertical drift crossed ~29% of the frame where a horizontal
        one crossed ~9% — one named gesture at three different speeds,
        decided by the picture.
        """
        img = image()
        fractions = {}
        for move, axis in (
            ("drift_right", "x"),
            ("drift_down", "y"),
        ):
            path = resolve_move(move, image=img, aspect=A)
            window = path.evaluate(0.0)
            size = window.w if axis == "x" else window.h
            fractions[move] = abs(travel(path, axis)) / size
        assert all(f <= DRIFT_SPAN + 1e-9 for f in fractions.values()), fractions
        assert max(fractions.values()) / min(fractions.values()) < 1.5, fractions

    def test_a_drift_near_an_edge_keeps_its_full_travel(self):
        """The travel interval slides inside the image; it is never shrunk.

        Clamping the two ends independently collapses the move to a hold
        whenever the subject sits near a wall.
        """
        img = image()
        centred = abs(
            travel(
                resolve_move(
                    "drift_right", image=img, aspect=A, focus=(0.4, 0.4, 0.2, 0.2)
                ),
                "x",
            )
        )
        cornered = abs(
            travel(
                resolve_move(
                    "drift_right", image=img, aspect=A, focus=(0.0, 0.0, 0.12, 0.12)
                ),
                "x",
            )
        )
        assert cornered == pytest.approx(centred, rel=1e-6)


class TestHold:
    def test_a_hold_does_not_move(self):
        path = resolve_move("hold", image=image(), aspect=A)
        assert path.evaluate(0.0) == path.evaluate(1.0)

    def test_a_hold_is_two_keyframes_so_it_is_valid_on_the_wire(self):
        """The TS schema requires minItems 2; nothing here may emit one."""
        for name in MOVES:
            path = resolve_move(name, image=image(), aspect=A, seed=13)
            assert len(path.keyframes) >= 2, name

    def test_a_hold_honours_zoom(self):
        img = image()
        wide = resolve_move("hold", image=img, aspect=A, zoom=1.0)
        tight = resolve_move("hold", image=img, aspect=A, zoom=1.35)
        assert tight.evaluate(0.0).zoom > wide.evaluate(0.0).zoom


class TestExplicitPath:
    def hand_authored(self, aspect=A):
        return BurnsPath.from_start_end(
            Rect(0.0, 0.0, 1.0, 1.0),
            Rect(0.1, 0.1, 0.6, 0.6),
            output_aspect=aspect,
        )

    def test_a_burnspath_is_returned_as_authored(self):
        path = self.hand_authored()
        assert resolve_move(path, image=image(), aspect=A) == path

    def test_a_to_dict_payload_is_the_same_front_door(self):
        path = self.hand_authored()
        assert resolve_move(path.to_dict(), image=image(), aspect=A) == path

    def test_an_override_ignores_the_named_moves_knobs(self):
        """Its rectangles are already resolved; zoom/focus/seed have nothing to do."""
        path = self.hand_authored()
        assert (
            resolve_move(
                path, image=image(), aspect=A, zoom=3.0, focus=(0, 0, 0.1, 0.1), seed=9
            )
            == path
        )

    def test_an_aspect_agnostic_override_is_preserved(self):
        """`output_aspect=None` says 'match the image' — a choice, not a mismatch."""
        path = self.hand_authored(aspect=None)
        assert resolve_move(path, image=image(), aspect=A) == path

    def test_an_override_authored_for_another_delivery_raises(self):
        """Silently cover-cropping somebody's hand-drawn framing is the defect class."""
        path = self.hand_authored(aspect=16 / 9)
        with pytest.raises(MoveError) as e:
            resolve_move(path, image=image(), aspect=9 / 16)
        assert "authored" in str(e.value) and "1.77" in str(e.value)

    def test_a_mapping_that_is_not_a_path_payload_says_so(self):
        """A mapping in `move` is read as a path; a malformed one must not
        surface as a KeyError from three frames down."""
        with pytest.raises(MoveError) as e:
            resolve_move({"move": "push_in"}, image=image(), aspect=A)
        assert "to_dict()" in str(e.value) and "push_in" in str(e.value)

    def test_an_override_survives_float_noise_in_the_aspect(self):
        path = self.hand_authored(aspect=1920 / 1080)
        assert resolve_move(path, image=image(), aspect=16 / 9) == path


class TestSerialization:
    def test_a_resolved_path_round_trips_through_json(self):
        """What the consumer stores when it freezes a resolved move.

        `dataclasses.asdict` emits the live `_ease` closure and raises on
        `json.dumps`; `to_dict` is the wire format.
        """
        for name in MOVES:
            path = resolve_move(name, image=image(), aspect=A, seed=23)
            payload = json.loads(json.dumps(path.to_dict()))
            assert BurnsPath.from_dict(payload) == path, name

    def test_asdict_is_the_trap_to_dict_avoids(self):
        import dataclasses

        path = resolve_move("push_in", image=image(), aspect=A)
        with pytest.raises(TypeError):
            json.dumps(dataclasses.asdict(path))

    def test_a_callable_easing_refuses_to_serialize(self):
        path = resolve_move("push_in", image=image(), aspect=A, easing=lambda t: t)
        with pytest.raises(ValueError):
            path.to_dict()


class TestAspect:
    def test_the_window_carries_the_delivery_aspect(self):
        """So the renderer's cover-crop is a no-op and what you frame is what shows."""
        iw, ih = 800, 600
        for name in [m for m in MOVES if m != "auto"]:
            path = resolve_move(name, image=image(w=iw, h=ih), aspect=A, seed=1)
            r = path.evaluate(0.0)
            assert (r.w * iw) / (r.h * ih) == pytest.approx(A, rel=0.02), name
            assert path.output_aspect == A

    def test_aspect_none_means_match_the_image(self):
        iw, ih = 800, 600
        path = resolve_move("hold", image=image(w=iw, h=ih), aspect=None, zoom=1.0)
        r = path.evaluate(0.0)
        assert (r.w, r.h) == (1.0, 1.0)
        assert path.output_aspect is None

    def test_a_portrait_still_delivers_at_the_asked_aspect(self):
        iw, ih = 1080, 1920
        for name in ("push_in", "drift_up", "hold"):
            r = resolve_move(name, image=image(w=iw, h=ih), aspect=A).evaluate(0.0)
            assert (r.w * iw) / (r.h * ih) == pytest.approx(A, rel=0.02), name


class TestRenders:
    def test_a_resolved_move_actually_drives_the_renderer(self, tmp_path):
        """The primary artifact: pixels, not numbers.

        Compared on DECODED frames — a first frame identical to the last is a
        silent hold, which is what every geometric guard here exists to catch
        and what only a render can confirm did not happen.
        """
        from moviepy import VideoFileClip

        src = tmp_path / "still.png"
        from PIL import Image as PIL_Image

        PIL_Image.fromarray(image(w=320, h=240)).save(src)
        out = ken_burns_video(
            src,
            resolve_move("drift_right", image=src, aspect=A),
            duration=1.0,
            fps=24,
            saveas=tmp_path / "drift.mp4",
        )
        assert out.exists()
        with VideoFileClip(str(out)) as clip:
            first = np.asarray(clip.get_frame(0.0), dtype="int16")
            last = np.asarray(clip.get_frame(0.9), dtype="int16")
        assert np.abs(first - last).mean() > 1.0
