"""On-device OCR via Apple Vision (pyobjc). No network, no third-party deps.

Works on image file paths (dev/tests) and CGImage objects (live capture).
Output uses pixel coordinates with a top-left origin (Vision's normalized
bottom-left boxes are converted here, once, so downstream code never deals
with flipped axes).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from linescreening.cgimage import image_size


@dataclass(frozen=True)
class OcrText:
    text: str
    confidence: float
    x: float  # pixels, top-left origin
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


def recognize_image(
    path: Path | str,
    languages: list[str] | None = None,
    min_confidence: float = 0.5,
) -> list[OcrText]:
    """OCR an image file -> observations sorted top-to-bottom, left-to-right."""
    from Foundation import NSURL
    from Vision import VNImageRequestHandler, VNRecognizeTextRequest

    languages = languages or ["zh-Hant", "zh-Hans", "en-US"]
    url = NSURL.fileURLWithPath_(str(Path(path).expanduser()))
    handler = VNImageRequestHandler.alloc().initWithURL_options_(url, None)
    request = VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLanguages_(languages)
    request.setUsesLanguageCorrection_(True)

    ok, _error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError("Vision OCR request failed")

    img_w, img_h = _image_pixel_size(url)
    return _convert(request.results(), img_w, img_h, min_confidence)


def recognize_cgimage(
    cgimage: Any,
    languages: list[str] | None = None,
    min_confidence: float = 0.5,
    pixel_scale: float = 1.0,
) -> list[OcrText]:
    """OCR a live-captured CGImage -> observations (same contract).

    pixel_scale: captured px per logical px (retina native-res captures are
    2.0). Coordinates are NORMALIZED to logical pixels so the parse-layer
    geometry constants stay calibrated regardless of capture resolution."""
    from Vision import VNImageRequestHandler, VNRecognizeTextRequest

    languages = languages or ["zh-Hant", "zh-Hans", "en-US"]
    handler = VNImageRequestHandler.alloc().initWithCGImage_options_(cgimage, None)
    request = VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLanguages_(languages)
    request.setUsesLanguageCorrection_(True)

    ok, _error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError("Vision OCR request failed")

    img_w = int(image_size(cgimage)[0])
    img_h = int(image_size(cgimage)[1])
    return _convert(request.results(), img_w, img_h, min_confidence, pixel_scale)


# ---------------------------------------------------------------------------


def _convert(
    observations: Any,
    img_w: int,
    img_h: int,
    min_confidence: float,
    pixel_scale: float = 1.0,
) -> list[OcrText]:
    out: list[OcrText] = []
    for obs in observations or []:
        candidates = obs.topCandidates_(1)
        if not candidates:
            continue
        top = candidates[0]
        box = obs.boundingBox()  # normalized, origin bottom-left
        x = box.origin.x * img_w
        w = box.size.width * img_w
        h = box.size.height * img_h
        y = (1.0 - box.origin.y - box.size.height) * img_h  # flip to top-left
        if float(top.confidence()) < min_confidence:
            continue
        text = str(top.string()).strip()
        if text:
            out.append(
                OcrText(
                    text=text,
                    confidence=float(top.confidence()),
                    x=round(x / pixel_scale, 1),
                    y=round(y / pixel_scale, 1),
                    w=round(w / pixel_scale, 1),
                    h=round(h / pixel_scale, 1),
                )
            )
    out.sort(key=lambda o: (o.y, o.x))
    return out


def _image_pixel_size(url: Any) -> tuple[int, int]:
    import Quartz

    src = Quartz.CGImageSourceCreateWithURL(url, None)
    if src is None:
        raise RuntimeError("cannot open image source")
    props = Quartz.CGImageSourceCopyPropertiesAtIndex(src, 0, None)
    return int(props.get("PixelWidth", 0)), int(props.get("PixelHeight", 0))
