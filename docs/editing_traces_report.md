# Отчёт: расхождения и следы редактирования (корпус 190 PDF)

**Вердикт валидатора:** 190/190 ЧИСТО (после исправления парсера stream)

## Исправление по `сбп альфа 2.pdf`

Ложный фейк: старый `find_streams` находил слово `stream` внутри бинарных данных.
Реальный content stream (obj 9, Oracle BI, 5091 байт) на месте — чек **оригинальный**.

## Расхождения с основной массой (не фейк, но отличается)

### gazprombank — `газпромбанк сбп1.pdf` (ЧИСТО)
- СБП-шифр: SBP_CIPHER_STRUCTURE, SBP_CIPHER_STRUCTURE
- уникальные шрифты: ['CITDPQ+ArialNarrow', 'DJOLRN+Calibri', 'HHPZBU+MicrosoftSansSerif']

### raif — `райф СБП.pdf` (ЧИСТО)
- другой producer: «(пусто)» (основной: «iText® pdfHTML 6.2.0 (AGPL version) ©2000-2025 Apryse Group NV»)
- уникальные шрифты: ['DKKAJK+PTSans-Regular', 'IRQSGB+PTSans-Bold']

### raif — `райф сбп2.pdf` (ЧИСТО)
- уникальные шрифты: ['CKADZB+ALSHauss-Bold', 'CKADZB+ALSHauss-Bold-Identity-H', 'FRADPV+ALSHauss-Regular']

### raif — `райф сбп4.pdf` (ЧИСТО)
- уникальные шрифты: ['TQGMVQ+ALSHauss-Bold', 'TQGMVQ+ALSHauss-Bold-Identity-H', 'TVTWWE+ALSHauss-Regular']

### sber — `сбер по карте в другой банк.pdf` (ЧИСТО)
- другой producer: «iOS Version 26.5.1 (Build 23F81) Quartz PDFContext» (основной: «iText 2.1.7 by 1T3XT»)
- нет встроенных шрифтов (растр или другой шаблон)

### sber — `сбер по номеру на сбер.pdf` (ЧИСТО)
- другой producer: «PDFium» (основной: «iText 2.1.7 by 1T3XT»)
- уникальные шрифты: ['BOHSZN+ArialMT']

### sber — `сбер по номеру телефона на сбер.pdf` (ЧИСТО)
- уникальные шрифты: ['OUWAKA+ArialMT']

### sber — `сбер сбп.pdf` (ЧИСТО)
- уникальные шрифты: ['MUWTXD+ArialMT']

### sber — `сбербанк сбп.pdf` (ЧИСТО)
- уникальные шрифты: ['OKMSGD+ArialMT']

### tbank — `$R0S81JH.pdf` (ЧИСТО)
- уникальные шрифты: ['JUQDTG+TinkoffSans-Medium', 'QVIXAH+TinkoffSans-Regular', 'UCHUNG+ALSRubl']

### tbank — `$R0TNJBG.pdf` (ЧИСТО)
- уникальные шрифты: ['CZBYXV+ALSRubl', 'DTTIUY+TinkoffSans-Regular', 'NJBHMF+TinkoffSans-Medium']

### tbank — `$R1YCVEZ.pdf` (ЧИСТО)
- уникальные шрифты: ['IECXOI+TinkoffSans-Regular', 'SMTDSN+ALSRubl', 'ZEVFYU+TinkoffSans-Medium']

### tbank — `$R2XX916.pdf` (ЧИСТО)
- уникальные шрифты: ['HBYYYB+TinkoffSans-Regular', 'MJCQVH+ALSRubl', 'XLKNKQ+TinkoffSans-Medium']

### tbank — `$R3Q4FWR.pdf` (ЧИСТО)
- уникальные шрифты: ['NQDUCY+TinkoffSans-Regular', 'UZKNMW+TinkoffSans-Medium', 'XXFPRF+ALSRubl']

### tbank — `$R4L3XYX.pdf` (ЧИСТО)
- уникальные шрифты: ['DLFMDT+TinkoffSans-Regular', 'NBSDYL+TinkoffSans-Medium', 'ZLIVCL+ALSRubl']

