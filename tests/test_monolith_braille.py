"""Teclado Braille del monolito (app/), que sigue desplegado hasta el corte.

Es la misma tabla que la de accessibility-backend-service; aquí se comprueba
que la copia del monolito traduce igual y que su ruta responde.
"""

import pytest
from fastapi.testclient import TestClient

from monolith import load_main

client = TestClient(load_main().app)

# Mismo nombre con el que lo importa el monolito, para no cargar otra copia.
from application.services.braille_translator import MAX_CELLS, translate  # noqa: E402

A, B, C, E, H, N, O, X = [1], [1, 2], [1, 4], [1, 5], [1, 2, 5], [1, 3, 4, 5], [1, 3, 5], [1, 3, 4, 6]
CAPITAL, NUMBER = [4, 6], [3, 4, 5, 6]


@pytest.mark.parametrize(
    "cells, text",
    [
        ([H, O, [1, 2, 3], A], "hola"),
        ([A, [], B], "a b"),
        ([[1, 2, 4, 5, 6], [1, 2, 3, 5, 6], [3, 4, 6]], "ñáó"),
        ([[5, 2, 1, 1]], "h"),
        ([CAPITAL, A, A], "Aa"),
        ([CAPITAL, CAPITAL, A, B, [], A], "AB a"),
        ([NUMBER, A, B, C, [], A], "123 a"),
        ([NUMBER, C, [2], E], "3,5"),
        ([A, [2, 6]], "a?"),
        ([A, N, A, [5], X, [3], C, O], "ana@x.co"),
        ([A, N, A, NUMBER, A, [5], X], "ana1@x"),
    ],
)
def test_translates_like_the_accessibility_service(cells, text):
    assert translate(cells).text == text


def test_unknown_combination_is_reported_not_invented():
    result = translate([A, [4, 5]])

    assert result.text == "a"
    assert result.unrecognized == [1]
    assert "4, 5" in result.cells[1].spoken


def test_each_cell_says_how_to_read_it_aloud():
    spoken = [cell.spoken for cell in translate([CAPITAL, A, [], [3]]).cells]

    assert spoken == ["mayúscula", "A mayúscula", "espacio", "punto"]


def test_translator_rejects_bad_input():
    with pytest.raises(ValueError):
        translate([[7]])
    with pytest.raises(ValueError):
        translate([A] * (MAX_CELLS + 1))


def test_endpoint_returns_text_and_cells():
    response = client.post("/api/braille/translate", json={"cells": [H, O]})

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "ho"
    assert [cell["value"] for cell in body["cells"]] == ["h", "o"]
    assert body["unrecognized"] == []


def test_endpoint_rejects_dots_out_of_range():
    assert client.post("/api/braille/translate", json={"cells": [[0]]}).status_code == 422


def test_endpoint_refuses_more_cells_than_the_limit():
    response = client.post("/api/braille/translate", json={"cells": [A] * (MAX_CELLS + 1)})

    assert response.status_code == 413
