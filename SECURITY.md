# Política de segurança

## Versões com correção de segurança
Somente a **versão mais recente** publicada em [Releases](../../releases/latest) recebe correções.

## Como reportar uma vulnerabilidade
**Não abra uma issue pública** para falhas de segurança. Use o recurso privado do GitHub:
**Security → Report a vulnerability** (relato privado de vulnerabilidade) neste repositório.

Inclua: versão do Eco, passos para reproduzir, impacto esperado e, se possível, uma sugestão de correção.
Respondemos em até 7 dias corridos com a avaliação inicial.

## Modelo de segurança (resumo)
- O Eco roda localmente; voz, conversas e tela não saem do PC por padrão.
- O servidor do modelo escuta só em `127.0.0.1`. O servidor MCP local usa loopback e token por sessão.
- Ações no PC passam por travas e confirmações; há tecla de emergência (`Ctrl+Alt+F12`).
- O modo livre do terminal e o modo YOLO só podem ser ativados manualmente, nunca por voz ou por agente de nuvem.
- Agentes de nuvem (ACP) são opcionais, ficam desligados por padrão e só recebem texto sem consentimento adicional.
- Atualizações só são instaladas com SHA-256 válido, por HTTPS.

## Fora de escopo
O terminal integrado usa uma lista de bloqueio por texto, que é uma rede de proteção e **não** uma sandbox.
Relatos que dependam de o usuário liberar manualmente o modo livre ou o YOLO não são vulnerabilidades.