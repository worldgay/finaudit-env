from finaudit import ENV_VERSION, SCHEMA_VERSION


def test_versions():
    assert ENV_VERSION == "1.2.0" and SCHEMA_VERSION == "1.0"
