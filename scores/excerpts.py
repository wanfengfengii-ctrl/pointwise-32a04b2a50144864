from dataclasses import dataclass

from festival import BusinessError
from scores.segments import order_segments
from scores.windows import BeatWindow, intersect_windows


@dataclass(frozen=True)
class ExcerptSpan:
    revision_id: str
    segment_id: str
    window: BeatWindow
    text: str

    def anonymous(self):
        return {'segment_id': self.segment_id, 'window': self.window.as_json(), 'text': self.text}

    def with_source(self):
        return {'revision_id': self.revision_id, **self.anonymous()}


def build_excerpt(revision_id, segments, requested):
    spans = []
    for segment in order_segments(segments):
        window = intersect_windows(segment.window, requested)
        if window is not None:
            spans.append(ExcerptSpan(revision_id, segment.segment_id, window, segment.text))
    if not spans:
        raise BusinessError(422, 'empty_excerpt')
    return tuple(spans)
