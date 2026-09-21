import pandas as pd
import pytest

from energia.etl import limpar

BASE = {
    "subsistema_id": "NE",
    "subsistema_nome": "Nordeste",
    "uf": "BA",
    "localizacao": "Interior",
    "latitude": -12.0,
    "longitude": -42.0,
    "latitude_coletora": -12.1,
    "longitude_coletora": -42.1,
    "cod_ponto_conexao": "BAPND-230-A",
    "modalidade": "Conjunto de Usinas",
    "fonte": "Eólica",
    "nome": "Conj. Teste",
    "usina_id": "CJU_BATST",
    "instante": "2025-06-01 00:00:00",
    "geracao_programada_mw": "49.00000000",
    "geracao_verificada_mw": "47.70900000",
    "capacidade_instalada_mw": "90.00000000",
    "fator_capacidade": "0.53010000",
}


def montar(*alteracoes) -> pd.DataFrame:
    """Um DataFrame no formato cru do ONS: tudo como texto, como vem no arquivo."""
    linhas = [BASE | mudanca for mudanca in (alteracoes or [{}])]
    return pd.DataFrame(linhas)


def test_converte_texto_em_numero_e_normaliza_a_fonte():
    limpo = limpar(montar())

    assert limpo["fator_capacidade"].dtype.kind == "f"
    assert limpo["fator_capacidade"].iloc[0] == pytest.approx(0.5301)
    assert limpo["fonte"].iloc[0] == "EOLICA"


def test_texto_vazio_vira_nulo_e_nao_string_vazia():
    limpo = limpar(montar({"localizacao": "", "cod_ponto_conexao": "   "}))

    assert limpo["localizacao"].iloc[0] is None
    assert limpo["cod_ponto_conexao"].iloc[0] is None


def test_geracao_programada_vazia_vira_nulo_sem_derrubar_a_linha():
    limpo = limpar(montar({"geracao_programada_mw": ""}))

    assert len(limpo) == 1
    assert pd.isna(limpo["geracao_programada_mw"].iloc[0])


def test_descarta_fator_implausivel_e_capacidade_nao_positiva():
    limpo = limpar(
        montar(
            {"usina_id": "A", "fator_capacidade": "0.5"},
            {"usina_id": "B", "fator_capacidade": "1.9"},
            {"usina_id": "C", "capacidade_instalada_mw": "0"},
        )
    )

    assert list(limpo["usina_id"]) == ["A"]


def test_sobregeracao_leve_e_mantida():
    limpo = limpar(montar({"fator_capacidade": "1.02"}))

    assert len(limpo) == 1


def test_duplicata_mantem_o_registro_mais_recente():
    limpo = limpar(
        montar(
            {"geracao_verificada_mw": "10.0", "fator_capacidade": "0.11"},
            {"geracao_verificada_mw": "20.0", "fator_capacidade": "0.22"},
        )
    )

    assert len(limpo) == 1
    assert limpo["fator_capacidade"].iloc[0] == pytest.approx(0.22)


def test_coordenada_ausente_cai_para_a_subestacao_coletora():
    limpo = limpar(montar({"latitude": None, "longitude": None}))

    assert limpo["latitude"].iloc[0] == pytest.approx(-12.1)
