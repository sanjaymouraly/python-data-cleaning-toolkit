"""Configuration schema validation tests."""

from __future__ import annotations

import pytest

from data_cleaning_toolkit import ConfigError, parse_config
from data_cleaning_toolkit.config.schema import load_config_file


class TestSchemaValidation:
    def test_minimal_config_is_valid(self):
        cfg = parse_config({"version": "1.0", "name": "x"})
        assert cfg.name == "x"
        assert cfg.rules == []

    def test_unknown_rule_key_rejected(self):
        with pytest.raises(ConfigError) as exc:
            parse_config(
                {
                    "version": "1.0",
                    "rules": [{"type": "duplicates", "keep": "first", "bogus_key": 1}],
                }
            )
        assert "bogus_key" in str(exc.value)

    def test_unknown_top_level_key_rejected(self):
        with pytest.raises(ConfigError):
            parse_config({"version": "1.0", "definitely_not_a_key": True})

    def test_unknown_rule_type_rejected(self):
        with pytest.raises(ConfigError):
            parse_config({"version": "1.0", "rules": [{"type": "make_data_up"}]})

    def test_invalid_regex_rejected_at_load(self):
        with pytest.raises(ConfigError):
            parse_config(
                {
                    "version": "1.0",
                    "rules": [
                        {"type": "regex_match", "column": "a", "pattern": "([unclosed"}
                    ],
                }
            )

    def test_bad_strftime_rejected(self):
        with pytest.raises(ConfigError):
            parse_config(
                {
                    "version": "1.0",
                    "rules": [
                        {
                            "type": "date_normalize",
                            "columns": ["d"],
                            "output_format": "%Q nonsense",
                        }
                    ],
                }
            )

    def test_duplicate_rule_ids_rejected(self):
        with pytest.raises(ConfigError) as exc:
            parse_config(
                {
                    "version": "1.0",
                    "rules": [
                        {"id": "same", "type": "duplicates"},
                        {"id": "same", "type": "required_column", "column": "x"},
                    ],
                }
            )
        assert "same" in str(exc.value)

    def test_auto_rule_ids_are_deterministic(self):
        cfg = parse_config(
            {
                "version": "1.0",
                "rules": [{"type": "duplicates"}, {"type": "duplicates", "id": "custom"}],
            }
        )
        assert cfg.rule_ids() == ["duplicates-01", "custom"]

    def test_missing_fill_constant_requires_value(self):
        with pytest.raises(ConfigError):
            parse_config(
                {
                    "version": "1.0",
                    "rules": [
                        {"type": "missing_values", "strategy": "fill_constant"}
                    ],
                }
            )

    def test_statistical_fill_rejects_fill_value(self):
        with pytest.raises(ConfigError):
            parse_config(
                {
                    "version": "1.0",
                    "rules": [
                        {
                            "type": "missing_values",
                            "strategy": "mean",
                            "fill_value": 3,
                        }
                    ],
                }
            )

    def test_unit_rule_validates_category_and_units(self):
        base = {
            "version": "1.0",
            "rules": [
                {
                    "type": "unit_normalize",
                    "value_column": "w",
                    "source_unit": "kg",
                    "category": "mass",
                    "target_unit": "stones",  # not in the table
                }
            ],
        }
        with pytest.raises(ConfigError):
            parse_config(base)
        base["rules"][0]["target_unit"] = "g"
        parse_config(base)  # now fine

    def test_unit_rule_requires_exactly_one_source(self):
        with pytest.raises(ConfigError):
            parse_config(
                {
                    "version": "1.0",
                    "rules": [
                        {
                            "type": "unit_normalize",
                            "value_column": "w",
                            "category": "mass",
                            "target_unit": "g",
                        }
                    ],
                }
            )

    def test_cross_column_requires_exactly_one_right(self):
        with pytest.raises(ConfigError):
            parse_config(
                {
                    "version": "1.0",
                    "rules": [
                        {"type": "cross_column", "left": "a", "operator": ">"}
                    ],
                }
            )

    def test_string_rule_requires_columns_or_all_text(self):
        with pytest.raises(ConfigError):
            parse_config({"version": "1.0", "rules": [{"type": "string_standardize"}]})

    def test_min_max_ordering(self):
        with pytest.raises(ConfigError):
            parse_config(
                {
                    "version": "1.0",
                    "rules": [
                        {
                            "type": "numeric_validate",
                            "columns": ["x"],
                            "min": 10,
                            "max": 5,
                        }
                    ],
                }
            )

    def test_yaml_and_json_text_parsing(self):
        cfg = parse_config('version: "1.0"\nname: from-yaml\nrules: []')
        assert cfg.name == "from-yaml"
        cfg2 = parse_config('{"version": "1.0", "name": "from-json"}')
        assert cfg2.name == "from-json"

    def test_empty_yaml_rejected(self):
        with pytest.raises(ConfigError):
            parse_config("")

    def test_yaml_arbitrary_code_not_executed(self):
        malicious = (
            "!!python/object/apply:os.system ['touch /tmp/pwned']"
        )
        with pytest.raises(ConfigError):
            parse_config(malicious)

    def test_load_config_file_missing(self, tmp_path):
        with pytest.raises(ConfigError):
            load_config_file(str(tmp_path / "nope.yaml"))

    def test_load_config_file_wrong_extension(self, tmp_path):
        p = tmp_path / "config.txt"
        p.write_text("version: '1.0'")
        with pytest.raises(ConfigError):
            load_config_file(str(p))

    def test_load_config_file_valid(self, tmp_path):
        import yaml

        p = tmp_path / "config.yaml"
        with open(p, "w") as fh:
            yaml.safe_dump({"version": "1.0", "name": "file-cfg"}, fh)
        assert load_config_file(str(p)).name == "file-cfg"

    def test_snapshot_is_deterministic_and_serializable(self):
        cfg = parse_config(
            {
                "version": "1.0",
                "name": "snap",
                "rules": [{"type": "duplicates", "keep": "last"}],
            }
        )
        a, b = cfg.to_snapshot(), cfg.to_snapshot()
        assert a == b

    def test_version_is_pinned(self):
        with pytest.raises(ConfigError):
            parse_config({"version": "9.9"})
