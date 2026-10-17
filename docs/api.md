# API local

Base: `http://127.0.0.1:5050`. Todas as respostas de dados usam JSON. Os downloads usam ZIP ou XLSX.

| Método e caminho | Comportamento |
| --- | --- |
| `GET /api/dashboard` | Última execução ou prévia fictícia se o histórico estiver vazio |
| `GET /api/dashboard?run=<id>&line=<linha>` | Consulta uma execução e aplica recorte por linha |
| `GET /api/runs` | Até 100 execuções, da mais recente para a mais antiga |
| `POST /api/runs/demo` | Consolida e salva o lote fictício; devolve `201` e `{ "id": "..." }` |
| `POST /api/runs` | Recebe multipart com `produtos`, `producao` e `perdas`; devolve ID do lote |
| `GET /api/runs/<id>/report` | Exporta o lote completo em Excel, independentemente dos filtros do painel |
| `GET /api/examples` | ZIP com os três CSVs fictícios |

## Erros

- `422`: lote inválido; a resposta contém `error` com o motivo. Nenhuma execução é gravada.
- `413`: limite de 5 MB excedido.
- `404`: ID de execução não encontrado.
- `403`: tentativa de processamento enviada por origem externa identificada.

Cada POST válido cria uma execução nova. Não há deduplicação entre execuções diferentes ou chave de idempotência. Uma repetição do mesmo lote aparece novamente no histórico.

## Datas e filtros

Horários de processamento são armazenados em UTC e apresentados no fuso do navegador. Datas das perdas são datas de calendário, sem conversão de fuso. O resumo inclui todas as ordens da linha selecionada, não apenas as que possuem perdas.