### tbank — `$R4STQ1J.pdf` (ЧИСТО)
- уникальные шрифты: ['HPNZEX+TinkoffSans-Regular', 'KLDUZF+ALSRubl', 'MEJWGM+TinkoffSans-Medium']

### tbank — `$R4UG9ND.pdf` (ЧИСТО)
- уникальные шрифты: ['GJMBMD+TinkoffSans-Regular', 'KPXXBM+ALSRubl', 'MMTMNW+TinkoffSans-Medium']

### tbank — `$R5E9XUX.pdf` (ЧИСТО)
- уникальные шрифты: ['CECYGP+TinkoffSans-Medium', 'ENEKKP+ALSRubl', 'ZEJFJH+TinkoffSans-Regular']

### tbank — `$R63GYR3.pdf` (ЧИСТО)
- уникальные шрифты: ['AFECMJ+TinkoffSans-Regular', 'SCRHNL+TinkoffSans-Medium', 'TLDTLP+ALSRubl']

### tbank — `$R64IN0O.pdf` (ЧИСТО)
- уникальные шрифты: ['KLXFKJ+TinkoffSans-Regular', 'SLTQSP+ALSRubl', 'UFXHXP+TinkoffSans-Medium']

### tbank — `$R6TYL3H.pdf` (ЧИСТО)
- уникальные шрифты: ['EMXOGW+TinkoffSans-Medium', 'PUIAIW+TinkoffSans-Regular', 'YCOVQI+ALSRubl']

### tbank — `$R79QRFU.pdf` (ЧИСТО)
- уникальные шрифты: ['IHWJHN+TinkoffSans-Medium', 'KKBDZT+TinkoffSans-Regular', 'MIHSWE+ALSRubl']

### tbank — `$R887D5E.pdf` (ЧИСТО)
- уникальные шрифты: ['FVROUN+TinkoffSans-Medium', 'KJKWQU+ALSRubl', 'XUAWYI+TinkoffSans-Regular']

### tbank — `$R8ALH0O.pdf` (ЧИСТО)
- уникальные шрифты: ['BZTZUT+TinkoffSans-Medium', 'LKPTRY+TinkoffSans-Regular', 'XZICLO+ALSRubl']

### tbank — `$R9RP24C.pdf` (ЧИСТО)
- уникальные шрифты: ['BHKSKD+TinkoffSans-Medium', 'CSULWF+TinkoffSans-Regular', 'CZRDGJ+ALSRubl']

### tbank — `$R9SEQVG.pdf` (ЧИСТО)
- уникальные шрифты: ['HHQOKZ+TinkoffSans-Regular', 'KORQUL+TinkoffSans-Medium', 'SQEQVA+ALSRubl']

### tbank — `$RAW6XRF.pdf` (ЧИСТО)
- уникальные шрифты: ['AVIRVA+ALSRubl', 'HPTZTU+TinkoffSans-Regular', 'IFOUNI+TinkoffSans-Medium']

### tbank — `$RB4UIPR.pdf` (ЧИСТО)
- уникальные шрифты: ['EBKSXY+ALSRubl', 'HGQOTL+TinkoffSans-Regular', 'XQTZOA+TinkoffSans-Medium']

### tbank — `$RB9BM33.pdf` (ЧИСТО)
- уникальные шрифты: ['SAGKUA+ALSRubl', 'UYMRPD+TinkoffSans-Medium', 'WBVZZE+TinkoffSans-Regular']

### tbank — `$RBH5Z4V.pdf` (ЧИСТО)
- уникальные шрифты: ['WPUCDR+TinkoffSans-Regular', 'WWFGTA+ALSRubl', 'XZGVXJ+TinkoffSans-Medium']

### tbank — `$RBIMWJ2.pdf` (ЧИСТО)
- уникальные шрифты: ['IEZZXW+ALSRubl', 'IFIYBZ+TinkoffSans-Medium', 'RYMZIP+TinkoffSans-Regular']

### tbank — `$RBNZNUE.pdf` (ЧИСТО)
- уникальные шрифты: ['IZYCZO+TinkoffSans-Medium', 'NBGMET+TinkoffSans-Regular', 'WAAQHB+ALSRubl']

### tbank — `$RCHI6HM.pdf` (ЧИСТО)
- уникальные шрифты: ['LRUJKR+ALSRubl', 'RKVXSM+TinkoffSans-Medium', 'YXHQUU+TinkoffSans-Regular']

