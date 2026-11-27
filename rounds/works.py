from dataclasses import dataclass

from festival import BusinessError, array, object_fields, required_text


@dataclass(frozen=True)
class RoundWork:
    work_id: str
    group: str
    proof_id: str

    def as_json(self):
        return {'work_id': self.work_id, 'group': self.group, 'proof_id': self.proof_id}


def parse_round_works(value):
    works = []
    seen = set()
    for item in array(value, 'works'):
        object_fields(item, 'work_id', 'group', 'proof_id')
        work_id = required_text(item['work_id'], 'work_id')
        if work_id in seen:
            raise BusinessError(422, 'duplicate_work', work_id=work_id)
        seen.add(work_id)
        works.append(RoundWork(work_id, required_text(item['group'], 'group'), required_text(item['proof_id'], 'proof_id')))
    if not works:
        raise BusinessError(422, 'empty_works')
    return ordered_round_works(works)


def ordered_round_works(works):
    return tuple(sorted(works, key=lambda work: work.work_id))
