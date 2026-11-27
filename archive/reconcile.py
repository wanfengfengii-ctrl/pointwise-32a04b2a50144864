from dataclasses import dataclass

from archive.intake import read_verified_receipts, record_verified_receipt, verify_receipt
from festival import atomic
from issue.readback import read_expected_relations


@dataclass(frozen=True)
class Reconciliation:
    release_id: str
    missing: tuple[tuple[str, str], ...]

    def as_json(self):
        return {'release_id': self.release_id, 'missing': missing_result(self.missing)}


def missing_result(missing):
    return [{'alias': alias, 'reviewer_id': reviewer_id} for alias, reviewer_id in missing]


def reconcile_receipt(connection, release_id, receipt):
    with atomic(connection):
        verified = verify_receipt(connection, release_id, receipt)
        record_verified_receipt(connection, verified)
        return Reconciliation(release_id, compute_missing_relations(connection, release_id))


def compute_missing_relations(connection, release_id):
    expected = read_expected_relations(connection, release_id=release_id)
    covered = {item.relation for item in read_verified_receipts(connection, release_id)}
    return tuple(sorted(expected - covered))
