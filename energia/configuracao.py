"""Configuracao lida do ambiente, com defaults que funcionam sem nenhum setup."""

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

URL_BANCO = os.getenv("ENERGIA_URL_BANCO", f"sqlite:///{RAIZ / 'energia.db'}")
DIRETORIO_DADOS = Path(os.getenv("ENERGIA_DIRETORIO_DADOS", RAIZ / "dados"))
DIRETORIO_RELATORIOS = Path(os.getenv("ENERGIA_DIRETORIO_RELATORIOS", RAIZ / "relatorios"))

ANO_PADRAO = int(os.getenv("ENERGIA_ANO", "2025"))

URL_BASE_ONS = "https://ons-aws-prod-opendata.s3.amazonaws.com/dataset/fator_capacidade_2_di"

# Janela maxima para a serie horaria: um ano inteiro em base horaria sao ~2 milhoes
# de linhas e a agregacao fica cara sem trazer nada de util para o cliente.
MAX_DIAS_SERIE_HORARIA = 31
