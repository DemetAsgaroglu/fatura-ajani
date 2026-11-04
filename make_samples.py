"""Degerlendirme ve demo icin test faturalari uretir.

Her fatura icin:
- fatura_XX.pdf       : e-Arsiv benzeri temiz PDF
- fatura_XX_foto.jpg  : ayni faturanin telefonla cekilmis gibi gorunen hali (egik, bulanik, gurultulu)
- fatura_XX.json      : faturada YAZAN degerler (dogru cevap) ve varsa bilerek eklenen hata

Faturalarin bir kismina bilerek hata eklenir (yanlis genel toplam, yanlis KDV, yanlis satir tutari).
Bu faturalarda dogru cevap yine faturada yazan degerdir; kontrol adiminin hatayi yakalamasi beklenir.

Calistirma: python make_samples.py --adet 30
"""

import argparse
import json
import random
import uuid
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter
import numpy as np
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

KOK = Path(__file__).resolve().parent
CIKTI = KOK / "samples"

# Turkce karakterler icin TTF gerekli; reportlab'in kendi fontlari s, g, i harflerini icermiyor
FONTLAR = [
    (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
    (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
]

SATICILAR = [
    ("Mavi Kalem Kırtasiye Ltd. Şti.", "vkn"),
    ("Yıldız Bilişim Hizmetleri A.Ş.", "vkn"),
    ("Çınar Ofis Malzemeleri Tic. Ltd. Şti.", "vkn"),
    ("Deniz Yazılım ve Danışmanlık A.Ş.", "vkn"),
    ("Güneş Temizlik Ürünleri San. ve Tic. Ltd. Şti.", "vkn"),
    ("Ege Lokanta ve Catering Hizmetleri Ltd. Şti.", "vkn"),
    ("Toros Gıda Toptan Tic. A.Ş.", "vkn"),
    ("Selin Aydın - Grafik Tasarım", "tckn"),
    ("Kerem Doğan Elektrik Tesisat", "tckn"),
]
ALICI = ("Örnek Alıcı Teknoloji A.Ş.", "Atatürk Mah. Cumhuriyet Cad. No: 12 Ankara")

# (ad, birim, fiyat araligi, KDV orani)
URUNLER = [
    ("A4 Fotokopi Kağıdı (500'lü)", "Paket", (95, 180), 20),
    ("Lazer Yazıcı Toneri", "Adet", (650, 2400), 20),
    ("Tükenmez Kalem (12'li)", "Kutu", (60, 140), 20),
    ("Dosya Klasörü", "Adet", (18, 45), 20),
    ("Yazılım Danışmanlık Hizmeti", "Saat", (750, 2200), 20),
    ("Web Sitesi Bakım Hizmeti", "Ay", (1500, 6000), 20),
    ("Bulaşık Deterjanı (5 lt)", "Adet", (140, 320), 20),
    ("Kağıt Havlu (6'lı)", "Paket", (90, 210), 20),
    ("Toplantı İkramı (Öğle Yemeği)", "Kişi", (220, 480), 10),
    ("Kahvaltı Servisi", "Kişi", (150, 300), 10),
    ("Ekmek", "Adet", (12, 20), 1),
    ("Beyaz Peynir", "Kg", (220, 380), 1),
    ("Pirinç (Baldo)", "Kg", (55, 95), 1),
    ("Logo Tasarımı", "Adet", (3000, 9000), 20),
    ("Elektrik Tesisatı İşçiliği", "Saat", (400, 900), 20),
]
HATA_TURLERI = ["genel_toplam", "kdv", "satir"]


def _vkn_uret(rng: random.Random) -> str:
    rakamlar = [rng.randint(0, 9) for _ in range(9)]
    toplam = 0
    for i, r in enumerate(rakamlar):
        v1 = (r + 9 - i) % 10
        v2 = (v1 * 2 ** (9 - i)) % 9
        if v1 != 0 and v2 == 0:
            v2 = 9
        toplam += v2
    return "".join(map(str, rakamlar)) + str((10 - toplam % 10) % 10)


def _tckn_uret(rng: random.Random) -> str:
    d = [rng.randint(1, 9)] + [rng.randint(0, 9) for _ in range(8)]
    d.append(((d[0] + d[2] + d[4] + d[6] + d[8]) * 7 - (d[1] + d[3] + d[5] + d[7])) % 10)
    d.append(sum(d) % 10)
    return "".join(map(str, d))


def tl(deger: float) -> str:
    """1250.5 -> 1.250,50"""
    tam, kurus = f"{deger:,.2f}".split(".")
    return f"{tam.replace(',', '.')},{kurus}"


def _miktar_yaz(m: float) -> str:
    return str(int(m)) if m == int(m) else f"{m:.2f}".replace(".", ",")


def fatura_uret(no: int, rng: random.Random, hata: str | None) -> dict:
    firma, kimlik_turu = rng.choice(SATICILAR)
    vkn = _vkn_uret(rng) if kimlik_turu == "vkn" else _tckn_uret(rng)
    tarih = date(2026, 1, 1) + timedelta(days=rng.randint(0, 290))
    kalemler = []
    for ad, birim, (lo, hi), oran in rng.sample(URUNLER, rng.randint(2, 5)):
        miktar = rng.choice([1, 1, 2, 3, 4, 5, 10, 12]) if birim != "Kg" else rng.choice([1.5, 2, 2.5, 5])
        fiyat = round(rng.uniform(lo, hi), 2)
        kalemler.append({"ad": ad, "birim": birim, "miktar": float(miktar), "birim_fiyat": fiyat,
                         "kdv_orani": float(oran), "tutar": round(miktar * fiyat, 2)})

    if hata == "satir":  # bir satirin tutari yanlis yazilmis
        k = rng.choice(kalemler)
        k["tutar"] = round(k["tutar"] + rng.choice([10, 100, 1000]), 2)

    ara = round(sum(k["tutar"] for k in kalemler), 2)
    kdv_oranlara = {}
    for k in kalemler:
        kdv_oranlara[k["kdv_orani"]] = round(kdv_oranlara.get(k["kdv_orani"], 0) + k["tutar"] * k["kdv_orani"] / 100, 2)
    kdv = round(sum(kdv_oranlara.values()), 2)
    if hata == "kdv":  # KDV yanlis oranla hesaplanmis
        kdv = round(ara * 0.18, 2) if abs(ara * 0.18 - kdv) > 1 else round(kdv + 50, 2)
        kdv_oranlara = {max(kdv_oranlara): kdv} if len(kdv_oranlara) == 1 else {**kdv_oranlara}
    genel = round(ara + kdv, 2)
    if hata == "genel_toplam":
        genel = round(genel + rng.choice([1, 10, 100, 250]), 2)

    return {
        "fatura": {
            "firma": firma, "vkn": vkn,
            "fatura_no": f"TST{tarih.year}{no:09d}",
            "tarih": tarih.strftime("%d.%m.%Y"),
            "kalemler": [{k2: v for k2, v in k.items() if k2 != "birim"} for k in kalemler],
            "ara_toplam": ara, "kdv_toplam": kdv, "genel_toplam": genel,
        },
        "kdv_oranlara": {f"{int(o)}": v for o, v in sorted(kdv_oranlara.items())},
        "birimler": [k["birim"] for k in kalemler],
        "hata": hata,
        "duzen": rng.choice(["a", "b"]),
        "ettn": str(uuid.UUID(int=rng.getrandbits(128))),
    }


def _font_kaydet() -> tuple[str, str]:
    for normal, kalin in FONTLAR:
        if normal.exists() and kalin.exists():
            pdfmetrics.registerFont(TTFont("Govde", str(normal)))
            pdfmetrics.registerFont(TTFont("Kalin", str(kalin)))
            return "Govde", "Kalin"
    raise RuntimeError("Türkçe karakter destekleyen bir TTF font bulunamadı (Arial veya DejaVu Sans)")


def pdf_yaz(veri: dict, yol: Path) -> None:
    govde, kalin = _font_kaydet()
    f = veri["fatura"]
    b = veri["duzen"] == "b"  # ikinci duzende etiketler ve yerlesim biraz farkli
    c = canvas.Canvas(str(yol), pagesize=A4)
    c.setTitle(f"Test Faturası {f['fatura_no']}")
    w, h = A4
    sol, sag = 18 * mm, w - 18 * mm

    c.setFont(kalin, 15)
    c.drawString(sol, h - 22 * mm, f["firma"])
    c.setFont(govde, 9)
    c.drawString(sol, h - 28 * mm, "Organize Sanayi Bölgesi 4. Cad. No: 7 İstanbul")
    etiket = "TCKN" if len(f["vkn"]) == 11 else "VKN"
    c.drawString(sol, h - 33 * mm, f"Vergi Dairesi: Merkez   {etiket}: {f['vkn']}")

    c.setFont(kalin, 16)
    c.drawRightString(sag, h - 22 * mm, "e-FATURA" if b else "e-ARŞİV FATURA")
    c.setFont(govde, 9)
    bilgiler = [("Fatura No", f["fatura_no"]), ("Fatura Tarihi", f["tarih"]), ("Senaryo", "TEMELFATURA"),
                ("ETTN", veri["ettn"])]
    for i, (k, v) in enumerate(bilgiler):
        y = h - (30 + i * 5) * mm
        c.drawRightString(sag - 62 * mm, y, f"{k}:")
        c.drawString(sag - 60 * mm, y, v if k != "ETTN" else v[:24] + "...")

    y = h - 52 * mm
    c.setFont(kalin, 9)
    c.drawString(sol, y, "SAYIN")
    c.setFont(govde, 9)
    c.drawString(sol, y - 5 * mm, ALICI[0])
    c.drawString(sol, y - 10 * mm, ALICI[1])
    c.drawString(sol, y - 15 * mm, "Vergi Dairesi: Çankaya   VKN: 1234567890")

    # kalem tablosu
    basliklar = ["Sıra", "Mal / Hizmet", "Miktar", "Birim Fiyat", "KDV %", "Tutar"]
    xler = [sol, sol + 12 * mm, sol + 95 * mm, sol + 120 * mm, sol + 145 * mm, sag]
    y = h - 78 * mm
    c.setFillColor(colors.HexColor("#E8ECF2"))
    c.rect(sol, y - 2 * mm, sag - sol, 7 * mm, stroke=0, fill=1)
    c.setFillColor(colors.black)
    c.setFont(kalin, 9)
    for i, (bas, x) in enumerate(zip(basliklar, xler)):
        (c.drawString if i < 2 else c.drawRightString)(x + (0 if i < 2 else 0), y, bas if i != 2 else "Miktar")
    c.setFont(govde, 9)
    for i, (k, birim) in enumerate(zip(f["kalemler"], veri["birimler"]), 1):
        y -= 7 * mm
        c.drawString(xler[0], y, str(i))
        c.drawString(xler[1], y, k["ad"])
        c.drawRightString(xler[2], y, f"{_miktar_yaz(k['miktar'])} {birim}")
        c.drawRightString(xler[3], y, f"{tl(k['birim_fiyat'])} TL")
        c.drawRightString(xler[4], y, f"%{int(k['kdv_orani'])}")
        c.drawRightString(xler[5], y, f"{tl(k['tutar'])} TL")
        c.setStrokeColor(colors.HexColor("#CCCCCC"))
        c.line(sol, y - 2.5 * mm, sag, y - 2.5 * mm)

    # toplamlar
    satirlar = [("Ara Toplam" if b else "Mal Hizmet Toplam Tutarı", f["ara_toplam"])]
    satirlar += [(f"Hesaplanan KDV (%{o})", v) for o, v in veri["kdv_oranlara"].items()]
    satirlar += [("Toplam KDV", f["kdv_toplam"]),
                 ("Genel Toplam" if b else "Vergiler Dahil Toplam Tutar", f["genel_toplam"]),
                 ("Ödenecek Tutar", f["genel_toplam"])]
    y -= 12 * mm
    for i, (k, v) in enumerate(satirlar):
        son = i >= len(satirlar) - 2
        c.setFont(kalin if son else govde, 10 if son else 9)
        c.drawRightString(sag - 35 * mm, y, f"{k}:")
        c.drawRightString(sag, y, f"{tl(v)} TL")
        y -= 6 * mm

    c.setFont(govde, 8)
    c.setFillColor(colors.HexColor("#666666"))
    c.drawString(sol, 20 * mm, "Bu belge test amaçlı üretilmiş örnek bir faturadır. Gerçek bir ticari işlemi göstermez.")
    c.save()


def foto_yap(pdf_yolu: Path, yol: Path, rng: random.Random) -> None:
    """PDF'i telefonla cekilmis bir fotografa benzetir: egiklik, bulaniklik, isik farki, gurultu."""
    import pypdfium2 as pdfium

    sayfa = pdfium.PdfDocument(str(pdf_yolu))[0]
    img = sayfa.render(scale=rng.uniform(1.15, 1.45)).to_pil().convert("RGB")
    # masa ustunde kagit gibi: kenarlara koyu bir zemin
    zemin = Image.new("RGB", (int(img.width * 1.08), int(img.height * 1.06)), (88, 84, 78))
    zemin.paste(img, ((zemin.width - img.width) // 2, (zemin.height - img.height) // 2))
    img = zemin.rotate(rng.uniform(-3.5, 3.5), resample=Image.BICUBIC, expand=False, fillcolor=(88, 84, 78))
    img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.5, 1.1)))
    img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.85, 1.05))
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.8, 1.0))
    # ustten alta hafif isik farki ve gurultu
    dizi = np.asarray(img).astype(np.float32)
    golge = np.linspace(rng.uniform(0.88, 1.0), rng.uniform(0.95, 1.05), dizi.shape[0])[:, None, None]
    dizi = dizi * golge + np.random.default_rng(rng.randint(0, 10**6)).normal(0, 6, dizi.shape)
    img = Image.fromarray(np.clip(dizi, 0, 255).astype(np.uint8))
    img.save(yol, "JPEG", quality=rng.randint(45, 65))


def uret(adet: int, cikti: Path = CIKTI, tohum: int = 42, hata_orani: float = 0.2, foto: bool = True) -> list[Path]:
    rng = random.Random(tohum)
    cikti.mkdir(parents=True, exist_ok=True)
    hatali = set(rng.sample(range(1, adet + 1), max(1, round(adet * hata_orani))))
    yollar = []
    for no in range(1, adet + 1):
        hata = HATA_TURLERI[no % len(HATA_TURLERI)] if no in hatali else None
        veri = fatura_uret(no, rng, hata)
        ad = f"fatura_{no:02d}"
        pdf_yaz(veri, cikti / f"{ad}.pdf")
        if foto:
            foto_yap(cikti / f"{ad}.pdf", cikti / f"{ad}_foto.jpg", rng)
        (cikti / f"{ad}.json").write_text(
            json.dumps({"fatura": veri["fatura"], "hata": hata}, ensure_ascii=False, indent=2), encoding="utf-8")
        yollar.append(cikti / f"{ad}.json")
    return yollar


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--adet", type=int, default=30)
    args = parser.parse_args()
    yollar = uret(args.adet)
    print(f"{len(yollar)} fatura üretildi: {CIKTI}")
