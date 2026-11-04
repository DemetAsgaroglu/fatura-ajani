"""Gemini istemcisi. Fatura dosyasi (PDF veya resim) ve talimat birlikte gonderilir, cevap
semaya uygun JSON olarak alinir. Ana model yogunsa veya kota dolduysa yedek modele gecilir.
"""

import json
import logging
import os
import time
from typing import Protocol

from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()
logger = logging.getLogger(__name__)

# Bu kodlarda ayni istegi baska modelle denemek mantikli: kota, yogunluk, zaman asimi
TEKRAR_DENENEBILIR = {408, 429, 500, 502, 503, 504}
BEKLEMELER = [3, 8]  # saniye; butun modeller denendikten sonra bir tur daha


class LLMHatasi(RuntimeError):
    pass


class DosyaOkuyanLLM(Protocol):
    def json_uret(self, dosya: bytes, mime: str, talimat: str, sema: type[BaseModel]) -> dict: ...


def api_anahtari() -> str | None:
    return os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or None


def modeller() -> list[str]:
    ana = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
    yedekler = os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.1-flash-lite,gemini-3.8-flash")
    return list(dict.fromkeys([ana, *(m.strip() for m in yedekler.split(",") if m.strip())]))


class GeminiIstemci:
    def __init__(self, api_key: str | None = None, model_listesi: list[str] | None = None, timeout: int = 60):
        api_key = api_key or api_anahtari()
        if not api_key:
            raise LLMHatasi("GOOGLE_API_KEY tanımlı değil. .env dosyasına veya Streamlit secrets'a ekleyin.")
        from google import genai
        from google.genai import types

        self._types = types
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout * 1000))
        self.modeller = model_listesi or modeller()
        self.son_model: str | None = None

    def json_uret(self, dosya: bytes, mime: str, talimat: str, sema: type[BaseModel]) -> dict:
        from google.genai import errors

        config = self._types.GenerateContentConfig(
            temperature=0, response_mime_type="application/json", response_schema=sema,
        )
        icerik = [self._types.Part.from_bytes(data=dosya, mime_type=mime), talimat]
        son_hata: Exception | None = None
        for bekle in [0, *BEKLEMELER]:
            if bekle:
                time.sleep(bekle)
            for model in self.modeller:
                try:
                    cevap = self._client.models.generate_content(model=model, contents=icerik, config=config)
                    self.son_model = model
                    return _json_coz(cevap.text or "")
                except errors.APIError as exc:
                    son_hata = exc
                    if exc.code not in TEKRAR_DENENEBILIR:
                        raise LLMHatasi(f"Gemini hatası ({exc.code}): {exc.message}") from exc
                    logger.warning("%s cevap vermedi (%s), siradaki modele geciliyor", model, exc.code)
                except LLMHatasi as exc:
                    son_hata = exc
                    logger.warning("%s gecersiz JSON dondurdu, siradaki modele geciliyor", model)
                except Exception as exc:  # noqa: BLE001 - ag hatalari, zaman asimi
                    son_hata = exc
                    logger.warning("%s istegi basarisiz: %s", model, exc)
        kod = getattr(son_hata, "code", None)
        raise LLMHatasi(f"Model şu an yoğun, biraz sonra tekrar deneyin ({f'hata kodu {kod}' if kod else son_hata}).")


def _json_coz(metin: str) -> dict:
    metin = metin.strip()
    if metin.startswith("```"):
        metin = metin.strip("`").removeprefix("json").strip()
    try:
        veri = json.loads(metin)
    except json.JSONDecodeError as exc:
        raise LLMHatasi(f"Model JSON döndürmedi: {metin[:200]}") from exc
    if not isinstance(veri, dict):
        raise LLMHatasi("Model JSON nesnesi döndürmedi")
    return veri
