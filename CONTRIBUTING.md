# Desenvolvimento

Instale `requirements.txt` em um ambiente virtual. Inicie `python app.py` para trabalhar na interface e execute `python -m unittest discover -s tests -v` antes de propor alterações.

Regras de cálculo devem ficar no pipeline, sem depender das rotas Flask. Alterações no contrato de entrada precisam atualizar exemplos, documentação e testes. Use exclusivamente dados fictícios em fixtures e capturas.

O código Python segue a formatação Black. HTML, CSS e JavaScript seguem Prettier. Esses formatadores são ferramentas opcionais de desenvolvimento; não são necessários para executar a aplicação.

Uma proposta de mudança deve explicar o problema, o comportamento esperado e como foi verificada. Não adicione serviços externos ou novas dependências sem uma necessidade concreta.
