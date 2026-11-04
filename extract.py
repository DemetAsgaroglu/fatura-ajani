"""Faturayi okuyan ajan.

1. Gemini faturayi (PDF veya fotograf) okur ve semaya uygun JSON dondurur.
2. Kod sonucu kontrol eder (toplamlar, KDV, vergi numarasi, tarih).
3. Kontrol hata bulursa hatalar modele geri verilir ve model sadece o alanlara tekrar bakar.
   Faturada gercekten yanlis yazan bir tutar varsa model onu duzeltmez; uyari kullaniciya kalir.
4. Sonuc kullaniciya onaya sunulur. Model hicbir zaman kendisi kayit yapmaz.
"""

import json
from dataclasses import dataclass, field

from pydantic import ValidationError

from llm import DosyaOkuyanLLM, LLMHatasi
from schema import Fatura
from validate import Uyari, kontrol_et

OKUMA_TALIMATI = """Bu bir Türk faturası (e-Fatura, e-Arşiv veya kağıt fatura olabilir). Bilgileri şemaya göre çıkar.
- Sayıları nokta ile ondalık yaz: 1.250,50 -> 1250.50. Para birimi sembolü yazma.
- firma ve vkn faturayı KESEN satıcıya aittir, alıcıya değil.
- Tarihi GG.AA.YYYY biçiminde yaz.
- Her kalem için KDV oranını yüzde olarak yaz (%20 -> 20).
- Faturada ne yazıyorsa onu yaz; hesaplama yapma, düzeltme yapma.
- Okuyamadığın alanı null bırak, tahmin etme."""

DUZELTME_TALIMATI = """Bu faturayı daha önce okudun ve şu sonucu çıkardın:
{onceki}

Kod kontrolü şu sorunları buldu:
{sorunlar}

Faturaya tekrar bak ve sadece bu sorunlarla ilgili alanları kontrol et. Yanlış okuduğun bir değer varsa düzelt.
Faturada gerçekten öyle yazıyorsa değeri DEĞİŞTİRME: amacımız faturada yazanı aynen almak, hesabı tutturmak değil.
Bütün faturayı aynı şemaya göre tekrar döndür.
""" + "\n" + OKUMA_TALIMATI


@dataclass
class Adim:
    baslik: str
    detay: str = ""


@dataclass
class Okuma:
    fatura: Fatura
    uyarilar: list[Uyari]
    adimlar: list[Adim] = field(default_factory=list)
    ilk_okuma: Fatura | None = None  # duzeltme oncesi; degerlendirmede karsilastirmak icin
    duzeltme_yapildi: bool = False


def _faturaya_cevir(veri: dict) -> Fatura:
    try:
        return Fatura.model_validate(veri)
    except ValidationError as exc:
        raise LLMHatasi(f"Model şemaya uymayan bir cevap döndürdü: {exc.errors()[0]['msg']}") from exc


def _sorun_listesi(uyarilar: list[Uyari]) -> str:
    return "\n".join(f"- {u.mesaj}" for u in uyarilar)


def _tek_rakam_farki(a: float | None, b: float | None) -> bool:
    """Iki sayi en fazla bir rakam eklenmesi, silinmesi veya degismesiyle birbirine donusuyor mu?"""
    if a is None or b is None:
        return True
    x, y = f"{a:.2f}", f"{b:.2f}"
    if len(x) == len(y):
        return sum(c != d for c, d in zip(x, y)) <= 1
    kisa, uzun = sorted((x, y), key=len)
    return len(uzun) - len(kisa) == 1 and any(uzun[:i] + uzun[i + 1:] == kisa for i in range(len(uzun)))


