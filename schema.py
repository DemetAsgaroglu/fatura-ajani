"""Faturadan cikarilan bilgilerin semasi.

Butun alanlar bos birakilabilir: model okuyamadigi alani uydurmak yerine bos birakir,
kontrol adimi da bunu "eksik alan" olarak kullaniciya gosterir.
"""

from pydantic import BaseModel, Field


class Kalem(BaseModel):
    ad: str | None = Field(None, description="Urun veya hizmetin adi")
    miktar: float | None = None
    birim_fiyat: float | None = Field(None, description="KDV haric birim fiyat")
    kdv_orani: float | None = Field(None, description="Yuzde olarak KDV orani, ornek: 20")
    tutar: float | None = Field(None, description="KDV haric satir tutari (miktar x birim fiyat)")


class Fatura(BaseModel):
    firma: str | None = Field(None, description="Faturayi kesen (satici) firmanin unvani")
    vkn: str | None = Field(None, description="Saticinin vergi numarasi (10 hane) veya TC kimlik numarasi (11 hane)")
    fatura_no: str | None = None
    tarih: str | None = Field(None, description="GG.AA.YYYY bicimde fatura tarihi")
    kalemler: list[Kalem] = Field(default_factory=list)
    ara_toplam: float | None = Field(None, description="KDV haric toplam")
    kdv_toplam: float | None = Field(None, description="Hesaplanan KDV toplami")
    genel_toplam: float | None = Field(None, description="KDV dahil odenecek tutar")
