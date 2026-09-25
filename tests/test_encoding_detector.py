"""Comprehensive unit test suite for EncodingDetector.

Verifies the complete 5-stage fallback chain:
1. BOM detection (UTF-8-SIG, UTF-16, UTF-32, precedence, partial signatures)
2. Strict UTF-8 probe (ASCII, Hangul, accented Latin, Astral plane/Emojis, invalid sequences)
3. charset-normalizer probe with CJK tiebreaker rules (Rules 3.1, 3.2, 3.3)
4. Korean CP949 / EUC-KR short strings ('한글', '공지사항', '설정', '버그', '가')
5. Latin-1 / CP1252 accented text and arbitrary high-byte fallback
6. File-based bounded I/O, error handling, and helper methods.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.encoding_detector import EncodingDetector


class TestEncodingDetectorBOM:
    """Stage 1: Byte Order Mark detection scenarios."""

    def test_detect_bom_utf8_sig(self) -> None:
        """ED-04: UTF-8 with BOM prefix b'\\xef\\xbb\\xbf' returns utf-8-sig."""
        detector = EncodingDetector()
        raw = b"\xef\xbb\xbfConfig file content header"
        assert detector.detect_from_bytes(raw) == "utf-8-sig"
        assert detector.detect_bom(raw) == "utf-8-sig"

    def test_detect_bom_utf16_le_and_be(self) -> None:
        """ED-05: UTF-16 Little Endian and Big Endian BOMs are detected."""
        detector = EncodingDetector()

        le_bytes = b"\xff\xfeH\x00e\x00l\x00l\x00o\x00"
        assert detector.detect_from_bytes(le_bytes) == "utf-16-le"
        assert detector.detect_bom(le_bytes) == "utf-16-le"

        be_bytes = b"\xfe\xff\x00H\x00e\x00l\x00l\x00o"
        assert detector.detect_from_bytes(be_bytes) == "utf-16-be"
        assert detector.detect_bom(be_bytes) == "utf-16-be"

    def test_detect_bom_utf32_le_and_be(self) -> None:
        """ED-06: UTF-32 Little Endian and Big Endian BOMs are detected."""
        detector = EncodingDetector()

        le32_bytes = b"\xff\xfe\x00\x00H\x00\x00\x00"
        assert detector.detect_from_bytes(le32_bytes) == "utf-32-le"
        assert detector.detect_bom(le32_bytes) == "utf-32-le"

        be32_bytes = b"\x00\x00\xfe\xff\x00\x00\x00H"
        assert detector.detect_from_bytes(be32_bytes) == "utf-32-be"
        assert detector.detect_bom(be32_bytes) == "utf-32-be"

    def test_detect_bom_precedence_utf32_over_utf16(self) -> None:
        """ED-07: 4-byte UTF-32-LE BOM must take precedence over 2-byte UTF-16-LE BOM."""
        detector = EncodingDetector()
        # UTF-32 LE prefix starts with \xff\xfe, same as UTF-16 LE
        data_utf32 = b"\xff\xfe\x00\x00" + b"Test Payload"
        assert detector.detect_bom(data_utf32) == "utf-32-le"
        assert detector.detect_from_bytes(data_utf32) == "utf-32-le"

        # Pure UTF-16 LE prefix without subsequent nulls
        data_utf16 = b"\xff\xfe" + b"T\x00e\x00s\x00t\x00"
        assert detector.detect_bom(data_utf16) == "utf-16-le"
        assert detector.detect_from_bytes(data_utf16) == "utf-16-le"

    def test_detect_bom_partial_or_corrupt_prefix(self) -> None:
        """ED-08: Partial BOM bytes do not trigger false BOM match."""
        detector = EncodingDetector()
        assert detector.detect_bom(b"\xef\xbb") is None
        assert detector.detect_bom(b"\xff") is None
        assert detector.detect_bom(b"\x00\x00\xfe") is None
        assert detector.detect_bom(b"") is None


class TestEncodingDetectorStrictUtf8:
    """Stage 2: Strict UTF-8 probe scenarios."""

    def test_detect_ascii_plain(self) -> None:
        """ED-09: Standard 7-bit ASCII text defaults to utf-8."""
        detector = EncodingDetector()
        assert detector.detect_from_bytes(b"Plain 7-bit ASCII text with 12345 symbols!") == "utf-8"

    def test_detect_strict_utf8_hangul(self) -> None:
        """ED-10: Multibyte UTF-8 Korean text without BOM is detected as utf-8."""
        detector = EncodingDetector()
        hangul_text = "안녕하세요. 파일파인더 검색 테스트입니다."
        assert detector.detect_from_bytes(hangul_text.encode("utf-8")) == "utf-8"

    def test_detect_strict_utf8_european_latin(self) -> None:
        """ED-11: Multibyte UTF-8 Western European text is detected as utf-8."""
        detector = EncodingDetector()
        text = "Café au lait à Paris, München Übergrößen, España señorita"
        assert detector.detect_from_bytes(text.encode("utf-8")) == "utf-8"

    def test_detect_strict_utf8_astral_plane_emojis(self) -> None:
        """ED-12: 4-byte UTF-8 astral plane characters (emojis, math) detected as utf-8."""
        detector = EncodingDetector()
        emoji_text = "🚀 Rocket Launch 🎉 Celebration 🐍 Python 3.13 🔍 Search"
        assert detector.detect_from_bytes(emoji_text.encode("utf-8")) == "utf-8"

    def test_try_utf8_invalid_sequences_fail(self) -> None:
        """ED-13: Invalid UTF-8 byte sequences fail try_utf8 and cause fallback."""
        detector = EncodingDetector()
        assert detector.try_utf8(b"\xc3\x28") is False  # Invalid continuation byte
        assert detector.try_utf8(b"\xff\xff") is False  # Illegal UTF-8 bytes
        assert detector.try_utf8("가".encode()[:2]) is False  # Truncated sequence


class TestEncodingDetectorCharsetNormalizerTiebreakers:
    """Stage 3: charset-normalizer probe with CJK tiebreaker rules (Rules 3.1 & 3.2)."""

    @pytest.mark.parametrize("word", ["한글", "공지사항", "스타트", "파", "항"])
    def test_rule_3_1_a_cyrillic_kana_artifact_disambiguation(self, word: str) -> None:
        """ED-14: Rule 3.1.a: CP949 Hangul that decodes into Big5 Cyrillic/Kana is resolved to cp949."""
        detector = EncodingDetector()
        raw_bytes = word.encode("cp949")

        # Verify Big5 decode produces Cyrillic or Kana artifact
        big5_decoded = raw_bytes.decode("big5", errors="replace")
        assert detector._has_cyrillic_or_kana(big5_decoded) is True

        detected = detector.detect_from_bytes(raw_bytes)
        assert detected == "cp949"

    @pytest.mark.parametrize("word", ["설정", "버그", "가", "공지"])
    def test_rule_3_1_b_zero_coherence_short_korean_strings(self, word: str) -> None:
        """ED-15: Rule 3.1.b: Short CP949 words with zero coherence in Big5 resolve to cp949."""
        detector = EncodingDetector()
        raw_bytes = word.encode("cp949")
        detected = detector.detect_from_bytes(raw_bytes)
        assert detected == "cp949"

    def test_rule_3_1_genuine_big5_preserved(self) -> None:
        """ED-16: Genuine Traditional Chinese text in Big5 with coherence is preserved as big5."""
        detector = EncodingDetector()
        trad_chinese = "國立臺灣大學電腦科學與資訊工程學系研究所"
        raw_bytes = trad_chinese.encode("big5")
        detected = detector.detect_from_bytes(raw_bytes)
        assert detected == "big5"

    def test_rule_3_2_false_positive_utf16_guard_without_nulls(self) -> None:
        """ED-17: Rule 3.2: False-positive UTF-16 without null bytes resolves to cp949 for Hangul."""
        detector = EncodingDetector()
        fake_utf16 = MagicMock()
        fake_utf16.encoding = "utf_16_le"
        fake_utf16.chaos = 0.0
        fake_utf16.coherence = 0.0

        fake_alt = MagicMock()
        fake_alt.encoding = "ascii"
        fake_alt.chaos = 0.5
        fake_alt.coherence = 0.0

        hangul_bytes = "안녕하세요 반갑습니다".encode("cp949")
        with patch("charset_normalizer.from_bytes", return_value=[fake_utf16, fake_alt]):
            assert detector.detect_from_bytes(hangul_bytes) == "cp949"

    def test_rule_3_2_discard_utf16_when_no_nulls_and_no_hangul(self) -> None:
        """ED-18: Rule 3.2: Discards UTF-16 if no null bytes and bytes do not decode as Hangul."""
        detector = EncodingDetector()
        fake_utf16 = MagicMock()
        fake_utf16.encoding = "utf_16_le"

        with patch("charset_normalizer.from_bytes", return_value=[fake_utf16]):
            # Arbitrary non-Hangul bytes without null byte
            raw = b"\x80\x81\x82\x83"
            # Must discard utf-16 and fall back through to latin-1
            assert detector.detect_from_bytes(raw) == "latin-1"

    def test_rule_3_3_preserve_japanese_shift_jis(self) -> None:
        """ED-19: Rule 3.3: Genuine Japanese Shift-JIS text is preserved."""
        detector = EncodingDetector()
        jp_text = "こんにちは世界、日本語の文字コードテストです。"
        raw_bytes = jp_text.encode("cp932")
        detected = detector.detect_from_bytes(raw_bytes)
        assert detected in ("cp932", "shift_jis")

    def test_rule_3_3_preserve_simplified_chinese_gbk(self) -> None:
        """ED-20: Rule 3.3: Genuine Simplified Chinese GBK text is preserved."""
        detector = EncodingDetector()
        zh_text = (
            "这是一篇关于计算机科学与人工智能的中文学术论文摘要。"
            "本文提出了一种新颖的深度学习网络结构，在多个标准基准测试集上取得了先进的性能表现。"  # noqa: RUF001
        )
        raw_bytes = zh_text.encode("gb18030")
        detected = detector.detect_from_bytes(raw_bytes)
        assert detected in ("gbk", "gb18030", "gb2312")


class TestEncodingDetectorKoreanLegacy:
    """Stage 4: Korean CP949 and EUC-KR legacy text scenarios."""

    def test_detect_cp949_long_corporate_document(self) -> None:
        """ED-21: Multi-sentence corporate document in CP949 resolves to cp949."""
        detector = EncodingDetector()
        doc = (
            "경영지원본부 인사총무팀 공지사항 안내문입니다.\n"
            "2026년도 정기 인사평가 및 성과급 지급 일정 안내.\n"
            "임직원 여러분께서는 첨부된 양식을 작성하여 기한 내 제출 바랍니다."
        )
        detected = detector.detect_from_bytes(doc.encode("cp949"))
        assert detected in ("cp949", "euc-kr", "euc_kr")

    def test_detect_euckr_legacy_text(self) -> None:
        """ED-22: EUC-KR encoded legacy Korean bytes map to cp949."""
        detector = EncodingDetector()
        legacy_bytes = "가나다라마바사 아자차카타파하 일이삼사오륙칠팔구십".encode("euc-kr")
        detected = detector.detect_from_bytes(legacy_bytes)
        assert detected in ("cp949", "euc-kr", "euc_kr")

    def test_hangul_codepoint_boundaries(self) -> None:
        """ED-23: _is_hangul_codepoint verifies exact boundary ranges."""
        # Precomposed Syllables: U+AC00 to U+D7A3
        assert EncodingDetector._is_hangul_codepoint(0xAC00) is True  # '가'
        assert EncodingDetector._is_hangul_codepoint(0xD7A3) is True  # '힣'
        assert EncodingDetector._is_hangul_codepoint(0xABFF) is False
        assert EncodingDetector._is_hangul_codepoint(0xD7A4) is False

        # Compatibility Jamo: U+3131 to U+318E
        assert EncodingDetector._is_hangul_codepoint(0x3131) is True  # 'ㄱ'
        assert EncodingDetector._is_hangul_codepoint(0x318E) is True
        assert EncodingDetector._is_hangul_codepoint(0x3130) is False
        assert EncodingDetector._is_hangul_codepoint(0x318F) is False

        # Conjoining Jamo: U+1100 to U+11FF
        assert EncodingDetector._is_hangul_codepoint(0x1100) is True
        assert EncodingDetector._is_hangul_codepoint(0x11FF) is True
        assert EncodingDetector._is_hangul_codepoint(0x10FF) is False
        assert EncodingDetector._is_hangul_codepoint(0x1200) is False


class TestEncodingDetectorLatin1AndFallback:
    """Stage 5: Western European Latin-1 / CP1252 and ultimate fallback."""

    def test_detect_western_european_cp1252_accents(self) -> None:
        """ED-24: French accented text in CP1252 resolves to cp1252 or latin-1."""
        detector = EncodingDetector()
        french = "Ceci est un document en français avec des accents: l'été, le garçon, la forêt, l'île."
        detected = detector.detect_from_bytes(french.encode("cp1252"))
        assert detected in ("cp1252", "latin-1")

    def test_detect_latin1_arbitrary_high_bytes_fallback(self) -> None:
        """ED-25: High bytes with no UTF-8, CP949, or linguistic coherence fallback to latin-1."""
        detector = EncodingDetector()
        raw_arbitrary = b"Raw Latin-1 fallback data: \xa0\x01\xff\xfe\x80\x81\x82\x83"
        detected = detector.detect_from_bytes(raw_arbitrary)
        assert detected in ("latin-1", "iso-8859-1")


class TestEncodingDetectorEdgeCasesAndIO:
    """Edge cases, disk I/O, and helper functions."""

    def test_detect_empty_bytes(self) -> None:
        """ED-01: Empty byte sequence defaults safely to utf-8."""
        detector = EncodingDetector()
        assert detector.detect_from_bytes(b"") == "utf-8"

    def test_detect_single_byte_ascii(self) -> None:
        """ED-02: Single byte ASCII returns utf-8."""
        detector = EncodingDetector()
        assert detector.detect_from_bytes(b"Z") == "utf-8"

    def test_detect_single_high_byte(self) -> None:
        """ED-03: Single high byte returns latin-1."""
        detector = EncodingDetector()
        assert detector.detect_from_bytes(b"\x80") == "latin-1"
        assert detector.detect_from_bytes(b"\xff") == "latin-1"

    def test_detect_from_file_path_bounded_sample(self, tmp_path: Path) -> None:
        """ED-26: detect(path) reads bounded sample and identifies encoding."""
        detector = EncodingDetector()
        file_path = tmp_path / "korean_sample.txt"
        file_path.write_bytes("인코딩 감지 파일 테스트".encode("cp949"))

        detected = detector.detect(file_path, sample_size=1024)
        assert detected in ("cp949", "euc-kr", "euc_kr")

    def test_detect_file_not_found_raises(self, tmp_path: Path) -> None:
        """ED-27: Non-existent file path raises FileNotFoundError."""
        detector = EncodingDetector()
        missing = tmp_path / "missing_target_file.txt"
        with pytest.raises(FileNotFoundError):
            detector.detect(missing)

    def test_normalize_codec_name_all_variants(self) -> None:
        """ED-28: _normalize_codec_name canonicalizes codec names."""
        assert EncodingDetector._normalize_codec_name("utf_8") == "utf-8"
        assert EncodingDetector._normalize_codec_name("UTF8") == "utf-8"
        assert EncodingDetector._normalize_codec_name("latin_1") == "latin-1"
        assert EncodingDetector._normalize_codec_name("latin1") == "latin-1"
        assert EncodingDetector._normalize_codec_name("iso8859_1") == "latin-1"
        assert EncodingDetector._normalize_codec_name("iso-8859-1") == "latin-1"
        assert EncodingDetector._normalize_codec_name("windows_1252") == "cp1252"
        assert EncodingDetector._normalize_codec_name("CP_1252") == "cp1252"

    def test_has_cyrillic_or_kana_boundaries(self) -> None:
        """ED-29: _has_cyrillic_or_kana flags Cyrillic and Japanese Kana correctly."""
        # Cyrillic boundary characters
        assert EncodingDetector._has_cyrillic_or_kana("\u0400") is True
        assert EncodingDetector._has_cyrillic_or_kana("\u04FF") is True

        # Kana boundary characters
        assert EncodingDetector._has_cyrillic_or_kana("\u3040") is True
        assert EncodingDetector._has_cyrillic_or_kana("\u30FF") is True

        # Non-Cyrillic / Non-Kana
        assert EncodingDetector._has_cyrillic_or_kana("Hello 123") is False
        assert EncodingDetector._has_cyrillic_or_kana("한글 텍스트") is False
        assert EncodingDetector._has_cyrillic_or_kana("繁體中文") is False
