def test_helpers_importable():
    from tests.helpers import assert_isolated

    assert callable(assert_isolated)
