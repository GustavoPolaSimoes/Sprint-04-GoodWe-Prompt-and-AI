import argparse
import json
from datetime import datetime
from pathlib import Path
from statistics import mean

from juiz import CRITERIOS, JUIZ_PADRAO, julgar
from metricas import nota_deterministica
from versoes_agente import VERSOES

PASTA = Path(__file__).resolve().parent
DATASET_PATH = PASTA / "golden_dataset.json"
RESULTADOS = PASTA / "resultados"
RESPOSTAS_PATH = RESULTADOS / "respostas.json"

MODELO_AGENTE = "qwen3:8b"
PARAMETROS = {"temperature": 0.1, "top_p": 0.9, "max_tokens": 512}


def carregar_dataset(ids=None):
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    if ids:
        dataset = [item for item in dataset if item["id"] in ids]
    return dataset


def fase_respostas(versoes, ids=None):
    dataset = carregar_dataset(ids)
    dados = (
        json.loads(RESPOSTAS_PATH.read_text(encoding="utf-8"))
        if RESPOSTAS_PATH.exists()
        else {"versoes": {}}
    )
    dados.update({"modelo_agente": MODELO_AGENTE, "parametros": PARAMETROS, "gerado_em": datetime.now().isoformat(timespec="seconds")})

    for vid in versoes:
        adaptador = VERSOES[vid](modelo=MODELO_AGENTE, **PARAMETROS)
        print(f"\n=== {adaptador.nome} ({len(dataset)} casos) ===")
        itens = []
        for item in dataset:
            thread = f"{vid}-{item['id']}"
            turnos = []
            for pergunta in item["turnos"]:
                texto, latencia, tokens = adaptador.responder(pergunta, thread)
                turnos.append({"pergunta": pergunta, "resposta": texto, "latencia_s": round(latencia, 3), "tokens": tokens})
            final = turnos[-1]["resposta"]
            nota = nota_deterministica(item, final)
            print(f"  {item['id']} det={nota} lat={sum(t['latencia_s'] for t in turnos):.1f}s | {final[:90]!r}")
            itens.append({
                "id": item["id"],
                "categoria": item["categoria"],
                "subcategoria": item.get("subcategoria"),
                "comportamento_esperado": item["comportamento_esperado"],
                "gabarito": item["gabarito"],
                "turnos": turnos,
                "resposta_final": final,
                "latencia_total_s": round(sum(t["latencia_s"] for t in turnos), 3),
                "tokens_total": sum(t["tokens"] for t in turnos),
                "nota_deterministica": nota,
            })
        dados["versoes"][vid] = {"nome": adaptador.nome, "itens": itens}
        RESULTADOS.mkdir(exist_ok=True)
        RESPOSTAS_PATH.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nRespostas salvas em {RESPOSTAS_PATH}")


NOTA_RESPOSTA_VAZIA = {c: 0.0 for c in CRITERIOS}
NOTA_RESPOSTA_VAZIA["justificativa"] = "Resposta vazia: nota 0 atribuída sem chamar o juiz."


def fase_julgar(juiz=JUIZ_PADRAO):
    dados = json.loads(RESPOSTAS_PATH.read_text(encoding="utf-8"))
    saida = RESULTADOS / f"avaliacao_{juiz.replace(':', '_').replace('.', '_')}.json"

    ja_julgados = {}
    if saida.exists():
        anterior = json.loads(saida.read_text(encoding="utf-8"))
        for vid, versao in anterior["versoes"].items():
            for item in versao["itens"]:
                if "juiz" in item and "erro" not in item["juiz"]:
                    ja_julgados[(vid, item["id"], item["resposta_final"])] = item["juiz"]

    for vid, versao in dados["versoes"].items():
        print(f"\n=== Juiz {juiz} avaliando {versao['nome']} ===")
        for item in versao["itens"]:
            chave = (vid, item["id"], item["resposta_final"])
            if not item["resposta_final"].strip():
                item["juiz"] = dict(NOTA_RESPOSTA_VAZIA)
            elif chave in ja_julgados:
                item["juiz"] = ja_julgados[chave]
                continue
            else:
                anteriores = [(t["pergunta"], t["resposta"]) for t in item["turnos"][:-1]]
                ultima = item["turnos"][-1]["pergunta"]
                item["juiz"] = julgar(item, anteriores, ultima, item["resposta_final"], juiz=juiz)
            scores = item["juiz"] if "erro" not in item["juiz"] else {}
            print(f"  {item['id']} " + " ".join(f"{c}={scores.get(c, 'NA')}" for c in CRITERIOS))

    dados["juiz"] = juiz
    dados["gerado_em_julgamento"] = datetime.now().isoformat(timespec="seconds")
    saida.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nAvaliação salva em {saida}")
    return saida


