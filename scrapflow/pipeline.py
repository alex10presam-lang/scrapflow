"""Contratos de entrada e cálculo dos indicadores, sem acesso a disco ou HTTP."""

from collections import Counter, defaultdict
import csv
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO, StringIO
import re
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook

SCHEMAS = {
    "produtos": ("produto", "descricao", "linha"),
    "producao": ("ordem", "produto", "quantidade_boa", "custo_unitario"),
    "perdas": ("id", "ordem", "data", "quantidade", "motivo"),
}
MAX_ROWS = 10000


class InputError(ValueError):
    """Um lote que não pode ser consolidado sem corrigir a origem."""


def read_table(content: bytes, filename: str, kind: str) -> list[dict]:
    """Lê CSV UTF-8 ou primeira aba XLSX. Fórmulas não são executadas."""
    try:
        if filename.lower().endswith(".csv"):
            text = content.decode("utf-8-sig")
            first = text.splitlines()[0] if text.strip() else ""
            delimiter = ";" if first.count(";") > first.count(",") else ","
            rows = list(csv.reader(StringIO(text), delimiter=delimiter))
        elif filename.lower().endswith(".xlsx"):
            with ZipFile(BytesIO(content)) as archive:
                if sum(item.file_size for item in archive.infolist()) > 30_000_000:
                    raise InputError("Planilha muito grande após descompactação (limite: 30 MB).")
            workbook = load_workbook(BytesIO(content), read_only=True, data_only=False)
            try:
                rows = []
                for row in workbook.active.iter_rows(values_only=True):
                    rows.append(list(row))
                    if len(rows) > MAX_ROWS + 1:
                        raise InputError(f"Limite de {MAX_ROWS} registros por arquivo.")
            finally:
                workbook.close()
        else:
            raise InputError("Use arquivos .csv ou .xlsx.")
    except InputError:
        raise
    except (UnicodeError, BadZipFile, ValueError, KeyError, OSError) as error:
        raise InputError(
            f"Não foi possível ler {kind}. Verifique formato e codificação."
        ) from error

    if not rows:
        raise InputError(f"O arquivo de {kind} está vazio.")
    headers = [str(value or "").strip() for value in rows[0]]
    if len(headers) != len(set(headers)) or set(headers) != set(SCHEMAS[kind]):
        raise InputError(f"Cabeçalho de {kind}: use exatamente {', '.join(SCHEMAS[kind])}.")
    result = []
    for number, row in enumerate(rows[1:], 2):
        if all(value in (None, "") for value in row):
            continue
        if len(row) != len(headers):
            raise InputError(f"{kind}, linha {number}: quantidade de colunas inválida.")
        record = {
            key: str(value).strip() if value is not None else "" for key, value in zip(headers, row)
        }
        if any(not value for value in record.values()):
            raise InputError(f"{kind}, linha {number}: preencha todos os campos.")
        if any(len(value) > 200 for value in record.values()):
            raise InputError(f"{kind}, linha {number}: campo excede 200 caracteres.")
        result.append(record)
    if not result or len(result) > MAX_ROWS:
        raise InputError(f"{kind}: informe de 1 a {MAX_ROWS} registros.")
    return result


def integer(value: str, label: str, *, zero=False) -> int:
    if not re.fullmatch(r"\d+", value) or len(value) > 9:
        raise InputError(f"{label}: use um inteiro positivo de até 9 dígitos.")
    number = int(value)
    if number < (0 if zero else 1):
        raise InputError(f"{label}: quantidade fora do intervalo permitido.")
    return number


def money(value: str) -> Decimal:
    try:
        number = Decimal(value.replace(",", "."))
        if not number.is_finite() or not 0 <= number <= 1_000_000:
            raise InvalidOperation
        if number != number.quantize(Decimal("0.01")):
            raise InvalidOperation
        return number
    except InvalidOperation as error:
        raise InputError(
            "Custo unitário: use um valor de 0 a 1.000.000 com até duas casas decimais."
        ) from error


def unique(records: list[dict], key: str, label: str) -> dict:
    indexed = {}
    for row in records:
        if row[key] in indexed:
            raise InputError(f"{label}: identificador duplicado ({row[key]}).")
        indexed[row[key]] = row
    return indexed


def consolidate(tables: dict[str, list[dict]]) -> dict:
    products = unique(tables["produtos"], "produto", "Produtos")
    orders = unique(tables["producao"], "ordem", "Produção")
    unique(tables["perdas"], "id", "Perdas")
    normalized_orders = []
    costs = {}
    for code, order in orders.items():
        if order["produto"] not in products:
            raise InputError(f"Ordem {code}: produto não cadastrado.")
        product = products[order["produto"]]
        costs[code] = money(order["custo_unitario"])
        normalized_orders.append(
            {
                **order,
                **product,
                "quantidade_boa": integer(order["quantidade_boa"], code, zero=True),
            }
        )
    records = []
    for loss in tables["perdas"]:
        if loss["ordem"] not in orders:
            raise InputError(f"Perda {loss['id']}: ordem não cadastrada.")
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", loss["data"]):
                raise ValueError
            day = date.fromisoformat(loss["data"])
        except ValueError as error:
            raise InputError(
                f"Perda {loss['id']}: use uma data válida no formato AAAA-MM-DD."
            ) from error
        quantity = integer(loss["quantidade"], loss["id"])
        order = orders[loss["ordem"]]
        product = products[order["produto"]]
        cents = int(
            (costs[loss["ordem"]] * quantity * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        records.append(
            {
                **loss,
                **product,
                "data": day.isoformat(),
                "quantidade": quantity,
                "custo_centavos": cents,
            }
        )
    return {
        "orders": normalized_orders,
        "records": sorted(records, key=lambda row: (row["data"], row["id"])),
    }


def summarize(dataset: dict, line: str = "") -> dict:
    records = [row for row in dataset["records"] if not line or row["linha"] == line]
    orders = [row for row in dataset["orders"] if not line or row["linha"] == line]
    lost = sum(row["quantidade"] for row in records)
    good = sum(row["quantidade_boa"] for row in orders)
    reasons = Counter()
    days = defaultdict(int)
    for row in records:
        reasons[row["motivo"]] += row["custo_centavos"]
        days[row["data"]] += row["quantidade"]
    costs = sum(row["custo_centavos"] for row in records)
    return {
        "lost": lost,
        "good": good,
        "rate": round(lost / (good + lost) * 100, 2) if good + lost else 0,
        "cost_cents": costs,
        "order_count": len(orders),
        "record_count": len(records),
        "reasons": [{"name": name, "cents": amount} for name, amount in reasons.most_common()],
        "daily": [{"date": day, "quantity": count} for day, count in sorted(days.items())],
        "lines": sorted({row["linha"] for row in dataset["orders"]}),
        "records": records,
    }
