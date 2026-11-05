"""Fatura Okuma Ajani - Streamlit arayuzu.

Calistirma: streamlit run app.py
"""

import io
import json
import os
import uuid
from pathlib import Path

import streamlit as st

# Streamlit Cloud'da anahtar secrets'ta durur; llm.py ortam degiskeninden okudugu icin aktarilir
try:
    for anahtar in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_FALLBACK_MODELS"):
        if anahtar in st.secrets and not os.getenv(anahtar):
            os.environ[anahtar] = str(st.secrets[anahtar])
except Exception:  # noqa: BLE001 - yerelde secrets.toml olmayabilir
    pass

from db import FaturaDB  # noqa: E402
from extract import Okuma, oku  # noqa: E402
from llm import GeminiIstemci, LLMHatasi, api_anahtari  # noqa: E402
from schema import Fatura, Kalem  # noqa: E402
from validate import kontrol_et  # noqa: E402

ORNEKLER = Path(__file__).resolve().parent / "samples"
MIME = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
ALAN_ADLARI = {"firma": "Firma", "vkn": "VKN / TCKN", "fatura_no": "Fatura no", "tarih": "Tarih (GG.AA.YYYY)",
               "ara_toplam": "Ara toplam (KDV hariç)", "kdv_toplam": "KDV toplamı", "genel_toplam": "Genel toplam"}

st.set_page_config(page_title="Fatura Okuma Ajanı", layout="wide")


@st.cache_resource(show_spinner=False)
def veritabani() -> FaturaDB:
    return FaturaDB()


@st.cache_resource(show_spinner=False)
def istemci() -> GeminiIstemci | None:
    return GeminiIstemci() if api_anahtari() else None


@st.cache_data(show_spinner=False)
def onizleme(dosya: bytes, mime: str) -> bytes:
    """PDF'in ilk sayfasini resme cevirir; resimler oldugu gibi doner."""
    if mime != "application/pdf":
        return dosya
    import pypdfium2 as pdfium

    sayfa = pdfium.PdfDocument(dosya)[0]
    tampon = io.BytesIO()
    sayfa.render(scale=1.6).to_pil().save(tampon, format="PNG")
    return tampon.getvalue()


def ornek_listesi() -> list[str]:
    return sorted(p.name for p in ORNEKLER.glob("fatura_*") if p.suffix in (".pdf", ".jpg"))


# Herkese acik demoda ziyaretciler birbirinin faturasini gormesin diye her tarayici oturumu ayri kimlikle baslar
oturum = st.session_state.setdefault("oturum", uuid.uuid4().hex[:12])
db = veritabani()
llm = istemci()

with st.sidebar:
    st.title("Fatura Okuma Ajanı")
    st.write("Fatura fotoğrafı veya PDF'i yükleyin. Gemini faturayı okur, kod toplamları ve vergi numarasını "
             "kontrol eder, siz onaylamadan hiçbir şey kaydedilmez.")
    if llm is None:
        st.warning("GOOGLE_API_KEY tanımlı değil, okuma yapılamaz.")
    kaynak = st.radio("Fatura", ["Örnek fatura", "Kendi faturam"], horizontal=True)
    secilen = None
    if kaynak == "Örnek fatura":
        ad = st.selectbox("Örnek seçin", ornek_listesi(),
                          help="_foto.jpg dosyaları aynı faturanın telefonla çekilmiş gibi bozulmuş halidir")
        if ad:
            yol = ORNEKLER / ad
            secilen = (ad, yol.read_bytes(), MIME[yol.suffix])
    else:
        st.caption("Demo herkese açık; gerçek bir faturayı yüklemeden önce kişisel bilgileri kapatın.")
        yuklenen = st.file_uploader("Fatura yükle", type=["pdf", "png", "jpg", "jpeg"])
        if yuklenen:
            secilen = (yuklenen.name, yuklenen.getvalue(), MIME[Path(yuklenen.name).suffix.lower()])
    duzeltme = st.toggle("Hatalı alanları modele tekrar okut", value=True,
                         help="Kontrol bir sorun bulursa sorunlar modele geri verilir ve model o alanlara tekrar bakar")
    oku_butonu = st.button("Faturayı oku", type="primary", use_container_width=True,
                           disabled=secilen is None or llm is None)

if oku_butonu and secilen:
    with st.spinner("Fatura okunuyor..."):
        try:
            okuma = oku(llm, secilen[1], secilen[2], duzeltme_turu=1 if duzeltme else 0)
            st.session_state.okuma = okuma
            st.session_state.dosya = secilen
            st.session_state.anahtar = uuid.uuid4().hex[:8]  # form alanlari yeni okumayla sifirlansin
        except LLMHatasi as exc:
            st.error(str(exc))

st.title("Fatura Okuma Ajanı")
st.caption("Okuma: Gemini  ·  Kontrol: Python  ·  Kayıt: kullanıcı onayıyla SQLite")

