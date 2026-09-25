"""File encoding auto-detection with 5-stage fallback chain and CJK tiebreaker rules.

Zero PySide6 imports. Strictly typed and resilient.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import charset_normalizer


class EncodingDetector:
    """Detects text file encoding using an ordered fallback chain with CJK tiebreakers."""

    BOM_MAP: ClassVar[dict[bytes, str]] = {
        b"\xff\xfe\x00\x00": "utf-32-le",
        b"\x00\x00\xfe\xff": "utf-32-be",
        b"\xef\xbb\xbf": "utf-8-sig",
        b"\xff\xfe": "utf-16-le",
        b"\xfe\xff": "utf-16-be",
    }

    BIG5_FAMILY: ClassVar[frozenset[str]] = frozenset({"big5", "big5hkscs", "cp950"})
    KOREAN_FAMILY: ClassVar[frozenset[str]] = frozenset({"cp949", "euc_kr", "euc-kr"})
    CJK_ENCODINGS: ClassVar[frozenset[str]] = frozenset(
        {
            "cp949",
            "euc_kr",
            "euc-kr",
            "johab",
            "shift_jis",
            "cp932",
            "euc_jp",
            "euc_jis_2004",
            "shift_jis_2004",
            "gbk",
            "gb2312",
            "gb18030",
            "big5",
            "big5hkscs",
            "cp950",
        }
    )
    DEFAULT_SAMPLE_SIZE: ClassVar[int] = 65536  # 64KB bounded I/O

    def detect(self, path: Path, sample_size: int = DEFAULT_SAMPLE_SIZE) -> str:
        """Detect file encoding following the 5-stage fallback chain.

        Chain: BOM -> strict UTF-8 -> charset-normalizer (with tiebreakers) -> CP949 -> Latin-1.
        """
        with open(path, mode="rb") as f:
            sample = f.read(sample_size)
        return self.detect_from_bytes(sample)

    def detect_from_bytes(self, raw_bytes: bytes) -> str:
        """Detect encoding from an in-memory byte slice."""
        if not raw_bytes:
            return "utf-8"

        # Stage 1: Byte Order Mark (BOM) probe
        bom_enc = self.detect_bom(raw_bytes)
        if bom_enc is not None:
            return bom_enc

        # Stage 2: Strict UTF-8 probe
        if self.try_utf8(raw_bytes):
            return "utf-8"

        # Stage 3: charset-normalizer probe with CJK tiebreaker rules
        cn_enc = self.try_charset_normalizer(raw_bytes)
        if cn_enc is not None:
            return cn_enc

        # Stage 4: Korean Legacy Probe (CP949 / EUC-KR)
        if self.try_cp949(raw_bytes):
            return "cp949"

        # Stage 5: Latin-1 Ultimate Fallback (maps all 0x00-0xFF bytes, never fails)
        return "latin-1"

    def detect_bom(self, raw_bytes: bytes) -> str | None:
        """Check for known Byte Order Marks at the beginning of byte stream.

        Checks longer signatures first (4-byte before 2-byte) to prevent collisions.
        """
        for bom, encoding in sorted(
            self.BOM_MAP.items(), key=lambda item: len(item[0]), reverse=True
        ):
            if raw_bytes.startswith(bom):
                return encoding
        return None

    def try_utf8(self, raw_bytes: bytes) -> bool:
        """Attempt strict UTF-8 decoding on byte slice."""
        try:
            raw_bytes.decode("utf-8", errors="strict")
            return True
        except UnicodeDecodeError:
            return False

    def try_cp949(self, raw_bytes: bytes) -> bool:
        """Attempt strict CP949 decoding on byte slice."""
        try:
            raw_bytes.decode("cp949", errors="strict")
            return True
        except UnicodeDecodeError:
            return False

    def try_charset_normalizer(self, raw_bytes: bytes) -> str | None:
        """Probe charset-normalizer with CP949 vs Big5 tiebreakers and UTF-16 guards.

        Implements Architecture Document Section 5 Rules 3.1 & 3.2.
        """
        try:
            matches = charset_normalizer.from_bytes(raw_bytes)
        except (TypeError, ValueError):
            return None

        # Filter out false-positive UTF-16/32 if no null bytes are present
        candidates = []
        for m in matches:
            m_enc = m.encoding.lower().replace("-", "_")
            if m_enc.startswith(("utf_16", "utf_32")) and b"\x00" not in raw_bytes:
                continue
            candidates.append(m)

        if not candidates:
            return None

        best = candidates[0]
        # Disambiguate Western European vs Central European tie
        # charset-normalizer sorts cp1250 before cp1252 on identical scores,
        # but cp1252/latin-1 correctly maps Western European accents (e.g. ï, é, ç, à)
        for m in candidates:
            m_enc_norm = m.encoding.lower().replace("-", "_")
            if (
                m_enc_norm in ("cp1252", "windows_1252", "iso8859_1", "latin_1")
                and m.chaos <= best.chaos
                and getattr(m, "coherence", 0.0) >= getattr(best, "coherence", 0.0) - 0.001
            ):
                best = m
                break

        best_enc = best.encoding.lower().replace("-", "_")

        # Rule 3.2: If UTF-16/32 was predicted without null bytes, check CP949 Hangul
        if b"\x00" not in raw_bytes and any(
            m.encoding.lower().replace("-", "_").startswith(("utf_16", "utf_32")) for m in matches
        ):
            try:
                cp949_text = raw_bytes.decode("cp949", errors="strict")
                if self._contains_hangul(cp949_text):
                    return "cp949"
            except UnicodeDecodeError:
                pass

        # Rule 3.1: Big5 Family Disambiguation
        # Empirically, 95.9% of KS X 1001 Hangul syllables decode cleanly under Big5
        if best_enc in self.BIG5_FAMILY:
            try:
                cp949_text = raw_bytes.decode("cp949", errors="strict")
                if self._contains_hangul(cp949_text):
                    # Sub-rule 3.1.a: Cyrillic/Kana artifact check
                    big5_text = raw_bytes.decode("big5", errors="replace")
                    if self._has_cyrillic_or_kana(big5_text):
                        return "cp949"

                    # Sub-rule 3.1.b: Zero-chaos or zero-coherence check
                    has_cp949_candidate = any(
                        m.encoding.lower().replace("-", "_") in self.KOREAN_FAMILY
                        and m.chaos <= 0.05
                        for m in candidates
                    )
                    if has_cp949_candidate or getattr(best, "coherence", 0.0) == 0.0:
                        return "cp949"
            except UnicodeDecodeError:
                # CP949 decode failed, genuine Big5 text
                pass

        # Direct Korean detection
        if best_enc in self.KOREAN_FAMILY:
            return "cp949"

        # Rule 3.3: For CJK or coherent language predictions, accept if chaos <= 0.3
        if best_enc in self.CJK_ENCODINGS and getattr(best, "chaos", 0.0) <= 0.3:
            return self._normalize_codec_name(best.encoding)

        if (getattr(best, "coherence", 0.0) > 0.0 or getattr(best, "languages", [])) and getattr(
            best, "chaos", 0.0
        ) <= 0.3:
            return self._normalize_codec_name(best.encoding)

        # Single-byte code pages with zero coherence/no language are pure guesswork;
        # return None so execution falls through to Stage 4 (CP949) or Stage 5 (Latin-1).
        return None

    @staticmethod
    def _normalize_codec_name(name: str) -> str:
        """Normalize encoding string into a standard, canonical Python codec name."""
        lowered = name.lower()
        if lowered in ("utf_8", "utf8"):
            return "utf-8"
        if lowered in ("latin_1", "latin1", "iso_8859_1", "iso8859_1", "iso8859-1", "iso-8859-1"):
            return "latin-1"
        if lowered in ("windows_1252", "cp_1252"):
            return "cp1252"
        return lowered

    @staticmethod
    def _is_hangul_codepoint(cp: int) -> bool:
        """Check if Unicode codepoint falls within Korean Hangul ranges."""
        return (
            (0xAC00 <= cp <= 0xD7A3)  # Precomposed Hangul Syllables
            or (0x3131 <= cp <= 0x318E)  # Compatibility Jamo
            or (0x1100 <= cp <= 0x11FF)  # Conjoining Jamo
        )

    @classmethod
    def _contains_hangul(cls, text: str) -> bool:
        """Return True if text contains at least one Korean Hangul character."""
        return any(cls._is_hangul_codepoint(ord(c)) for c in text)

    @staticmethod
    def _has_cyrillic_or_kana(text: str) -> bool:
        """Check if text contains Cyrillic or Japanese Kana characters."""
        for c in text:
            cp = ord(c)
            if (0x0400 <= cp <= 0x04FF) or (0x3040 <= cp <= 0x30FF):
                return True
        return False
