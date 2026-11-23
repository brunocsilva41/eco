"""Cliente ACP (Agent Client Protocol) do Eco: JSON-RPC 2.0 por stdio, sem interface gráfica.

Módulos: `client` (protocolo), `agents` (catálogo e detecção), `mcp_server` (ferramentas do Eco em loopback),
`policy` (privacidade e permissões), `cloud` (o cérebro em nuvem que o Agent usa). Documentação: docs/CEREBRO-NUVEM.md.
"""
from .client import AcpClient, AcpError, AcpTimeout, PromptResult, AcpCancelled  # noqa: F401
