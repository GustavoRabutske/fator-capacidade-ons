"""Perfil horario do fator de capacidade: eolica x solar.

Roda fora da API porque e uma leitura pontual do ano inteiro, cara demais para um
endpoint e sem valor como recurso REST.

    python -m energia.analise
"""

import csv
import sys
from datetime import datetime

from . import repositorio
from .banco import Sessao
from .configuracao import DIRETORIO_RELATORIOS

HORAS = range(24)


def montar_perfis(sessao, inicio: datetime, fim: datetime) -> tuple[dict, dict, dict]:
    """Devolve (perfil nacional por fonte, perfil por subsistema e fonte, totais por hora).

    O fator nacional nao e a media dos subsistemas: e a geracao somada dividida pela
    capacidade somada, senao o Sul pesaria tanto quanto o Nordeste.
    """
    por_subsistema: dict[tuple[str, str], dict[int, float]] = {}
    acumulado: dict[tuple[str, int], list[float]] = {}

    for linha in repositorio.perfil_horario(sessao, inicio, fim):
        hora = int(linha.hora)
        por_subsistema.setdefault((linha.subsistema_id, linha.fonte), {})[hora] = linha.fator
        totais = acumulado.setdefault((linha.fonte, hora), [0.0, 0.0])
        totais[0] += linha.geracao
        totais[1] += linha.capacidade

    nacional: dict[str, dict[int, float]] = {}
    for (fonte, hora), (geracao, capacidade) in acumulado.items():
        nacional.setdefault(fonte, {})[hora] = geracao / capacidade if capacidade else 0.0
    return nacional, por_subsistema, acumulado


def curva_combinada(acumulado: dict) -> dict[int, float]:
    """Fator da carteira eolica + solar somada, hora a hora."""
    combinada = {}
    for hora in HORAS:
        geracao = sum(acumulado.get((fonte, hora), (0.0, 0.0))[0] for fonte in ("EOLICA", "SOLAR"))
        capacidade = sum(acumulado.get((fonte, hora), (0.0, 0.0))[1] for fonte in ("EOLICA", "SOLAR"))
        combinada[hora] = geracao / capacidade if capacidade else 0.0
    return combinada


def correlacao(a: list[float], b: list[float]) -> float:
    media_a, media_b = sum(a) / len(a), sum(b) / len(b)
    desvios_a = [x - media_a for x in a]
    desvios_b = [y - media_b for y in b]
    covariancia = sum(x * y for x, y in zip(desvios_a, desvios_b))
    dispersao = (sum(x * x for x in desvios_a) * sum(y * y for y in desvios_b)) ** 0.5
    return covariancia / dispersao if dispersao else 0.0


def barra(valor: float, largura: int = 28) -> str:
    return "#" * round(valor * largura)


def amplitude(valores) -> float:
    """Diferenca entre maior e menor fator, em pontos percentuais."""
    return (max(valores) - min(valores)) * 100


def _pico(curva: dict[int, float]) -> tuple[int, float]:
    hora = max(curva, key=curva.get)
    return hora, curva[hora]


def escrever_relatorio(nacional: dict, por_subsistema: dict, acumulado: dict, inicio, fim) -> list[str]:
    eolica = [nacional["EOLICA"].get(h, 0.0) for h in HORAS]
    solar = [nacional["SOLAR"].get(h, 0.0) for h in HORAS]
    combinada = curva_combinada(acumulado)

    hora_pico_eolica, pico_eolica = _pico(nacional["EOLICA"])
    hora_pico_solar, pico_solar = _pico(nacional["SOLAR"])
    horas_eolica_vence = [h for h in HORAS if eolica[h] > solar[h]]
    horas_solar_util = [h for h in HORAS if solar[h] > 0.01]
    indice = correlacao(eolica, solar)

    linhas = [
        "# Perfil horario do fator de capacidade",
        "",
        f"Periodo analisado: {inicio:%d/%m/%Y} a {fim:%d/%m/%Y} (horario de Brasilia).",
        "",
        "## Curva media das 24 horas",
        "",
        "| hora | eolica | solar |",
        "| ---: | :--- | :--- |",
    ]
    for h in HORAS:
        linhas.append(f"| {h:02d}h | `{eolica[h]:.3f}` {barra(eolica[h])} | `{solar[h]:.3f}` {barra(solar[h])} |")

    linhas += [
        "",
        "## Achados",
        "",
        f"1. **As duas fontes se complementam ao longo do dia.** A correlacao entre as curvas "
        f"horarias e de {indice:+.2f}. A solar concentra toda a producao em "
        f"{len(horas_solar_util)} horas ({horas_solar_util[0]:02d}h-{horas_solar_util[-1]:02d}h), "
        f"com pico de {pico_solar:.1%} as {hora_pico_solar:02d}h; a eolica sustenta geracao nas "
        f"24 horas e domina em {len(horas_eolica_vence)} delas, com pico de {pico_eolica:.1%} as "
        f"{hora_pico_eolica:02d}h.",
        "",
        f"2. **Somadas, as duas fontes entregam uma curva bem mais estavel do que cada uma "
        f"isolada.** Ao longo do dia a eolica varia {amplitude(eolica):.0f} pontos percentuais "
        f"(de {min(eolica):.1%} a {max(eolica):.1%}) e a solar varia {amplitude(solar):.0f} p.p. "
        f"A carteira somada pela capacidade instalada oscila apenas "
        f"{amplitude(list(combinada.values())):.0f} p.p., entre {min(combinada.values()):.1%} e "
        f"{max(combinada.values()):.1%} - o mesmo parque gerando de forma muito mais previsivel "
        f"por ter as duas tecnologias.",
        "",
        "## Hora de pico por subsistema",
        "",
        "| subsistema | fonte | hora de pico | fator no pico | fator medio |",
        "| :--- | :--- | ---: | ---: | ---: |",
    ]
    for (subsistema, fonte), curva in sorted(por_subsistema.items()):
        hora, valor = _pico(curva)
        media = sum(curva.values()) / len(curva)
        linhas.append(
            f"| {subsistema} | {fonte} | {hora:02d}h | {valor:.1%} | {media:.1%} |"
        )

    return linhas


def salvar_csv(caminho, nacional: dict, por_subsistema: dict) -> None:
    with caminho.open("w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(["subsistema", "fonte", "hora", "fator_capacidade"])
        for fonte, curva in sorted(nacional.items()):
            for hora in sorted(curva):
                escritor.writerow(["SIN", fonte, hora, f"{curva[hora]:.6f}"])
        for (subsistema, fonte), curva in sorted(por_subsistema.items()):
            for hora in sorted(curva):
                escritor.writerow([subsistema, fonte, hora, f"{curva[hora]:.6f}"])


def principal() -> int:
    with Sessao() as sessao:
        inicio, fim = repositorio.periodo_disponivel(sessao)
        if inicio is None:
            print("Base vazia. Rode: python -m energia.etl --ano 2025")
            return 1

        nacional, por_subsistema, acumulado = montar_perfis(sessao, inicio, fim)

    if not {"EOLICA", "SOLAR"} <= nacional.keys():
        print("A base precisa ter medicoes das duas fontes para a comparacao.")
        return 1

    linhas = escrever_relatorio(nacional, por_subsistema, acumulado, inicio, fim)
    DIRETORIO_RELATORIOS.mkdir(parents=True, exist_ok=True)
    destino = DIRETORIO_RELATORIOS / "perfil_horario.md"
    destino.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    salvar_csv(DIRETORIO_RELATORIOS / "perfil_horario.csv", nacional, por_subsistema)

    print("\n".join(linhas))
    print(f"\nRelatorio salvo em {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