### tbank — `$RCQL37U.pdf` (ЧИСТО)
- уникальные шрифты: ['RXXIFB+TinkoffSans-Regular', 'TORPJO+ALSRubl', 'TQMAAP+TinkoffSans-Medium']

### tbank — `$RDBBYJF.pdf` (ЧИСТО)
- уникальные шрифты: ['CKPJIJ+TinkoffSans-Medium', 'LAPLME+TinkoffSans-Regular', 'VTVNCK+ALSRubl']

### tbank — `$RE8GET5.pdf` (ЧИСТО)
- уникальные шрифты: ['COZKYK+TinkoffSans-Regular', 'UQJBJU+ALSRubl', 'YQYYRV+TinkoffSans-Medium']

### tbank — `$REHI4QZ.pdf` (ЧИСТО)
- уникальные шрифты: ['IAWTTB+TinkoffSans-Regular', 'PBGYUE+ALSRubl', 'WIXHRK+TinkoffSans-Medium']

### tbank — `$RERIWJI.pdf` (ЧИСТО)
- уникальные шрифты: ['MXURLF+TinkoffSans-Medium', 'RIBSVW+ALSRubl', 'YCKXJN+TinkoffSans-Regular']

### tbank — `$RFS8KNF.pdf` (ЧИСТО)
- уникальные шрифты: ['JCADMV+TinkoffSans-Regular', 'TKMGVF+TinkoffSans-Medium', 'YFLVMF+ALSRubl']

### tbank — `$RG2L52G.pdf` (ЧИСТО)
- уникальные шрифты: ['EXICFO+ALSRubl', 'HVSDIP+TinkoffSans-Medium', 'TMBETY+TinkoffSans-Regular']

### tbank — `$RGJPTNZ.pdf` (ЧИСТО)
- уникальные шрифты: ['IRHSMT+ALSRubl', 'MHBAJF+TinkoffSans-Medium', 'WUQMFY+TinkoffSans-Regular']

### tbank — `$RH6OM0Q.pdf` (ЧИСТО)
- уникальные шрифты: ['AQWJNM+TinkoffSans-Regular', 'HAOOSW+ALSRubl', 'JKEICS+TinkoffSans-Medium']

### tbank — `$RHBR0BK.pdf` (ЧИСТО)
- уникальные шрифты: ['IIGLLJ+TinkoffSans-Medium', 'IRKDJM+ALSRubl', 'SOYUVI+TinkoffSans-Regular']

### tbank — `$RHGE8D6.pdf` (ЧИСТО)
- уникальные шрифты: ['LQRHND+ALSRubl', 'PGGRXG+TinkoffSans-Medium', 'RECGWX+TinkoffSans-Regular']

### tbank — `$RHL880Q.pdf` (ЧИСТО)
- уникальные шрифты: ['BZQEAM+ALSRubl', 'GLXQWY+TinkoffSans-Regular', 'MAKXAQ+TinkoffSans-Medium']

### tbank — `$RHOA1HA.pdf` (ЧИСТО)
- уникальные шрифты: ['FZWWJZ+TinkoffSans-Regular', 'GMJHBL+ALSRubl', 'QICPZQ+TinkoffSans-Medium']

### tbank — `$RHS9Q52.pdf` (ЧИСТО)
- уникальные шрифты: ['EAODGJ+ALSRubl', 'GXWXZO+TinkoffSans-Regular', 'PEROCY+TinkoffSans-Medium']

### tbank — `$RJHJLN6.pdf` (ЧИСТО)
- уникальные шрифты: ['CSDJTC+TinkoffSans-Regular', 'KQDQKF+TinkoffSans-Medium', 'YKUYNE+ALSRubl']

### tbank — `$RK4101J.pdf` (ЧИСТО)
- уникальные шрифты: ['BQRBRQ+TinkoffSans-Medium', 'FLNAVZ+ALSRubl', 'UIXGWH+TinkoffSans-Regular']

### tbank — `$RL6U847.pdf` (ЧИСТО)
- уникальные шрифты: ['MISNTX+TinkoffSans-Regular', 'UZJRZW+ALSRubl', 'XYCBKN+TinkoffSans-Medium']

