"""Faturanin kodla kontrolu. Hesaplari modele degil buraya yaptiriyoruz.

Her kontrol bir Uyari listesi dondurur; bos liste faturada sorun bulunmadigi anlamina gelir.
"""

from dataclasses import dataclass
from datetime import date, datetime

from schema import Fatura

GECERLI_KDV_ORANLARI = {0, 1, 10, 20}
ZORUNLU_ALANLAR = {
    "firma": "Firma",
    "vkn": "Vergi / TC kimlik no",
    "fatura_no": "Fatura no",
    "tarih": "Tarih",
    "genel_toplam": "Genel toplam",
}


@dataclass(frozen=True)
class Uyari:
    alan: str  # arayuzde hangi alanin isaretlenecegi
    mesaj: str


def _yakin(a: float, b: float, tolerans: float = 0.05) -> bool:
    return abs(a - b) <= tolerans


def vkn_gecerli(vkn: str) -> bool:
    """10 haneli vergi kimlik numarasinin kontrol hanesini dogrular."""
    if len(vkn) != 10 or not vkn.isdigit():
        return False
    toplam = 0
    for i in range(9):
        v1 = (int(vkn[i]) + 9 - i) % 10
        v2 = (v1 * 2 ** (9 - i)) % 9
        if v1 != 0 and v2 == 0:
            v2 = 9
        toplam += v2
    return (10 - toplam % 10) % 10 == int(vkn[9])


def tckn_gecerli(tckn: str) -> bool:
    """11 haneli TC kimlik numarasini dogrular. Sahis sirketleri faturaya VKN yerine bunu yazar."""
    if len(tckn) != 11 or not tckn.isdigit() or tckn[0] == "0":
        return False
    d = [int(c) for c in tckn]
    onuncu = ((d[0] + d[2] + d[4] + d[6] + d[8]) * 7 - (d[1] + d[3] + d[5] + d[7])) % 10
    return onuncu == d[9] and sum(d[:10]) % 10 == d[10]


def _eksik_alanlar(f: Fatura) -> list[Uyari]:
    uyarilar = [Uyari(alan, f"{ad} okunamadı") for alan, ad in ZORUNLU_ALANLAR.items()
                if getattr(f, alan) in (None, "")]
    if not f.kalemler:
        uyarilar.append(Uyari("kalemler", "Faturada kalem bulunamadı"))
    return uyarilar


def _kalem_kontrolleri(f: Fatura) -> list[Uyari]:
    uyarilar = []
    for i, k in enumerate(f.kalemler, 1):
        ad = k.ad or f"{i}. kalem"
        if None in (k.miktar, k.birim_fiyat, k.tutar):
            uyarilar.append(Uyari("kalemler", f"'{ad}': miktar, birim fiyat veya tutar eksik"))
        elif not _yakin(k.miktar * k.birim_fiyat, k.tutar):
            uyarilar.append(Uyari("kalemler", f"'{ad}': miktar x birim fiyat ({k.miktar * k.birim_fiyat:.2f}) "
                                              f"tutara ({k.tutar:.2f}) eşit değil"))
        if k.kdv_orani is None:
            uyarilar.append(Uyari("kalemler", f"'{ad}': KDV oranı eksik"))
        elif k.kdv_orani not in GECERLI_KDV_ORANLARI:
            uyarilar.append(Uyari("kalemler", f"'{ad}': %{k.kdv_orani:g} alışılmadık bir KDV oranı"))
    return uyarilar


def _toplam_kontrolleri(f: Fatura) -> list[Uyari]:
    uyarilar = []
    kalemler = [k for k in f.kalemler if k.tutar is not None]
    # Her satir kurusa yuvarlandigi icin satir sayisi arttikca kucuk farklar birikebilir
    tolerans = 0.05 + 0.01 * len(kalemler)

    if kalemler and f.ara_toplam is not None:
        toplam = sum(k.tutar for k in kalemler)
        if not _yakin(toplam, f.ara_toplam, tolerans):
            uyarilar.append(Uyari("ara_toplam", f"Kalemlerin toplamı ({toplam:.2f}) ara toplama "
                                                f"({f.ara_toplam:.2f}) eşit değil"))

    oranli = [k for k in kalemler if k.kdv_orani is not None]
    if oranli and len(oranli) == len(kalemler) and f.kdv_toplam is not None:
        beklenen = sum(k.tutar * k.kdv_orani / 100 for k in oranli)
        if not _yakin(beklenen, f.kdv_toplam, tolerans):
            uyarilar.append(Uyari("kdv_toplam", f"Kalemlere göre KDV {beklenen:.2f} olmalı, "
                                                f"faturada {f.kdv_toplam:.2f}"))

    if None not in (f.ara_toplam, f.kdv_toplam, f.genel_toplam):
        if not _yakin(f.ara_toplam + f.kdv_toplam, f.genel_toplam):
            uyarilar.append(Uyari("genel_toplam", f"Ara toplam + KDV ({f.ara_toplam + f.kdv_toplam:.2f}) "
                                                  f"genel toplama ({f.genel_toplam:.2f}) eşit değil"))
    return uyarilar


def _kimlik_ve_tarih(f: Fatura, bugun: date) -> list[Uyari]:
    uyarilar = []
    if f.vkn:
        no = f.vkn.replace(" ", "")
        if len(no) == 11:
            if not tckn_gecerli(no):
                uyarilar.append(Uyari("vkn", "TC kimlik numarası geçersiz"))
        elif not vkn_gecerli(no):
            uyarilar.append(Uyari("vkn", "Vergi numarası geçersiz"))
    if f.tarih:
        try:
            tarih = datetime.strptime(f.tarih.strip(), "%d.%m.%Y").date()
        except ValueError:
            uyarilar.append(Uyari("tarih", "Tarih GG.AA.YYYY biçiminde değil"))
        else:
            if tarih > bugun:
                uyarilar.append(Uyari("tarih", "Fatura tarihi ileri bir tarih"))
    return uyarilar


def kontrol_et(f: Fatura, bugun: date | None = None) -> list[Uyari]:
    bugun = bugun or date.today()
    return _eksik_alanlar(f) + _kalem_kontrolleri(f) + _toplam_kontrolleri(f) + _kimlik_ve_tarih(f, bugun)
