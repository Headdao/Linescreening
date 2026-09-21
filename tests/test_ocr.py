"""OCR adapter tests — coordinate math only (no Vision, no capture)."""

from __future__ import annotations

from Foundation import NSMakeRect

from linescreening.ocr import _convert


class _Cand:
    def __init__(self, text: str, conf: float = 0.9) -> None:
        self._t, self._c = text, conf

    def confidence(self) -> float:
        return self._c

    def string(self) -> str:
        return self._t


class _Obs:
    def __init__(self, rect, text: str, conf: float = 0.9) -> None:
        self._r, self._c = rect, _Cand(text, conf)

    def boundingBox(self):  # noqa: ANN202 — Vision bridge shape
        return self._r

    def topCandidates_(self, n: int) -> list:  # noqa: ARG002, ANN202
        return [self._c]


def test_convert_normalizes_retina_pixel_scale():
    # captured image is 1200x800 (2x retina); observation at normalized
    # bottom-left rect (0.5, 0.5, 0.1, 0.05)
    obs = _Obs(NSMakeRect(0.5, 0.5, 0.1, 0.05), "媽媽")
    out = _convert([obs], 1200, 800, 0.3, pixel_scale=2.0)
    assert len(out) == 1
    o = out[0]
    assert o.text == "媽媽"
    assert o.x == 300.0  # 0.5 * 1200 / 2
    assert o.w == 60.0  # 0.1 * 1200 / 2
    assert o.y == 180.0  # (1 - 0.5 - 0.05) * 800 / 2
    assert o.h == 20.0


def test_convert_defaults_to_identity_scale_and_filters_low_confidence():
    obs_ok = _Obs(NSMakeRect(0.0, 0.9, 0.2, 0.1), "修好了", conf=0.8)
    obs_low = _Obs(NSMakeRect(0.0, 0.5, 0.2, 0.1), "雜訊", conf=0.1)
    out = _convert([obs_ok, obs_low], 600, 400, 0.3)
    assert [o.text for o in out] == ["修好了"]
    assert out[0].x == 0.0 and out[0].y == 0.0  # top-left origin flip