### tbank — `$RLYHP7N.pdf` (ЧИСТО)
- уникальные шрифты: ['CLGSPZ+ALSRubl', 'GBZQZM+TinkoffSans-Medium', 'PNFHBP+TinkoffSans-Regular']

### tbank — `$RM4RP9P.pdf` (ЧИСТО)
- уникальные шрифты: ['SWTZHV+TinkoffSans-Regular', 'UQGLZI+ALSRubl', 'UYUMZN+TinkoffSans-Medium']

### tbank — `$RN1UQX3.pdf` (ЧИСТО)
- уникальные шрифты: ['DKDPDX+TinkoffSans-Medium', 'IBIWJU+TinkoffSans-Regular', 'OATIHO+ALSRubl']

### tbank — `$RNXE35S.pdf` (ЧИСТО)
- уникальные шрифты: ['OWGGVB+TinkoffSans-Medium', 'WHYNFD+TinkoffSans-Regular', 'XYTDYM+ALSRubl']

### tbank — `$RNZEDIX.pdf` (ЧИСТО)
- уникальные шрифты: ['HYWBIX+TinkoffSans-Medium', 'QQIGBI+TinkoffSans-Regular', 'XQZHSY+ALSRubl']

### tbank — `$RO29T1V.pdf` (ЧИСТО)
- уникальные шрифты: ['JSHTAS+TinkoffSans-Regular', 'JXVBZR+ALSRubl', 'VHKECT+TinkoffSans-Medium']

### tbank — `$ROC41BI.pdf` (ЧИСТО)
- уникальные шрифты: ['UCNRFK+ALSRubl', 'YAGKNU+TinkoffSans-Regular', 'YSLGUC+TinkoffSans-Medium']

### tbank — `$ROW3HJM.pdf` (ЧИСТО)
- уникальные шрифты: ['DBCYVP+TinkoffSans-Regular', 'GDBFDU+ALSRubl', 'XXGLUM+TinkoffSans-Medium']

### tbank — `$RPT82YX.pdf` (ЧИСТО)
- уникальные шрифты: ['IYZRHG+TinkoffSans-Medium', 'NBMFOX+TinkoffSans-Regular', 'VBADLP+ALSRubl']

### tbank — `$RPWY57W.pdf` (ЧИСТО)
- уникальные шрифты: ['CCZYVV+ALSRubl', 'DLMRDN+TinkoffSans-Regular', 'JYNAVP+TinkoffSans-Medium']

### tbank — `$RRNSXMS.pdf` (ЧИСТО)
- уникальные шрифты: ['GOQFED+ALSRubl', 'PKEWAR+TinkoffSans-Regular', 'PYGAOJ+TinkoffSans-Medium']

### tbank — `$RS080CW.pdf` (ЧИСТО)
- уникальные шрифты: ['LMCDKL+TinkoffSans-Medium', 'LRTOEW+ALSRubl', 'NVHEXM+TinkoffSans-Regular']

### tbank — `$RS6C4VT.pdf` (ЧИСТО)
- уникальные шрифты: ['WEDJVD+TinkoffSans-Regular', 'WRYAEP+TinkoffSans-Medium', 'XZHBHX+ALSRubl']

### tbank — `$RSJGH60.pdf` (ЧИСТО)
- уникальные шрифты: ['FTILSM+TinkoffSans-Medium', 'JSOLSA+ALSRubl', 'VHZJVH+TinkoffSans-Regular']

### tbank — `$RTSX13Y.pdf` (ЧИСТО)
- уникальные шрифты: ['JRCFFJ+ALSRubl', 'LZBDAO+TinkoffSans-Regular', 'XAIJBQ+TinkoffSans-Medium']

### tbank — `$RU1RFU3.pdf` (ЧИСТО)
- уникальные шрифты: ['CARZJQ+ALSRubl', 'PMPWCV+TinkoffSans-Medium', 'RNNXYR+TinkoffSans-Regular']

### tbank — `$RU7VOGW.pdf` (ЧИСТО)
- уникальные шрифты: ['FUFWMR+TinkoffSans-Regular', 'VIAUNC+ALSRubl', 'XRFWAP+TinkoffSans-Medium']

