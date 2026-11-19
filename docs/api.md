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
| `GET /api/automation` | Modo demonstrativo, configuração explicativa da agenda e até 30 trabalhos dos bots |
| `POST /api/automation/jobs` | Inicia ou reutiliza um trabalho; recebe JSON com `scenario` e `trigger` |
| `GET /api/automation/jobs/<id>` | Estado, fases, fontes, tentativas, contagens e resultado |
| `GET /api/automation/jobs/<id>/archive` | ZIP dos arquivos de conferência após término, inclusive artefatos parciais de falhas |
| `GET /api/automation/workflow` | Template n8n inativo, sem credenciais |

## Erros

- `422`: lote inválido; a resposta contém `error` com o motivo. Nenhuma execução é gravada.
- `413`: limite de 5 MB excedido.
- `404`: ID de execução não encontrado.
- `403`: tentativa de processamento enviada por origem externa identificada.

Os POSTs de importação e demonstração manual criam lotes novos. Os bots usam outro contrato: um trabalho ativo é reutilizado e `trigger: schedule` utiliza uma chave diária de Manaus, persistente após reinício. O processamento automático é assíncrono; o POST retorna `202` enquanto o trabalho estiver ativo e `200` quando reutilizar um resultado terminal. O corpo contém `job` e `reused`. Consulte [a automação](automation.md).

```json
{"scenario": "temporary_failure", "trigger": "manual"}
```

Os cenários aceitos são `normal`, `temporary_failure` e `invalid_batch`; o disparo agendado aceita apenas `normal`. Não são aceitos caminhos de arquivos, URLs ou credenciais. Um lote inválido durante o trabalho retorna estado `failed` na consulta, sem publicar o lote. Baixar a conferência de um trabalho ainda ativo retorna `409`.

## Datas e filtros

Horários dos lotes são armazenados em UTC; os trabalhos dos bots usam timestamps com deslocamento de Manaus. A interface apresenta horários no fuso do navegador. A chave diária e os diretórios dos bots usam UTC-04 (Manaus). Datas das perdas são datas de calendário, sem conversão de fuso. O resumo inclui todas as ordens da linha selecionada, não apenas as que possuem perdas.
