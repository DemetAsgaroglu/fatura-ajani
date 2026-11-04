from datetime import date

from schema import Fatura, Kalem
from validate import kontrol_et, tckn_gecerli, vkn_gecerli

BUGUN = date(2026, 11, 4)


def dogru_fatura(**degisen) -> Fatura:
    veri = dict(
        firma="Mavi Kalem Kırtasiye Ltd. Şti.", vkn="1234567890", fatura_no="TST2026000000001", tarih="15.03.2026",
        kalemler=[
            Kalem(ad="Kağıt", miktar=2, birim_fiyat=150.0, kdv_orani=20, tutar=300.0),
            Kalem(ad="Ekmek", miktar=10, birim_fiyat=15.5, kdv_orani=1, tutar=155.0),
        ],
        ara_toplam=455.0, kdv_toplam=61.55, genel_toplam=516.55,
    )
    veri.update(degisen)
    return Fatura(**veri)


def mesajlar(f: Fatura) -> list[str]:
    return [u.mesaj for u in kontrol_et(f, BUGUN)]


def test_vkn_ve_tckn_kontrol_hanesi():
    assert vkn_gecerli("1234567890")
    assert not vkn_gecerli("1234567891")
    assert not vkn_gecerli("12345678")
    assert tckn_gecerli("10000000146")
    assert not tckn_gecerli("10000000147")
    assert not tckn_gecerli("01234567890")


def test_dogru_fatura_uyari_vermez():
    assert mesajlar(dogru_fatura()) == []


def test_karisik_kdv_oranlari_dogru_hesaplanir():
    # %20 ve %1 ayni faturada; tek oran varsayilsaydi yanlis uyari cikardi
    assert not any("KDV" in m for m in mesajlar(dogru_fatura()))


def test_sahis_sirketi_tckn_kabul_edilir():
    assert mesajlar(dogru_fatura(vkn="10000000146")) == []
    assert "TC kimlik numarası geçersiz" in mesajlar(dogru_fatura(vkn="10000000147"))


def test_yanlis_toplamlar_yakalanir():
    assert any("genel toplama" in m for m in mesajlar(dogru_fatura(genel_toplam=600.0)))
    assert any("KDV" in m for m in mesajlar(dogru_fatura(kdv_toplam=91.0)))
    assert any("ara toplama" in m for m in mesajlar(dogru_fatura(ara_toplam=500.0, genel_toplam=561.55)))


def test_satir_hatasi_yakalanir():
    f = dogru_fatura()
    f.kalemler[0].tutar = 310.0
    assert any("'Kağıt'" in m for m in mesajlar(f))


def test_eksik_alanlar_uydurulmaz_uyari_olur():
    m = mesajlar(dogru_fatura(vkn=None, genel_toplam=None, kalemler=[]))
    assert "Vergi / TC kimlik no okunamadı" in m
    assert "Genel toplam okunamadı" in m
    assert "Faturada kalem bulunamadı" in m


def test_tarih_kontrolleri():
    assert "Tarih GG.AA.YYYY biçiminde değil" in mesajlar(dogru_fatura(tarih="2026-03-15"))
    assert "Fatura tarihi ileri bir tarih" in mesajlar(dogru_fatura(tarih="01.12.2026"))


def test_alisilmadik_kdv_orani():
    f = dogru_fatura()
    f.kalemler[0].kdv_orani = 18
    assert any("alışılmadık" in m for m in mesajlar(f))


def test_kurus_yuvarlama_farki_uyari_vermez():
    assert mesajlar(dogru_fatura(kdv_toplam=61.57, genel_toplam=516.57)) == []