### tbank — `$RUNB9J7.pdf` (ЧИСТО)
- уникальные шрифты: ['GANOIU+TinkoffSans-Regular', 'KPVSTT+ALSRubl', 'PQQPFP+TinkoffSans-Medium']

### tbank — `$RUU302M.pdf` (ЧИСТО)
- уникальные шрифты: ['EBZGAR+TinkoffSans-Medium', 'GAPFVF+TinkoffSans-Regular', 'TBFHMJ+ALSRubl']

### tbank — `$RV94AYF.pdf` (ЧИСТО)
- уникальные шрифты: ['CTOZJB+ALSRubl', 'HERQML+TinkoffSans-Medium', 'ZFBXEB+TinkoffSans-Regular']

### tbank — `$RVMNUW7.pdf` (ЧИСТО)
- уникальные шрифты: ['GOVGBM+TinkoffSans-Regular', 'ICAJZI+ALSRubl', 'PAJZHC+TinkoffSans-Medium']

### tbank — `Receipt (1).pdf` (ЧИСТО)
- уникальные шрифты: ['JYTMRG+TinkoffSans-Medium', 'SNZSOJ+TinkoffSans-Regular', 'XGBEPA+ALSRubl']

### tbank — `Receipt (10).pdf` (ЧИСТО)
- уникальные шрифты: ['FCSMTD+ALSRubl', 'JLAXKQ+TinkoffSans-Regular', 'VTFZOR+TinkoffSans-Medium']

### tbank — `Receipt (11).pdf` (ЧИСТО)
- уникальные шрифты: ['CSZIPX+TinkoffSans-Regular', 'TIAJJD+ALSRubl', 'YUIIGX+TinkoffSans-Medium']

### tbank — `Receipt (12).pdf` (ЧИСТО)
- уникальные шрифты: ['CNWRHC+TinkoffSans-Regular', 'HNMNIA+ALSRubl', 'TPWCMY+TinkoffSans-Medium']

### tbank — `Receipt (13).pdf` (ЧИСТО)
- уникальные шрифты: ['OEVMSN+TinkoffSans-Medium', 'ZCXDLV+TinkoffSans-Regular', 'ZXBSRY+ALSRubl']

### tbank — `Receipt (14).pdf` (ЧИСТО)
- уникальные шрифты: ['JHNDNC+ALSRubl', 'VEZNOI+TinkoffSans-Regular', 'WIWFBM+TinkoffSans-Medium']

### tbank — `Receipt (15).pdf` (ЧИСТО)
- уникальные шрифты: ['AQWEXQ+ALSRubl', 'GIESWV+TinkoffSans-Medium', 'MDHFDN+TinkoffSans-Regular']

### tbank — `Receipt (16).pdf` (ЧИСТО)
- уникальные шрифты: ['FYGSUV+TinkoffSans-Regular', 'KMAUIC+ALSRubl', 'TACAQY+TinkoffSans-Medium']

### tbank — `Receipt (17).pdf` (ЧИСТО)
- уникальные шрифты: ['FRBZKI+ALSRubl', 'QCJVSJ+TinkoffSans-Medium', 'WVTSZI+TinkoffSans-Regular']

### tbank — `Receipt (18).pdf` (ЧИСТО)
- уникальные шрифты: ['ASIBLF+ALSRubl', 'PTDQRF+TinkoffSans-Regular', 'UGXKKH+TinkoffSans-Medium']

### tbank — `Receipt (19).pdf` (ЧИСТО)
- уникальные шрифты: ['AYPLZM+TinkoffSans-Medium', 'BESWVF+ALSRubl', 'KQLQFE+TinkoffSans-Regular']

### tbank — `Receipt (2).pdf` (ЧИСТО)
- уникальные шрифты: ['AKGXZO+TinkoffSans-Regular', 'NZMUCZ+TinkoffSans-Medium', 'UJDZZV+ALSRubl']

### tbank — `Receipt (20).pdf` (ЧИСТО)
- уникальные шрифты: ['GUBYQM+TinkoffSans-Regular', 'LWLSCS+ALSRubl', 'TCFWKZ+TinkoffSans-Medium']

### tbank — `Receipt (23).pdf` (ЧИСТО)
- уникальные шрифты: ['AMZDVD+TinkoffSans-Medium', 'OEGFNY+ALSRubl', 'TFYUXN+TinkoffSans-Regular']

