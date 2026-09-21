from io import BytesIO

from PIL import Image, PngImagePlugin


def png_fixture(label: str) -> bytes:
    output = BytesIO()
    info = PngImagePlugin.PngInfo()
    info.add_text("fixture", label)
    Image.new("RGB", (2, 2), (20, 80, 120)).save(output, format="PNG", pnginfo=info)
    return output.getvalue()
