"""Pruebas de la normalizacion de texto."""

from __future__ import annotations

import pytest

from src.utils.texto import empieza_con_alguno, normalizar


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("México", "mexico"),
        ("MÉXICO", "mexico"),
        ("Administrador De Sistemas", "administrador de sistemas"),
        ("  OAT/Cedis/BY  ", "oat/cedis/by"),
        ("OAT/CEDIS/BY", "oat/cedis/by"),
        ("Cedis  5687   Salinas", "cedis 5687 salinas"),
        ("Corporativo", "corporativo"),
        ("0520", "0520"),
    ],
)
def test_normalizar_quita_acentos_y_colapsa_espacios(entrada, esperado):
    assert normalizar(entrada) == esperado


@pytest.mark.parametrize("entrada", [None, "", "   ", "\n\t"])
def test_normalizar_tolera_valores_vacios(entrada):
    assert normalizar(entrada) == ""


def test_normalizar_es_idempotente():
    """Normalizar dos veces da el mismo resultado que normalizar una vez."""
    valor = "  Gerente   De  Tienda  "
    assert normalizar(normalizar(valor)) == normalizar(valor)


def test_normalizar_conserva_el_cero_a_la_izquierda():
    """Las oficinas son codigos de texto: '0520' nunca debe volverse '520'."""
    assert normalizar("0520") == "0520"


@pytest.mark.parametrize(
    ("descripcion", "esperado"),
    [
        ("Administrador De Sistemas", True),
        ("Gerente Tienda", True),
        ("Gerente de Tienda", True),
        ("GERENTE EN ENTRENAMIENTO", True),
        ("Administrador Sistemas 1602 Arco Norte", True),
        ("Mozo", False),
        ("Supervisor", False),
        ("Encargado de soporte tecnico", False),
        ("Subgerente", False),
        ("", False),
        (None, False),
    ],
)
def test_empieza_con_alguno(descripcion, esperado):
    assert empieza_con_alguno(descripcion, ("gerente", "admin")) is esperado
