from dataclasses import dataclass

from festival import BusinessError, array, object_fields, required_text
from scores.windows import BeatWindow, parse_beat_window


@dataclass(frozen=True)
class Segment:
    segment_id: str
    window: BeatWindow
    text: str

    def as_json(self):
        return {'segment_id': self.segment_id, 'window': self.window.as_json(), 'text': self.text}


def parse_segments(value):
    segments = []
    seen = set()
    for item in array(value, 'segments'):
        object_fields(item, 'segment_id', 'window', 'text')
        segment_id = required_text(item['segment_id'], 'segment_id')
        if segment_id in seen:
            raise BusinessError(422, 'duplicate_segment', segment_id=segment_id)
        seen.add(segment_id)
        segments.append(Segment(segment_id, parse_beat_window(item['window']), required_text(item['text'], 'text')))
    return tuple(segments)


def order_segments(segments):
    return tuple(sorted(segments, key=lambda segment: segment.window.start))
