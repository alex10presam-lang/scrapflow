# Decisões de arquitetura

## Contexto

Esta edição demonstra a consolidação de dados de produção em um computador local. O contrato é genérico e o lote de exemplo foi criado exclusivamente para o projeto. Não existe dependência de planilhas, logotipos ou regras de uma organização específica.

## Backend pequeno, responsabilidades distintas

`pipeline.py` recebe tabelas e devolve dados normalizados. Ele não conhece requisições HTTP, banco de dados ou interface. `storage.py` guarda cada lote em uma transação SQLite. `reports.py` usa o mesmo conjunto persistido para gerar o Excel.

A fábrica `create_app()` permite trocar o caminho do banco nos testes. Cada teste de API usa um diretório temporário, evitando dependência do estado da máquina.

## Persistência do lote inteiro

O JSON normalizado é guardado em uma linha SQLite com ID, horário UTC e origem. Isso simplifica a reprodução de uma execução e impede que uma edição de cadastro altere retroativamente seu resultado. Não há rotas de edição de lotes.

A contrapartida é a leitura do conjunto inteiro para recalcular filtros. Para volumes maiores, seria necessário normalizar tabelas e executar agregações no banco. O limite de tamanho e a finalidade local tornam essa troca aceitável nesta versão.

## Dinheiro e quantidades

Custos entram como `Decimal`; resultados são armazenados em centavos inteiros. A taxa é arredondada para duas casas somente na apresentação do resultado. Quantidades são inteiras e o custo é uma estimativa baseada no valor informado por ordem.

Não se deve comparar taxas de lotes com períodos ou critérios diferentes sem revisar as fontes. O aplicativo não verifica completude temporal nem calcula OEE.

## Interface sem build

HTML, CSS e JavaScript nativos são suficientes para os três fluxos: consultar, importar e entender o cálculo. A interface usa `textContent` para inserir dados e não injeta HTML vindo dos arquivos. Não carrega fontes ou bibliotecas de terceiros.

A identidade visual usa desenho vetorial próprio, marca geométrica, linhas de construção e cores de leitura industrial. O SVG é código do repositório, sem dependência de imagens geradas ou banco de imagens.

## Limites de segurança

O servidor é local e não tem contas de usuário. As rotas de gravação rejeitam origens externas identificadas nos cabeçalhos do navegador. Há limites de tamanho, cabeçalhos HTTP de proteção e escape de textos que poderiam virar fórmulas no Excel exportado.

Isso não substitui autenticação, autorização, armazenamento protegido ou configuração de um servidor de produção. Não exponha a porta do aplicativo na rede. Uma versão multiusuário precisaria de outro desenho de implantação e de política de retenção de dados.

## Validação realizada

- 30 testes de backend, incluindo regressões e requisições completas de importação/exportação.
- Teste manual no navegador: demonstração, importação dos três exemplos, filtro por linha, busca sem resultados e navegação.
- Conferência visual em desktop e viewport móvel de 390 px.
- Dados e resultados de exemplo determinísticos.

Os testes de navegador ainda são manuais. A suíte automática cobre os contratos e a API, mas não garante ausência de regressões visuais.
