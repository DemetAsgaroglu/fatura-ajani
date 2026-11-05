# Fatura Okuma Ajanı

Bu proje, fatura fotoğrafını veya PDF'ini okuyup bilgileri çıkaran, çıkan sonucu kodla kontrol eden ve kullanıcı onayladıktan sonra kaydeden bir ajandır. Faturayı Gemini okur; toplamların, KDV'nin ve vergi numarasının doğruluğunu ise model değil Python kodu kontrol eder. Model hiçbir zaman kendisi kayıt yapmaz.

## Nasıl Çalışıyor?

```text
Fatura (PDF / fotoğraf)
   -> Gemini okur, sonucu şemaya uygun JSON olarak döndürür
   -> Kod kontrol eder (kalem tutarları, ara toplam, KDV, genel toplam, VKN/TCKN, tarih)
   -> Sorun varsa sorunlar modele geri verilir, model sadece o alanlara tekrar bakar
   -> Kullanıcı ekranda düzeltir ve onaylar
   -> SQLite'a kaydedilir (aynı fatura ikinci kez kaydedilemez)
```

- **Okuma:** Gemini PDF'i ve resmi doğrudan okuyor. Ayrı bir OCR adımı yok: klasik yöntemde önce OCR metni çıkarır, sonra kurallarla alanlar ayrıştırılır. Burada model sayfanın düzenini de gördüğü için "satıcı mı alıcı mı", "hangi satır hangi KDV oranına ait" gibi ayrımları tek adımda yapabiliyor. Cevap Pydantic şemasıyla alınıyor; okunamayan alan uydurulmuyor, boş bırakılıyor.
- **Kontrol:** Kalemlerde miktar x birim fiyat, kalemlerin toplamı, kalem bazında KDV (aynı faturada %1, %10 ve %20 olabilir), genel toplam, vergi numarasının kontrol hanesi (şahıs şirketleri için 11 haneli TC kimlik numarası da), tarih biçimi ve ileri tarih.
- **Düzeltme turu:** Kontrol bir sorun bulursa, bulunan sorunlar ve ilk okuma modele geri verilir. Model yanlış okuduğu bir değer varsa düzeltir; faturada gerçekten yanlış yazan bir tutar varsa değiştirmez. Amaç faturada yazanı aynen almak, hesabı tutturmak değil; o durumda uyarı kullanıcıya kalır. İkinci okuma daha fazla sorun getirirse ilk okuma korunur. Bu turda bir sayının birden fazla rakamı değiştiyse değişiklik geri alınır: gerçek okuma hataları genelde tek rakamdır (3 ile 8'in karışması gibi), sayının tamamen değişmesi ise modelin hesabı tutturan değeri yazdığını gösterir. Testlerde yedek modelin, satır tutarı yanlış yazılmış bir faturada birim fiyatı 167,86'dan 168,69'a çevirip uyarıyı kaybettirdiği görüldü; bu kural o durumu yakalıyor.
- **Onay:** Kullanıcı bütün alanları ve kalemleri ekranda düzeltebilir, kontroller her değişiklikte yeniden çalışır. Uyarı varken kayıt butonu kapalıdır; faturada gerçekten öyle yazıyorsa kullanıcı "uyarılara rağmen kaydet" diyebilir ve kayıt bu bilgiyle saklanır.

Herkese açık demoda her tarayıcı oturumu ayrı bir kimlikle çalışır; ziyaretçiler birbirinin kaydettiği faturaları göremez. Gerçek fatura yüklemeden denemek için örnek faturalar hazır.

## Test Faturaları

Değerlendirme için `make_samples.py` ile 30 test faturası üretildi (`samples/`). Her fatura için üç dosya var:
- `fatura_XX.pdf`: e-Arşiv / e-Fatura düzeninde PDF (iki farklı düzen)
- `fatura_XX_foto.jpg`: aynı faturanın telefonla çekilmiş gibi bozulmuş hali (eğik, bulanık, ışık farkı, gürültü, düşük JPEG kalitesi)
- `fatura_XX.json`: faturada yazan değerler

Faturalarda 1 ile 5 arası kalem ve karışık KDV oranları var; bir kısmı şahıs şirketi (TCKN), alıcının da geçerli bir VKN'si var (model satıcıyla alıcıyı karıştırmamalı). 30 faturanın 6'sına bilerek hata eklendi: yanlış genel toplam, yanlış hesaplanmış KDV veya yanlış satır tutarı. Bu faturalarda doğru cevap yine faturada yazan değer; kontrolün hatayı yakalaması bekleniyor. Bütün faturaların altında test amaçlı üretildikleri yazıyor.

## Değerlendirme

`eval.py` her faturanın PDF ve fotoğraf halini okur ve şunları ölçer:
- **Alan doğruluğu:** firma, VKN, fatura no, tarih, ara toplam, KDV, genel toplam ve kalemler (bütün kalemlerin miktar, fiyat, KDV oranı ve tutarı)
- **Tam doğru fatura:** bütün alanları doğru okunan fatura oranı
- **Düzeltme turunun etkisi:** düzeltme turundan önce ve sonra doğruluk
- **Hata tespiti:** hatalı faturalarda uyarı çıkma oranı, temiz faturalarda yanlış uyarı oranı ve hatalı faturalarda modelin faturada yazan değeri koruyup korumadığı

### Sonuçlar

30 faturanın PDF ve fotoğraf hali, toplam 60 okuma (`eval/results/ozet.json`):

| | PDF | Fotoğraf |
|---|---|---|
| Alan doğruluğu | %100 (240/240) | %98,3 (236/240) |
| Bütün alanları doğru fatura | %100 (30/30) | %86,7 (26/30) |

| Hata tespiti | Sonuç |
|---|---|
| Hatalı faturada uyarı çıkması | %100 (12/12) |
| Temiz faturada yanlış uyarı | %0 (0/48) |
| Hatalı faturada faturada yazan tutarların korunması | %100 (12/12) |

- Fotoğraflardaki 4 hatanın dördü de fatura numarasında (16 karakterlik, çoğu sıfır olan numara bulanık fotoğrafta yanlış okundu; incelenen örnekte bir sıfır eksikti). Fatura numarasının kontrol hanesi olmadığı için kod bunu yakalayamıyor; kullanıcı onay ekranında görüp düzeltmeli. Tutarlarda, kalemlerde, KDV'de ve vergi numarasında hata çıkmadı. Bu yüzden `ozet.json`'da hatalı faturalarda bütün alanların doğru olma oranı %83,3 (10/12) görünüyor; tutarlar 12 faturanın hepsinde korundu.
- Düzeltme turu 12 okumada çalıştı, hepsi bilerek hata eklenen faturalardı. Hiçbirinde faturadaki yanlış tutar "düzeltilip" hesap tutturulmadı; uyarı kullanıcıya kaldı.
- Ücretsiz API kotası yüzünden okumaların 6'sını `gemini-3.6-flash`, 54'ünü yedek model `gemini-3.1-flash-lite` yaptı. 4 hatalı fatura numarasının dördü de yedek modelden geldi. Ortalama okuma süresi 6,7 saniye.
- Test faturaları sentetik ve düzenleri sabit. Gerçek, el yazısı içeren ya da buruşmuş faturalarda sonuçlar daha düşük olacaktır.

## Proje Yapısı

```text
fatura-ajani/
├── schema.py         # Pydantic şeması (fatura ve kalemler)
├── llm.py            # Gemini istemcisi ve yedek modeller
├── extract.py        # Ajan: okuma, kontrol, düzeltme turu
├── validate.py       # Kontroller (toplamlar, KDV, VKN/TCKN, tarih)
├── db.py             # SQLite kayıt
├── app.py            # Streamlit arayüzü
├── make_samples.py   # Test faturalarını üretir
├── eval.py           # Doğruluk ölçümü
├── samples/          # Test faturaları
└── tests/            # Birim testleri
```

## Kurulum ve Kullanım

1. **Projeyi klonlayın:**
   ```bash
   git clone https://github.com/DemetAsgaroglu/fatura-ajani.git
   cd fatura-ajani
   ```
2. **Gerekli kütüphaneleri kurun:**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. **API anahtarını ekleyin:** `.env.example` dosyasını `.env` olarak kopyalayıp `GOOGLE_API_KEY` değerini girin.
4. **Uygulamayı çalıştırın:**
   ```bash
   streamlit run app.py
   ```

Testler, test faturaları ve değerlendirme için:
```bash
pip install -r requirements-dev.txt
pytest
python make_samples.py --adet 30
python eval.py
```

## Kullanılan Teknolojiler

- **Gemini API (google-genai):** Faturayı okuma (görüntü ve PDF)
- **Pydantic:** Yapılandırılmış çıktı şeması
- **SQLite:** Kayıt
- **Streamlit:** Arayüz
- **reportlab, Pillow, pypdfium2:** Test faturası üretimi ve önizleme
- **Pytest:** Testler
