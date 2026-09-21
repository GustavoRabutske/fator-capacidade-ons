from datetime import date

import pytest

from energia import servicos
from energia.esquemas import Fonte, Granularidade
from energia.servicos import DadosIndisponiveis, ParametroInvalido

INICIO = date(2025, 6, 1)
FIM = date(2025, 6, 3)


def _por_chave(itens):
    return {(item.subsistema, item.fonte.value): item for item in itens}


def test_fator_agregado_e_ponderado_pela_capacidade(sessao_populada):
    """As duas eolicas do NE tem 100 MW a fator 0,48 e 300 MW a fator 0,24.

    Ponderado: (48 + 72) / 400 = 0,30. A media simples dos fatores daria 0,36.
    """
    atual = _por_chave(servicos.obter_ultima_medicao(sessao_populada))

    assert atual[("NE", "EOLICA")].fator_capacidade == pytest.approx(0.30)
    assert atual[("NE", "EOLICA")].capacidade_instalada_mw == pytest.approx(400.0)
    assert atual[("NE", "EOLICA")].usinas == 2


def test_ultima_medicao_usa_a_ultima_hora_disponivel(sessao_populada):
    atual = servicos.obter_ultima_medicao(sessao_populada)

    assert {item.instante.isoformat() for item in atual} == {"2025-06-03T23:00:00"}
    # 23h esta fora da janela solar, entao o fator do NE solar e zero e nao ausente.
    assert _por_chave(atual)[("NE", "SOLAR")].fator_capacidade == 0.0


def test_ultima_medicao_filtra_por_fonte(sessao_populada):
    atual = servicos.obter_ultima_medicao(sessao_populada, fonte=Fonte.EOLICA)

    assert {item.fonte for item in atual} == {Fonte.EOLICA}
    assert {item.subsistema for item in atual} == {"NE", "S"}


def test_ultima_medicao_sem_medicoes(sessao):
    with pytest.raises(DadosIndisponiveis):
        servicos.obter_ultima_medicao(sessao)


def test_historico_diario_agrupa_por_dia(sessao_populada):
    serie = servicos.obter_historico(sessao_populada, INICIO, FIM, Granularidade.DIA)

    # 3 dias x 3 combinacoes de subsistema/fonte.
    assert serie.total_pontos == 9
    assert {ponto.instante.hour for ponto in serie.pontos} == {0}
    assert {ponto.instante.date() for ponto in serie.pontos} == {
        date(2025, 6, 1),
        date(2025, 6, 2),
        date(2025, 6, 3),
    }


def test_historico_horario_devolve_uma_linha_por_hora(sessao_populada):
    serie = servicos.obter_historico(
        sessao_populada,
        INICIO,
        INICIO,
        Granularidade.HORA,
        subsistema="NE",
        fonte=Fonte.SOLAR,
    )

    assert serie.total_pontos == 24
    meio_dia = next(p for p in serie.pontos if p.instante.hour == 12)
    assert meio_dia.fator_capacidade == pytest.approx(0.60)
    assert meio_dia.geracao_media_mw == pytest.approx(60.0)


def test_historico_horario_recusa_janela_acima_do_limite(sessao_populada):
    with pytest.raises(ParametroInvalido, match="31 dias"):
        servicos.obter_historico(
            sessao_populada, date(2025, 1, 1), date(2025, 12, 31), Granularidade.HORA
        )


def test_historico_diario_aceita_o_ano_inteiro(sessao_populada):
    serie = servicos.obter_historico(
        sessao_populada, date(2025, 1, 1), date(2025, 12, 31), Granularidade.DIA
    )

    assert serie.total_pontos == 9


def test_intervalo_invertido_e_rejeitado(sessao_populada):
    with pytest.raises(ParametroInvalido, match="posterior"):
        servicos.obter_historico(sessao_populada, FIM, INICIO, Granularidade.DIA)


def test_subsistema_desconhecido_e_rejeitado(sessao_populada):
    with pytest.raises(ParametroInvalido, match="SE"):
        servicos.obter_historico(
            sessao_populada, INICIO, FIM, Granularidade.DIA, subsistema="SE"
        )


def test_comparativo_traz_a_hora_de_pico_de_cada_fonte(sessao_populada):
    comparativo = {item.subsistema: item for item in servicos.comparar_fontes(sessao_populada, INICIO, FIM)}

    nordeste = comparativo["NE"]
    assert nordeste.eolica.hora_pico == 21
    assert nordeste.solar.hora_pico == 12
    assert nordeste.solar.fator_no_pico == pytest.approx(0.60)
    assert nordeste.diferenca_fator == pytest.approx(
        nordeste.eolica.fator_capacidade - nordeste.solar.fator_capacidade
    )


def test_comparativo_sem_solar_no_subsistema(sessao_populada):
    comparativo = servicos.comparar_fontes(sessao_populada, INICIO, FIM, subsistema="S")

    assert len(comparativo) == 1
    assert comparativo[0].solar is None
    assert comparativo[0].diferenca_fator is None


def test_comparativo_em_periodo_vazio(sessao_populada):
    with pytest.raises(DadosIndisponiveis):
        servicos.comparar_fontes(sessao_populada, date(2024, 1, 1), date(2024, 1, 31))
