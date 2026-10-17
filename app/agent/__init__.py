"""Agente de IA: interpreta mensagens em linguagem natural e chama a camada de serviços.

- tools.py   ferramentas que o modelo pode chamar (todas passam pelos serviços)
- prompt.py  instruções de sistema (regras de comportamento do agente)
- llm.py     adaptador do provedor de LLM (Gemini). Trocar de provedor = trocar este arquivo
- agent.py   laço: mensagem -> modelo -> ferramentas -> modelo -> resposta
"""
