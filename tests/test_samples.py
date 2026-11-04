"""Uretilen test faturalarinin tutarliligi: temiz faturalar kontrolden gecmeli, hatalilar yakalanmali."""

import json

from make_samples import uret
from schema import Fatura
from validate import kontrol_et, tckn_gecerli, vkn_gecerli


def test_uretilen_faturalar_tutarli(tmp_path):
    yollar = uret(9, cikti=tmp_path, tohum=7, hata_orani=0.34, foto=False)
    hatali = 0
    for yol in yollar:
        veri = json.loads(yol.read_text(encoding="utf-8"))
        fatura = Fatura(**veri["fatura"])
        assert (tmp_path / yol.name.replace(".json", ".pdf")).exists()
        no = fatura.vkn
        assert vkn_gecerli(no) if len(no) == 10 else tckn_gecerli(no)
        uyarilar = kontrol_et(fatura)
        if veri["hata"]:
            hatali += 1
            assert uyarilar, f"{yol.name}: eklenen hata yakalanmadi"
        else:
            assert not uyarilar, f"{yol.name}: temiz faturada uyari: {uyarilar}"
    assert hatali == 3
