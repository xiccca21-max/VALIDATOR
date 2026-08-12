# Cheki bank PDF corpus report

| Bank | N | Generator | Objects | Channels | SBP ID | Edit (non-native) | Fonts |
|---|---:|---|---|---|---|---|---|
| т банк | 126 | JasperReports (126) | 26-28 | sbp:55, phone_unknown:52, card_unknown:12, card_interbank:7 | alfa_style_AB+31; pfx A6(28),B6(23),A5(3),B5(1) | missing_content_stream | ALSRubl, TinkoffSans-Medium, TinkoffSans-Regular |
| альфа | 14 | Oracle BI Publisher (14) | 16 | sbp:12, card_unknown:2 | alfa_style_AB+31; pfx A6(9),B6(3) | missing_content_stream | Tahoma |
| озонбанк | 11 | Skia/PDF m105 (11) | 73-89 | phone_unknown:6, phone_interbank:5 | alfa_style_AB+31; pfx B6(3),A6(2) | - | GTEestiProDisplay-Bold, GTEestiProDisplay-Regular |
| втб | 10 | openhtmltopdf.com (10) | 18 | sbp:10 | alfa_style_AB+31; pfx B6(6),A6(4) | - | SFProDisplay-Regular |
| сбер | 7 | JasperReports (6), PDFium (1) | 14-18 | sbp:3, phone_unknown:2, card_unknown:1, phone_interbank:1 | hex32_lower/alfa_style_AB+31; pfx A6(3),20(1) | foreign_producer:itext; foreign_producer:quartz; foreign_producer:pdfium | ArialMT, font000000002fe890e5 |
| яндекс банк | 5 | JasperReports (5) | 23 | sbp:5 | alfa_style_AB+31; pfx B6(3),A6(2) | - | Helvetica, YSText-Medium, YSText-Regular |
| псб | 4 | FastReport.NET (4) | 17 | sbp:4 | alfa_style_AB+31; pfx A6(4) | missing_content_stream | DejaVuSans, DejaVuSans-Bold |
| газпромбанк | 3 | iText (3) | 30 | card_unknown:2, phone_interbank:1 | alfa_style_AB+31; pfx A6(1) | foreign_producer:itext | ArialNarrow, Calibri, MicrosoftSansSerif, TimesNewRomanPS-BoldMT |
| райф | 3 | iText (2), (empty) (1) | 18-29 | phone_interbank:3 | alfa_style_AB+31; pfx A6(1),B6(1) | foreign_producer:itext; missing_content_stream | ALSHauss-Bold, ALSHauss-Bold-Identity-H, ALSHauss-Regular, ALSHauss-Regular-Identity-H |
| ОТП БАНК | 2 | Quartz/PDFKit (2) | 28 | sbp:2 | alfa_style_AB+31; pfx B6(2) | foreign_producer:quartz | font000000002fbd849e |
| уралсиб | 2 | rPDF.0.9 (2) | 24 | sbp:2 | alfa_style_AB+31; pfx A6(2) | - | ArialMT |
| бчпб | 1 | PDFProducer (1) | 23 | sbp:1 | alfa_style_AB+31; pfx A6(1) | - | DejaVuSans, DejaVuSans-Bold, Helvetica |
| рокетбанк | 1 | iText (1) | 181 | sbp:1 | alfa_style_AB+31; pfx A6(1) | foreign_producer:itext; missing_content_stream | RocketMono-Regular, RocketMono-Regular-Identity-H, RocketSans-Wide, RocketSans-Wide-Identity-H |
| совком | 1 | OpenPDF (Jasper stack) (1) | 12 | card_interbank:1 | - | - | Montserrat-Regular, Times-Roman |

## Shared PDF generators
- **JasperReports**: т банк (126), сбер (6), яндекс банк (5)
- **Oracle BI Publisher**: альфа (14)
- **Skia/PDF m105**: озонбанк (11)
- **openhtmltopdf.com**: втб (10)
- **iText**: газпромбанк (3), райф (2), рокетбанк (1)
- **FastReport.NET**: псб (4)
- **Quartz/PDFKit**: ОТП БАНК (2)
- **rPDF.0.9**: уралсиб (2)
- **PDFProducer**: бчпб (1)
- **(empty)**: райф (1)
- **PDFium**: сбер (1)
- **OpenPDF (Jasper stack)**: совком (1)

## Validator hints