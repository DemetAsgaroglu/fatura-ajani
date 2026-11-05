"""Arayuzun okuma sonrasi akisi. Model cagrilmaz; okuma sonucu oturuma hazir konur."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import db as db_modulu
from extract import Adim, Okuma
from schema import Fatura
from validate import kontrol_et

KOK = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def gecici_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db_modulu, "VARSAYILAN_DB", tmp_path / "test.db")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def hazir_uygulama(ornek: str) -> AppTest:
    veri = json.loads((KOK / "samples" / f"{ornek}.json").read_text(encoding="utf-8"))
    fatura = Fatura(**veri["fatura"])
    at = AppTest.from_file(str(KOK / "app.py"), default_timeout=30)
    at.session_state["okuma"] = Okuma(fatura, kontrol_et(fatura), [Adim("Test", "")], ilk_okuma=fatura)
    at.session_state["dosya"] = (f"{ornek}.pdf", (KOK / "samples" / f"{ornek}.pdf").read_bytes(), "application/pdf")
    at.session_state["anahtar"] = "t"
    at.session_state["oturum"] = "test"
    return at.run()


def test_temiz_fatura_onaylanip_kaydedilir():
    at = hazir_uygulama("fatura_02")
    assert not at.exception
    assert any("Bütün kontroller geçti" in s.value for s in at.success)
    kaydet = next(b for b in at.button if b.label == "Onayla ve kaydet")
    assert not kaydet.disabled
    at = kaydet.click().run()
    assert not at.exception
    assert len(at.dataframe) == 1  # kayitli faturalar tablosu


def test_hatali_faturada_kayit_onay_kutusu_olmadan_kapali():
    at = hazir_uygulama("fatura_09")  # genel toplami bilerek yanlis yazilmis fatura
    assert not at.exception
    assert any("genel toplama" in w.value for w in at.warning)
    kaydet = next(b for b in at.button if b.label == "Onayla ve kaydet")
    assert kaydet.disabled
    at.checkbox[0].check().run()
    assert not next(b for b in at.button if b.label == "Onayla ve kaydet").disabled


def test_kullanici_duzeltince_uyari_kalkar():
    at = hazir_uygulama("fatura_09")
    dogru_toplam = 2716.23
    at.number_input(key="t_genel_toplam").set_value(dogru_toplam).run()
    assert not at.exception
    assert any("Bütün kontroller geçti" in s.value for s in at.success)
