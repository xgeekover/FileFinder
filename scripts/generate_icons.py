#!/usr/bin/env python3
"""Render app_icon.svg into multiple PNG resolutions and desktop icon assets."""

import os
import sys
from pathlib import Path

# Run headlessly without requiring a display server
os.environ["QT_QPA_PLATFORM"] = "offscreen"

try:
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
except ImportError:
    print("Error: PySide6 is required. Run 'uv pip install PySide6' first.", file=sys.stderr)
    sys.exit(1)


def rasterize_svg(svg_path: Path, output_path: Path, size: int) -> None:
    """Rasterize an SVG file to a transparent PNG of the specified size.

    Args:
        svg_path: Path to source SVG file.
        output_path: Target path for output PNG.
        size: Width and height of output PNG in pixels.

    Raises:
        ValueError: If the SVG file is corrupted, malformed, or invalid.
        RuntimeError: If the rasterized PNG cannot be saved to disk.
    """
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise ValueError(f"Invalid or corrupted SVG file: {svg_path}")

    image = QImage(QSize(size, size), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))

    painter = QPainter(image)
    renderer.render(painter)
    painter.end()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(output_path)):
        raise RuntimeError(f"Failed to save PNG to {output_path}")
    print(f"Generated: {output_path.name} ({size}x{size})")


def main() -> None:
    """Generate standard PNG sizes for application window, taskbar, and packaging."""
    root_dir = Path(__file__).resolve().parent.parent
    icons_dir = root_dir / "resources" / "icons"
    svg_path = icons_dir / "app_icon.svg"

    if not svg_path.exists():
        print(f"Error: {svg_path} does not exist!", file=sys.stderr)
        sys.exit(1)

    # Standard icon dimensions: window icon, system tray, taskbar, dock
    icon_sizes = [16, 24, 32, 48, 64, 128, 256, 512]
    try:
        for size in icon_sizes:
            out_file = icons_dir / f"app_icon_{size}.png"
            rasterize_svg(svg_path, out_file, size)

        # Main default app_icon.png (256x256)
        rasterize_svg(svg_path, icons_dir / "app_icon.png", 256)
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print("\nAll icon assets generated successfully in resources/icons/.")


if __name__ == "__main__":
    main()
