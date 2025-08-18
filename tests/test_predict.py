from plpred.predict import outcome_probs, top_scorelines

def test_outcome_probs_sane():
    ph,pd,pa = outcome_probs(1.3, 1.1, draw_scale=1.05)
    assert 0 < ph < 1 and 0 < pd < 1 and 0 < pa < 1
    assert abs((ph+pd+pa)-1.0) < 1e-6

def test_top_scorelines_len_and_keys():
    tops = top_scorelines(1.2, 0.9, k=3, cap=5)
    assert len(tops) == 3
    assert set(tops[0].keys()) == {"home_goals","away_goals","prob"}
