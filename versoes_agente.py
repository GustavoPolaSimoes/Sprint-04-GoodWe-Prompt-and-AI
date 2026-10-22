"""
- V2 (manual, Sprint 2): reconstrução da versão sem framework. O histórico é uma
  lista Python por thread, a base inteira vai no system prompt e não há tool,
  checkpointer nem validação determinística em Python.

- V3 (framework, Sprint 3): o próprio chatbot_goodwe.py, sem alterações.
"""

import time

import ollama

from chatbot_goodwe import (
    BASE_GOODWE,
    SYSTEM_PROMPT,
    criar_agente,
    validar_pergunta,
)

CONTEXTO_MANUAL = "\n".join(BASE_GOODWE.values())


def _tokens_ollama(meta: dict) -> int:
    return (meta.get("prompt_eval_count") or 0) + (meta.get("eval_count") or 0)


class VersaoManualSprint2:
    nome = "V2 manual (Sprint 2)"

    def __init__(self, modelo="qwen3:8b", temperature=0.1, top_p=0.9, max_tokens=512):
        self.modelo = modelo
        self.opcoes = {"temperature": temperature, "top_p": top_p, "num_predict": max_tokens}
        self.historicos = {}

    def responder(self, pergunta: str, thread_id: str):
        historico = self.historicos.setdefault(thread_id, [])
        mensagens = [
            {"role": "system", "content": SYSTEM_PROMPT + "\n\nBASE DE CONHECIMENTO:\n" + CONTEXTO_MANUAL}
        ]
        mensagens += historico
        mensagens.append({"role": "user", "content": pergunta})

        inicio = time.perf_counter()
        resposta = ollama.chat(model=self.modelo, messages=mensagens, think=False, options=self.opcoes)
        latencia = time.perf_counter() - inicio

        texto = resposta["message"]["content"]
        historico.append({"role": "user", "content": pergunta})
        historico.append({"role": "assistant", "content": texto})
        return texto, latencia, _tokens_ollama(resposta)


class VersaoFrameworkSprint3:
    nome = "V3 framework (Sprint 3)"

    def __init__(self, modelo="qwen3:8b", temperature=0.1, top_p=0.9, max_tokens=512):
        self.agente = criar_agente(modelo=modelo, temperature=temperature, top_p=top_p, max_tokens=max_tokens)

    def responder(self, pergunta: str, thread_id: str):
        inicio = time.perf_counter()
        bloqueio = validar_pergunta(pergunta)
        if bloqueio:
            return bloqueio, time.perf_counter() - inicio, 0

        resultado = self.agente.invoke(
            {"messages": [{"role": "user", "content": pergunta}]},
            config={"configurable": {"thread_id": thread_id}},
        )
        latencia = time.perf_counter() - inicio

        texto = resultado["messages"][-1].content
        tokens = sum(_tokens_ollama(getattr(m, "response_metadata", {}) or {}) for m in resultado["messages"])
        return texto, latencia, tokens


VERSOES = {
    "v2_manual": VersaoManualSprint2,
    "v3_framework": VersaoFrameworkSprint3,
}
