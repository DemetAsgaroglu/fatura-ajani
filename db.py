"""Onaylanan faturalarin SQLite'a kaydi.

Canli demoda ayni dosyayi butun ziyaretciler kullanir. Her kayit bir oturum kimligiyle saklanir
ve sorgular bu kimlige gore filtrelenir; bir ziyaretci baskasinin faturasini goremez.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from schema import Fatura

VARSAYILAN_DB = Path(__file__).resolve().parent / "data" / "faturalar.db"

TABLO = """CREATE TABLE IF NOT EXISTS faturalar (
    id INTEGER PRIMARY KEY,
    oturum TEXT NOT NULL,
    firma TEXT, vkn TEXT, fatura_no TEXT, tarih TEXT,
    ara_toplam REAL, kdv_toplam REAL, genel_toplam REAL,
    kalemler TEXT,
    uyari_ile_kaydedildi INTEGER NOT NULL DEFAULT 0,
    kaydedilme TEXT NOT NULL,
    UNIQUE(oturum, vkn, fatura_no)
)"""


class FaturaDB:
    def __init__(self, yol: Path | str | None = None):
        self.yol = str(yol or VARSAYILAN_DB)
        # Testlerde bellekte calisir; tek baglanti acik tutulmazsa tablo kaybolur
        self._bellek = sqlite3.connect(":memory:", check_same_thread=False) if self.yol == ":memory:" else None
        if not self._bellek:
            Path(self.yol).parent.mkdir(parents=True, exist_ok=True)
        with self._baglanti() as con:
            con.execute(TABLO)

    @contextmanager
    def _baglanti(self) -> Iterator[sqlite3.Connection]:
        con = self._bellek or sqlite3.connect(self.yol)
        con.row_factory = sqlite3.Row
        try:
            with con:  # hata yoksa commit, varsa rollback
                yield con
        finally:
            if con is not self._bellek:
                con.close()

    def zaten_var(self, oturum: str, vkn: str | None, fatura_no: str | None) -> bool:
        if not vkn or not fatura_no:
            return False
        with self._baglanti() as con:
            satir = con.execute("SELECT 1 FROM faturalar WHERE oturum=? AND vkn=? AND fatura_no=?",
                                (oturum, vkn, fatura_no)).fetchone()
        return satir is not None

    def kaydet(self, oturum: str, f: Fatura, uyari_ile: bool = False) -> None:
        with self._baglanti() as con:
            con.execute(
                "INSERT INTO faturalar (oturum, firma, vkn, fatura_no, tarih, ara_toplam, kdv_toplam, genel_toplam,"
                " kalemler, uyari_ile_kaydedildi, kaydedilme) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (oturum, f.firma, f.vkn, f.fatura_no, f.tarih, f.ara_toplam, f.kdv_toplam, f.genel_toplam,
                 json.dumps([k.model_dump() for k in f.kalemler], ensure_ascii=False), int(uyari_ile),
                 datetime.now().isoformat(timespec="seconds")),
            )

    def listele(self, oturum: str) -> list[dict]:
        with self._baglanti() as con:
            satirlar = con.execute(
                "SELECT id, firma, vkn, fatura_no, tarih, ara_toplam, kdv_toplam, genel_toplam, uyari_ile_kaydedildi"
                " FROM faturalar WHERE oturum=? ORDER BY id DESC", (oturum,)).fetchall()
        return [dict(s) for s in satirlar]

    def sil(self, oturum: str, fatura_id: int) -> None:
        with self._baglanti() as con:
            con.execute("DELETE FROM faturalar WHERE oturum=? AND id=?", (oturum, fatura_id))
