from dataclasses import dataclass

from rounds.roster import RosterSnapshot


@dataclass(frozen=True, order=True)
class ReviewRelation:
    work_id: str
    reviewer_id: str


def compute_eligibility(roster: RosterSnapshot):
    return frozenset(
        ReviewRelation(work.work_id, reviewer.reviewer_id)
        for work in roster.works
        for reviewer in roster.reviewers
        if work.group != reviewer.group
    )
