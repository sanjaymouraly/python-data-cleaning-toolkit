"""Excel reader tests: multi-sheet, formulas, limits, empty sheets."""

from __future__ import annotations

import pandas as pd
import pytest

from data_cleaning_toolkit import DataImportError
from data_cleaning_toolkit.readers.excel_reader import list_sheets, read_excel


@pytest.fixture()
def workbook(tmp_path):
    path = tmp_path / "book.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame({"sku": ["A1", "A2"], "qty": [5, 0]}).to_excel(
            writer, sheet_name="stock", index=False
        )
        pd.DataFrame({"code": ["S1"], "name": ["Acme"]}).to_excel(
            writer, sheet_name="suppliers", index=False
        )
    return str(path)


class TestExcelReading:
    def test_list_sheets(self, workbook):
        assert list_sheets(workbook) == ["stock", "suppliers"]

    def test_default_reads_first_sheet(self, workbook):
        ds = read_excel(workbook)
        assert ds.metadata.sheet == "stock"
        assert ds.shape == (2, 2)

    def test_read_by_name(self, workbook):
        ds = read_excel(workbook, sheet="suppliers")
        assert ds.dataframe.iloc[0]["name"] == "Acme"

    def test_read_by_index(self, workbook):
        ds = read_excel(workbook, sheet=1)
        assert ds.metadata.sheet == "suppliers"

    def test_sheet_out_of_range(self, workbook):
        with pytest.raises(DataImportError):
            read_excel(workbook, sheet=5)

    def test_unknown_sheet_name(self, workbook):
        with pytest.raises(DataImportError):
            read_excel(workbook, sheet="nope")

    def test_multi_sheet_default_warns(self, workbook):
        ds = read_excel(workbook)
        assert any("sheets" in w for w in ds.metadata.import_warnings)

    def test_empty_sheet_rejected(self, tmp_path):
        path = tmp_path / "empty.xlsx"
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            pd.DataFrame({"a": []}).to_excel(writer, sheet_name="blank", index=False)
        with pytest.raises(DataImportError):
            read_excel(str(path), sheet="blank")

    def test_dtypes_preserved_as_objects(self, workbook):
        ds = read_excel(workbook)
        # qty stays int (not coerced to text)
        assert list(ds.dataframe["qty"]) == [5, 0]


class TestExcelFormulas:
    def test_formula_cells_warned(self, tmp_path):
        from openpyxl import Workbook

        path = tmp_path / "formula.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.append(["a", "b"])
        ws.append([1, "=SUM(A2:A2)"])
        wb.save(path)
        ds = read_excel(str(path))
        assert any("formula" in w.lower() for w in ds.metadata.workbook_warnings)

    def test_plain_workbook_has_no_formula_warning(self, workbook):
        ds = read_excel(workbook)
        assert not ds.metadata.workbook_warnings


class TestExcelSafety:
    def test_corrupt_file_rejected(self, tmp_path):
        path = tmp_path / "corrupt.xlsx"
        path.write_bytes(b"PK\x03\x04 not really a zip file")
        with pytest.raises(DataImportError):
            read_excel(str(path))

    def test_renamed_csv_with_xlsx_extension_rejected(self, tmp_path):
        path = tmp_path / "fake.xlsx"
        path.write_text("a,b\n1,2\n")
        with pytest.raises(DataImportError):
            read_excel(str(path))

    def test_file_limit(self, workbook):
        from data_cleaning_toolkit import LimitExceededError
        from data_cleaning_toolkit.config.schema import LimitsConfig

        with pytest.raises(LimitExceededError):
            read_excel(workbook, limits=LimitsConfig(max_file_mb=0.000001))

    def test_source_not_modified(self, workbook):
        before = open(workbook, "rb").read()
        read_excel(workbook)
        read_excel(workbook, sheet="suppliers")
        assert open(workbook, "rb").read() == before