def _uydurma_degisiklikleri_geri_al(ilk: Fatura, yeni: Fatura) -> tuple[Fatura, list[str]]:
    """Duzeltme turunda birden fazla rakami degisen sayilari ilk okumadaki haline dondurur.

    Gercek okuma hatalari genelde tek rakamdir (3 ile 8'in karismasi gibi). Model bir sayiyi tamamen
    degistirdiyse buyuk ihtimalle faturada yazani degil, hesabi tutturan degeri yazmistir.
    """
    geri_alinan = []
    veri = yeni.model_dump()
    for alan in ("ara_toplam", "kdv_toplam", "genel_toplam"):
        if not _tek_rakam_farki(getattr(ilk, alan), getattr(yeni, alan)):
            veri[alan] = getattr(ilk, alan)
            geri_alinan.append(alan)
    if len(ilk.kalemler) == len(yeni.kalemler):
        for i, (k1, k2) in enumerate(zip(ilk.kalemler, yeni.kalemler)):
            for alan in ("miktar", "birim_fiyat", "kdv_orani", "tutar"):
                if not _tek_rakam_farki(getattr(k1, alan), getattr(k2, alan)):
                    veri["kalemler"][i][alan] = getattr(k1, alan)
                    geri_alinan.append(f"{i + 1}. kalem {alan}")
    return Fatura.model_validate(veri), geri_alinan


def oku(llm: DosyaOkuyanLLM, dosya: bytes, mime: str, duzeltme_turu: int = 1) -> Okuma:
    adimlar = [Adim("Fatura modele gönderildi", mime)]
    fatura = _faturaya_cevir(llm.json_uret(dosya, mime, OKUMA_TALIMATI, Fatura))
    ilk = fatura
    uyarilar = kontrol_et(fatura)
    adimlar.append(Adim("Kod kontrolü", "Sorun yok" if not uyarilar else _sorun_listesi(uyarilar)))

    duzeltme_yapildi = False
    for tur in range(duzeltme_turu):
        if not uyarilar:
            break
        talimat = DUZELTME_TALIMATI.format(
            onceki=json.dumps(fatura.model_dump(), ensure_ascii=False, indent=1),
            sorunlar=_sorun_listesi(uyarilar),
        )
        try:
            yeni = _faturaya_cevir(llm.json_uret(dosya, mime, talimat, Fatura))
        except LLMHatasi as exc:
            # Ilk okuma elimizde; duzeltme turu yapilamadi diye kullaniciyi bos ekranla birakmiyoruz
            adimlar.append(Adim("Düzeltme turu yapılamadı", f"{exc}\nİlk okuma kullanıcıya gösteriliyor"))
            break
        yeni, geri_alinan = _uydurma_degisiklikleri_geri_al(fatura, yeni)
        if geri_alinan:
            adimlar.append(Adim("Hesabı tutturmak için değiştirilen değerler geri alındı",
                                f"Birden fazla rakamı değişen alanlar: {', '.join(geri_alinan)}"))
        yeni_uyarilar = kontrol_et(yeni)
        duzeltme_yapildi = True
        degisen = [alan for alan in Fatura.model_fields if getattr(yeni, alan) != getattr(fatura, alan)]
        # Ikinci okuma daha fazla sorun getirdiyse ilk okumada kalinir
        if len(yeni_uyarilar) <= len(uyarilar):
            fatura, uyarilar = yeni, yeni_uyarilar
            sonuc = f"Değişen alanlar: {', '.join(degisen)}" if degisen else "Model değerleri değiştirmedi"
        else:
            sonuc = "Yeni okuma daha fazla sorun içerdiği için ilk okuma korundu"
        kalan = "Kalan sorun yok" if not uyarilar else f"Kalan sorunlar:\n{_sorun_listesi(uyarilar)}"
        adimlar.append(Adim(f"Sorunlu alanlar modele tekrar okutuldu ({tur + 1}. tur)", f"{sonuc}\n{kalan}"))

    adimlar.append(Adim("Kullanıcı onayı bekleniyor",
                        "Uyarılar faturada gerçekten yanlış yazan değerleri gösteriyor olabilir"
                        if uyarilar else "Bütün kontroller geçti"))
    return Okuma(fatura, uyarilar, adimlar, ilk_okuma=ilk, duzeltme_yapildi=duzeltme_yapildi)
