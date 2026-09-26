from ml_common.fingerprint import compute_data_id, compute_working_copy_id


def test_working_copy_id_is_stable():
    assert compute_working_copy_id("v1", "abc") == compute_working_copy_id("v1", "abc")
    assert len(compute_working_copy_id("v1", "abc")) == 16


def test_working_copy_id_changes_with_the_raw_object():
    assert compute_working_copy_id("v1", "abc") != compute_working_copy_id("v1", "xyz")
    assert compute_working_copy_id("v1", "abc") != compute_working_copy_id("v2", "abc")


def test_data_id_separates_row_limits():
    wc = compute_working_copy_id("v1", "abc")
    assert compute_data_id(wc, 200_000, 42) != compute_data_id(wc, None, 42)
    assert compute_data_id(wc, 0, 42) != compute_data_id(wc, None, 42)


def test_data_id_separates_seeds():
    wc = compute_working_copy_id("v1", "abc")
    assert compute_data_id(wc, 200_000, 42) != compute_data_id(wc, 200_000, 7)


def test_data_id_changes_with_the_working_copy():
    assert compute_data_id("a", None, 42) != compute_data_id("b", None, 42)
