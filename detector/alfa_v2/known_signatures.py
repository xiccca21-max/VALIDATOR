"""Exact signatures for user-confirmed Alfa forgeries."""

from __future__ import annotations


KNOWN_FAKE_FILE_SHA256: frozenset[str] = frozenset({
    # PDF Document (89).pdf — confirmed fake Quartz/iOS shell clone.
    "9b614fe525d1940859bcca746fa92c712dad30dd178c3eb553f8d9c7ada2c9d2",
    # alfa_sbp_142944.pdf — SEQ Oracle SBP, FF2 21202 in 21132–21682 hole.
    "4feebd6e1219e32f10463e3d57ef54d1d461aabbcb76fad07966474e4050f01f",
    # alfa_sbp_143126.pdf — SEQ Oracle SBP, FF2 21250 in the same hole.
    "c94364a434ae05915735428e909b27da0bfd33da80814e9b633f8caa44afc8ec",
    # SEQ Oracle 38-slot kit 2026-08-24 (user-confirmed). File SHA only —
    # content/FF2 size holes would FAKE a future genuine in the same gaps.
    "b90f5a8092df69cbfb449d2d4a98bf22f2ee9196cc9db40eeb94516a481e3cc9",
    "368cdf595f4d1e5c52ad27963d76f2f466e604e2833754e04c3167898ef78ac0",
    "0ca02110e2cedb0e172f5fcbbbcdc2d0e1a76b27b954223184afdf8c1ac11f1b",
    "55886846ab3633e39e76b72e73185548ae65bd52ea5590e453afd6a55c8806de",
    "15b6380655b60db16878803af6d5bff9813f8cc8c7ae1f1e966681d236f6c92f",
    "3decf55f8824b7943188e86b2501539a8657c83096e8375691ec0127121c7ad6",
    "f9a81bd777f0ad51fc6fa9fc75af035b5af1d7b56ca16de655a4bbc5a87c4212",
    "e095d6ccc126f88e87975f8b72e86f97661e454f94790cf5f087661e7c5dc70a",
    "5c7cb27e4f97bb2503b9e25cde63441716d3aad43339f004a8cd46501624d337",
    "79280c94fb8a1cb28eae358f8cde688b1a419a5e0630ebb7977fc571c0f4a243",
    "71468e5b5120a58899b3c486ed7e72d907addc270c80e8828ef98c5208202903",
    "2f1443b560b214353cbcc6dcf24a9c7cb0ea253f931fa80ec53e0237105fec51",
    "e7c223d9d4d30cc211bdf0e756ac4dc5d2770364d510cb193f2fd103b3ef5220",
    "2a52dc6184abbc9eeed125de8dcf5066dc8a38e7171179704d809cc0d8cf062c",
    "5916468e1b5c654870a0f1feb58b4e335072bc6b0642ec14c8f27bda29076c19",
    "9f825ba382c5a422db4f55f69e9293c8413bc676c589617ec8361eb577a2dea8",
    "a70eaaf0a9f2ad439b0331349402fcdb74921ed49133a1c075fa0a431ade9633",
    "b760965f63df8ca8a31ef425fca911c3e0d5142a14bb4abc5188b6abf6d3c5cd",
})