### tbank — `Receipt (24).pdf` (ЧИСТО)
- уникальные шрифты: ['LHNVYW+TinkoffSans-Medium', 'PATWKJ+TinkoffSans-Regular', 'YXZAPY+ALSRubl']

### tbank — `Receipt (25).pdf` (ЧИСТО)
- уникальные шрифты: ['DNSFDC+TinkoffSans-Medium', 'RQRFAS+ALSRubl', 'WWOSSL+TinkoffSans-Regular']

### tbank — `Receipt (26).pdf` (ЧИСТО)
- уникальные шрифты: ['DRAXBE+TinkoffSans-Regular', 'UHCPQL+ALSRubl', 'WPBVDD+TinkoffSans-Medium']

### tbank — `Receipt (27).pdf` (ЧИСТО)
- уникальные шрифты: ['GRMCFM+TinkoffSans-Medium', 'LGJUCY+TinkoffSans-Regular', 'SYRDWG+ALSRubl']

### tbank — `Receipt (28).pdf` (ЧИСТО)
- уникальные шрифты: ['AUNAPH+ALSRubl', 'ELNDIQ+TinkoffSans-Medium', 'QBSVLX+TinkoffSans-Regular']

### tbank — `Receipt (29).pdf` (ЧИСТО)
- уникальные шрифты: ['EVTJCX+TinkoffSans-Regular', 'NBUZVG+ALSRubl', 'RMLVRC+TinkoffSans-Medium']

### tbank — `Receipt (3).pdf` (ЧИСТО)
- уникальные шрифты: ['ASIPGL+ALSRubl', 'PBDZXQ+TinkoffSans-Regular', 'WYJXRH+TinkoffSans-Medium']

### tbank — `Receipt (30).pdf` (ЧИСТО)
- уникальные шрифты: ['DLVKWX+TinkoffSans-Regular', 'IARRKY+TinkoffSans-Medium', 'TLUTKN+ALSRubl']

### tbank — `Receipt (31).pdf` (ЧИСТО)
- уникальные шрифты: ['CCESDR+ALSRubl', 'FPXZEA+TinkoffSans-Regular', 'HSLRXG+TinkoffSans-Medium']

### tbank — `Receipt (32).pdf` (ЧИСТО)
- уникальные шрифты: ['CBPUUZ+TinkoffSans-Medium', 'HRLFWW+TinkoffSans-Regular', 'MXFDNY+ALSRubl']

### tbank — `Receipt (33).pdf` (ЧИСТО)
- уникальные шрифты: ['GCCDYM+TinkoffSans-Regular', 'NOZAAD+TinkoffSans-Medium', 'VASBSD+ALSRubl']

### tbank — `Receipt (34).pdf` (ЧИСТО)
- уникальные шрифты: ['PYIGNM+TinkoffSans-Regular', 'SCVNAR+ALSRubl', 'TQYQSK+TinkoffSans-Medium']

### tbank — `Receipt (35).pdf` (ЧИСТО)
- уникальные шрифты: ['BBPOMG+TinkoffSans-Medium', 'CLBVOV+ALSRubl', 'KUTVIR+TinkoffSans-Regular']

### tbank — `Receipt (36).pdf` (ЧИСТО)
- уникальные шрифты: ['CXVXDZ+TinkoffSans-Medium', 'LFBZVV+TinkoffSans-Regular', 'LLCFMK+ALSRubl']

### tbank — `Receipt (37).pdf` (ЧИСТО)
- уникальные шрифты: ['KUTFOQ+TinkoffSans-Regular', 'PTNPHQ+ALSRubl', 'YDXZFF+TinkoffSans-Medium']

### tbank — `Receipt (38).pdf` (ЧИСТО)
- уникальные шрифты: ['GJMKIB+ALSRubl', 'HYQMFE+TinkoffSans-Medium', 'JNTBVG+TinkoffSans-Regular']

### tbank — `Receipt (4).pdf` (ЧИСТО)
- уникальные шрифты: ['BMIQWU+ALSRubl', 'OTLVCU+TinkoffSans-Regular', 'YXVMLU+TinkoffSans-Medium']

### tbank — `Receipt (5).pdf` (ЧИСТО)
- уникальные шрифты: ['ATOPJX+TinkoffSans-Medium', 'GVZDCJ+TinkoffSans-Regular', 'UTBNNN+ALSRubl']

