"""Tests for schemas module."""

from opi_agent.schemas import (
    CONFIG_SCHEMAS,
    get_schema,
    list_schemas,
    validate_value,
)


class TestConfigSchemas:
    """Tests for configuration schemas."""

    def test_all_schemas_present(self):
        expected_keys = [
            "OPI_BASE_DIR",
            "OPI_SERVICE_NAME",
            "OPI_UPDATE_BRANCH",
            "OPI_ORIGIN_URL",
            "OPI_SHELL_ENABLED",
            "OPI_HEARTBEAT_SECONDS",
            "OPI_API_KEY",
            "OPI_ALLOWED_COMMANDS",
            "OPI_ALLOWED_PATHS",
            "OPI_EXEC_TIMEOUT",
            "OPI_EXTRA_GROUPS",
            "OPI_GRANT_ACL",
            "OPI_PATCH_URL",
            "OPI_PATCH_PATH",
        ]
        for key in expected_keys:
            assert key in CONFIG_SCHEMAS, f"Missing schema for {key}"

    def test_get_schema(self):
        schema = get_schema("OPI_SHELL_ENABLED")
        assert schema is not None
        assert schema.key == "OPI_SHELL_ENABLED"
        assert schema.choices == ["true", "false", "1", "0", "yes", "no", "on", "off", "y", "n"]

    def test_get_schema_unknown(self):
        assert get_schema("UNKNOWN_KEY") is None

    def test_list_schemas(self):
        schemas = list_schemas()
        assert len(schemas) == len(CONFIG_SCHEMAS)
        assert all(hasattr(s, "key") for s in schemas)


class TestValidateValue:
    """Tests for value validation."""

    def test_choices_validation(self):
        schema = CONFIG_SCHEMAS["OPI_SHELL_ENABLED"]
        valid, error = validate_value(schema, "true")
        assert valid is True
        assert error is None

        valid, error = validate_value(schema, "invalid")
        assert valid is False
        assert "must be one of" in error

    def test_positive_int_validator(self):
        schema = CONFIG_SCHEMAS["OPI_HEARTBEAT_SECONDS"]
        valid, error = validate_value(schema, "60")
        assert valid is True

        valid, error = validate_value(schema, "0")
        assert valid is False

        valid, error = validate_value(schema, "-1")
        assert valid is False

        valid, error = validate_value(schema, "not_a_number")
        assert valid is False

    def test_no_validator(self):
        schema = CONFIG_SCHEMAS["OPI_BASE_DIR"]
        valid, error = validate_value(schema, "/any/path")
        assert valid is True
