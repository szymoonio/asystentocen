"""Router modułu ASSISTANT (agent B). Stub z kroku 0 — agent B rozwija dowolnie."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.templating import render

router = APIRouter()


@router.get("/teczka")
def teczka(request: Request):
    return render(
        request,
        "placeholder.html",
        title="Teczka",
        owner="B",
        what="Notatki o podwładnych (opis, zalety, obszary do poprawy, suwaki), notatki głosowe, historia.",
    )


@router.get("/teczka/{subject_id}")
def teczka_osoby(subject_id: str, request: Request):
    return render(
        request,
        "placeholder.html",
        title="Teczka pracownika",
        owner="B",
        what=f"Oś czasu notatek o pracowniku {subject_id} i zestawienie suwaków per kryterium.",
    )


@router.get("/hr")
def hr_partner(request: Request):
    return render(
        request,
        "placeholder.html",
        title="Asystent HR",
        owner="B",
        what="Przygotowanie do trudnej rozmowy, próba rozmowy, notatka → informacja zwrotna, pytania o procedury.",
    )
