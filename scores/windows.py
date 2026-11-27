from dataclasses import dataclass

from festival import BusinessError


@dataclass(frozen=True, order=True)
class BeatWindow:
    start: int
    stop: int

    def __post_init__(self):
        if type(self.start) is not int or type(self.stop) is not int or self.start >= self.stop:
            raise BusinessError(422, 'invalid_beat_window')

    def as_json(self):
        return [self.start, self.stop]


def parse_beat_window(value):
    if not isinstance(value, list) or len(value) != 2:
        raise BusinessError(422, 'invalid_beat_window')
    return BeatWindow(value[0], value[1])


def intersect_windows(left, right):
    start = max(left.start, right.start)
    stop = min(left.stop, right.stop)
    if start < stop:
        return BeatWindow(start, stop)
    return None


def covers_window(target, spans):
    covered_until = target.start
    for span in sorted(spans):
        if span.stop <= covered_until:
            continue
        if span.start > covered_until:
            return False
        covered_until = span.stop
        if covered_until >= target.stop:
            return True
    return False