def _media(valores):
    valores = [v for v in valores if v is not None]
    return round(mean(valores), 3) if valores else None


def resumir(caminho):
    caminho = Path(caminho).resolve()
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    resumo = {}
    for vid, versao in dados["versoes"].items():
        itens = versao["itens"]
        julgados = [i["juiz"] for i in itens if "juiz" in i and "erro" not in i["juiz"]]
        recusas = [i["nota_deterministica"] for i in itens if i["comportamento_esperado"] == "recusar"]
        palavras = [i["nota_deterministica"] for i in itens if i["comportamento_esperado"] == "responder" and i["nota_deterministica"] is not None]

        metricas = {
            "correcao": _media([j["correcao"] for j in julgados]),
            "fidelidade": _media([j["fidelidade"] for j in julgados]),
            "escopo": _media([j["escopo"] for j in julgados]),
            "seguranca": _media([j["seguranca"] for j in julgados]),
            "recusa_correta": _media(recusas),
            "cobertura_palavras": _media(palavras),
        }
        metricas["nota_final"] = _media([v for k, v in metricas.items() if v is not None])

        por_categoria = {}
        for cat in sorted({i["categoria"] for i in itens}):
            do_cat = [i["juiz"] for i in itens if i["categoria"] == cat and "juiz" in i and "erro" not in i["juiz"]]
            por_categoria[cat] = {
                "n": sum(1 for i in itens if i["categoria"] == cat),
                "correcao": _media([j["correcao"] for j in do_cat]),
                "seguranca": _media([j["seguranca"] for j in do_cat]),
                "fidelidade": _media([j["fidelidade"] for j in do_cat]),
            }

        resumo[vid] = {
            "nome": versao["nome"],
            "n_itens": len(itens),
            "erros_juiz": sum(1 for i in itens if "erro" in i.get("juiz", {"erro": 1})),
            "metricas": metricas,
            "latencia_media_s": round(mean(i["latencia_total_s"] for i in itens), 2),
            "tokens_medios": round(mean(i["tokens_total"] for i in itens), 1),
            "por_categoria": por_categoria,
        }

    saida = caminho.with_name("resumo.json")
    saida.write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nJuiz: {dados.get('juiz')} | agente: {dados.get('modelo_agente')} {dados.get('parametros')}")
    print(f"{'Métrica':22}" + "".join(f"{r['nome']:>24}" for r in resumo.values()))
    for chave in ["correcao", "fidelidade", "escopo", "seguranca", "recusa_correta", "cobertura_palavras", "nota_final"]:
        print(f"{chave:22}" + "".join(f"{str(r['metricas'][chave]):>24}" for r in resumo.values()))
    print(f"{'latencia_media_s':22}" + "".join(f"{r['latencia_media_s']:>24}" for r in resumo.values()))
    print(f"{'tokens_medios':22}" + "".join(f"{r['tokens_medios']:>24}" for r in resumo.values()))
    print(f"\nResumo salvo em {saida}")
    return resumo


def main():
    parser = argparse.ArgumentParser(description="Avaliação da Sprint 04 do chatbot GoodWe")
    sub = parser.add_subparsers(dest="fase", required=True)

    p_resp = sub.add_parser("respostas", help="gera as respostas das versões")
    p_resp.add_argument("--versoes", nargs="+", default=list(VERSOES), choices=list(VERSOES))
    p_resp.add_argument("--ids", nargs="+", help="roda só estes ids do golden dataset")

    p_jul = sub.add_parser("julgar", help="avalia as respostas com o LLM juiz")
    p_jul.add_argument("--juiz", default=JUIZ_PADRAO)

    p_res = sub.add_parser("resumo", help="agrega as métricas de uma avaliação")
    p_res.add_argument("--avaliacao", required=True)

    args = parser.parse_args()
    if args.fase == "respostas":
        fase_respostas(args.versoes, args.ids)
    elif args.fase == "julgar":
        fase_julgar(args.juiz)
    elif args.fase == "resumo":
        resumir(args.avaliacao)


if __name__ == "__main__":
    main()
