import pytest
from eval.question_gen import band


def test_classify_n8():
    assert band.classify(0, n=8) == band.Tag(label="too_hard", in_rl=False, prime=False)
    assert band.classify(8, n=8) == band.Tag(label="too_easy", in_rl=False, prime=False)
    assert band.classify(1, n=8) == band.Tag(label="rl_band", in_rl=True, prime=False)
    assert band.classify(7, n=8) == band.Tag(label="rl_band", in_rl=True, prime=False)
    for k in (3, 4, 5):
        assert band.classify(k, n=8) == band.Tag(label="rl_band", in_rl=True, prime=True)


def test_classify_validates():
    with pytest.raises(ValueError):
        band.classify(9, n=8)
