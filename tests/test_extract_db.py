"""Ajan akisi ve veritabani testleri. Gemini yerine sirayla cevap donduren sahte bir model kullanilir."""

import pytest

from db import FaturaDB
from extract import oku
from llm import LLMHatasi, _json_coz
from schema import Fatura


def dogru():
    return {
        "firma": "Mavi Kalem Kırtasiye Ltd. Şti.", "vkn": "1234567890", "fatura_no": "TST2026000000001",
        "tarih": "15.03.2026",
        "kalemler": [{"ad": "Kağıt", "miktar": 2, "birim_fiyat": 150, "kdv_orani": 20, "tutar": 300}],
        "ara_toplam": 300, "kdv_toplam": 60, "genel_toplam": 360,
    }


class SahteLLM:
    def __init__(self, *cevaplar):
        self.cevaplar = list(cevaplar)
        self.talimatlar: list[str] = []

    def json_uret(self, dosya, mime, talimat, sema):
        self.talimatlar.append(talimat)
        return self.cevaplar.pop(0)


def test_sorunsuz_faturada_tek_cagri():
    llm = SahteLLM(dogru())
    okuma = oku(llm, b"x", "application/pdf")
    assert okuma.uyarilar == [] and not okuma.duzeltme_yapildi
    assert len(llm.talimatlar) == 1


def test_yanlis_okunan_alan_ikinci_turda_duzelir():
    yanlis = dogru() | {"genel_toplam": 860}  # 3 yerine 8 okunmus
    llm = SahteLLM(yanlis, dogru())
    okuma = oku(llm, b"x", "image/jpeg")
    assert okuma.duzeltme_yapildi
    assert okuma.ilk_okuma.genel_toplam == 860
    assert okuma.fatura.genel_toplam == 360 and okuma.uyarilar == []
    # ikinci talimatta kontrolun buldugu sorun ve onceki okuma modele verilmis olmali
    assert "genel toplama" in llm.talimatlar[1] and "860" in llm.talimatlar[1]


def test_faturada_gercekten_yanlis_yazan_tutar_uyari_olarak_kalir():
    hatali = dogru() | {"genel_toplam": 370}
    llm = SahteLLM(hatali, hatali)  # model ikinci bakista da ayni degeri goruyor
    okuma = oku(llm, b"x", "application/pdf")
    assert okuma.fatura.genel_toplam == 370
    assert any("genel toplama" in u.mesaj for u in okuma.uyarilar)


def test_daha_kotu_ikinci_okuma_kabul_edilmez():
    ilk = dogru() | {"genel_toplam": 370}
    daha_kotu = dogru() | {"genel_toplam": 370, "vkn": "999", "tarih": None}
    okuma = oku(SahteLLM(ilk, daha_kotu), b"x", "application/pdf")
    assert okuma.fatura.vkn == "1234567890"


class IkinciCagridaHataVerenLLM(SahteLLM):
    def json_uret(self, dosya, mime, talimat, sema):
        if self.talimatlar:
            raise LLMHatasi("Model şu an yoğun")
        return super().json_uret(dosya, mime, talimat, sema)


def test_duzeltme_turu_basarisiz_olursa_ilk_okuma_kullanilir():
    okuma = oku(IkinciCagridaHataVerenLLM(dogru() | {"genel_toplam": 370}), b"x", "application/pdf")
    assert okuma.fatura.genel_toplam == 370
    assert any(a.baslik == "Düzeltme turu yapılamadı" for a in okuma.adimlar)


def test_duzeltme_kapatilabilir():
    llm = SahteLLM(dogru() | {"genel_toplam": 370})
    okuma = oku(llm, b"x", "application/pdf", duzeltme_turu=0)
    assert not okuma.duzeltme_yapildi and len(llm.talimatlar) == 1


def test_semaya_uymayan_cevap_hata_verir():
    with pytest.raises(LLMHatasi):
        oku(SahteLLM({"kalemler": "yok"}), b"x", "application/pdf")


def test_json_kod_blogu_temizlenir():
    assert _json_coz('```json\n{"firma": "A"}\n```') == {"firma": "A"}


def test_db_oturumlar_birbirini_gormez_ve_mukerrer_engellenir():
    db = FaturaDB(":memory:")
    f = Fatura(**dogru())
    db.kaydet("a", f)
    assert db.zaten_var("a", f.vkn, f.fatura_no)
    assert not db.zaten_var("b", f.vkn, f.fatura_no)
    assert len(db.listele("a")) == 1 and db.listele("b") == []
    with pytest.raises(Exception):
        db.kaydet("a", f)  # ayni oturumda ayni fatura ikinci kez kaydedilemez
    db.sil("a", db.listele("a")[0]["id"])
    assert db.listele("a") == []


def test_hesabi_tutturmak_icin_degistirilen_birim_fiyat_geri_alinir():
    # Faturada 2 x 147,25 = 310 yazili. Model ikinci turda birim fiyati 155 yapip hesabi tutturuyor.
    hatali = dogru() | {"kalemler": [{"ad": "Kağıt", "miktar": 2, "birim_fiyat": 147.25, "kdv_orani": 20, "tutar": 310}],
                        "ara_toplam": 310, "kdv_toplam": 62, "genel_toplam": 372}
    uydurma = hatali | {"kalemler": [{"ad": "Kağıt", "miktar": 2, "birim_fiyat": 155, "kdv_orani": 20, "tutar": 310}]}
    okuma = oku(SahteLLM(hatali, uydurma), b"x", "application/pdf")
    assert okuma.fatura.kalemler[0].birim_fiyat == 147.25
    assert okuma.uyarilar  # uyari kullaniciya kalir
    assert any("geri alındı" in a.baslik for a in okuma.adimlar)