okuma: Okuma | None = st.session_state.get("okuma")
if okuma is None:
    st.info("Soldan bir örnek fatura seçip 'Faturayı oku' butonuna basın.")
else:
    ad, dosya, mime = st.session_state.dosya
    k = st.session_state.anahtar
    sol, sag = st.columns([5, 6], gap="large")
    with sol:
        st.subheader(ad)
        st.image(onizleme(dosya, mime), use_container_width=True)

    with sag:
        st.subheader("Okunan bilgiler")
        f = okuma.fatura
        c1, c2 = st.columns(2)
        degerler = {}
        for i, alan in enumerate(["firma", "vkn", "fatura_no", "tarih"]):
            degerler[alan] = (c1 if i % 2 == 0 else c2).text_input(ALAN_ADLARI[alan], getattr(f, alan) or "",
                                                                  key=f"{k}_{alan}") or None
        st.markdown("**Kalemler**")
        kalem_tablosu = st.data_editor(
            [kl.model_dump() for kl in f.kalemler], num_rows="dynamic", use_container_width=True, key=f"{k}_kalemler",
            column_config={"ad": "Mal / hizmet", "miktar": st.column_config.NumberColumn("Miktar", format="%.2f"),
                           "birim_fiyat": st.column_config.NumberColumn("Birim fiyat", format="%.2f"),
                           "kdv_orani": st.column_config.NumberColumn("KDV %", format="%.0f"),
                           "tutar": st.column_config.NumberColumn("Tutar", format="%.2f")},
        )
        c1, c2, c3 = st.columns(3)
        for kolon, alan in zip((c1, c2, c3), ["ara_toplam", "kdv_toplam", "genel_toplam"]):
            deger = getattr(f, alan)
            degerler[alan] = kolon.number_input(ALAN_ADLARI[alan], value=deger, format="%.2f", key=f"{k}_{alan}")

        satirlar = kalem_tablosu if isinstance(kalem_tablosu, list) else kalem_tablosu.to_dict("records")
        guncel = Fatura(**degerler, kalemler=[Kalem(**{a: (None if v != v else v) for a, v in s.items()})
                                               for s in satirlar if any(v not in (None, "") for v in s.values())])
        uyarilar = kontrol_et(guncel)  # kullanici duzelttikce kontroller yeniden calisir

        if uyarilar:
            st.warning("**Kontrol uyarıları**\n\n" + "\n".join(f"- {u.mesaj}" for u in uyarilar))
        else:
            st.success("Bütün kontroller geçti.")

        mukerrer = db.zaten_var(oturum, guncel.vkn, guncel.fatura_no)
        if mukerrer:
            st.error("Bu fatura (aynı VKN ve fatura no) daha önce kaydedilmiş.")
        yine_de = bool(uyarilar) and st.checkbox("Faturada gerçekten böyle yazıyor, uyarılara rağmen kaydet",
                                                key=f"{k}_yine")
        if st.button("Onayla ve kaydet", type="primary", disabled=mukerrer or (bool(uyarilar) and not yine_de)):
            db.kaydet(oturum, guncel, uyari_ile=bool(uyarilar))
            st.session_state.pop("okuma")
            st.toast("Fatura kaydedildi")
            st.rerun()

        with st.expander("Ajan adımları"):
            for i, adim in enumerate(okuma.adimlar, 1):
                st.markdown(f"**{i}. {adim.baslik}**")
                if adim.detay:
                    st.text(adim.detay)
            if llm and llm.son_model:
                st.caption(f"Model: {llm.son_model}")
        with st.expander("Modelin döndürdüğü JSON"):
            st.code(json.dumps(okuma.fatura.model_dump(), ensure_ascii=False, indent=2), language="json")

st.divider()
st.subheader("Kayıtlı faturalar")
kayitlar = db.listele(oturum)
if not kayitlar:
    st.caption("Henüz kayıtlı fatura yok. Kayıtlar sadece bu tarayıcı oturumunda görünür.")
else:
    st.dataframe(
        [{"Firma": r["firma"], "Fatura no": r["fatura_no"], "Tarih": r["tarih"], "Ara toplam": r["ara_toplam"],
          "KDV": r["kdv_toplam"], "Genel toplam": r["genel_toplam"],
          "Not": "Uyarıyla kaydedildi" if r["uyari_ile_kaydedildi"] else ""} for r in kayitlar],
        use_container_width=True, hide_index=True,
    )
    st.download_button("CSV indir", data="\n".join(
        [";".join(["firma", "vkn", "fatura_no", "tarih", "ara_toplam", "kdv_toplam", "genel_toplam"])]
        + [";".join(str(r[c] if r[c] is not None else "") for c in
                    ["firma", "vkn", "fatura_no", "tarih", "ara_toplam", "kdv_toplam", "genel_toplam"])
           for r in kayitlar]).encode("utf-8-sig"), file_name="faturalar.csv", mime="text/csv")
