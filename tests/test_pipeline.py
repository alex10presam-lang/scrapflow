"""Contratos e contas com fixtures pequenas, independentes da demonstração."""

from copy import deepcopy
from io import BytesIO
import unittest
from openpyxl import Workbook

from scrapflow.pipeline import InputError, consolidate, read_table, summarize


def fixture():
    return {
        "produtos": [{"produto": "A", "descricao": "Peça de teste", "linha": "Linha 1"}],
        "producao": [
            {"ordem": "OP1", "produto": "A", "quantidade_boa": "90", "custo_unitario": "0.29"}
        ],
        "perdas": [
            {
                "id": "P1",
                "ordem": "OP1",
                "data": "2026-10-01",
                "quantidade": "10",
                "motivo": "Ajuste",
            }
        ],
    }


class PipelineTests(unittest.TestCase):
    def test_cost_is_exact_in_cents_and_rate_includes_losses(self):
        summary = summarize(consolidate(fixture()))
        self.assertEqual(summary["cost_cents"], 290)
        self.assertEqual(summary["rate"], 10)
        self.assertEqual(summary["good"], 90)

    def test_duplicate_loss_is_not_double_counted(self):
        tables = fixture()
        tables["perdas"].append(deepcopy(tables["perdas"][0]))
        with self.assertRaisesRegex(InputError, "duplicado"):
            consolidate(tables)

    def test_duplicate_order_is_rejected(self):
        tables = fixture()
        tables["producao"] *= 2
        with self.assertRaisesRegex(InputError, "duplicado"):
            consolidate(tables)

    def test_unknown_order_is_rejected(self):
        tables = fixture()
        tables["perdas"][0]["ordem"] = "UNKNOWN"
        with self.assertRaisesRegex(InputError, "ordem não cadastrada"):
            consolidate(tables)

    def test_unknown_product_is_rejected(self):
        tables = fixture()
        tables["producao"][0]["produto"] = "UNKNOWN"
        with self.assertRaisesRegex(InputError, "produto não cadastrado"):
            consolidate(tables)

    def test_invalid_calendar_date_is_rejected(self):
        tables = fixture()
        tables["perdas"][0]["data"] = "2026-02-30"
        with self.assertRaisesRegex(InputError, "data válida"):
            consolidate(tables)

    def test_negative_and_fractional_quantities_are_rejected(self):
        for value in ("-1", "0", "1.5", "1e3"):
            with self.subTest(value=value):
                tables = fixture()
                tables["perdas"][0]["quantidade"] = value
                with self.assertRaises(InputError):
                    consolidate(tables)

    def test_invalid_money_is_rejected(self):
        for value in ("NaN", "Infinity", "-1", "1.001", "1000001"):
            with self.subTest(value=value):
                tables = fixture()
                tables["producao"][0]["custo_unitario"] = value
                with self.assertRaises(InputError):
                    consolidate(tables)

    def test_zero_good_units_is_valid(self):
        tables = fixture()
        tables["producao"][0]["quantidade_boa"] = "0"
        self.assertEqual(summarize(consolidate(tables))["rate"], 100)

    def test_filter_includes_good_orders_without_loss(self):
        tables = fixture()
        tables["producao"].append(
            {"ordem": "OP2", "produto": "A", "quantidade_boa": "100", "custo_unitario": "1.00"}
        )
        summary = summarize(consolidate(tables), "Linha 1")
        self.assertEqual(summary["rate"], 5)
        self.assertEqual(summary["order_count"], 2)

    def test_empty_filter_has_zero_rate(self):
        summary = summarize(consolidate(fixture()), "Unknown")
        self.assertEqual(summary["rate"], 0)
        self.assertEqual(summary["records"], [])

    def test_csv_bom_semicolon_and_whitespace(self):
        content = "\ufeffproduto;descricao;linha\n A ; Peça ; Linha 1 \n".encode("utf-8")
        self.assertEqual(read_table(content, "test.csv", "produtos")[0]["produto"], "A")

    def test_header_reordering_is_supported(self):
        data = read_table(b"linha,produto,descricao\nL1,A,Part", "test.csv", "produtos")
        self.assertEqual(data[0]["produto"], "A")

    def test_empty_missing_duplicate_and_extra_columns(self):
        for content in (
            b"",
            b"produto,descricao\nA,X",
            b"produto,produto,linha\nA,A,L",
            b"produto,descricao,linha,x\nA,X,L,Y",
        ):
            with self.subTest(content=content), self.assertRaises(InputError):
                read_table(content, "test.csv", "produtos")

    def test_missing_cell(self):
        with self.assertRaisesRegex(InputError, "preencha"):
            read_table(b"produto,descricao,linha\nA,,L", "test.csv", "produtos")

    def test_broken_xlsx_and_unsupported_extension(self):
        for filename in ("broken.xlsx", "file.xlsm", "file.exe"):
            with self.subTest(filename=filename), self.assertRaises(InputError):
                read_table(b"not a workbook", filename, "produtos")

    def test_excel_input(self):
        book = Workbook()
        book.active.append(["produto", "descricao", "linha"])
        book.active.append(["A", "Test", "L1"])
        stream = BytesIO()
        book.save(stream)
        book.close()
        self.assertEqual(read_table(stream.getvalue(), "test.xlsx", "produtos")[0]["produto"], "A")

    def test_blank_rows_are_ignored(self):
        content = b"produto,descricao,linha\n\nA,Test,L1\n,,\n"
        self.assertEqual(len(read_table(content, "test.csv", "produtos")), 1)
