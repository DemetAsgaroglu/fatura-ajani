"""Ajanin dogrulugunu test faturalariyla olcer.

python eval.py            # samples/ altindaki butun faturalar, PDF ve fotograf halleri
python eval.py --limit 5  # hizli deneme

Her faturanin sonucu eval/results/okumalar.json dosyasina yazilir; kota yuzunden yarida kalirsa
tekrar calistirildiginda okunmus faturalar atlanir. Ozet eval/results/ozet.json dosyasina yazilir.
"""

import argparse
import json
import time
from pathlib import Path

from extract import oku
from llm import GeminiIstemci, LLMHatasi
from schema import Fatura
from validate import kontrol_et

KOK = Path(__file__).resolve().parent
ORNEKLER = KOK / "samples"
SONUC = KOK / "eval" / "results"
ALANLAR = ["firma", "vkn", "fatura_no", "tarih", "ara_toplam", "kdv_toplam", "genel_toplam", "kalemler"]


def _ayni_metin(a, b) -> bool:
    return a is not None and b is not None and " ".join(str(a).split()).casefold() == " ".join(str(b).split()).casefold()


def _ayni_sayi(a, b) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) <= 0.01


def alan_dogru_mu(alan: str, okunan: Fatura, gercek: Fatura) -> bool:
    a, b = getattr(okunan, alan), getattr(gercek, alan)
    if alan == "kalemler":
        return len(a) == len(b) and all(
            _ayni_sayi(x.tutar, y.tutar) and _ayni_sayi(x.kdv_orani, y.kdv_orani)
            and _ayni_sayi(x.miktar, y.miktar) and _ayni_sayi(x.birim_fiyat, y.birim_fiyat) for x, y in zip(a, b))
    if alan in ("ara_toplam", "kdv_toplam", "genel_toplam"):
        return _ayni_sayi(a, b)
    if alan == "vkn":
        return a is not None and a.replace(" ", "") == b
    return _ayni_metin(a, b)


def degerlendir(okunan: Fatura, gercek: Fatura) -> dict:
    return {alan: alan_dogru_mu(alan, okunan, gercek) for alan in ALANLAR}


def ornekler(limit: int | None) -> list[tuple[str, Path, str, dict]]:
    isler = []
    for js in sorted(ORNEKLER.glob("fatura_*.json"))[:limit]:
        veri = json.loads(js.read_text(encoding="utf-8"))
        isler.append((js.stem + "_pdf", js.with_suffix(".pdf"), "application/pdf", veri))
        foto = js.with_name(js.stem + "_foto.jpg")
        if foto.exists():
            isler.append((js.stem + "_foto", foto, "image/jpeg", veri))
    return isler


def calistir(limit: int | None) -> dict:
    SONUC.mkdir(parents=True, exist_ok=True)
    kayit_yolu = SONUC / "okumalar.json"
    kayitlar = json.loads(kayit_yolu.read_text(encoding="utf-8")) if kayit_yolu.exists() else {}
    llm = GeminiIstemci()

    for ad, yol, mime, veri in ornekler(limit):
        if ad in kayitlar:
            continue
        gercek = Fatura(**veri["fatura"])
        baslangic = time.perf_counter()
        try:
            okuma = oku(llm, yol.read_bytes(), mime)
        except LLMHatasi as exc:
            print(f"{ad}: atlandi ({exc})")
            continue
        kayitlar[ad] = {
            "tur": "foto" if ad.endswith("_foto") else "pdf",
            "hata": veri["hata"],
            "ilk": degerlendir(okuma.ilk_okuma, gercek),
            "son": degerlendir(okuma.fatura, gercek),
            "uyari_var": bool(okuma.uyarilar),
            "uyarilar": [u.mesaj for u in okuma.uyarilar],
            "duzeltme_yapildi": okuma.duzeltme_yapildi,
            "duzeltme_basarisiz": any(a.baslik == "Düzeltme turu yapılamadı" for a in okuma.adimlar),
            "model": llm.son_model,
            "saniye": round(time.perf_counter() - baslangic, 1),
        }
        tamam = all(kayitlar[ad]["son"].values())
        print(f"{ad}: {'tam dogru' if tamam else 'hatali alan var'}"
              f"{' (duzeltme turu)' if okuma.duzeltme_yapildi else ''}, uyari: {bool(okuma.uyarilar)}")
        kayit_yolu.write_text(json.dumps(kayitlar, ensure_ascii=False, indent=1), encoding="utf-8")

    return ozetle(kayitlar)


def _oran(pay: int, payda: int) -> str:
    return f"%{100 * pay / payda:.1f} ({pay}/{payda})" if payda else "-"


def ozetle(kayitlar: dict) -> dict:
    ozet = {}
    for tur in ("pdf", "foto"):
        satirlar = [k for k in kayitlar.values() if k["tur"] == tur]
        if not satirlar:
            continue
        n = len(satirlar)
        ozet[tur] = {
            "fatura": n,
            "alan_dogrulugu_ilk": _oran(sum(sum(k["ilk"].values()) for k in satirlar), n * len(ALANLAR)),
            "alan_dogrulugu_son": _oran(sum(sum(k["son"].values()) for k in satirlar), n * len(ALANLAR)),
            "tam_dogru_fatura_ilk": _oran(sum(all(k["ilk"].values()) for k in satirlar), n),
            "tam_dogru_fatura_son": _oran(sum(all(k["son"].values()) for k in satirlar), n),
            "alan_bazinda_son": {a: _oran(sum(k["son"][a] for k in satirlar), n) for a in ALANLAR},
        }
    hatali = [k for k in kayitlar.values() if k["hata"]]
    temiz = [k for k in kayitlar.values() if not k["hata"]]
    ozet["hata_tespiti"] = {
        "hatali_faturada_uyari": _oran(sum(k["uyari_var"] for k in hatali), len(hatali)),
        "temiz_faturada_yanlis_uyari": _oran(sum(k["uyari_var"] for k in temiz), len(temiz)),
        # Duzeltme turu faturadaki gercek hatayi "duzeltip" saklamamali: okunan deger faturada yazanla ayni kalmali
        "hatali_faturada_yazan_deger_korundu": _oran(sum(all(k["son"].values()) for k in hatali), len(hatali)),
    }
    ozet["duzeltme_turu"] = {
        "calisan": sum(k["duzeltme_yapildi"] for k in kayitlar.values()),
        "kota_yuzunden_yapilamayan": sum(k["duzeltme_basarisiz"] for k in kayitlar.values()),
        "yanlis_okunan_alani_duzelten": sum(1 for k in kayitlar.values()
                                            if sum(k["son"].values()) > sum(k["ilk"].values())),
        "dogru_alani_bozan": sum(1 for k in kayitlar.values() if sum(k["son"].values()) < sum(k["ilk"].values())),
    }
    modeller: dict[str, int] = {}
    for k in kayitlar.values():
        modeller[k["model"]] = modeller.get(k["model"], 0) + 1
    ozet["okuyan_model"] = modeller
    ozet["ortalama_sure_sn"] = round(sum(k["saniye"] for k in kayitlar.values()) / max(1, len(kayitlar)), 1)
    (SONUC / "ozet.json").write_text(json.dumps(ozet, ensure_ascii=False, indent=2), encoding="utf-8")
    return ozet


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="ilk N fatura")
    args = parser.parse_args()
    print(json.dumps(calistir(args.limit), ensure_ascii=False, indent=2))
