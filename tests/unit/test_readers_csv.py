"""CSV reader tests: encodings, delimiters, malformed rows, limits, safety."""

from __future__ import annotations

import pandas as pd
import pytest

from data_cleaning_toolkit import (
    DataImportError,
    LimitExceededError,
    UnsupportedFormatError,
)
from data_cleaning_toolkit.config.schema import ImportOptionsConfig, LimitsConfig
from data_cleaning_toolkit.readers.csv_reader import read_csv


class TestCsvBasics:
    def test_basic_read(self, tmp_csv, dirty_df):
        path = tmp_csv(dirty_df)
        ds = read_csv(path)
        assert ds.shape == (6, 6)
        assert ds.metadata.fmt == "csv"
        assert len(ds.metadata.sha256) == 64
        assert ds.dataframe.iloc[0]["name"] == "  Alice  "  # raw text preserved

    def test_header_row_option(self, tmp_path):
        path = tmp_path / "skipped.csv"
        path.write_text("junk line\nname,qty\na,1\nb,2\n")
        ds = read_csv(str(path), ImportOptionsConfig(header_row=1))
        assert list(ds.dataframe.columns) == ["name", "qty"]
        assert ds.shape == (2, 1 + 1)

    def test_column_selection_and_rename(self, tmp_csv, dirty_df):
        path = tmp_csv(dirty_df)
        ds = read_csv(
            path,
            ImportOptionsConfig(columns=["name", "qty"], rename={"qty": "quantity"}),
        )
        assert list(ds.dataframe.columns) == ["name", "quantity"]

    def test_rename_unknown_column_rejected(self, tmp_csv, dirty_df):
        path = tmp_csv(dirty_df)
        with pytest.raises(DataImportError):
            read_csv(path, ImportOptionsConfig(rename={"nope": "x"}))


class TestCsvEncodings:
    def test_utf8_bom_detected(self, tmp_csv, dirty_df):
        path = tmp_csv(dirty_df, "bom.csv", encoding="utf-8-sig")
        ds = read_csv(path)
        assert ds.metadata.encoding == "utf-8-sig"
        assert ds.dataframe.columns[0] == "id"

    def test_cp1252_fallback(self, tmp_path):
        path = tmp_path / "cp.csv"
        df = pd.DataFrame({"city": ["München", "Köln"]})
        df.to_csv(path, index=False, encoding="cp1252")
        ds = read_csv(str(path))
        assert ds.metadata.encoding == "cp1252"
        assert ds.dataframe.iloc[0]["city"] == "München"
        assert any("fallback encoding" in w for w in ds.metadata.import_warnings)

    def test_explicit_encoding_override(self, tmp_path):
        path = tmp_path / "cp2.csv"
        df = pd.DataFrame({"city": ["München"]})
        df.to_csv(path, index=False, encoding="cp1252")
        ds = read_csv(str(path), ImportOptionsConfig(encoding="cp1252"))
        assert ds.metadata.encoding == "cp1252"
        assert not any("fallback" in w for w in ds.metadata.import_warnings)

    def test_unknown_encoding_rejected(self, tmp_csv, dirty_df):
        path = tmp_csv(dirty_df)
        with pytest.raises(DataImportError):
            read_csv(path, ImportOptionsConfig(encoding="not-a-real-encoding"))


class TestCsvDelimiters:
    def test_semicolon_auto_detected(self, tmp_path):
        path = tmp_path / "semi.csv"
        path.write_text("name;qty\na;1\nb;2\n")
        ds = read_csv(str(path))
        assert ds.metadata.delimiter == ";"
        assert list(ds.dataframe.columns) == ["name", "qty"]

    def test_tab_auto_detected(self, tmp_path):
        path = tmp_path / "tab.tsv"
        path.write_text("name\tqty\na\t1\nb\t2\n")
        ds = read_csv(str(path))
        assert ds.metadata.delimiter == "\t"

    def test_explicit_delimiter(self, tmp_path):
        path = tmp_path / "pipe.txt"
        path.write_text("name|qty\na|1\n")
        ds = read_csv(str(path), ImportOptionsConfig(delimiter="|"))
        assert ds.metadata.delimiter == "|"


class TestCsvMalformed:
    def test_ragged_rows_counted(self, tmp_path):
        path = tmp_path / "ragged.csv"
        path.write_text("a,b\n1,2\n3\n4,5\n")
        ds = read_csv(str(path))
        assert any("malformed" in w for w in ds.metadata.import_warnings)
        # the short row is padded with a null field, never silently dropped
        assert len(ds.dataframe) == 3
        assert pd.isna(ds.dataframe.iloc[1]["b"])

    def test_empty_file_rejected(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("")
        with pytest.raises(DataImportError):
            read_csv(str(path))

    def test_header_only_file(self, tmp_path):
        path = tmp_path / "header.csv"
        path.write_text("a,b\n")
        with pytest.raises(DataImportError):
            read_csv(str(path))

    def test_header_row_beyond_file(self, tmp_csv, dirty_df):
        path = tmp_csv(dirty_df)
        with pytest.raises(DataImportError):
            read_csv(path, ImportOptionsConfig(header_row=100))

    def test_missing_file(self, tmp_path):
        with pytest.raises(DataImportError):
            read_csv(str(tmp_path / "ghost.csv"))


class TestFormatSafety:
    def test_xlsx_rejected_by_csv_reader(self, tmp_path):
        p = tmp_path / "data.xlsx"
        pd.DataFrame({"a": [1]}).to_excel(p, index=False)
        with pytest.raises(DataImportError):
            read_csv(str(p))

    @pytest.mark.parametrize(
        "name", ["data.xls", "data.xlsm", "data.parquet", "data.zip", "data.ods"]
    )
    def test_unsupported_formats(self, tmp_path, name):
        p = tmp_path / name
        p.write_text("dummy")
        with pytest.raises(UnsupportedFormatError):
            from data_cleaning_toolkit.readers.excel_reader import load_any

            load_any(str(p))

    def test_filename_with_spaces_and_unicode(self, tmp_csv, dirty_df):
        path = tmp_csv(dirty_df, "my file äöü.csv")
        ds = read_csv(path)
        assert ds.shape == (6, 6)
        assert "äöü" in ds.metadata.filename

    def test_file_limit_enforced(self, tmp_csv, dirty_df):
        path = tmp_csv(dirty_df)
        limits = LimitsConfig(max_file_mb=0.000001)
        with pytest.raises(LimitExceededError):
            read_csv(path, limits=limits)

    def test_row_limit_enforced(self, tmp_csv, dirty_df):
        path = tmp_csv(dirty_df)
        limits = LimitsConfig(max_rows=3)
        with pytest.raises(LimitExceededError):
            read_csv(path, limits=limits)

    def test_source_file_not_modified_by_reading(self, tmp_csv, dirty_df):
        path = tmp_csv(dirty_df)
        before = open(path, "rb").read()
        read_csv(path)
        assert open(path, "rb").read() == before
