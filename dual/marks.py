from dataclasses import dataclass

from festival import BusinessError, array, object_fields
from scores.windows import BeatWindow, parse_beat_window

PASS = 'pass'
REDO = 'redo'
MARKS = (PASS, REDO)


@dataclass(frozen=True, order=True)
class MarkedWindow:
    window: BeatWindow
    mark: str

    def as_json(self):
        return {'window': self.window.as_json(), 'mark': self.mark}


def parse_mark(value):
    if value not in MARKS:
        raise BusinessError(422, 'invalid_mark')
    return value


def parse_marked_windows(value):
    """Parse the non-overlapping half-open marked windows carried by a prelim page."""
    entries = []
    seen = set()
    for item in array(value, 'marks'):
        object_fields(item, 'window', 'mark')
        window = parse_beat_window(item['window'])
        mark = parse_mark(item['mark'])
        if window in seen:
            raise BusinessError(422, 'duplicate_mark_window')
        seen.add(window)
        entries.append(MarkedWindow(window, mark))
    entries.sort()
    for earlier, later in zip(entries, entries[1:]):
        if later.window.start < earlier.window.stop:
            raise BusinessError(422, 'overlapping_mark_windows')
    return tuple(entries)


def merge_windows(windows):
    """Merge overlapping or touching windows into a sorted tuple of disjoint windows."""
    merged = []
    for window in sorted(windows):
        if merged and window.start <= merged[-1].stop:
            if window.stop > merged[-1].stop:
                merged[-1] = BeatWindow(merged[-1].start, window.stop)
        else:
            merged.append(BeatWindow(window.start, window.stop))
    return tuple(merged)


@dataclass(frozen=True)
class MarkSource:
    mark: str
    window: BeatWindow

    def as_json(self):
        return {'mark': self.mark, 'window': self.window.as_json()}


@dataclass(frozen=True)
class Dispute:
    """A disagreement sub-window with the provenance of both original prelim pages."""
    window: BeatWindow
    first: MarkSource
    second: MarkSource

    def as_json(self):
        return {
            'window': self.window.as_json(),
            'sources': [self.first.as_json(), self.second.as_json()],
        }


def _split_on_boundaries(window, boundaries):
    start = window.start
    for boundary in sorted(boundaries):
        if window.start < boundary < window.stop:
            if start < boundary:
                yield BeatWindow(start, boundary)
            start = boundary
    if start < window.stop:
        yield BeatWindow(start, window.stop)


def compute_disputes(prelim_left, prelim_right):
    """Cut opposite-mark intersections into non-overlapping sub-windows.

    Unmarked beats never oppose anything: only beats carrying a mark on both
    prelim pages with different labels produce a dispute. Touching endpoints do
    not intersect, so identical boundaries never create a dispute.
    """
    boundaries = set()
    for entry in prelim_left:
        boundaries.update((entry.window.start, entry.window.stop))
    for entry in prelim_right:
        boundaries.update((entry.window.start, entry.window.stop))

    disputes = []
    for left in prelim_left:
        for right in prelim_right:
            if left.mark == right.mark:
                continue
            start = max(left.window.start, right.window.start)
            stop = min(left.window.stop, right.window.stop)
            if start >= stop:
                continue
            for piece in _split_on_boundaries(BeatWindow(start, stop), boundaries):
                disputes.append(Dispute(
                    piece,
                    MarkSource(left.mark, left.window),
                    MarkSource(right.mark, right.window),
                ))
    disputes.sort(key=lambda dispute: dispute.window)
    return tuple(disputes)


def dispute_windows(disputes):
    return tuple(sorted(dispute.window for dispute in disputes))


def remaining_dispute_windows(disputes, decided_windows):
    """Subtract decided coverage from each dispute window, keeping sub-windows.

    Distinct dispute sub-windows are kept separate even when they touch, so the
    adjudicator always answers along the original disagreement boundaries.
    """
    decided = merge_windows(decided_windows)
    remaining = []
    for dispute in disputes:
        cursor = dispute.window.start
        for window in decided:
            if window.stop <= cursor or window.start >= dispute.window.stop:
                continue
            overlap_start = max(cursor, window.start)
            if overlap_start > cursor:
                remaining.append(BeatWindow(cursor, overlap_start))
            cursor = max(cursor, min(dispute.window.stop, window.stop))
        if cursor < dispute.window.stop:
            remaining.append(BeatWindow(cursor, dispute.window.stop))
    return tuple(sorted(remaining))
