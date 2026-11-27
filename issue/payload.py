from dataclasses import dataclass

from festival import BusinessError, array, object_fields, required_text
from scores.windows import BeatWindow, covers_window, parse_beat_window


@dataclass(frozen=True)
class IssuedSpan:
    segment_id: str
    window: BeatWindow
    text: str

    def as_json(self):
        return {'segment_id': self.segment_id, 'window': self.window.as_json(), 'text': self.text}


@dataclass(frozen=True)
class IssuedExcerpt:
    alias: str
    proof_id: str
    spans: tuple[IssuedSpan, ...]

    def covers_window(self, window):
        return covers_window(window, (span.window for span in self.spans))

    def as_json(self):
        return {'alias': self.alias, 'proof_id': self.proof_id, 'spans': [span.as_json() for span in self.spans]}


@dataclass(frozen=True)
class BundlePayload:
    release_id: str
    round_id: str
    works: tuple[IssuedExcerpt, ...]
    reviewers: tuple[str, ...]
    eligible: tuple[tuple[str, str], ...]
    dual_review: tuple[dict, ...] = ()

    def excerpt_for(self, alias):
        for excerpt in self.works:
            if excerpt.alias == alias:
                return excerpt
        raise BusinessError(404, 'alias_not_found')

    def dual_for_alias(self, alias):
        for entry in self.dual_review:
            if entry['alias'] == alias:
                return entry
        return None


def encode_bundle_payload(payload):
    result = {
        'release_id': payload.release_id,
        'round_id': payload.round_id,
        'works': [work.as_json() for work in payload.works],
        'reviewers': list(payload.reviewers),
        'eligible': [{'alias': alias, 'reviewer_id': reviewer_id} for alias, reviewer_id in payload.eligible],
    }
    if payload.dual_review:
        result['dual_review'] = [
            {
                'alias': entry['alias'],
                'prelim_reviewers': list(entry['prelim_reviewers']),
                'adjudicator': entry['adjudicator'],
            }
            for entry in payload.dual_review
        ]
    return result


def decode_bundle_payload(value):
    object_fields(value, 'release_id', 'round_id', 'works', 'reviewers', 'eligible', *_optional_dual(value))
    release_id = required_text(value['release_id'], 'release_id')
    round_id = required_text(value['round_id'], 'round_id')
    works = tuple(_decode_excerpt(item) for item in array(value['works'], 'works'))
    aliases = {work.alias for work in works}
    if not works or len(aliases) != len(works):
        raise BusinessError(422, 'invalid_bundle_works')
    reviewers = tuple(required_text(item, 'reviewer_id') for item in array(value['reviewers'], 'reviewers'))
    known_reviewers = set(reviewers)
    if len(known_reviewers) != len(reviewers):
        raise BusinessError(422, 'duplicate_reviewer')
    eligible = []
    seen = set()
    for item in array(value['eligible'], 'eligible'):
        object_fields(item, 'alias', 'reviewer_id')
        alias = required_text(item['alias'], 'alias')
        reviewer_id = required_text(item['reviewer_id'], 'reviewer_id')
        relation = (alias, reviewer_id)
        if alias not in aliases or reviewer_id not in known_reviewers or relation in seen:
            raise BusinessError(422, 'invalid_bundle_relation')
        seen.add(relation)
        eligible.append(relation)
    dual_review = tuple(_decode_dual(entry, aliases, known_reviewers) for entry in _optional_array(value, 'dual_review'))
    dual_aliases = [entry['alias'] for entry in dual_review]
    if len(dual_aliases) != len(set(dual_aliases)):
        raise BusinessError(422, 'duplicate_dual_work')
    return BundlePayload(
        release_id, round_id, works, reviewers, tuple(eligible), dual_review
    )


def _optional_dual(value):
    return ('dual_review',) if isinstance(value, dict) and 'dual_review' in value else ()


def _optional_array(value, field):
    if field not in value:
        return ()
    return array(value[field], field)


def _decode_dual(item, aliases, known_reviewers):
    object_fields(item, 'alias', 'prelim_reviewers', 'adjudicator')
    alias = required_text(item['alias'], 'alias')
    if alias not in aliases:
        raise BusinessError(422, 'invalid_dual_alias')
    prelim = tuple(required_text(part, 'prelim_reviewers') for part in array(item['prelim_reviewers'], 'prelim_reviewers'))
    adjudicator = required_text(item['adjudicator'], 'adjudicator')
    people = (*prelim, adjudicator)
    if len(prelim) != 2 or len(set(people)) != 3 or any(person not in known_reviewers for person in people):
        raise BusinessError(422, 'invalid_dual_reviewer')
    return {'alias': alias, 'prelim_reviewers': prelim, 'adjudicator': adjudicator}


def _decode_excerpt(value):
    object_fields(value, 'alias', 'proof_id', 'spans')
    alias = required_text(value['alias'], 'alias')
    proof_id = required_text(value['proof_id'], 'proof_id')
    spans = []
    seen = set()
    for item in array(value['spans'], 'spans'):
        object_fields(item, 'segment_id', 'window', 'text')
        segment_id = required_text(item['segment_id'], 'segment_id')
        window = parse_beat_window(item['window'])
        if segment_id in seen or (spans and window.start < spans[-1].window.start):
            raise BusinessError(422, 'invalid_excerpt_order')
        seen.add(segment_id)
        spans.append(IssuedSpan(segment_id, window, required_text(item['text'], 'text')))
    if not spans:
        raise BusinessError(422, 'empty_excerpt')
    return IssuedExcerpt(alias, proof_id, tuple(spans))
