INTERVALO = {"inicio": "2025-06-01", "fim": "2025-06-03"}


def test_saude_informa_o_periodo_carregado(cliente):
    resposta = cliente.get("/saude")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["status"] == "ok"
    assert corpo["periodo_carregado"]["fim"] == "2025-06-03T23:00:00"
    assert corpo["subsistemas"] == ["NE", "S"]


def test_documentacao_e_servida(cliente):
    assert cliente.get("/docs").status_code == 200
    assert "/geracao/comparativo" in cliente.get("/openapi.json").json()["paths"]


def test_ultima_medicao(cliente):
    resposta = cliente.get("/geracao/ultima-medicao")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert len(corpo) == 3
    nordeste_eolico = next(
        item for item in corpo if item["subsistema"] == "NE" and item["fonte"] == "EOLICA"
    )
    assert nordeste_eolico == {
        "subsistema": "NE",
        "nome_subsistema": "Nordeste",
        "fonte": "EOLICA",
        "instante": "2025-06-03T23:00:00",
        "fator_capacidade": 0.3,
        "geracao_verificada_mw": 120.0,
        "capacidade_instalada_mw": 400.0,
        "usinas": 2,
    }


def test_ultima_medicao_filtrada_por_fonte(cliente):
    resposta = cliente.get("/geracao/ultima-medicao", params={"fonte": "SOLAR"})

    assert resposta.status_code == 200
    assert [item["subsistema"] for item in resposta.json()] == ["NE"]


def test_ultima_medicao_com_fonte_invalida(cliente):
    assert cliente.get("/geracao/ultima-medicao", params={"fonte": "NUCLEAR"}).status_code == 422


def test_ultima_medicao_sem_carga_no_banco(cliente_sem_dados):
    resposta = cliente_sem_dados.get("/geracao/ultima-medicao")

    assert resposta.status_code == 404
    assert "ETL" in resposta.json()["detail"]


def test_historico_diario_filtrado(cliente):
    resposta = cliente.get(
        "/geracao/historico", params={**INTERVALO, "subsistema": "NE", "fonte": "EOLICA"}
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["granularidade"] == "dia"
    assert corpo["total_pontos"] == 3
    assert all(ponto["fator_capacidade"] > 0 for ponto in corpo["pontos"])


def test_historico_horario(cliente):
    resposta = cliente.get(
        "/geracao/historico",
        params={"inicio": "2025-06-01", "fim": "2025-06-01", "granularidade": "hora"},
    )

    corpo = resposta.json()
    assert corpo["total_pontos"] == 24 * 3
    assert corpo["pontos"][0]["instante"] == "2025-06-01T00:00:00"


def test_historico_horario_com_janela_longa_demais(cliente):
    resposta = cliente.get(
        "/geracao/historico",
        params={"inicio": "2025-01-01", "fim": "2025-12-31", "granularidade": "hora"},
    )

    assert resposta.status_code == 422
    assert "granularidade=dia" in resposta.json()["detail"]


def test_historico_com_subsistema_inexistente(cliente):
    resposta = cliente.get("/geracao/historico", params={**INTERVALO, "subsistema": "XX"})

    assert resposta.status_code == 422
    assert "desconhecido" in resposta.json()["detail"]


def test_historico_exige_o_intervalo(cliente):
    assert cliente.get("/geracao/historico").status_code == 422


def test_comparativo(cliente):
    resposta = cliente.get("/geracao/comparativo", params=INTERVALO)

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert [item["subsistema"] for item in corpo] == ["NE", "S"]

    nordeste = corpo[0]
    assert nordeste["eolica"]["hora_pico"] == 21
    assert nordeste["solar"]["hora_pico"] == 12
    assert nordeste["diferenca_fator"] > 0
    assert corpo[1]["solar"] is None
