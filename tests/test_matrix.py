"""The validation matrix in docs/evidence must stay true: every automated case passes."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import validation_matrix as matrix  # noqa: E402


@pytest.mark.parametrize('case', matrix.CASES, ids=[c['id'] for c in matrix.CASES])
def test_matrix_case(case):
    actual, ok = case['run']()
    assert ok, f"{case['id']} {case['title']}: {actual}"
