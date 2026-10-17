# Contrato dos arquivos

Cada processamento recebe três tabelas. Os nomes dos arquivos são livres; o campo do formulário define sua função. Não é necessário usar as mesmas ordens ou produtos da demonstração.

## Formato

- CSV em UTF-8 (com ou sem BOM), separado por vírgula ou ponto e vírgula.
- XLSX: primeira aba, cabeçalho na primeira linha. Datas devem ser texto `AAAA-MM-DD`.
- Cabeçalhos exatos, sem colunas adicionais ou duplicadas. A ordem das colunas pode variar.
- Campos obrigatórios, com até 200 caracteres. Espaços nas extremidades são removidos.
- Linhas completamente vazias são ignoradas. Células vazias em registros são erro.
- Um arquivo de cada tipo por lote; limite de 5 MB para a requisição e 10.000 registros por arquivo.
- XLSX tem limite adicional de 30 MB descompactados. Arquivos XLS, XLSM, protegidos por senha ou com estrutura inválida não são aceitos.

## Produtos

| Campo | Regra |
| --- | --- |
| `produto` | Identificador único. Recomenda-se texto, como `P-101` |
| `descricao` | Descrição legível do produto |
| `linha` | Nome da linha de produção |

## Produção

| Campo | Regra |
| --- | --- |
| `ordem` | Identificador único no lote |
| `produto` | Deve existir no cadastro de produtos |
| `quantidade_boa` | Inteiro não negativo, até 9 dígitos |
| `custo_unitario` | De 0 a 1.000.000, até duas casas decimais; ponto ou vírgula decimal, sem milhares |

Uma ordem pode não ter perdas; sua quantidade boa continua no denominador da taxa. Valores de quantidade no XLSX devem ser numéricos inteiros, não fórmulas.

## Perdas

| Campo | Regra |
| --- | --- |
| `id` | Identificador único da ocorrência |
| `ordem` | Deve existir na tabela de produção |
| `data` | Data válida em `AAAA-MM-DD` |
| `quantidade` | Inteiro positivo, até 9 dígitos |
| `motivo` | Categoria usada para agrupar o custo |

Ocorrências com IDs diferentes são consideradas distintas, mesmo que tenham valores idênticos. O sistema não tenta inferir se elas são duplicatas de negócio. Cabe a quem prepara o lote garantir uma ordem e uma ocorrência por identificador.

## Exemplo mínimo

`produtos.csv`

```csv
produto,descricao,linha
P-1,Peça demonstrativa,Linha A
```

`producao.csv`

```csv
ordem,produto,quantidade_boa,custo_unitario
OP-1,P-1,90,2.50
```

`perdas.csv`

```csv
id,ordem,data,quantidade,motivo
PER-1,OP-1,2026-10-01,10,Ajuste de processo
```

Resultado esperado: 10 unidades perdidas, 90 boas, taxa de 10% e custo de R$ 25,00.
