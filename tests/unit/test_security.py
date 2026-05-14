"""Security tests — magic-byte upload sniffing rejects renamed binaries,
and report-id tokens roundtrip cleanly but reject tampered values."""

import io

from app.blueprints.reports import _encode_report_id, _sniff_media_type


def test_upload_rejects_exe_renamed_to_png():
    """_sniff_media_type reads the first bytes of the stream — a Windows .exe
    renamed as .png has 'MZ' as its first bytes, not the PNG magic header,
    so the sniffer returns None and the upload endpoint will 400."""
    exe_bytes = b'MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00'
    stream = io.BytesIO(exe_bytes)
    assert _sniff_media_type(stream) is None

    # A real PNG header (the 8-byte signature) does sniff as image/png
    png_bytes = b'\x89PNG\r\n\x1a\n' + b'\x00' * 8
    assert _sniff_media_type(io.BytesIO(png_bytes)) == ('image', 'png')


def test_report_token_roundtrip(app):
    """Encoded report ID decodes back to the original integer. Tampered
    tokens raise — the URL-safe serializer is the gate against guessing
    /reports/1, /reports/2, ... by changing one digit."""
    from itsdangerous import BadSignature

    with app.app_context():
        token = _encode_report_id(42)
        from app.blueprints.reports import _report_serializer
        decoded = _report_serializer().loads(token)
        assert decoded == 42

        # change the last char to break the signature
        tampered = token[:-1] + ('Z' if token[-1] != 'Z' else 'Y')
        try:
            _report_serializer().loads(tampered)
            assert False, 'tampered token should not load'
        except BadSignature:
            pass
