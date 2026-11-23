# Como contribuir com o Eco

Obrigado pelo interesse! O Eco é um assistente de voz local em português do Brasil para Windows.

## Antes de abrir um Pull Request
1. Abra uma **issue** descrevendo o problema ou a ideia, para alinharmos o escopo.
2. Faça um *fork* e crie uma branch curta (`fix/...`, `feat/...`, `docs/...`).
3. Rode as verificações locais (PowerShell, na raiz do projeto):

```powershell
python -W error -m compileall -q src
python -I -c "from jarvis.settings import schema; assert not schema.uncovered_fields()"
$env:QT_QPA_PLATFORM = "offscreen"; python -I -m unittest discover -s tests -p "test_*.py"
```

4. Escreva mensagens de commit claras, no imperativo, em português ou inglês.
5. Atualize o `CHANGELOG.md` (seção *Não lançado*) e a documentação afetada em `docs\`.

## Regras do projeto
- Privacidade primeiro: nada de enviar voz, tela ou arquivos para a rede sem consentimento explícito e configurável.
- Nunca inclua segredos, tokens, caminhos pessoais ou dados de usuário em código, testes ou capturas.
- Mudanças de interface precisam de capturas em 100% e 150%, tema claro e escuro.
- Mudanças em ferramentas que controlam o PC precisam de testes de permissão (negar, confirmar, permitir).
- Textos voltados ao usuário em português do Brasil, com acentuação correta.

## Licença
Ao contribuir, você concorda que sua contribuição será licenciada sob a [MIT](LICENSE).