### tbank — `Receipt (6).pdf` (ЧИСТО)
- уникальные шрифты: ['CGMJCG+TinkoffSans-Medium', 'SHTTZV+TinkoffSans-Regular', 'VXHEPR+ALSRubl']

### tbank — `Receipt (7).pdf` (ЧИСТО)
- уникальные шрифты: ['AXAKBJ+ALSRubl', 'GQGXUF+TinkoffSans-Medium', 'YXIXXR+TinkoffSans-Regular']

### tbank — `Receipt (8).pdf` (ЧИСТО)
- уникальные шрифты: ['BPGMBA+TinkoffSans-Medium', 'DPTDGV+TinkoffSans-Regular', 'DWYTPS+ALSRubl']

### tbank — `Receipt (9).pdf` (ЧИСТО)
- уникальные шрифты: ['KTKJHZ+TinkoffSans-Medium', 'LUYFMF+ALSRubl', 'WZNNXI+TinkoffSans-Regular']

### tbank — `Receipt.pdf` (ЧИСТО)
- уникальные шрифты: ['BPVFCF+TinkoffSans-Regular', 'EQUEGL+ALSRubl', 'UMDVIY+TinkoffSans-Medium']

### tbank — `коммса.pdf` (ЧИСТО)
- уникальные шрифты: ['QYARPL+TinkoffSans-Medium', 'UVMHDG+ALSRubl', 'ZWPTXW+TinkoffSans-Regular']

### tbank — `т банк по карте в другой банк.pdf` (ЧИСТО)
- уникальные шрифты: ['COHVKV+TinkoffSans-Medium', 'IESQOC+ALSRubl', 'NTQIKI+TinkoffSans-Regular']

### tbank — `т банк по карте на т банк3.pdf` (ЧИСТО)
- уникальные шрифты: ['DIHGIF+TinkoffSans-Regular', 'KGBYTR+TinkoffSans-Medium', 'VHGBVT+ALSRubl']

### tbank — `т банк по номееру на т баннк1.pdf` (ЧИСТО)
- уникальные шрифты: ['JDVYMW+ALSRubl', 'RKZTHE+TinkoffSans-Medium', 'SMBLMF+TinkoffSans-Regular']

### tbank — `т банк по номееру на т баннк2.pdf` (ЧИСТО)
- уникальные шрифты: ['FAOMTM+TinkoffSans-Regular', 'ZNRJXK+ALSRubl', 'ZTKTAZ+TinkoffSans-Medium']

### tbank — `т банк по номеру карты в другой банк.pdf` (ЧИСТО)
- уникальные шрифты: ['DYFYRM+TinkoffSans-Regular', 'VIUQTX+ALSRubl', 'ZAKDCZ+TinkoffSans-Medium']

### tbank — `т банк сбп1.pdf` (ЧИСТО)
- уникальные шрифты: ['CYVZAM+ALSRubl', 'RVEYJT+TinkoffSans-Medium', 'WHLPAZ+TinkoffSans-Regular']

### tbank — `т банк сбп11.pdf` (ЧИСТО)
- уникальные шрифты: ['IEICOT+TinkoffSans-Regular', 'IRUFRJ+TinkoffSans-Medium', 'SDEACC+ALSRubl']

### tbank — `т банк сбп5.pdf` (ЧИСТО)
- уникальные шрифты: ['FTEKIP+TinkoffSans-Medium', 'GIDYEK+ALSRubl', 'IHECAS+TinkoffSans-Regular']

### tbank — `т банк сбп7.pdf` (ЧИСТО)
- уникальные шрифты: ['IBXZAU+ALSRubl', 'ILTHSH+TinkoffSans-Regular', 'XTAFFI+TinkoffSans-Medium']

### uralsib — `уралсиб сбп.pdf` (ЧИСТО)
- структура: STREAM_LENGTH_MISMATCH

### uralsib — `уралсиб сбп4.pdf` (ЧИСТО)
- структура: STREAM_LENGTH_MISMATCH


## Вывод

В корпусе **нет файлов с признаками редактирования**, которые валидатор банит.
Отличия ниже — разные каналы выписки / версии шаблона банка, не подделка.