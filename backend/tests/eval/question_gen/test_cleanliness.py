from eval.question_gen import cleanliness


def _traj(halt="natural", n_steps=3):
    return {
        "case_id": "c1",
        "messages": [{"role": "assistant", "content": "ok"}],
        "n_steps": n_steps,
        "halt_reason": halt,
    }


def test_clean_pass():
    assert cleanliness.is_clean(_traj(), ideal_steps=5) is True


def test_halt_not_natural_fails():
    assert cleanliness.is_clean(_traj(halt="max_steps"), ideal_steps=5) is False


def test_over_ideal_steps_fails():
    assert cleanliness.is_clean(_traj(n_steps=9), ideal_steps=5) is False


def test_missing_steps_fails():
    t = _traj()
    del t["n_steps"]
    assert cleanliness.is_clean(t, ideal_steps=5) is False
